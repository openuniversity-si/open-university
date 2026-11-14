"""The fast deploy (DEP8, docs/operations/aws.md 22.2/22.3): a pointer swap of the alias live to a package the gate built.

The gate's artifact job left artifacts/lambda/head/<pr head sha>.json (the digest of each port Lambda built from that head, and
the base it was built on) and the zips by digest. When the service sees a push to the base whose changed paths touch the
modules of a port Lambda, autodeploy asks this module to deploy that push:

  1. the manifest is found by the push's commit ids and checked FRESH: the pushes between the manifest's base and this one
     touched none of the function's files (a path list missing anywhere means unknown, so no fast deploy: the slow path runs);
  2. lambda:UpdateFunctionCode(S3Bucket, S3Key) uploads the digest (FAST-WAIT-ACTIVE: a function in a VPC is InProgress for
     seconds, so a ResourceConflictException first waits for the previous update; then LastUpdateStatus must be Successful,
     Failed aborts with its reason), PublishVersion makes the version, whose CodeSha256 must be the digest, and the version
     must be State Active before anything invokes it; all of that is activate_ms, inside deploy.fast_activate_s (120 s,
     a safety timeout: not active in time is smoke_pre 'not active in N s', no swap); the previous version is read from
     the alias first (GetAlias);
  3. PRE-swap smoke (FAST-SMOKE-ORDER): the NEW VERSION is invoked by its qualifier (immediately consistent) with the health
     payload: no FunctionError, answered by that version; red -> the alias is not touched (smoke_pre failed, no rollback);
  4. lambda:UpdateAlias live -> the new version, timed: that call is swap_ms;
  5. POST-swap check: the alias is invoked until it answers the new version, at most deploy.fast_propagation_s (10 s):
     propagation_ms, propagated. Answering the previous version meanwhile is eventual consistency (the first live swap,
     09/11, rolled back a healthy version for it); not converging in the window is recorded (ok, propagated false) and does
     not roll back. Only an ERROR answered by the alias (unhealthy) swaps it back to the previous version.

Every function is a platform.deploy.fast event {function, version, sha, swap_ms, ok} (plus previous, rolled_back, reason); a
rollback is also platform.deploy.rolledback. Only the activation waits (bounded); the swap itself is ~60 ms, and a failure ends
the attempt as a recorded failure, and the slow path that follows every tower_infra change (the service image) puts the head right anyway.
IAM (30-service.json, inside tower-boundary): UpdateFunctionCode, PublishVersion, UpdateAlias, GetAlias, InvokeFunction on the
three functions and s3:GetObject on artifacts/lambda/*.
"""
import base64
import hashlib
import json
import logging
import time

LOG = logging.getLogger('tower_infra.fastdeploy')
FAST, ROLLEDBACK = 'platform.deploy.fast', 'platform.deploy.rolledback'
ALIAS = 'live'
ACTIVATE_STEP_S = 1.0  # between two polls of the function / version state while the code activates
PROPAGATION_STEP_S = 0.25  # between two invokes of the alias while it converges (bounded by deploy.fast_propagation_s)
FUNCTIONS = ('tower-port-api', 'tower-port-ack-ingress', 'tower-port-webhook-consumer')
# module (file name in tower_infra) -> the Lambdas whose package holds it: the import closure of each handler. A test pins it to
# scripts/lib/deploy_classify.py (LAMBDA_MODULES, itself pinned to the packages): the service has no copy of the repository's
# scripts. SLOW-PATH-NO-ROLLOUT-WAIT: every module of a package, not only the handlers and three of their imports.
API, INGRESS, CONSUMER = FUNCTIONS
MODULES = {
    'ingress': (INGRESS,), 'awsjson': (INGRESS,), 'webhook_consumer': (CONSUMER,),
    **{name: (API, CONSUMER) for name in ('__init__', 'branches', 'canary', 'checks', 'code_bundle', 'config_data', 'database', 'dbinit', 'drills', 'engine', 'http_port',
                                          'live_image', 'observations', 'port', 'subscriptions', 'supervisor', 'wake')},
    **{name: FUNCTIONS for name in ('ed25519', 'forge_webhooks')},
}
PREFIX = 'infra/service/tower_infra/'
INGRESS_INIT = 'infra/ingress/__init__.py'
ARTIFACT = 'artifacts/lambda/'
# the smoke of each alias: an API Gateway v2 request the port answers without a token, a bad delivery the ingress refuses, an
# empty batch for the consumer. Each runs the code (it must return, with no FunctionError) and is answered by the new version.
SMOKE = {
    'tower-port-api': {'version': '2.0', 'rawPath': '/v1/health', 'rawQueryString': '', 'headers': {},
                   'requestContext': {'http': {'method': 'GET', 'path': '/v1/health'}}, 'isBase64Encoded': False},
    'tower-port-ack-ingress': {'version': '2.0', 'rawPath': '/v1/forge/origin/webhooks', 'rawQueryString': '', 'headers': {},
                           'body': '{}', 'requestContext': {'http': {'method': 'POST', 'path': '/v1/forge/origin/webhooks'}},
                           'isBase64Encoded': False},
    'tower-port-webhook-consumer': {'Records': []},
}


def functions_of(paths):
    """The Lambdas whose package a change to these paths changes ([] for none; sorted)."""
    found = set()
    for path in paths:
        path = path.strip().lstrip('./')
        if path.startswith(PREFIX) and path.endswith('.py') and '/' not in path[len(PREFIX):]:
            found.update(MODULES.get(path[len(PREFIX):-3], ()))
    return sorted(found)


def inputs_of(files):
    """The repository paths behind a manifest's archive names (tower_infra/x.py -> infra/service/tower_infra/x.py)."""
    return {PREFIX + name.split('/', 1)[1] for name in files} | {INGRESS_INIT}


def digest_b64(digest):
    return base64.b64encode(bytes.fromhex(digest)).decode()


class NotActive(Exception):
    """The code or the version did not become active inside deploy.fast_activate_s."""
    def __init__(self, message, version=None):
        super().__init__(message)
        self.version = version


class FastDeploy:
    def __init__(self, lam, s3, bucket, clock=time.monotonic, sleep=time.sleep, propagation_s=10.0, activate_s=120.0):
        self.lam, self.s3, self.bucket, self.clock, self.sleep = lam, s3, bucket, clock, sleep
        self.propagation_s = propagation_s  # deploy.fast_propagation_s: autodeploy sets it before each swap
        self.activate_s = activate_s  # deploy.fast_activate_s: the safety timeout of the whole code activation

    # --- the artifact ---------------------------------------------------------------------------------------------
    def manifest(self, commits):
        """The gate's manifest for the first commit id that has one, newest first; None when no commit has."""
        for commit in commits:
            try:
                body = self.s3.get_object(Bucket=self.bucket, Key=f'{ARTIFACT}head/{commit}.json')['Body'].read()
            except Exception:  # noqa: BLE001 - not there (or not readable): the next commit, then the slow path
                continue
            found = json.loads(body)
            if found.get('head') == commit:
                return found
        return None

    @staticmethod
    def fresh(function, found, between):
        """True when no push between the manifest's base and this one touched a file the function's package holds.
        `between` is the list of path lists of those pushes (None for a push that did not list its paths: unknown)."""
        if between is None:
            return False
        inputs = inputs_of(found['functions'][function]['files'])
        return all(paths is not None and not (inputs & {p.strip().lstrip('./') for p in paths}) for paths in between)

    # --- the swap --------------------------------------------------------------------------------------------------
    def deploy(self, function, found, sha):
        """One function swapped, smoked and (if red) swapped back: the event payload. Never raises. The payload carries
        {function, from_version, to_version, sha, swap_ms, smoke, ok} (version/previous are the same two, kept for readers)."""
        entry = self.swap_one(function, found, sha)
        entry.update(from_version=entry['previous'], to_version=entry['version'],
                     smoke='ok' if entry['ok'] and entry['reason'] in (None, 'already live') else (entry['reason'] or 'failed'))
        return entry

    def swap_one(self, function, found, sha):
        entry = {'function': function, 'sha': sha, 'version': None, 'previous': None, 'swap_ms': None, 'ok': False,
                 'rolled_back': False, 'reason': None, 'digest': None, 'smoke_pre': None, 'smoke_pre_ms': None,
                 'activate_ms': None, 'propagation_ms': None, 'propagated': None}
        try:
            wanted = found['functions'][function]
            entry['digest'] = wanted['sha256']
            entry['previous'] = self.lam.get_alias(FunctionName=function, Name=ALIAS)['FunctionVersion']
            if entry['previous'] and self.code_sha(function, entry['previous']) == digest_b64(wanted['sha256']):
                entry.update(ok=True, version=entry['previous'], swap_ms=0, reason='already live')
                return entry
            begin = self.clock()
            try:
                uploaded = self.activate(function, wanted, begin)
            except NotActive as error:
                entry['activate_ms'] = round((self.clock() - begin) * 1000, 1)
                entry['version'] = error.version
                entry['smoke_pre'], entry['reason'] = 'not active in %s s' % round(self.activate_s), str(error)
                return entry
            entry['activate_ms'] = round((self.clock() - begin) * 1000, 1)
            entry['version'] = uploaded['Version']
            if uploaded.get('CodeSha256') != digest_b64(wanted['sha256']):
                entry['reason'] = 'the published code is not the artifact (CodeSha256 differs)'
                return entry
            # 1. PRE-swap smoke: the NEW VERSION by its qualifier (immediately consistent); red -> the alias is never touched
            begin = self.clock()
            entry['reason'] = self.smoke(function, uploaded['Version'], uploaded['Version'])
            entry['smoke_pre_ms'] = round((self.clock() - begin) * 1000, 1)
            if entry['reason']:
                entry['smoke_pre'] = 'failed'
                return entry
            entry['smoke_pre'] = 'ok'
            # 2. the swap: swap_ms is the UpdateAlias call alone
            begin = self.clock()
            self.lam.update_alias(FunctionName=function, Name=ALIAS, FunctionVersion=uploaded['Version'])
            entry['swap_ms'] = round((self.clock() - begin) * 1000, 1)
            # 3. propagation: the alias may keep answering the previous version for a short while (eventual consistency)
            entry['reason'] = self.propagate(function, uploaded['Version'], entry)
            entry['ok'] = entry['reason'] is None
        except Exception as error:  # noqa: BLE001 - recorded, and the alias is put back below when it moved
            entry['reason'] = f'{type(error).__name__}: {str(error)[:200]}'
        if not entry['ok'] and entry['swap_ms'] is not None and entry['previous']:
            entry['rolled_back'] = self.rollback(function, entry['previous'], entry)
        return entry

    # --- the activation (FAST-WAIT-ACTIVE) -----------------------------------------------------------------------------
    def activate(self, function, wanted, begin):
        """UpdateFunctionCode, PublishVersion, and the waits between them, inside activate_s from `begin`. Returns
        {Version, CodeSha256}; raises NotActive on the timeout and RuntimeError when the update Failed."""
        deadline = begin + self.activate_s
        version = None
        self.settle(function, None, deadline, version)  # an update still running (another task, the last deploy): wait first
        while True:
            try:
                self.lam.update_function_code(FunctionName=function, S3Bucket=self.bucket, S3Key=wanted['key'])
                break
            except Exception as error:  # noqa: BLE001
                if type(error).__name__ != 'ResourceConflictException' and 'ResourceConflictException' not in str(error):
                    raise
                if self.clock() >= deadline:
                    raise NotActive(f'the code update conflicts with another one, not active in {round(self.activate_s)} s')
                self.settle(function, None, deadline, version)  # another update began meanwhile: wait it out, then try again
                self.sleep(ACTIVATE_STEP_S)
        self.settle(function, None, deadline, version)
        published = self.lam.publish_version(FunctionName=function, CodeSha256=digest_b64(wanted['sha256']))
        version = published['Version']
        self.settle(function, version, deadline, version)
        return {'Version': version, 'CodeSha256': published.get('CodeSha256')}

    def settle(self, function, version, deadline, published):
        """Poll GetFunctionConfiguration until the function's last update is Successful (version None) or the version is
        Active; Failed raises with its LastUpdateStatusReason; past the deadline raises NotActive."""
        args = {'FunctionName': function, **({'Qualifier': version} if version else {})}
        while True:
            config = self.lam.get_function_configuration(**args)
            if config.get('LastUpdateStatus') == 'Failed':
                raise RuntimeError(f'the code update failed: {config.get("LastUpdateStatusReason") or "no reason"}')
            if version and config.get('State') == 'Failed':
                raise RuntimeError(f'the version failed to activate: {config.get("StateReason") or "no reason"}')
            if config.get('LastUpdateStatus') in (None, 'Successful') and (not version or config.get('State') in (None, 'Active')):
                return
            if self.clock() >= deadline:
                what = 'version %s' % version if version else 'the code update'
                raise NotActive(f'{what} not active in {round(self.activate_s)} s '
                                f'(State {config.get("State")}, LastUpdateStatus {config.get("LastUpdateStatus")})', published)
            self.sleep(ACTIVATE_STEP_S)

    def propagate(self, function, version, entry):
        """Invoke the alias until it answers `version`, at most propagation_s. None unless the alias answered an ERROR (then
        why, and the caller rolls back). Answering another version during the window is propagation, not failure: a window
        that ends without convergence is recorded (propagated false) and the swap stays."""
        begin = self.clock()
        entry['propagated'] = False
        while True:
            answer = self.invoke(function, ALIAS)
            problem = self.problem(function, answer)
            if problem:
                return f'smoke: {problem}'
            if answer.get('ExecutedVersion') == version:
                entry['propagated'] = True
                entry['propagation_ms'] = round((self.clock() - begin) * 1000, 1)
                return None
            if self.clock() - begin >= self.propagation_s:
                entry['propagation_ms'] = round((self.clock() - begin) * 1000, 1)
                return None
            self.sleep(PROPAGATION_STEP_S)

    def code_sha(self, function, version):
        return self.lam.get_function_configuration(FunctionName=function, Qualifier=str(version)).get('CodeSha256')

    def invoke(self, function, qualifier):
        answer = self.lam.invoke(FunctionName=function, Qualifier=str(qualifier), InvocationType='RequestResponse',
                                 Payload=json.dumps(SMOKE[function]).encode())
        body = answer['Payload'].read() if hasattr(answer.get('Payload'), 'read') else b''
        return {**answer, 'body': body}

    @staticmethod
    def problem(function, answer):
        """None when the answer is healthy (no FunctionError; the port's health 200), else why not."""
        body = answer['body']
        if answer.get('FunctionError'):
            return f'the function failed: {body[:200].decode(errors="replace")}'
        if function == 'tower-port-api':
            status = (json.loads(body or b'{}') or {}).get('statusCode')
            if status != 200:
                return f'GET /v1/health answered {status}'
        return None

    def smoke(self, function, qualifier, version):
        """None when `qualifier` answered the smoke from `version` with no error, else why not."""
        answer = self.invoke(function, qualifier)
        problem = self.problem(function, answer)
        if problem:
            return f'smoke: {problem}'
        if answer.get('ExecutedVersion') != version:
            return f'smoke: answered by version {answer.get("ExecutedVersion")}, not {version}'
        return None

    def rollback(self, function, previous, entry):
        begin = self.clock()  # FAST-ROLLBACK-MS: the rollback is the same pointer write back; rollback_ms is that call alone
        try:
            self.lam.update_alias(FunctionName=function, Name=ALIAS, FunctionVersion=previous)
            entry['rollback_ms'] = round((self.clock() - begin) * 1000, 1)
            return True
        except Exception as error:  # noqa: BLE001
            entry['reason'] = f'{entry["reason"]}; the rollback failed: {type(error).__name__}'
            LOG.error('fastdeploy: ROLLBACK FAILED for %s to version %s: %s', function, previous, error)
            return False


def sha_of(data):
    return hashlib.sha256(data).hexdigest()
