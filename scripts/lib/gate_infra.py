"""The gate over the infrastructure (GATE-INFRA 2, P5 F2): our management's adapter, outside the infrastructure (D-306),
that judges one PR head with the infrastructure's jobs, the way scripts/deliver judges it on the box.

The plan of a head is the gate's own: gate_policy's area plan of base...head and gate_script_tests' selection, computed
in a worktree of the head with the head's own selection code and registry when it has them. Each check becomes a job of
the container executor through the port, as config/management/gate-train.json says (always-stages,
selected-script-tests, exact-head): its command is scripts/gate-check, its input the exact commit with its base, and it
is memoized under a digest of what it reads: a script test's own key from the gate's test cache (the files its covers
name, as the box keys it, so a test whose inputs did not change comes from the cache on any head), else the head's tree;
the base's tree for a stage that compares with it; the two commits for the history scan; the day for the structure
check's age rules. `pr metadata` reads the forge with
management's credential and runs here, beside the jobs: a check job's command gets no credential. The landing is a job
of the forge executor that depends on every check (land-with-expected-head): the expected head, the rule's merge method
and exclusive key, head_moved never retried; in shadow it is a dry run, which checks the head and merges nothing. A
check that fails cancels the landing.

The adapter waits on the tenant's log, one read per poll and each read from the last event seen, never one call per
job. The verdict: green when the landing succeeded (in shadow: the head would land), red with the checks that failed,
moved when the head moved, late when the wait ran out; with the seconds to the verdict and from the last check to the
landing (ready to merged, measured in shadow), and the checks the runner could not even prepare (unprepared: a run that
ended not_started, a fault of the infrastructure, not of the head). The port is TOWER_PORT_URL with the tenant's token TOWER_PORT_TOKEN; with
neither, nothing is judged and the answer says so. A shadow never fails anything: it is a measure beside the box.

  scripts/gate-infra shadow --pr <n> [--head <sha>]   judge the PR's live head on the infrastructure, in shadow
  scripts/gate-infra plan --base <sha> --head <sha>   the plan of base...head in this checkout, as JSON
  scripts/gate-infra backfill [--last <n>] [--round <name>]   the last merged heads judged again, checks only (P5 F3)

land() is the same judgment with the real landing (GATE-INFRA 3, P5 F4): scripts/deliver calls it when delivery.judge is
infra; a late verdict cancels the landing, so a delivery that gave up never merges behind its back.
"""
import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import hashlib
from http import HTTPStatus
import json
import os
from pathlib import Path
import random
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request

LIB = Path(__file__).resolve().parent
ROOT = LIB.parent.parent
sys.path.insert(0, str(LIB))
import config  # noqa: E402

RULES = ROOT / 'config' / 'management' / 'gate-train.json'
METADATA = 'pr metadata'
COMMAND = ['scripts/gate-check']
# A head that predates scripts/gate-check (GATE-INFRA 2, 04/11) is judged by a later commit's copy (GATE-INFRA 7): read
# from the repository into a file outside the tree and run with GATE_CHECK_ROOT at the checkout, so the head's own tree
# and gate functions are judged, the way gate_test_cache's --tool-root runs the gate's tools on another tree.
TOOL_OF = ('tool="$(mktemp)"; trap \'rm -f "$tool"\' EXIT; '
           'git show "$1:scripts/gate-check" > "$tool" || { echo "gate-check: no scripts/gate-check at $1" >&2; exit 2; }; '
           'shift; GATE_CHECK_ROOT="$PWD" bash "$tool" "$@"')
READS_THE_BASE = ('secret scan (tree)', 'structure check', 'production guard', 'schema compat')
READS_THE_HISTORY = ('secret scan (history)',)
DATED = ('structure check',)
ENDED = ('succeeded', 'failed', 'stopped', 'cancelled')
RED = ('failed', 'stopped', 'cancelled')
FORGE = 'origin'
TRANSIENT = (HTTPStatus.TOO_MANY_REQUESTS, HTTPStatus.BAD_GATEWAY, HTTPStatus.SERVICE_UNAVAILABLE, HTTPStatus.GATEWAY_TIMEOUT)


class Refused(RuntimeError):
    """The port refused a call: its HTTP status and what it said."""

    def __init__(self, status, said):
        super().__init__(f'{status}: {said}')
        self.status = status


def encode(action):
    """A job's inline input, a data: URI of JSON (the shape the infrastructure's executors decode)."""
    return 'data:application/json;base64,' + base64.b64encode(json.dumps(action, sort_keys=True).encode()).decode()


def digest(*parts):
    return 'sha256:' + hashlib.sha256('\0'.join(str(part) for part in parts).encode('utf-8')).hexdigest()


def said(text):
    """The end of what a tool said, as long as a verdict keeps it."""
    return text.strip()[-config.get('gate-infra.said_chars'):]


def git(root, *args):
    return subprocess.run(['git', '-C', str(root), *args], check=True, capture_output=True, text=True).stdout.strip()


def rule(name):
    return next(item for item in json.loads(RULES.read_text(encoding='utf-8'))['rules'] if item['id'] == name)


def fast_lambda(paths):
    """True when the paths hold a fast Lambda target. An ImportError of the classifier is loud (FAST-ARTIFACT-FIX): a silent
    False once left a Lambda-only PR without its `artifact:lambda` job, and so without a fast swap."""
    import deploy_classify
    return any(t.startswith('fast:lambda-') for t in deploy_classify.classify(paths)['fast'])


def plan_here(base, head):
    """The gate's plan of base...head in this checkout of the head: the always stages and the script tests it selects,
    through the box's own selection (gate_test_cache.selection, GATE-INFRA 9), which also leaves out a test the change
    deletes with its manifest; a head whose test cache has no selection is planned by select_plan."""
    import gate_policy
    import gate_script_tests
    import gate_test_cache
    root = Path.cwd()
    paths = gate_policy.changed_paths(root, base, head)
    dev = gate_policy.select_dev_plan(paths, base, head, root)
    if 'script tests' not in dev['stages']:
        tests, reason = (), 'no script test'
    elif hasattr(gate_test_cache, 'selection'):
        tests, reason = gate_test_cache.selection(paths, base, root)
    else:
        tests, reason = gate_script_tests.select_plan(dev)
    hashes = {}  # one digest per file across the tests
    keys = {test: gate_test_cache.key(test, root, hashes=hashes) for test in tests}
    held = box_cached(gate_test_cache, keys)
    fast = fast_lambda(paths)  # DEP8: only a PR with a fast Lambda target builds a package
    return {'kind': dev['kind'], 'stages': [stage for stage in dev['stages'] if stage in gate_policy.PREREQUISITES],
            'artifacts': ['lambda'] if fast else [],
            'tests': [test for test in tests if test not in held], 'box_cached': sorted(held), 'reason': reason,
            'keys': {test: key for test, key in keys.items() if test not in held},
            'costs': {test: cost for test, cost in gate_test_cache.costs(root).items() if test in keys}
            if hasattr(gate_test_cache, 'costs') else {}}


def box_cached(gate_test_cache, keys):
    """The tests whose key the box's test cache holds a valid pass for (AWS2): the box does not run them, so neither
    does the infrastructure (gate-infra.box_cache). A store that cannot be read, or a head without the cache's lookup,
    holds none: the test is a job, as before."""
    try:  # a head older than this key plans with its own registry, which does not have it: no shortcut there
        if not config.get('gate-infra.box_cache') or not hasattr(gate_test_cache, 'lookup'):
            return {}
        location = gate_test_cache.store_location()
        return {test: True for test, key in keys.items() if key and gate_test_cache.lookup(location, key)}
    except Exception:  # noqa: BLE001 - the box's cache is a shortcut; whatever is wrong with it, run the test
        return {}


def plan_of(root, base, head):
    """The plan of base...head computed in a worktree of the head, by the head's own adapter when it has one. A head
    with selection code of its own but no adapter (before GATE-INFRA 2) gets this adapter copied into its worktree, so
    the head's own selection code and registry choose its checks, as its box did (GATE-INFRA 7); run from here, this
    adapter would choose with today's covers, tests the head never had."""
    with tempfile.TemporaryDirectory() as tmp:
        tree = Path(tmp) / 'head'
        git(root, 'worktree', 'add', '--quiet', '--detach', str(tree), head)
        try:
            own = tree / 'scripts' / 'lib' / 'gate_infra.py'
            if not own.is_file() and (own.parent / 'gate_policy.py').is_file():
                shutil.copyfile(Path(__file__).resolve(), own)
            classifier = own.parent / 'deploy_classify.py'  # FAST-ARTIFACT-FIX: a head without it gets the judge's, not a silent no
            if own.parent.is_dir() and not classifier.is_file():
                shutil.copyfile(LIB / 'deploy_classify.py', classifier)
            done = subprocess.run([sys.executable, str(own if own.is_file() else Path(__file__).resolve()), 'plan',
                                   '--base', base, '--head', head], cwd=tree, capture_output=True, text=True,
                                  check=False)
        finally:
            git(root, 'worktree', 'remove', '--force', str(tree))
    if done.returncode:
        raise RuntimeError(f'gate-infra: no plan for {head}: {said(done.stderr)}')
    plan = json.loads(done.stdout)
    # FAST-ARTIFACT-FIX: the head's own adapter (or its tree, which may lack the classifier) must not decide the artifact:
    # the judge's own classifier names the fast Lambda target from the PR's paths, whatever the head's plan said.
    paths = [each for each in git(root, 'diff', '--no-renames', '--name-only', f'{base}...{head}').split('\n') if each]
    if fast_lambda(paths) and 'lambda' not in (plan.get('artifacts') or []):
        plan['artifacts'] = [*(plan.get('artifacts') or []), 'lambda']
    return plan


def pregate_jobs(root, base, head, plan, today=None):
    """PRE-GATE: [{name, body}] of the check jobs the delivery's gate makes for this plan of base...head (checks()): the same
    input_digest each, so the port's cache answers the gate with what the pre-gate already ran. Their idempotency is the
    head's, keyed apart from a delivery's (the PR is not known when the branch is pushed)."""
    trees = {name: git(root, 'rev-parse', f'{sha}^{{tree}}') for name, sha in (('head', head), ('base', base))}
    spec = {'repo': config.get('forge-events.repo'), 'pr': 'pregate', 'head': head, 'base': base, 'ref': ''}
    today = today or datetime.now(timezone.utc).date().isoformat()
    made = []
    for name, body in checks(spec, fast_plan(plan, root, base, head), trees, today):
        made.append({'name': name, 'body': dict(body, idempotency_key=f'pregate:{head}:{base}:{name}')})
    return made


def fast_plan(plan, root, base, head):
    """The plan with FAST-ARTIFACT-FIX's artifact, as the delivery's gate completes it (planned, plan_of)."""
    paths = [each for each in git(root, 'diff', '--no-renames', '--name-only', f'{base}...{head}').split('\n') if each]
    if fast_lambda(paths) and 'lambda' not in (plan.get('artifacts') or []):
        return {**plan, 'artifacts': [*(plan.get('artifacts') or []), 'lambda']}
    return plan


def planned(port, spec, sleep=time.sleep, clock=time.monotonic):
    """PLAN-ON-RUNNER: the plan of base...head computed on the runner, in its checkout of the head, by the head's own
    adapter (scripts/gate-check plan checks), first in the checks' queue; (plan, seconds), or (None, why) when there is no
    answer (a runner or a head older than it, a run that failed): the lane plans it then, as before."""
    try:
        return _planned(port, spec, sleep, clock)
    except Exception as error:  # noqa: BLE001 - the lane plans it, as before
        return None, f'{type(error).__name__}: {error}'[:200]


def _planned(port, spec, sleep, clock):
    started = clock()
    body = {'queue': config.get('gate-infra.check_queue'), 'rank': RANK_PER_CHECK * RANK_CAP, 'selector': {'adapter': 'container'},
            'memoize': True,
            'input_uri': encode({'repo': spec['repo'], 'ref': spec['ref'], 'commit': spec['head'], 'base': spec['base'],
                                 'command': command_of(['plan', 'checks', '--base', spec['base']], spec.get('tools')),
                                 'timeout_s': config.get('gate-infra.check_timeout_s')}),
            'input_digest': digest('gate-plan', spec['head'], spec['base']),
            'idempotency_key': f"plan:{spec['pr']}:{spec['head']}:{spec['base']}" + (f":{spec['round']}" if spec.get('round') else '')}
    job = port.call('POST', '/v1/jobs', body)['id']
    deadline = started + config.get('gate-infra.metadata_blind_wait_s')
    while True:
        found = port.call('GET', f'/v1/jobs/{job}')
        if found['state'] in ENDED:
            break
        if clock() >= deadline:
            return None, 'no answer in time'
        sleep(config.get('gate-infra.poll_last_s'))
    answer = (found.get('result') or {}).get('answer') or {}
    if found['state'] != 'succeeded' or not isinstance(answer.get('plan'), dict):
        return None, f"the plan job ended {found['state']}{': ' + str(answer.get('refused')) if answer.get('refused') else ''}"
    plan = answer['plan']
    # FAST-ARTIFACT-FIX: the judge's own classifier names the fast Lambda target from the PR's paths, as plan_of does
    if fast_lambda(answer.get('paths') or []) and 'lambda' not in (plan.get('artifacts') or []):
        plan['artifacts'] = [*(plan.get('artifacts') or []), 'lambda']
    return plan, round(clock() - started, 3)


# STAGE-RANK-BY-COST: a stage's seconds on the runner (the gates of #627 to #631, 13/11), so it takes its place among the
# tests by what it costs: every stage first made a slot's first test wait behind it (10.7 and 12.9 s in #631)
STAGE_COSTS = {'structure check': 12.0, 'production guard': 1.0, 'secret scan (tree)': 7.0, 'secret scan (history)': 7.0, 'schema compat': 3.0,
               'generated drift': 4.0, 'no GitHub Actions workflows': 2.0}
STAGE_COST_UNKNOWN = 5.0
# UNMEASURED-MIDDLE: a test with no cost hint is placed as a 10 s one, not last: #635's runner-env.test.sh (18.8 s on
# the runner, no hint) started at 35.9 s, behind every measured test, and ended the gate at 54.8 s
UNMEASURED_S = 10.0
RANK_PER_CHECK, RANK_CAP = 1000, 1000  # rank = 1000 * (1000 - checks of the head) + cost in s, under 1000


def command_of(args, tools=None):
    """A check's command: the head's own scripts/gate-check, or, with `tools` (a commit that has it), that commit's copy
    on the head's tree (TOOL_OF), for a head that predates it."""
    return ['bash', '-c', TOOL_OF, 'gate-check', tools, *args] if tools else [*COMMAND, *args]


def checks(spec, plan, trees, today):
    """The check jobs of a head, as (name, body); pr metadata is management's own, never a job. spec['tools'], when set,
    is the commit whose scripts/gate-check judges a head that has none (GATE-INFRA 7), named in each job's key."""
    made = []
    for stage in plan['stages']:
        if stage == METADATA:
            continue
        args, reads = ['stage', stage], [stage, trees['head']]
        if stage in READS_THE_BASE + READS_THE_HISTORY:
            args += ['--base', spec['base']]
            reads += [spec['base'], spec['head']] if stage in READS_THE_HISTORY else [trees['base']]
        if stage in DATED:
            reads.append(today)
        made.append((f'stage:{stage}', args, reads))
    keys, costs = plan.get('keys') or {}, plan.get('costs') or {}  # no key of its own (no covers, cache off): the tree
    # the longest first, as the box orders them: the slots take the jobs in the order they were made, so the longest
    # test starts at once instead of last (a hint only: the unmeasured keep the plan's order after the measured)
    ordered = sorted(plan['tests'], key=lambda test: -costs.get(test, UNMEASURED_S))
    made += [(f'test:{test}', ['test', test], [test, keys.get(test) or trees['head']]) for test in ordered]
    for artifact in plan.get('artifacts') or []:  # DEP8: the zip of the port's Lambdas, built from this head and kept by digest
        made.append((f'artifact:{artifact}', ['artifact', artifact, '--base', spec['base']], [f'artifact:{artifact}', spec['head']]))
    queue, timeout, tools = config.get('gate-infra.check_queue'), config.get('gate-infra.check_timeout_s'), spec.get('tools')
    # AWS8: for a queue of policy rank (PUT /v1/queues/checks {"policy": "rank"}; fifo ignores it) the head with the
    # fewest checks goes first and, inside a head, the longest: a small head no longer waits behind a big one's tail
    heavy = {f'test:{test}': costs.get(test, UNMEASURED_S) for test in plan['tests']}
    # STAGE-RANK-BY-COST: a stage by its measured seconds, like a test; the made jobs in that order too, since a job
    # created later (47 jobs took 7.2 s to create in #633) cannot be taken before it is made. An artifact keeps its place
    heavy.update({f'stage:{stage}': STAGE_COSTS.get(stage, STAGE_COST_UNKNOWN) for stage in plan['stages']})
    made.sort(key=lambda each: -heavy.get(each[0], RANK_PER_CHECK))
    # UID0-FROM-BASE (the Torre, 13/11 ~14:15 BRT): a test that needs a real uid 0 process runs as root from the base's landed
    # code (its file and its harness the base's), never from the PR's head; the runner gives root only to a commit the forge
    # pushed to the base branch (runner.check_user), so no PR code is in the root process
    rooted = {f'test:{test}' for test in config.get('gate-infra.root_from_base_tests')}
    base_ref = spec.get('base_ref') or ''
    base_ref = base_ref if base_ref.startswith('refs/') else f'refs/heads/{base_ref}'

    def where(name):
        if name in rooted:
            return {'ref': base_ref, 'commit': spec['base'], 'user': 'root'}
        return {'ref': spec['ref'], 'commit': spec['head']}
    return [(name, {'queue': queue, 'rank': RANK_PER_CHECK * (RANK_CAP - len(made)) + min(heavy.get(name, RANK_PER_CHECK), RANK_PER_CHECK - 1),
                    'selector': {'adapter': 'container'},
                    # FAST-ARTIFACT-NOCACHE: an artifact job is a side effect (the head's manifest in S3), never a cached
                    # verdict: the port's result cache must not answer it; the job itself is a no-op when the manifest exists
                    'memoize': not name.startswith('artifact:'),
                    'input_uri': encode({'repo': spec['repo'], **where(name),
                                         'base': spec['base'], 'command': command_of(args, tools),
                                         'timeout_s': timeout}),
                    'input_digest': digest('gate-check', *reads) if name not in rooted
                    else digest('gate-check', 'uid0-from-base', name, spec['base']),
                    'idempotency_key': f"check:{spec['pr']}:{spec['head']}:{name}"
                                       + (f":{spec['round']}" if spec.get('round') else '')
                                       + (f':tools-{tools}' if tools else '')})
            for name, args, reads in made]


def landing(spec, depends_on, shadow, check_run=None):
    """The landing of a head once every check passed: the forge's land with the expected head (a dry run in shadow).
    CHECK-IN-LANDING: with the tower/gate success's body, which the forge posts right before it merges."""
    land = rule('land-with-expected-head')
    mode = 'shadow' if shadow else 'land'
    action = {'action': 'land', 'repo': spec['repo'], 'pr': str(spec['pr']), 'head': spec['head'],
              'method': land['value']['method'], 'dry_run': bool(shadow)}
    if check_run is not None and not shadow:
        action['check_run'] = check_run
    return {'queue': config.get('gate-infra.land_queue'), 'selector': land['job']['selector'],
            'input_uri': encode(action), 'input_digest': digest('land', spec['pr'], spec['head'], mode),
            'idempotency_key': f"land:{spec['pr']}:{spec['head']}:{mode}",
            'exclusive_key': land['job']['exclusive_key'].format(forge=FORGE, repo=spec['repo'], base=spec['base_ref']),
            'max_attempts': config.get('gate-infra.landing_attempts'), 'non_retryable': ['head_moved', 'merged'],
            'depends_on': list(depends_on)}


class Port:
    """The infrastructure's port over HTTP with the tenant's token; call is replaceable (the test's port in
    process)."""

    def __init__(self, url, token, call=None, opener=urllib.request.urlopen, sleep=time.sleep,
                 jitter=random.uniform):
        self.url, self.token = (url or '').rstrip('/'), token
        self.colds = []  # GATE-COLD-PARTS: (the call, its wall s, the port's cold ms) of each answer a cold Lambda gave
        self.call = call or self.http
        self.opener, self.sleep, self.jitter = opener, sleep, jitter

    def http(self, method, path, body=None):
        """One call to the port. A transient answer (429 from the API Gateway's throttle, 502, 503, 504, or a
        connection that drops: the port's Lambda starting cold answers 503 past the HTTP API's 30 s) is tried again,
        at most gate-infra.call_retries times and gate-infra.call_max_wait_s seconds of pauses in all, each pause a
        full jitter of an exponential (gate-infra.call_backoff_s doubling) or the answer's Retry-After; one line per
        retry on stderr. A 429 is the throttle rejecting the request before the port saw it, and the port's commands
        are idempotent by their key, so a repeat makes nothing twice."""
        retries, base = config.get('gate-infra.call_retries'), config.get('gate-infra.call_backoff_s')
        limit, waited = config.get('gate-infra.call_max_wait_s'), 0.0
        for attempt in range(retries + 1):
            request = urllib.request.Request(self.url + path, method=method,
                                             data=json.dumps(body or {}).encode('utf-8'),
                                             headers={'Authorization': f'Bearer {self.token}',
                                                      'Content-Type': 'application/json'})
            hinted, began = None, time.monotonic()
            try:
                with self.opener(request, timeout=config.get('gate-infra.call_timeout_s')) as answer:
                    answered = json.loads(answer.read() or b'{}')
                    cold = COLD.search(str((getattr(answer, 'headers', None) or {}).get('Server-Timing') or ''))
                    if cold:  # GATE-COLD-PARTS: PORT-COLD-START's mark: this call started a Lambda environment
                        self.colds.append((f"{method} {re.sub(r'[0-9a-f-]{36}', '<id>', path)}",
                                           round(time.monotonic() - began, 3), float(cold.group(1))))
                    return answered
            except urllib.error.HTTPError as error:
                told = (error.headers or {}).get('Retry-After')
                hinted = float(told) if told and re.fullmatch(r'\d+(\.\d+)?', told.strip()) else None
                why = error.code
                refusal = (error.code, said(error.read().decode('utf-8', 'replace')))
                if error.code not in TRANSIENT:
                    raise Refused(*refusal) from None
            except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
                why = type(error).__name__
                refusal = (HTTPStatus.SERVICE_UNAVAILABLE, f'{type(error).__name__}: {error}')
            pause = hinted if hinted is not None else self.jitter(0, base * 2 ** attempt)
            if attempt == retries or waited + pause > limit:
                raise Refused(refusal[0], f'{refusal[1]} (gave up after {attempt + 1} call(s), {waited:.1f} s waited)') from None
            print(f'gate-infra: {method} {path} answered {why}; retry {attempt + 1}/{retries} in {pause:.1f} s',
                  file=sys.stderr)
            self.sleep(pause)
            waited += pause


COLD = re.compile(r'(?:^|,\s*)cold;dur=([0-9.]+)')


def when(stamp):
    return datetime.fromisoformat(stamp)


def ended(event):
    """The state a log event ends a job in, or None when it ends none (a run that goes back to the queue)."""
    found = {'cache.hit': 'succeeded', 'job.cancelled': 'cancelled'}.get(event['type'])
    if event['type'] == 'run.ended':
        found = (event.get('payload') or {}).get('state')
    return found if found in ENDED else None


def last_error(job):
    """The error type of a job's last run that named one (GET /v1/jobs/<id>), else None."""
    return next((run.get('error_type') for run in reversed(job.get('runs') or []) if run.get('error_type')), None)


def judge(port, spec, plan, trees, today, shadow=True, metadata=None, sleep=time.sleep, clock=time.monotonic,
          now=None, landing_too=True, before_landing=None, retry=False, progress=None):
    """Create a head's checks and landing through the port, wait on the log, and answer the verdict; with landing_too
    False (a head that merged already, judged again for P5 F3) the checks alone decide it. With before_landing (F37-INFRA-CHECK,
    D-313) the landing is created only after the checks are decided and before_landing(ok, red, seconds) has run, so the
    forge sees the verdict on the head (tower/gate) before it merges; it raises to stop the delivery. With retry (the
    landing path), checks that all ended not_started, the runner's word that it could not prepare them and no word on the
    code, are made again once, under a round of their own, before anything is declared red or before_landing runs."""
    started = clock()
    skew = timedelta(seconds=config.get('gate-infra.clock_skew_s'))
    since = ((now or datetime.now(timezone.utc)) - skew).isoformat()
    told = {}
    thread = None
    if metadata and METADATA in plan['stages']:
        thread = threading.Thread(target=lambda: (told.update(zip(('green', 'said'), metadata())),
                                                  told.update(done_at=clock())), daemon=True)
        thread.start()
    names, states, at, cached, unprepared = {}, {}, {}, set(), set()

    def retried(spec, jobs, spent):
        """The checks again, once, under a round of their own (their keys are new); the first try is named."""
        round_ = 'unprepared-retry-' + (now or datetime.now(timezone.utc)).strftime('%Y%m%dT%H%M%S')
        if thread is not None:
            thread.join()
        told_already = (lambda: (told.get('green', True), told.get('said'))) if thread is not None else metadata
        second = judge(port, dict(spec, round=round_), plan, trees, today, shadow, told_already, sleep, clock, now,
                       landing_too, before_landing, retry=False)
        second['retried'] = sorted(names[job] for job in jobs)
        second['seconds'] += spent
        return second

    def make(body):
        return settle(port.call('POST', '/v1/jobs', body))

    def settle(made):
        if not made.get('created', True):  # the same head judged again: the job may have ended already
            found = port.call('GET', f"/v1/jobs/{made['id']}")
            if found['state'] in ENDED:
                states[made['id']] = found['state']
                if last_error(found) == 'not_started':  # its log events are older than this wait: the run says it
                    unprepared.add(made['id'])
        return made['id']
    bodies = checks(spec, plan, trees, today)
    # JOBS-BATCH: the head's jobs in one call, which the port's warm Lambda answers: made four at a time, they reached
    # cold instances (#636: 9.9 s to make 39, its longest checks made at 9.5 s). A port without the route: as before
    try:
        batch = port.call('POST', '/v1/jobs/batch', {'jobs': [body for _, body in bodies]})['jobs'] if bodies else []
    except Refused as error:
        if error.status != HTTPStatus.NOT_FOUND:
            raise
        batch = None
    if batch is not None:
        for (name, _body), made in zip(bodies, batch):
            names[settle(made)] = name
    else:
        with ThreadPoolExecutor(max_workers=max(1, min(config.get('gate-infra.create_parallel'), len(bodies) or 1))) as pool:
            for (name, _body), job in zip(bodies, pool.map(lambda each: make(each[1]), bodies)):  # in order, at once
                names[job] = name
    created = clock() - started
    held = landing_too and before_landing is not None
    land = make(landing(spec, names, shadow)) if landing_too and not held else None
    firsts, checks_done, parts = {}, None, {}  # LANDING-PARTS: when the landing's steps came, from the start
    seen, deadline, verdict, red = set(), started + config.get('gate-infra.wait_s'), None, []
    while verdict is None:
        if progress is not None:  # TRAIN-LEASE-IN-JUDGMENT: the judgment is alive: the train's lease follows it
            progress()
        for event in port.call('POST', '/v1/log/query', {'since': since,
                                                          'limit': config.get('gate-infra.log_limit')})['events']:
            if event['event_id'] in seen:
                continue
            seen.add(event['event_id'])
            since = event['occurred_at']
            job, state = (event.get('payload') or {}).get('job_id'), ended(event)
            if state and (job in names or job == land):
                states[job], at[job] = state, event['occurred_at']
                firsts.setdefault(job in names, clock() - started)
                if event['type'] == 'cache.hit':
                    cached.add(job)
                if (event.get('payload') or {}).get('error_type') == 'not_started':  # the runner could not prepare it
                    unprepared.add(job)
        if checks_done is None and names and all(job in states for job in names):
            checks_done = clock()
        red = [METADATA] if thread is not None and not thread.is_alive() and not told.get('green', True) else []
        red += sorted(names[job] for job, state in states.items() if job in names and state in RED)
        again = [job for job, state in states.items() if job in names and state in RED]
        if retry and land is None and red and len(red) == len(again) and all(job in unprepared for job in again):
            if all(job in states for job in names):  # nothing else is running: the checks never judged the code
                return retried(spec, again, clock() - started)
            if clock() <= deadline:
                sleep(config.get('gate-infra.poll_s'))
                continue
        decided = thread is None or not thread.is_alive()
        if held and land is None and decided and (red or all(states.get(job) == 'succeeded' for job in names)):
            begun = clock()  # LANDING-PARTS
            # D-313: the verdict on the head before the forge merges it; CHECK-IN-LANDING: or the success's body, which the
            # landing posts right before its merge
            said = before_landing(not red, red, clock() - started)
            parts.update(before_at=begun - started, before_s=clock() - begun)
            said = said if isinstance(said, dict) else {}  # a hook that hands nothing back published it itself
            parts.update(said.get('parts') if isinstance(said.get('parts'), dict) else {})
            if red:
                verdict = 'red'
            else:
                land = make(landing(spec, names, shadow, check_run=said.get('body') if isinstance(said.get('body'), dict) else None))
                parts['land_made_at'] = clock() - started
        elif held and land is None and red:  # a check red while the metadata stage still runs
            before_landing(False, red, clock() - started)
            verdict = 'red'
        elif land is None and not held and not red and all(states.get(job) == 'succeeded' for job in names):
            verdict = 'green'
        elif land in states:
            verdict = 'green' if states[land] == 'succeeded' else 'red'
        elif red:
            if land is not None:
                port.call('POST', f'/v1/jobs/{land}/cancel', {})
            verdict = 'red'
        elif clock() > deadline:
            if held and land is None:
                before_landing(False, ['late'], clock() - started)
            verdict = 'late'
        else:
            last = len([job for job in names if job not in states]) <= 1  # the verdict is seconds away (AWS9)
            sleep(min(config.get('gate-infra.poll_s'), config.get('gate-infra.poll_last_s')) if last
                  else config.get('gate-infra.poll_s'))
    if thread is not None:
        thread.join()
        if not told.get('green', True) and METADATA not in red:
            verdict, red = 'red', [METADATA, *red]
    landed = port.call('GET', f'/v1/jobs/{land}') if land is not None else {}
    error = last_error(landed)
    merged_first = shadow and verdict == 'red' and not red and merged_already(error, landed.get('result'))
    if merged_first:  # every check green and the box merged the PR before the dry run: the infrastructure's green
        verdict = 'green'
    elif verdict == 'red' and not red:
        verdict, red = ('moved', []) if error == 'head_moved' else ('red', [f'landing: {error}'])
    ready = max((when(at[job]) for job in names if job in at), default=None)
    return {'pr': spec['pr'], 'head': spec['head'], 'base': spec['base'], 'shadow': bool(shadow), 'verdict': verdict,
            'red': red, 'checks': len(names), 'from_cache': len(cached), 'seconds': clock() - started,
            'box_cached': list(plan.get('box_cached') or []),
            # where the wall time went (AWS2): the jobs made, the first check ended, the last one ended; the rest of
            # `seconds` is the landing (a dry run in shadow) and the wait for the poll
            'phases': {'created_s': round(created, 3), 'first_check_s': round(firsts[True], 3) if True in firsts
                       else None, 'checks_s': round(checks_done - started, 3) if checks_done is not None else None,
                       # LANDING-PARTS: the metadata check's end, the hook before the landing (its start and length:
                       # the train's front and the verdict's publish) and the landing job made
                       **({'metadata_s': round(told['done_at'] - started, 3)} if told.get('done_at') else {}),
                       **{name: round(value, 3) for name, value in parts.items()}},
            'unprepared': sorted(names[job] for job in unprepared if job in names),
            'ready_to_landed_s': ((when(at[land]) - ready).total_seconds() if ready is not None and land in at
                                  else None),
            'landing': {'id': land, 'state': landed.get('state'), 'error': error, 'result': landed.get('result'),
                        **({'landed_by': 'box'} if merged_first else {})},
            'metadata': told.get('said')}


# METADATA-FORGE-RETRY: the refusals of `pr metadata` that say the forge could not be read (structure.Blind): not a word
# about the PR
BLIND = re.compile(r'^FAIL (commit-check|review): PR #\d+ not readable \(')


def blind(text):
    """Whether everything `pr metadata` refused was the forge not answering: the PR was not judged."""
    refused = [line for line in text.splitlines() if line.startswith('FAIL ')]
    return bool(refused) and all(BLIND.match(line) for line in refused)




def observed(port, pr, head, sleep=time.sleep, clock=time.monotonic):
    """PR-OBSERVATION: what the live service read of PR `pr` on `head` with the forge's key (POST /v1/pr-observation and
    its state): (observation, None), (None, why) when it could not read it, or None when the port has no route (a port
    older than PR-OBSERVATION: the lane reads the forge itself, as before)."""
    try:
        asked = port.call('POST', '/v1/pr-observation', {'pr': int(pr), 'head': head})
    except Refused as error:
        if error.status == HTTPStatus.NOT_FOUND:
            return None
        return None, f'the port refused the observation ({error.status})'
    # the wait of a blind read (gate-infra.metadata_blind_wait_s), asked at the landing's short poll; #643 was read in 4.4 s
    wait_s, poll_s = config.get('gate-infra.metadata_blind_wait_s'), config.get('gate-infra.poll_last_s')
    deadline = clock() + wait_s
    while True:
        said = port.call('GET', f"/v1/pr-observation/{asked['id']}")
        if said.get('state') == 'observed':
            # OBSERVE-HTTP: the live service's own read, its seconds and each read's, in the gate's record
            METADATA_PARTS.update(metadata_read_s=said.get('read_s'), metadata_read=said.get('parts'))
            return {**said['observation'], 'head': head}, None
        if said.get('state') == 'failed':
            return None, f"the live service could not read it: {said.get('why')}"
        if clock() >= deadline:
            return None, f'the live service did not read it in {wait_s:.0f} s'
        sleep(poll_s)


# GATE-COLD-PARTS: the metadata stage's parts of the last delivery of this process: the observation (the port and the
# live service) and the structure check run on it
METADATA_PARTS = {}


def metadata_of(pr, base, run=subprocess.run, sleep=time.sleep, jitter=random.uniform, port=None, head=None):
    """`pr metadata`, the box's own stage, judged by management with its credential; (green, what it said).
    METADATA-FORGE-RETRY (the review's finding 22): on 11/11 03:04 UTC the forge answered 503 for about three minutes
    and a delivery was judged red at `pr metadata` with nothing wrong in its PR. A run whose only refusals are the forge
    not answering is tried again, as a call to the port is (gate-infra.call_retries, a full jitter of
    gate-infra.call_backoff_s doubling), for gate-infra.metadata_blind_wait_s of pauses at most; one line per retry on
    stderr. A forge that stays away is still red, fail closed, and says so by name: the PR was not judged.
    PR-OBSERVATION: with the port and the head, what is judged is what the live service read with the forge's key (the
    lane's login and reflog off the path); a service that could not read it counts as a forge that did not answer."""
    command = [str(ROOT / 'scripts' / 'structure-check'), '--metadata', '--pr', str(pr), '--base', base, '--no-publish']
    METADATA_PARTS.clear()
    retries, backoff = config.get('gate-infra.call_retries'), config.get('gate-infra.call_backoff_s')
    limit, waited = config.get('gate-infra.metadata_blind_wait_s'), 0.0
    for attempt in range(retries + 1):
        began, seen = time.monotonic(), None
        if port is not None and head:
            seen = observed(port, pr, head, sleep=sleep)
            METADATA_PARTS['metadata_observe_s'] = round(METADATA_PARTS.get('metadata_observe_s', 0) + time.monotonic() - began, 3)
        if seen is not None and seen[0] is None:
            text = f'FAIL commit-check: PR #{pr} not readable ({seen[1]})'
        else:
            with tempfile.TemporaryDirectory() as tmp:
                extra = []
                if seen is not None:
                    path = Path(tmp) / 'observation.json'
                    path.write_text(json.dumps(seen[0]))
                    extra = ['--observation', str(path)]
                began = time.monotonic()
                done = run(command + extra, cwd=ROOT, capture_output=True, text=True, check=False)
                METADATA_PARTS['metadata_check_s'] = round(METADATA_PARTS.get('metadata_check_s', 0) + time.monotonic() - began, 3)
            text = done.stdout + done.stderr
            if done.returncode == 0 or not blind(text):
                return done.returncode == 0, said(text)
        pause = jitter(0, backoff * 2 ** attempt)
        if attempt == retries or waited + pause > limit:
            break
        print(f'gate-infra: pr metadata could not read the forge; retry {attempt + 1}/{retries} in {pause:.1f} s',
              file=sys.stderr)
        sleep(pause)
        waited += pause
    return False, said(f'{text.strip()}\npr metadata: the forge did not answer the read of PR #{pr} ({attempt + 1} tries, '
                       f'{waited:.1f} s waited): the PR was not judged')


def folder():
    """Where the shadow keeps its verdicts and logs, and the box keeps its verdict beside them."""
    where = Path(os.environ.get('XDG_CACHE_HOME') or Path.home() / '.cache') / 'the-tower' / 'gate-infra'
    where.mkdir(parents=True, exist_ok=True)
    return where


def kept(verdict):
    path = folder() / f"pr-{verdict['pr']}-{verdict['head']}.json"
    path.write_text(json.dumps(verdict, indent=1) + '\n')
    return path


def merged_already(error, result):
    """The dry run found the PR merged: the forge's own error since GATE-INFRA 6, or the words of the forge executor
    deployed before it (a generic refused)."""
    return error == 'merged' or (error == 'refused' and (result or {}).get('detail') == 'the pull request is merged')


def kept_box(verdict):
    """The box's verdict on a head the shadow judges too (GATE-INFRA 4): box-<pr>-<head>.json beside the shadow's."""
    path = folder() / f"box-{verdict['pr']}-{verdict['head']}.json"
    path.write_text(json.dumps(verdict, indent=1) + '\n')
    return path


def merged(root, ref, last):
    """The last merges of the base branch, newest first, as (pr, base, head): a merge commit's first parent is the base
    the box judged the head against, its second the head it merged."""
    found = []
    for line in git(root, 'log', '--first-parent', '--merges', f'--max-count={last}', '--format=%H %P %s',
                    f'origin/{ref}').splitlines():
        _merge, base, head, *subject = line.split(' ')
        number = re.search(r'\(#(\d+)\)$', ' '.join(subject))
        if number:
            found.append((number.group(1), base, head))
    return found


def port_from_env():
    url, token = os.environ.get('TOWER_PORT_URL'), os.environ.get('TOWER_PORT_TOKEN')
    if not url or not token:
        raise RuntimeError('delivery.judge is infra but the port is not configured (TOWER_PORT_URL and '
                           'TOWER_PORT_TOKEN)')
    return Port(url, token)


LAMBDAS = {'port': 'tower-port-api', 'ingress': 'tower-port-ack-ingress', 'webhooks': 'tower-port-webhook-consumer'}


def landed_event(root, pr, head, base, merge_sha):
    """FAST-ON-LANDED: what the merge changed, for the registry's platform.deploy.landed. Origin's push events carry no file
    lists, so the autodeploy reads its fast targets from this: the Lambdas the gate's fast classifier names for the PR's
    paths (the ones its `artifact:lambda` job built a package for, [] for none), the manifest that job wrote, the paths."""
    import deploy_classify
    paths = [each for each in git(root, 'diff', '--no-renames', '--name-only', f'{base}...{head}').split('\n') if each]
    targets = [t for t in deploy_classify.classify(paths)['fast'] if t.startswith('fast:lambda-')]
    names = sorted({name for t in targets for name in (LAMBDAS.values() if t == 'fast:lambda-all' else
                                                       [LAMBDAS[t[len('fast:lambda-'):]]])})
    return {'merge_sha': merge_sha, 'base_before': base, 'pr': str(pr), 'pr_head': head, 'functions': names,
            'manifest_key': f'artifacts/lambda/head/{head}.json', 'paths': paths, 'code': landed_code(root, head, base, paths)}


def landed_code(root, head, base, paths):
    """IMAGE-PREWARM-C: whether the merge runs the PR head's code bundle, so the autodeploy may swap to the head's standbys.
    code_only of the PR's paths (deploy_classify, as the prewarm's job judged them) and bundle_same: the base changed none
    of the bundle's inputs (lambda_package.CODE_INPUTS) since the PR left it (head...base), so the clean merge's inputs are
    the head's, file by file, and build_code gives the same bytes. Local git only: no call to the forge."""
    import deploy_classify
    import lambda_package
    ok, why = deploy_classify.code_only(paths)
    moved = [each for each in git(root, 'diff', '--no-renames', '--name-only', f'{head}...{base}', '--',
                                  *map(str, lambda_package.CODE_INPUTS)).split('\n') if each]
    return {'code_only': ok, 'why': why, 'bundle_same': not moved, **({'moved': moved[:5]} if moved else {})}


def announce_landed(port, root, pr, head, base, judged):
    """After the forge merge succeeded: tell the registry (POST /v1/deploy/landed). The PR is merged already, so a failure
    here is a line on stderr, never a failed delivery: the push-path of the autodeploy and the slow ring stay the net."""
    landing = judged.get('landing') or {}
    merge_sha = (landing.get('result') or {}).get('merge_sha')
    if judged.get('verdict') != 'green' or landing.get('state') != 'succeeded' or not merge_sha:
        return None
    try:
        return port.call('POST', '/v1/deploy/landed', landed_event(root, pr, head, base, merge_sha))
    except Exception as error:  # noqa: BLE001 - merged already: the slow path is the net
        print(f'gate-infra: platform.deploy.landed for #{pr} not recorded: {error}', file=sys.stderr)
        return None


def land(pr, head, base, ref, base_ref, root=ROOT, port=None, judged=None, publisher=None, front=None, progress=None):
    """The head judged and landed by the infrastructure (not a shadow): (verdict, what the late cancel answered). With
    `front` (the merge train, scripts/lib/merge_train.py) the landing is held until the checks are decided and front(ok, red,
    seconds) has returned: it blocks until this delivery is the front and raises to send it back to merge the base.
    BASE-MOVED-SWAP: front answers the base's tip when the base moved and the verdict stands (else None); the landing is
    announced against it, the parent the merge has: base_before and bundle_same are then the merge's own, and a
    code-only landing whose base moved elsewhere swaps in a second instead of waiting for the slow path."""
    at = {}
    if port is None:
        port = port_from_env()
    spec = {'repo': config.get('forge-events.repo'), 'pr': str(pr), 'head': head, 'base': base, 'ref': ref,
            'base_ref': base_ref}
    if judged is None:
        began = time.monotonic()
        plan, plan_said = planned(port, spec)  # PLAN-ON-RUNNER: the lane's worktree and Python off the plan's path
        plan_by = 'runner' if plan is not None else 'lane'
        if plan is None:
            print(f'gate-infra: the runner gave no plan ({plan_said}): the lane plans it', file=sys.stderr)
            plan = plan_of(root, base, head)
        plan_s = round(time.monotonic() - began, 3)
        trees = {name: git(root, 'rev-parse', f'{spec[name]}^{{tree}}') for name in ('head', 'base')}
        import gate_status
        hooks = gate_status.check_hooks(head, publisher)
        if hooks:
            hooks[0]()  # D-313: tower/gate pending on the head before the checks are created

        def before(ok, red, seconds):
            began = time.monotonic()
            if front:
                at['base'] = front(ok, red, seconds)  # the train first: a stale entry must not publish a verdict it will not land
            fronted = time.monotonic()
            body = hooks[1](ok, red, seconds, landing=True) if hooks else None  # CHECK-IN-LANDING: the body, or published
            return {'body': body, 'parts': {'front_s': round(fronted - began, 3), 'publish_s': round(time.monotonic() - fronted, 3),
                                            'check_in_landing': body is not None}}
        with gate_status.trails_held():  # TRAIL-AFTER-LANDING: the success's trail is pushed once the forge merged
            judged = judge(port, spec, plan, trees, datetime.now(timezone.utc).date().isoformat(), shadow=False,
                           metadata=lambda: metadata_of(pr, base, port=port, head=head),  # PR-OBSERVATION
                           before_landing=before if front or hooks else None,
                           retry=True, progress=progress)
        judged.setdefault('phases', {}).update(plan_s=plan_s, plan_by=plan_by)  # PLAN-ON-RUNNER: measured with the verdict
        # GATE-COLD-PARTS: the port's calls that started a Lambda environment, and the metadata stage's two parts
        judged['phases'].update(cold_calls=list(getattr(port, 'colds', [])), **METADATA_PARTS)
        kept(judged)  # GATE-INFRA 10: beside the shadow's, so medir measures ready to merged on the real merges too
    announce_landed(port, root, pr, head, at.get('base') or base, judged)
    cancelled = None
    if judged['verdict'] == 'late' and judged['landing']['id']:  # the delivery gives up: the landing must not merge behind its back
        try:
            cancelled = port.call('POST', f"/v1/jobs/{judged['landing']['id']}/cancel", {})
        except Refused as error:
            cancelled = {'refused': error.status}
    return judged, cancelled


def shadow(args):
    url, token = os.environ.get('TOWER_PORT_URL'), os.environ.get('TOWER_PORT_TOKEN')
    if not url or not token:
        print('gate-infra: no port (TOWER_PORT_URL and TOWER_PORT_TOKEN); nothing judged')
        return 0
    import gate_policy
    repo = args.repo or config.get('forge-events.repo')
    info = gate_policy.identity(args.pr, repo)
    if args.head and info.get('head') != args.head:
        print(f"gate-infra: the head of #{args.pr} is {info.get('head')}, not {args.head}; nothing judged")
        return 0
    spec = {'repo': repo, 'pr': args.pr, 'head': info['head'], 'base': info['base'], 'ref': info['head_ref'],
            'base_ref': info['base_ref']}
    subprocess.run(['git', '-C', str(ROOT), 'fetch', '-q', 'origin', spec['base'], spec['head']], check=True,
                   capture_output=True)
    plan = plan_of(ROOT, spec['base'], spec['head'])
    trees = {name: git(ROOT, 'rev-parse', f'{spec[name]}^{{tree}}') for name in ('head', 'base')}
    verdict = judge(Port(url, token), spec, plan, trees, datetime.now(timezone.utc).date().isoformat(),
                    metadata=lambda: metadata_of(args.pr, spec['base']))
    path = kept(verdict)
    print(f"gate-infra: #{args.pr} {spec['head']} {verdict['verdict']} in {verdict['seconds']:.1f} s "
          f"({verdict['checks']} check(s), {verdict['from_cache']} from the cache"
          f"{', red: ' + ', '.join(verdict['red']) if verdict['red'] else ''}); {path}")
    return 0


def judged_already(verdict, round_):
    """A head needs no new judgment when its verdict is of this round and every check was prepared, or a live one that
    really judged it (it names its unprepared checks, none of them, and is green or red); a live verdict from before
    GATE-INFRA 4 does not say and is judged again (on 04/11 those all ended not_started for the missing forge key), and
    so is a round's verdict with checks the runner could not prepare (GATE-INFRA 7: a head with no scripts/gate-check)."""
    if not verdict:
        return False
    if verdict.get('round'):
        return verdict['round'] == round_ and not verdict.get('unprepared')
    return 'unprepared' in verdict and not verdict['unprepared'] and verdict.get('verdict') in ('green', 'red')


def has(root, commit, path):
    """Whether `commit` holds `path` in the repository at `root`."""
    return subprocess.run(['git', '-C', str(root), 'cat-file', '-e', f'{commit}:{path}'], capture_output=True,
                          check=False).returncode == 0


def backfill(args, port=None, judging=None, heads=None, planned=None, today=None, tool_of=None):
    """GATE-INFRA 5 (P5 F3): the last merged heads judged again by the infrastructure, checks only, beside the box's
    verdict on them, which was green, since the delivery merges only on green with the expected head. A head already
    judged is skipped (judged_already), so a backfill picks up where it stopped. One head at a time. A head that predates
    scripts/gate-check is judged by the copy at the tip of the base branch (tool_of, GATE-INFRA 7), which the runner
    fetches with the branch."""
    if port is None:
        url, token = os.environ.get('TOWER_PORT_URL'), os.environ.get('TOWER_PORT_TOKEN')
        if not url or not token:
            print('gate-infra: no port (TOWER_PORT_URL and TOWER_PORT_TOKEN); nothing judged')
            return 0
        port = Port(url, token)
    ref = args.ref or config.get('gate-infra.backfill_ref')
    if heads is None:
        subprocess.run(['git', '-C', str(ROOT), 'fetch', '-q', 'origin', ref], check=True, capture_output=True)
        heads = merged(ROOT, ref, args.last if args.last is not None else config.get('gate-infra.backfill_last'))
    planned = planned or (lambda base, head: (plan_of(ROOT, base, head), {
        name: git(ROOT, 'rev-parse', f'{commit}^{{tree}}') for name, commit in (('head', head), ('base', base))}))
    judging, today = judging or judge, today or datetime.now(timezone.utc).date().isoformat()
    if tool_of is None:
        tip = git(ROOT, 'rev-parse', f'origin/{ref}')

        def tool_of(head):
            return None if has(ROOT, head, COMMAND[0]) else tip
    for pr, base, head in heads:
        shadow_path = folder() / f'pr-{pr}-{head}.json'
        if judged_already(json.loads(shadow_path.read_text()) if shadow_path.exists() else None, args.round):
            continue
        kept_box({'pr': pr, 'head': head, 'verdict': 'green', 'red': [], 'source': 'merge',
                  'at': datetime.now(timezone.utc).isoformat()})
        tools = tool_of(head)
        spec = {'repo': config.get('forge-events.repo'), 'pr': pr, 'head': head, 'base': base, 'ref': ref,
                'base_ref': ref, 'round': args.round, **({'tools': tools} if tools else {})}
        plan, trees = planned(base, head)
        verdict = judging(port, spec, plan, trees, today, shadow=True, landing_too=False)
        verdict.update({'round': args.round, **({'tools': tools} if tools else {})})
        path = kept(verdict)
        print(f"gate-infra: backfill #{pr} {head} {verdict['verdict']} in {verdict['seconds']:.1f} s "
              f"({verdict['checks']} check(s), {verdict['from_cache']} from the cache"
              f"{', gate-check of ' + tools if tools else ''}"
              f"{', red: ' + ', '.join(verdict['red']) if verdict['red'] else ''}); {path}", flush=True)
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog='scripts/gate-infra', description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest='command', required=True)
    judged = sub.add_parser('shadow', help="judge a PR's live head on the infrastructure, in shadow")
    judged.add_argument('--pr', type=int, required=True)
    judged.add_argument('--head', help='judge only if this is still the live head')
    judged.add_argument('--repo')
    planned = sub.add_parser('plan', help='the plan of base...head in this checkout, as JSON')
    planned.add_argument('--base', required=True)
    planned.add_argument('--head', required=True)
    planned.add_argument('--answer', type=Path, help='PLAN-ON-RUNNER: write {plan, paths} here instead of printing the plan')
    planned.add_argument('--jobs', action='store_true',
                         help='PRE-GATE: with --answer, also the bodies of the check jobs the gate makes for this plan')
    again = sub.add_parser('backfill', help='the last merged heads judged again by the infrastructure (P5 F3)')
    again.add_argument('--last', type=int, help="how many merges (default: the registry's gate-infra.backfill_last)")
    again.add_argument('--ref', help='the base branch whose merges are judged (default: the registry\'s)')
    again.add_argument('--round', default='backfill', help='a new round judges the same heads again')
    args = parser.parse_args(argv)
    if args.command == 'plan':
        plan = plan_here(args.base, args.head)
        if args.answer:
            paths = [each for each in git(Path.cwd(), 'diff', '--no-renames', '--name-only', f'{args.base}...{args.head}').split('\n')
                     if each]
            said = {'plan': plan, 'paths': paths}
            if args.jobs:  # PRE-GATE: the very jobs the delivery's gate makes, by content: the same input_digest each
                said['jobs'] = pregate_jobs(Path.cwd(), args.base, args.head, plan)
            args.answer.write_text(json.dumps(said))
            print(f"gate-infra: plan of {args.head[:12]}: {len(plan['stages'])} stage(s), {len(plan['tests'])} test(s)")
        else:
            print(json.dumps(plan))
        return 0
    if args.command == 'backfill':
        return backfill(args)
    return shadow(args)


if __name__ == '__main__':
    sys.exit(main())
