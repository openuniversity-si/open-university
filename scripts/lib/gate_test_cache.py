"""Per-test result cache for the script tests (GS1, scope addition 2026-10-26 22:56; D-064 (f), D-069 items 3, 5, 6, 14).

A script test whose inputs did not change since a recorded PASS is reported as PASS (cached) and not run again; only a
failed, new or affected test runs. A test's key is a pure function of what the test reads:

  the registry's key version, the node version and the toolchain pins, the test's own entry in
  scripts/lib/gate-script-tests.json, and the content of every tracked or unignored file that the test, its `covers`
  globs or gate.test_cache_common_inputs name (the hermetic wrapper every test runs through, this module)

Tier (GX-11, D-065 (5)): only a cacheable tier (gate_tier.script_tests_cacheable, gate-tier.cacheable_tiers) reads or
writes markers; at tier 2 (the train's batch) and tier 3 (the battery) every key is '' and every selected test runs.
The key also covers gate_keys.key_parts() (empty until GX-28).

Isolation (TX10, T6): each test that runs gets its own TMPDIR under gate.test_tmp_root (mode gate.test_tmp_mode, removed
after the run), and no gate variable reaches it: every name with a prefix in gate.test_env_scrub_prefixes (OU_GATE_TIER
among them), gate.test_env_scrub_names and the forge count file are removed, except the slot contract gate.test_env_keep
that a nested gate shares with its parent.

Fail safe: a test the map does not know, one with no covers, one whose script is missing, and any input that cannot be
read (a broken link, a directory, a permission error) has NO key and always runs. A marker records its key, when it was
stored and the run that produced it; one that does not parse, names another key, is older than gate.test_cache_ttl_s or
comes from the future is a miss. The store is the storage port (providers.storage_adapter) at gate.test_cache_dir
(GATE_TEST_CACHE_DIR overrides it for one run); the flag gate.test_cache_enabled switches the whole cache off.

  key(script, root, mapping=None, files=None)           the key, or '' when the test must run
  lookup(store, key, now)                               the recorded marker, or None
  run(scripts, root, ...)                               hits are reported, the rest run through gate_graph at
                                                        script_tests_workers() (sized to the vCPUs, GX-03), longest
                                                        measured first, every result in test order
  gate_slots()                                          the gate slot count; `gate_test_cache.py slots` prints it
  test_cpus(running, workers)                           each running test's share of the vCPUs, handed to it as
                                                        OU_TEST_CPUS (parallel_tests.py runs its files side by side)

gate_test_cache.py suite [--changed [--base REF]]      every script test, or only the gate's selection for the diff
gate_test_cache.py run <list-file> --root R --tool-root T --logs L [--source S]
  writes L/script-tests.json: [{test, result, cached, key, source, tail}, and seconds for a test that ran] and prints one
  PASS/FAIL line per test.
"""
import argparse
import contextlib
import fcntl
import functools
from datetime import timedelta
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import config
import fork_server
import gate_graph
import gate_keys
import gate_script_tests
import gate_tier
import parallel_tests
import shared_results
from adapters import storage
from gate_areas import _compile_glob, glob_match
from gate_speed import _digest, _node_version

# registry names (D-069 item 12), never their values; pnpm left the toolchain (vazão F16)
TOOLCHAIN_PINS = ('toolchain.node_version', 'toolchain.python_version', 'toolchain.claude_cli_version')


def setting(name):
    return config.get(f'gate.{name}')


def vcpus():
    """The CPUs this process may use (the cgroup-aware affinity set), never less than 1."""
    try:
        return max(1, len(os.sched_getaffinity(0)))
    except (AttributeError, OSError):
        return max(1, os.cpu_count() or 1)


# FULL-RUN-BATCH-ONE: a process tree's own count of tests at once (the base's full run's batch: one, in a slot of four on two
# vCPUs: with the box's count a batch ran its twelve tests together and infra-intask-standby's 20 s waits ran out, five
# reds of `not in time` at e8e66675, 13/11 23:53 UTC)
WORKERS_ENV = 'GATE_TEST_WORKERS'


def script_tests_workers(cpus=None):
    """Script-test concurrency: min(gate.script_tests_concurrency, floor(vCPUs x gate.script_tests_per_vcpu)), >= 1;
    GATE_TEST_WORKERS (a positive integer) when the process tree names it."""
    named = os.environ.get(WORKERS_ENV, '').strip()
    if named.isdigit() and int(named) > 0:
        return int(named)
    cpus = vcpus() if cpus is None else cpus
    return max(1, min(setting('script_tests_concurrency'), int(cpus * setting('script_tests_per_vcpu'))))


def test_cpus(running, workers, cpus=None):
    """D-076: the processes one script test may run at once (parallel_tests.ENV): the vCPUs shared by the tests that run
    at the same time, min(workers, running), never less than 1. A full suite gets 1, a single test the whole box."""
    cpus = vcpus() if cpus is None else cpus
    return max(1, cpus // max(1, min(workers, running)))


def gate_slots(cpus=None):
    """Gates at once on this machine: gate.slots when it overrides (> 0), else max(1, floor(vCPUs x slots_per_vcpu))."""
    if setting('slots') > 0:
        return setting('slots')
    cpus = vcpus() if cpus is None else cpus
    return max(1, int(cpus * setting('slots_per_vcpu')))


MEASURED = 'engine.step.measured'
STEP_PREFIX = 'gate:script-test:'  # the engine.step.measured `step` of one script test: STEP_PREFIX + its path


def last_durations(events):
    """{script: duration_ms} from the latest engine.step.measured event of each script test, in log order."""
    found = {}
    for event in events:
        payload = event.get('payload') or {}
        step = payload.get('step', '')
        if event.get('type') == 'engine.step.measured' and step.startswith(STEP_PREFIX) and payload.get('result') == 'ok':
            found[step[len(STEP_PREFIX):]] = payload['duration_ms']
    return found


def costs(root):
    """{script: seconds} of the committed cost hints (gate.test_costs_file, written by `scripts/test-suite --metrics
    --write-costs` from a cold pass): the longest-first order of a box that has recorded no durations yet, a fresh
    runner or a session (GATE-SPEED F2, D-120). Only an order: a stale or missing hint never changes a verdict."""
    try:
        found = json.loads((Path(root) / setting('test_costs_file')).read_text())
        return {str(name): float(seconds) for name, seconds in found.items()}
    except (OSError, ValueError, AttributeError, TypeError):
        return {}


def longest_first(scripts, durations):
    """Scripts with a measured duration first, longest first; the unmeasured keep their declared order after them."""
    measured = sorted((s for s in scripts if s in durations), key=lambda s: -durations[s])
    return measured + [s for s in scripts if s not in durations]


def _port():
    import forge_events
    return forge_events.ForgeEvents(forge_events.adapter_from_config(), forge_events.clock_from_config(),
                                    'gate_test_cache', 'gate-script-tests')


def measured_durations():
    """The recorded durations from the repository channel; any failure reading them is an empty map (declared order).
    GX-FIX-forge-rate-2 (D-070): only the log that stores the kind is read (the local file log, forge-events.file_kinds)."""
    try:
        port = _port()
        return last_durations(port.read_recent(config.get('forge-events.repo'), kinds=(MEASURED,)))  # D-085
    except Exception:  # noqa: BLE001 - ordering is an optimisation, never a reason to fail the gate
        return {}


def record_durations(timed, source, port=None):
    """Publish engine.step.measured for each (script, ms, ok) in one append (GX-FIX-forge-rate, D-070: never one
    write per test; forge-events.file_kinds keeps the kind off issue comments). Best effort, like the read."""
    try:
        import forge_events
        port = port or _port()
        fields = forge_events.subject(config.get('forge-events.repo'), None, source)
        port.publish([port.build(MEASURED, forge_events.step_payload(
            fields, STEP_PREFIX + script, ms, 'ok' if ok else 'fail')) for script, ms, ok in timed])
    except Exception:  # noqa: BLE001
        pass


STORE_ENV = 'GATE_TEST_CACHE_DIR'  # a result store this process tree uses instead of gate.test_cache_dir
# FULL-RUN-NO-CACHE: '1' runs every test of this process tree and records nothing (the base's full run, tower_infra.fullrun):
# its job ran `gate-check test` in a slot whose store answered it, by a key that did not cover what the test reads
# (infra-autodeploy at c8d1fa3f, 13/11: "PASS (cached ..., source b92b3616)", red when it ran at 3b07bf52)
OFF_ENV = 'GATE_TEST_CACHE_OFF'


def cache_off():
    return os.environ.get(OFF_ENV) == '1'


def store_location():
    return Path(os.environ.get(STORE_ENV) or os.path.expanduser(setting('test_cache_dir')))


def _now():
    import forge_events  # the registry's injected clock (forge-events.clock), never the wall clock read here
    return int(forge_events.clock_from_config().now().timestamp())


def tracked(root):
    out = subprocess.run(['git', '-C', str(root), 'ls-files', '-z', '--cached', '--others', '--exclude-standard',
                          '--deduplicate'], capture_output=True, check=True).stdout
    return sorted(os.fsdecode(name) for name in out.split(b'\0') if name)


def _listing(root):
    """tracked(root), or None when git cannot list it: each key then asks again and answers '' as before."""
    try:
        return tracked(root)
    except (OSError, subprocess.CalledProcessError):
        return None


def key(script, root, mapping=None, files=None, node=None, hashes=None):
    """The test's cache key; '' when it must run (unknown test, no covers, an input that cannot be hashed, cache off,
    or a tier that never uses box-local markers).

    `hashes` is an optional dict that remembers each file's digest, so a run over many tests reads a shared file once."""
    if not setting('test_cache_enabled') or not gate_tier.script_tests_cacheable():
        return ''
    try:
        mapping = mapping or gate_script_tests.load()
        entry = next((item for item in mapping['tests'] if item['script'] == script), None)
        if entry is None or not entry['covers']:
            return ''
        root = Path(root)
        patterns = [script, *entry['covers'], *setting('test_cache_common_inputs')]
        listed = tracked(root) if files is None else sorted(files)
        if script not in listed:
            return ''
        digests = []
        matches = _matcher(tuple(patterns))
        for name in listed:
            if not matches(name):
                continue
            path = root / name
            if path.is_symlink() or not path.is_file():
                return ''
            if hashes is None or name not in hashes:
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                if hashes is not None:
                    hashes[name] = digest
            else:
                digest = hashes[name]
            digests.append(f'{name}\0{digest}')
    except (OSError, subprocess.CalledProcessError, gate_script_tests.ScriptTestMapError, KeyError, ValueError):
        return ''
    return _digest([
        'script-test', setting('test_cache_version'), script, node or _node_version(),
        *(config.get(name) for name in TOOLCHAIN_PINS),
        json.dumps({'script': entry['script'], 'covers': list(entry['covers'])}, sort_keys=True), *digests,
        *gate_keys.key_parts(),
    ])


@functools.lru_cache(maxsize=None)
def _matcher(patterns):
    """One compiled alternation of a test's globs (gate_areas' own translation): a key matches each tracked file once
    instead of once per glob (GATE-SPEED R1: 111 keys over 3,491 files took 3.6 s, most of it in glob_match)."""
    return re.compile('|'.join(f'(?:{_compile_glob(pattern).pattern})' for pattern in patterns)).fullmatch


def _marker(key_value):
    return f'script-tests/{key_value}'


def lookup(location, key_value, now=None):
    """The marker recorded for exactly this key and still valid, else None."""
    if not key_value:
        return None
    blob = storage.open_store(location).get(_marker(key_value))
    if blob is None:
        return None
    try:
        marker = json.loads(blob)
        stored_at = marker['stored_at']
        valid = (marker['key'] == key_value and isinstance(stored_at, int) and not isinstance(stored_at, bool)
                 and isinstance(marker['source'], str))
    except (ValueError, KeyError, TypeError):
        return None
    now = _now() if now is None else now
    return marker if valid and 0 <= now - stored_at <= setting('test_cache_ttl_s') else None


def record(location, key_value, script, source, now=None):
    if not key_value:
        raise ValueError('an empty key is never stored: the test ran without a key')
    marker = {'key': key_value, 'stored_at': _now() if now is None else now, 'source': source, 'test': script}
    storage.open_store(location).put(_marker(key_value), json.dumps(marker, sort_keys=True).encode())


def scrubbed(environ=None):
    """TX10 (T6): the names of `environ` (the gate's) that a script test never sees, sorted."""
    environ = os.environ if environ is None else environ
    keep = set(setting('test_env_keep'))
    # a script test never reads or publishes the shared results itself (GATE-SPEED F10): only the run that judges it
    names = set(setting('test_env_scrub_names')) | {shared_results.ENV}
    prefixes = tuple(setting('test_env_scrub_prefixes'))
    return sorted(name for name in environ if name not in keep and (name in names or name.startswith(prefixes)))


def hermetic_git(tool_root):
    """GATE-SPEED F1 (D-118): the git configuration a script test sees is the judge's gate.test_git_config, never the
    box's global or system configuration (this container signs every commit: 80 ms against 7 ms per fixture commit)."""
    env = {'GIT_CONFIG_GLOBAL': str(Path(tool_root) / setting('test_git_config')), 'GIT_CONFIG_NOSYSTEM': '1'}
    # GATE-SPEED F5: the same settings at the environment's level, which a fixture's own GIT_CONFIG_GLOBAL cannot drop
    overrides = [item.split('=', 1) for item in setting('test_git_overrides')]
    env['GIT_CONFIG_COUNT'] = str(len(overrides))
    for index, (name, value) in enumerate(overrides):
        env[f'GIT_CONFIG_KEY_{index}'], env[f'GIT_CONFIG_VALUE_{index}'] = name, value
    return env


def isolated(command, tmpdir, scrub):
    """`command` run without the `scrub` names and with its own TMPDIR: the overlay gate_graph merges into the gate's
    environment can add a key but never remove one."""
    return shlex.join(['env', *(part for name in scrub for part in ('-u', name)), f'TMPDIR={tmpdir}']) + ' ' + command


@contextlib.contextmanager
def private_tmp(scripts):
    """{script: its own TMPDIR} for one run, each removed afterwards (TX10, T6)."""
    mode = int(setting('test_tmp_mode'), 0)
    dirs = {}
    try:
        for script in scripts:
            dirs[script] = tempfile.mkdtemp(prefix='ou-script-test-', dir=setting('test_tmp_root'))
            os.chmod(dirs[script], mode)  # mkdtemp makes it 0700; a test that drops root must enter it
        yield dirs
    finally:
        for path in dirs.values():
            shutil.rmtree(path, ignore_errors=True)


def forks(env, todo, tool_root=None):
    """GATE-SPEED F4 (D-122): one fork server for the tests this run starts (gate.fork_server, from gate.fork_server_min_tests tests), or none. Its client
    execs the tool root's toolchain python3 even when this runner was not started under scripts/cloud/env.sh."""
    if len(todo) < max(1, setting('fork_server_min_tests')) or not setting('fork_server'):
        return contextlib.nullcontext({})
    return fork_server.started({**os.environ, **env}, setting('fork_server_preload'), setting('fork_server_compiler'),
                               setting('fork_server_start_s'), setting('jobserver_poll_s'),
                               toolchain=str(Path(tool_root) / '.toolchain') if tool_root else None)


def progressed(path):
    """FULL-RUN-KEEP: answered(script, passed) that rewrites `path` whole (a temporary file renamed over it, so a run
    killed between two tests leaves the last whole answer); None without a path."""
    if not path:
        return None
    said, lock = {}, threading.Lock()

    def answered(script, passed):
        with lock:
            said[script] = 'PASS' if passed else 'FAIL'
            part = f'{path}.part'
            Path(part).write_text(json.dumps({'tests': said}))
            os.replace(part, path)
    return answered


def run(scripts, root, location, source, tool_root, concurrency=None, mapping=None, now=None, files=None, lines=None,
        durations=None, measure=False, timings=None, progress=None):
    """Report every script test in order: a valid recorded PASS is cached, the others run and a PASS is recorded.
    timings, when given, receives {script: seconds} of every test that ran (scripts/test-metrics, D-117).
    progress, when given, is a file that holds {"tests": {script: PASS|FAIL}} of the tests ended so far, rewritten whole as
    each one ends (FULL-RUN-KEEP: a full run's batch taken back for a gate keeps what it ran)."""
    mapping = mapping or gate_script_tests.load()
    hashes = {}
    # GATE-SPEED F3: the tree listing and the node version are one answer per run; each key asked git and node again
    listed, node = (sorted(files) if files is not None else _listing(root)), _node_version()
    # One immutable input observation for this batch, as for the gate's structure analysis. Without the context,
    # every parameter of every key stats the entire registry again. End it before any test process starts.
    with config.reading():
        keys = {script: key(script, root, mapping, listed, node=node, hashes=hashes) for script in scripts}
        off = cache_off()
        hits = {script: None if off else lookup(location, keys[script], now) for script in scripts}
    # GATE-SPEED F10 (D-130): a key another box judged PASS is a PASS here too
    shared = (shared_results.SharedResults(tool_root) if not off and shared_results.enabled() and not all(hits.values())
              else None)
    held, moment = (shared.read() if shared else {}), (_now() if now is None else now)
    for script in scripts:
        if not hits[script] and keys[script]:
            hits[script] = shared_results.valid(held.get(keys[script]), keys[script], moment, setting('test_cache_ttl_s'))
    hermetic = str(Path(tool_root) / 'scripts' / 'lib' / 'hermetic')
    env = {'PYTHONPATH': hermetic + (os.pathsep + os.environ['PYTHONPATH'] if os.environ.get('PYTHONPATH') else ''),
           **hermetic_git(tool_root)}
    order = durations or costs(root)  # a box with no recorded durations orders by the committed hints (D-120)
    todo = [(script, f'bash {script}') for script in longest_first([s for s in scripts if not hits[s]], order)]
    scrub = scrubbed()
    took = {} if timings is None else timings
    workers = concurrency or script_tests_workers()
    share = test_cpus(len(todo), workers)
    env[parallel_tests.ENV] = str(share)
    with private_tmp([script for script, _ in todo]) as tmp, parallel_tests.jobserver(
            len(todo), workers, share, vcpus(), setting('jobserver_poll_s')) as (pool, ended), \
            forks(env, todo, tool_root) as warm:
        env.update(pool)
        env.update(warm)
        todo = [(script, isolated(command, tmp[script], scrub)) for script, command in todo]
        ran = {item['name']: item for item in gate_graph.run_commands(
            todo, workers, env, cwd=root, timings=took, ended=ended,
            **({'answered': progressed(progress)} if progress else {}))}
    keep = lines or setting('script_tests_log_lines')
    results, timed, added = [], [], {}
    for script in scripts:
        if hits[script]:
            results.append({'test': script, 'result': 'PASS', 'cached': True, 'key': keys[script],
                            'source': hits[script]['source'], 'tail': []})
            continue
        item = ran[script]
        passed = item['result'] == gate_graph.PASS
        timed.append((script, timedelta(seconds=took[script]) // timedelta(milliseconds=1), passed))
        if passed and keys[script] and not off:
            record(location, keys[script], script, source, now)
            added[keys[script]] = {'key': keys[script], 'stored_at': moment, 'source': source, 'test': script}
        results.append({'test': script, 'result': 'PASS' if passed else 'FAIL', 'cached': False, 'key': keys[script],
                        'seconds': round(took[script], 1),  # GATE-PACE: its wall in this batch (verify-commit's pace line)
                        'source': source, 'tail': [] if passed else item['output'].splitlines()[-keep:],
                        'failure': [] if passed else gate_graph.failure_lines(item['output'])})
    if measure:
        record_durations(timed, source)
    if shared:
        shared.publish(held, added, moment)
    return results


def deleted(scripts, root):
    """OU-DECOUPLE F2 (D-107): the selected tests that the judged change deletes together with their covers manifest.
    The selection is the base's (the pin, P-46), so it can name a test the checkout no longer has, and such a test has
    nothing left to judge. A test deleted while its manifest stays is not one of them: it runs, and fails."""
    root = Path(root)
    return [script for script in scripts
            if not (root / script).exists() and not gate_script_tests.manifest_path(script, root).exists()]


def report(results):
    for item in results:
        if item['cached']:
            print(f'PASS {item["test"]} (cached: key {item["key"][:12]}, source {item["source"][:12]})')
        elif item['result'] == 'PASS':
            print(f'PASS {item["test"]}')
        else:
            print(f'FAIL {item["test"]}')
            print('\n'.join(item['tail']))
    # the LAST lines: a runner's tail (2000 characters) holds what the 40 lines above it push out (AWS7)
    text = gate_graph.summary([(item['test'], item.get('failure') or item['tail'][-3:]) for item in results
                                  if not item['cached'] and item['result'] != 'PASS'])
    if text:
        print(text)
    return 0 if all(item['result'] == 'PASS' for item in results) else 1


def changed(root, base):
    """VAZÃO F50: the paths this checkout changes against `base`: the gate's own diff `base...HEAD`
    (gate_policy.changed_paths) plus what is not committed yet (staged, unstaged and untracked), sorted."""
    import gate_policy  # the gate's diff and plan; loaded only for a --changed suite
    git = ['git', '-C', str(root)]
    committed = gate_policy.changed_paths(root, base, 'HEAD')
    pending = subprocess.check_output(git + ['diff', '--no-renames', '--name-only', '-z', 'HEAD']).decode().split('\0')
    untracked = subprocess.check_output(git + ['ls-files', '--others', '--exclude-standard', '-z']).decode().split('\0')
    return sorted({path for path in committed + pending + untracked if path})


def selection(paths, base, root):
    """VAZÃO F50: (tests, reason) the PR gate picks for `paths`, through its own function path: the dev plan
    (gate_policy.select_dev_plan) and, when that plan has the script tests stage, gate_script_tests.select_plan, minus
    the tests the change deletes with their manifest (`deleted`, as `run` does). A plan without the stage selects none."""
    import gate_policy
    plan = gate_policy.select_dev_plan(list(paths), base, 'HEAD', root)
    if 'script tests' not in plan['stages']:
        return [], f'the {plan["kind"]} plan has no script tests stage ({plan.get("reason", "")})'
    chosen, reason = gate_script_tests.select_plan(plan)
    gone = set(deleted(chosen, root))
    return [script for script in chosen if script not in gone], reason


@contextlib.contextmanager
def hold(lock, log=None, err=sys.stderr, clock=time.monotonic, wall=time.time, kind='suite'):
    """VAZÃO F50: flock(2) on `lock`, the box lock scripts/test-suite and deliver's gate queue on (F23), for the body of
    the `with`. A --changed suite takes it only when its selection runs something. F58: on release it appends
    {pr: null, kind: suite, waited_s, held_s, at} to the box's lock log `log` (delivery.gate_lock_log, F38), as a
    delivery's box_gate does, so scripts/flow-metrics --constraint counts the suites' hold of the box too."""
    path = Path(lock)
    path.parent.mkdir(parents=True, exist_ok=True)
    waited = 0.0
    with path.open('a') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(f'test-suite: a gate or a suite holds the box ({lock}); waiting', file=err)
            started = clock()
            fcntl.flock(handle, fcntl.LOCK_EX)
            waited = clock() - started
        taken = clock()
        try:
            yield handle
        finally:
            held = clock() - taken
            fcntl.flock(handle, fcntl.LOCK_UN)
            if log:
                log_hold(log, waited, held, wall(), kind)


SLOT_KIND = 'suite_slot'  # F65: a lock-log line of a --changed suite's slot, apart from the box's own holds


@contextlib.contextmanager
def slot(lock, log=None, slots=None, err=sys.stderr, clock=time.monotonic, wall=time.time):
    """VAZÃO F65: a --changed suite holds one of `slots` (gate.changed_suite_slots) slot locks beside the box lock
    `lock` (suite-slot-<i>.lock), not the box lock itself, which stays the deliveries'. The first free slot is taken;
    when all are busy it waits on one of them (chosen by pid). Each hold is a line of kind suite_slot in `log`."""
    count = max(1, int(slots or setting('changed_suite_slots')))
    folder = Path(lock).parent
    folder.mkdir(parents=True, exist_ok=True)
    paths = [folder / f'suite-slot-{index}.lock' for index in range(count)]
    waited, handle = 0.0, None
    for path in paths:
        candidate = path.open('a')
        try:
            fcntl.flock(candidate, fcntl.LOCK_EX | fcntl.LOCK_NB)
            handle = candidate
            break
        except BlockingIOError:
            candidate.close()
    if handle is None:
        print(f'test-suite: {count} --changed suite(s) hold every slot ({folder}); waiting', file=err)
        handle = paths[os.getpid() % count].open('a')
        started = clock()
        fcntl.flock(handle, fcntl.LOCK_EX)
        waited = clock() - started
    taken = clock()
    try:
        yield handle
    finally:
        held = clock() - taken
        fcntl.flock(handle, fcntl.LOCK_UN)
        handle.close()
        if log:
            log_hold(log, waited, held, wall(), SLOT_KIND)


def niced(increment=None):
    """F65: lower this process's CPU priority by gate.changed_suite_nice, inherited by every test it starts."""
    try:
        os.nice(int(setting('changed_suite_nice') if increment is None else increment))
    except OSError:
        pass


def log_hold(log, waited, held, at, kind='suite'):
    """F58: one suite line of the box's lock log (F65: kind suite_slot for a --changed slot); a log that cannot be
    written never fails the suite."""
    try:
        path = Path(os.path.expanduser(log))
        path.parent.mkdir(parents=True, exist_ok=True)
        row = {'pr': None, 'kind': kind, 'waited_s': round(waited, 1), 'held_s': round(held, 1), 'at': round(at)}
        with open(path, 'a') as handle:
            handle.write(json.dumps(row) + '\n')
    except OSError:
        pass


def suite(root, tool_root, location, source, concurrency=None, clock=None, out=print, scripts=None):
    """GATE-SPEED (D-092, ADR-42): judge every script test of the checkout (or only `scripts`, VAZÃO F50 --changed): a
    test whose key matches a recorded PASS is answered by it, every other test runs (and a PASS is recorded). Prints the
    counts and the wall against gate.suite_wall_goal_s (a miss) and gate.suite_wall_warn_s (a warning); the wall is
    report-only. The results, in test order."""
    clock = clock or time.monotonic
    began = clock()
    scripts = list(gate_script_tests.discover(root)) if scripts is None else list(scripts)
    results = run(scripts, root, location, source, tool_root, concurrency=concurrency)
    wall = clock() - began
    cached = sum(1 for item in results if item['cached'])
    failed = sum(1 for item in results if item['result'] != 'PASS')
    goal, warn = setting('suite_wall_goal_s'), setting('suite_wall_warn_s')
    verdict = 'MISS (above the goal)' if wall > goal else 'WARN (above the ideal)' if wall > warn else 'ok'
    out(f'suite: {len(results)} script tests judged, {cached} by key, {len(results) - cached} ran, {failed} failed; '
        f'wall {wall:.2f} s (goal {goal} s, ideal {warn} s): {verdict}')
    return results


def main(argv):
    parser = argparse.ArgumentParser(prog='gate_test_cache', description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest='command', required=True)
    runner = commands.add_parser('run')
    runner.add_argument('listing')
    runner.add_argument('--root', required=True)
    runner.add_argument('--tool-root', required=True)
    runner.add_argument('--logs', required=True)
    runner.add_argument('--source', default='working-tree')
    runner.add_argument('--progress', help="FULL-RUN-KEEP: rewrite this file with each ended test's PASS or FAIL")
    commands.add_parser('slots')
    whole = commands.add_parser('suite', help='judge every script test (GATE-SPEED): by key when unchanged, else run')
    whole.add_argument('--root', default=str(Path(__file__).resolve().parents[1].parent))
    whole.add_argument('--source', default='working-tree')
    whole.add_argument('--workers', type=int)
    whole.add_argument('--json', help='write the results here')
    whole.add_argument('--changed', action='store_true',
                       help="only the tests the PR gate selects for this checkout's diff (committed and not), VAZÃO F50")
    whole.add_argument('--base', help='with --changed: the base ref of the diff (default gate.changed_base_ref)')
    whole.add_argument('--lock', help='the box lock (F23), held while the whole suite runs; --changed takes one of '
                       'gate.changed_suite_slots slots beside it instead, under nice, only when the selection runs a '
                       'test (F65). Each hold is a line of delivery.gate_lock_log (F58)')
    whole.add_argument('--metrics', action='store_true',
                       help="GATE-SPEED's main and guard metrics instead (scripts/lib/test_metrics.py, D-117): a cold pass")
    whole.add_argument('--warm', type=int, nargs='?', const=1, default=0, metavar='N',
                       help='with --metrics: also time N passes answered by key (the median is the guard)')
    whole.add_argument('--coverage', metavar='DIR', help='with --metrics: line coverage, coverage.py importable from DIR')
    whole.add_argument('--write-costs', metavar='FILE',
                       help='with --metrics: write the cold walls as the cost hints a box without durations orders by')
    whole.add_argument('--test', metavar='PATH',
                       help='with --write-costs: measure only this script test and merge its one hint (VAZÃO F67)')
    args = parser.parse_args(argv[1:])
    if args.command == 'suite':
        with contextlib.ExitStack() as box:
            log = config.get('delivery.gate_lock_log') if args.lock else None
            return _suite(args, lambda: box.enter_context(hold(args.lock, log)) if args.lock else None,
                          lambda: box.enter_context(slot(args.lock, log)) if args.lock else None)
    if args.command == 'slots':
        print(gate_slots(int(os.environ['GATE_VCPUS']) if os.environ.get('GATE_VCPUS') else None))
        return 0
    scripts = [line.strip() for line in Path(args.listing).read_text().splitlines() if line.strip()]
    gone = deleted(scripts, args.root)
    for script in gone:
        print(f'SKIP {script} (this change deletes it with its covers manifest; D-107)')
    todo = [script for script in scripts if script not in gone]
    # CHECK-ENVELOPE: one test (a check job's, scripts/gate-check) has no order to keep: no durations read or recorded
    # (two adapters of the forge's port each, ~0.15 s here and about twice that on the runner, per job)
    alone = len(todo) == 1
    results = run(todo, args.root, store_location(), args.source, args.tool_root,
                  durations={} if alone else measured_durations(), measure=not alone, progress=args.progress)
    _write(Path(args.logs) / 'script-tests.json', results)
    return report(results)


def _suite(args, take_box, take_slot=None):
    """The `suite` command; `take_box()` holds the box lock until the command returns, called only once it runs a test.
    A --changed suite calls `take_slot()` instead and runs niced (F65): the box lock stays the deliveries'."""
    if args.metrics:
        import test_metrics  # imports this module; loaded only for a measurement
        take_box()
        return test_metrics.main(args, tool_root=str(Path(__file__).resolve().parents[1].parent))
    chosen = None
    if args.changed:
        base = args.base or config.get('gate.changed_base_ref')
        paths = changed(args.root, base)
        chosen, why = selection(paths, base, args.root)
        print(f'changed: {len(paths)} path(s) against {base}; {len(chosen)} script test(s) selected: {why}')
    results = []
    if chosen is None or chosen:
        if args.changed:
            niced()
            (take_slot or take_box)()
        else:
            take_box()
        results = suite(args.root, args.root, store_location(), args.source, args.workers, scripts=chosen)
    # F79: the full results stay on disk (--json, else .gate/test-suite.json); the console shows the failures only
    full = Path(args.json) if args.json else Path(args.root) / '.gate' / 'test-suite.json'
    try:
        full.parent.mkdir(parents=True, exist_ok=True)
        _write(full, list(results))
    except OSError:
        full = None
    code = report([item for item in results if item['result'] != 'PASS'])
    if results and full:
        print(f'suite log: {full}')
    return code


def _write(path, results):
    path.write_text(json.dumps(results, indent=2))


if __name__ == '__main__':
    sys.exit(main(sys.argv))
