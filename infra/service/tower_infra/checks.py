"""CHECK-RUN-AWS (docs/operations/aws.md 22.9; F4 item d): the gate's tower/gate check run posted by the engine, on AWS.

The forge requires tower/gate on the head of every merge into the base (the ruleset tower-gate-required, F37), and
only an installation token of the Origin app tower-factory may post a check run (D-299). It was posted by the
Cloudflare Worker forge-webhook (services/control-plane), which held the app's signing key: a piece outside the engine
on the path of every merge, against Daniel's rule of 09/11 (the engine on AWS, the Worker out of the deploy). The key
is in Parameter Store since 08/11 (/tower/origin/factory-app-signing-key, SecureString, Ed25519 PKCS#8 PEM).

The port's Lambda runs in the VPC with no route out (no NAT: one is a cost), so it neither reaches Origin nor Parameter
Store; the live service does, as it already reads the forge's key. So:
  - POST /v1/check-run {repo, headSha, checkSuite, checkRun} (the body the Worker took; the installation or the
    configuration tenant) is one event, platform.forge.check_run {id, state: asked, ...}, and a NOTIFY of tower_deploy;
  - the live service's look (Poster, woken by that NOTIFY) takes each asked one once (state taken, one event an id), mints
    the installation token as the Worker did (an app JWT: EdDSA over {iss: app id, aud: origin-apps, iat, exp: iat + 300},
    exchanged at /app/installations/<id>/access_tokens, kept until a minute before it ends), posts the check run and
    says posted {outcome, kid} or failed {why}: kid is the JWK thumbprint (RFC 7638) of the key's public half, to tell
    keys apart across posts (nothing of the secret is said); it is not the id `origin app view` lists, which Origin
    computes otherwise (13/11: UyWZWjSc... here, LqCeA8gL... there, the app's only key, and the token was minted);
  - GET /v1/check-run/<id> answers the newest state, which the gate's client waits for (forge_control.PortAdapter).
"""
import base64
import hashlib
import json
import logging
import os
import re
import time
import urllib.error
import urllib.request

from . import ed25519

LOG = logging.getLogger('tower_infra.checks')
EVENT = 'platform.forge.check_run'
REPO = 'openuniversity-si/open-university'
SHA = re.compile(r'^[0-9a-f]{40}$')
ORIGIN_API = 'https://api.cursor.com/v1/origin'
AUDIENCE, JWT_TTL_S, TOKEN_MARGIN_S, TOKEN_FALLBACK_S = 'origin-apps', 300, 60, 300
ASKED_S = 600  # an asked check run older than this is no longer taken (the gate's client has given up long before)
KEY_PARAMETER = 'TOWER_ORIGIN_APP_KEY_PARAMETER'  # the environment: the parameter's name, the app's id, its installation
APP_ID, INSTALLATION = 'TOWER_ORIGIN_APP_ID', 'TOWER_ORIGIN_APP_INSTALLATION'
PKCS8_ED25519 = bytes.fromhex('302e020100300506032b657004220420')  # the DER prefix of an Ed25519 PKCS#8 key; the seed follows

SAY = ("with said as (insert into log.event (event_id, tenant_id, type, occurred_at, producer, subject, payload) "
       f"select %(event)s, null, '{EVENT}', clock_timestamp(), %(producer)s, 'forge/check-run', %(payload)s::jsonb "
       "|| jsonb_build_object('at', round(extract(epoch from clock_timestamp())::numeric, 3)) "
       f"where not exists (select 1 from log.event where event_id = %(event)s and type = '{EVENT}' "
       "and occurred_at > now() - interval '1 day') returning type) "
       "select said.type from said cross join lateral (select pg_notify('tower_deploy', said.type)) n")
NEWEST = (f"select payload::text from log.event where type = '{EVENT}' and tenant_id is null "
          "and occurred_at > now() - interval '1 day' and payload->>'id' = %(id)s order by occurred_at desc limit 1")
OPEN = (f"select a.payload::text from log.event a where a.type = '{EVENT}' and a.tenant_id is null "
        "and a.payload->>'state' = 'asked' and a.occurred_at > clock_timestamp() - make_interval(secs => %(asked_s)s::float8) "
        f"and not exists (select 1 from log.event t where t.type = '{EVENT}' and t.tenant_id is null "
        "and t.payload->>'id' = a.payload->>'id' and t.payload->>'state' <> 'asked') order by a.occurred_at")


def say(db, ident, state, producer, **more):
    """One state of a check run, once (its event id is the id and the state): answers whether this call said it."""
    return bool(db.rows(SAY, {'event': f'{EVENT}:{ident}:{state}', 'producer': producer,
                              'payload': json.dumps({'id': ident, 'state': state, **more})}))


def ask(db, who, body, clock=time.time_ns, configured=None):
    """POST /v1/check-run: the check run asked, for the live service to post. The body is the Worker's."""
    from . import canary, port
    (configured or canary.configured)(db, who)
    body = body or {}
    if body.get('repo') != REPO:
        raise port.PortError(400, f'only {REPO} is served')
    if not SHA.match(str(body.get('headSha') or '')) or not isinstance(body.get('checkRun'), dict) \
            or not isinstance(body.get('checkSuite'), dict):
        raise port.PortError(400, 'headSha (40 hex), checkSuite and checkRun required')
    ident = str(clock())
    say(db, ident, 'asked', port.PRODUCER, headSha=body['headSha'], checkSuite=body['checkSuite'],
        checkRun=body['checkRun'])
    return {'id': ident, 'state': 'asked'}


def state(db, who, ident, configured=None):
    """GET /v1/check-run/<id>: the newest state of that check run (404 for none in a day)."""
    from . import canary, port
    (configured or canary.configured)(db, who)
    found = db.rows(NEWEST, {'id': str(ident)})
    if not found:
        raise port.PortError(404, 'no such check run')
    said = json.loads(found[0][0]) if isinstance(found[0][0], str) else found[0][0]
    return {name: value for name, value in said.items() if name not in ('checkRun', 'checkSuite')}


def b64url(data):
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode()


def seed_of(pem):
    """The 32-byte seed of an Ed25519 PKCS#8 PEM key; ValueError for anything else."""
    body = ''.join(line for line in str(pem).strip().splitlines() if not line.startswith('-----'))
    der = base64.b64decode(body)
    if len(der) != len(PKCS8_ED25519) + 32 or not der.startswith(PKCS8_ED25519):
        raise ValueError('not an Ed25519 PKCS#8 key')
    return der[len(PKCS8_ED25519):]


def kid(seed):
    """The JWK thumbprint (RFC 7638) of the key's public half: the same key says the same kid (Origin's own key id is another)."""
    public = b64url(ed25519.public_key(seed))
    return b64url(hashlib.sha256(json.dumps({'crv': 'Ed25519', 'kty': 'OKP', 'x': public}, separators=(',', ':'),
                                            sort_keys=True).encode()).digest())


def app_jwt(seed, app_id, now_s):
    header = b64url(json.dumps({'alg': 'EdDSA', 'typ': 'JWT'}, separators=(',', ':')).encode())
    claims = b64url(json.dumps({'iss': app_id, 'aud': AUDIENCE, 'iat': now_s, 'exp': now_s + JWT_TTL_S},
                               separators=(',', ':')).encode())
    data = f'{header}.{claims}'
    return f'{data}.{b64url(ed25519.sign(seed, data.encode()))}'


class Poster:
    """The live service's half: the asked check runs posted with the app's installation token."""

    def __init__(self, scope, key, app_id, installation, opener=urllib.request.urlopen, clock=time.time,
                 api=ORIGIN_API, agent='tower-service'):
        self.scope, self.key, self.app_id, self.installation = scope, key, app_id, installation
        self.opener, self.clock, self.api, self.agent = opener, clock, api, agent
        self.seed = self.kid = None
        self.token, self.until = None, 0.0

    def call(self, method, url, token, body=None):
        request = urllib.request.Request(url, method=method, data=None if body is None else json.dumps(body).encode(),
                                         headers={'authorization': f'Bearer {token}', 'accept': 'application/json',
                                                  'content-type': 'application/json', 'user-agent': self.agent})
        with self.opener(request, timeout=15) as answer:
            return json.loads(answer.read() or b'{}')

    def installation_token(self):
        if self.token and self.clock() < self.until:
            return self.token
        if self.seed is None:
            self.seed = seed_of(self.key())
            self.kid = kid(self.seed)
        jwt = app_jwt(self.seed, self.app_id, int(self.clock()))
        said = self.call('POST', f'{self.api}/app/installations/{self.installation}/access_tokens', jwt)
        token = said.get('token') or said.get('accessToken') or said.get('access_token')
        if not token:
            raise RuntimeError('the installation token answer has no token')
        ends = said.get('expiresAt') or said.get('expires_at')
        try:
            from datetime import datetime
            until = datetime.fromisoformat(str(ends).replace('Z', '+00:00')).timestamp() - TOKEN_MARGIN_S
        except ValueError:
            until = self.clock() + TOKEN_FALLBACK_S
        self.token, self.until = token, until
        return token

    def post(self, asked):
        owner, name = REPO.split('/')
        token = self.installation_token()
        try:
            return self.call('POST', f'{self.api}/repos/{owner}/{name}/check-runs', token, {
                'headSha': asked['headSha'], 'checkSuite': asked['checkSuite'], 'checkRun': asked['checkRun']})
        except urllib.error.HTTPError as error:
            if error.code == 401:
                self.token = None  # revoked: minted anew next time
            raise

    def step(self, db):
        """Each asked check run, taken once and posted; answers how many were posted."""
        posted = 0
        for (payload,) in db.rows(OPEN, {'asked_s': ASKED_S}):
            asked = json.loads(payload) if isinstance(payload, str) else payload
            if not say(db, asked['id'], 'taken', 'tower-service'):
                continue  # another live service took it
            began = self.clock()
            try:
                answer = self.post(asked)
            except urllib.error.HTTPError as error:
                say(db, asked['id'], 'failed', 'tower-service', why=f'origin answered {error.code}', kid=self.kid)
                LOG.warning('checks: the check run on %s was refused: %s', asked['headSha'][:12], error.code)
                continue
            except Exception as error:  # noqa: BLE001 - said; the gate's client stops on it
                say(db, asked['id'], 'failed', 'tower-service', why=f'{type(error).__name__}: {error}'[:300], kid=self.kid)
                LOG.exception('checks: the check run on %s was not posted', asked['headSha'][:12])
                continue
            say(db, asked['id'], 'posted', 'tower-service', outcome=answer.get('outcome'), kid=self.kid,
                post_s=round(self.clock() - began, 3))
            posted += 1
        return posted


def from_environ(scope, environ=None):
    """The service's Poster, or None when the environment names no app key (a local run)."""
    environ = os.environ if environ is None else environ
    name, app_id, installation = (environ.get(each, '').strip() for each in (KEY_PARAMETER, APP_ID, INSTALLATION))
    if not (name and app_id and installation):
        return None

    def key():
        import boto3
        return boto3.client('ssm', region_name=environ.get('AWS_REGION')).get_parameter(
            Name=name, WithDecryption=True)['Parameter']['Value']
    return Poster(scope, key, app_id, installation)


def start(scope, stop, wait, active=None, environ=None, poster=None):
    """The look in a daemon thread, woken by tower_deploy (an asked check run notifies it); None when not configured.
    CHECK-IN-LANDING: the Poster is the forge's too (its token minted once), when the caller made it."""
    import threading
    poster = poster or from_environ(scope, environ)
    if poster is None:
        LOG.info('checks: off (no Origin app key named)')
        return None

    def loop():
        while not stop.is_set():
            if active is None or active():
                try:
                    with scope() as db:
                        poster.step(db)
                except Exception:  # noqa: BLE001 - the next notification looks again
                    LOG.exception('checks: look failed')
            wait(60)
    thread = threading.Thread(target=loop, name='checks', daemon=True)
    thread.start()
    return thread
