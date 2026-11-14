"""Hermetic Python tests (plan v3 H1, D-069 item 5): network denied, seeded random, injected clock, per-test timeout.

install() is idempotent. The gate puts scripts/lib/hermetic/ on PYTHONPATH for the script tests (scripts/gate-local), whose
sitecustomize.py calls it, so every test script and every Python child it starts runs under the same rules. Every value is
a registry entry (tests.*, config/registry/tests.json); a test never reads the wall clock, it takes clock().
"""
from datetime import datetime, timedelta, timezone
import atexit
import functools
import hashlib
import json
import os
from pathlib import Path
import random
import shlex
import shutil
import signal
import socket
import sys
import tempfile
import time

import config

_state = {'installed': False, 'clock': None, 'run': None, 'loopback': None, 'clock_start': None, 'seed': None, 'store': None}
_trace = {'on': False, 'reads': set(), 'writes': set(), 'root': None, 'test': None, 'dir': None, 'owner': False}
_LIB = Path(__file__).resolve().parent
MIN_TIMER_S = sys.float_info.epsilon  # setitimer(0) would disarm: an already passed deadline fires at once

# The Node half of the denial (GX-29): shell_env() writes it once to a content-named file in the temp directory and puts it on NODE_OPTIONS.
_NODE_HOOK = r''''use strict';
// GX-29: the Node half of the hermetic network denial (scripts/lib/hermetic.py shell_env puts it on NODE_OPTIONS for the gate's shell).
// A connection or name lookup to a host outside OU_HERMETIC_LOOPBACK (comma-separated, from tests.loopback_hosts) fails with EHERMETIC.
const net = require('node:net');
const dns = require('node:dns');

const allowed = new Set((process.env.OU_HERMETIC_LOOPBACK || '').split(',').filter(Boolean));

function loopback(host) {
  if (host === undefined || host === null || host === '') return true;
  const text = String(host);
  return allowed.has(text) || text.startsWith('127.') || text === '::1';
}

function denied(host) {
  const error = new Error(`hermetic gate: network is denied; refused ${String(host)}`);
  error.code = 'EHERMETIC';
  return error;
}

const connect = net.Socket.prototype.connect;
net.Socket.prototype.connect = function guardedConnect(...args) {
  // net.connect() hands the socket its arguments already normalized, as [options, callback].
  const normalized = Array.isArray(args[0]) ? args[0] : net._normalizeArgs(args);
  const options = normalized[0] || {};
  if (options.path === undefined && !loopback(options.host)) {
    process.nextTick(() => {
      this.emit('error', denied(options.host));
      this.destroy();
    });
    return this;
  }
  return connect.apply(this, args);
};

const lookup = dns.lookup;
dns.lookup = function guardedLookup(host, ...rest) {
  if (!loopback(host)) {
    const callback = rest[rest.length - 1];
    if (typeof callback === 'function') {
      process.nextTick(() => callback(denied(host)));
      return {};
    }
    throw denied(host);
  }
  return lookup.call(this, host, ...rest);
};
'''



class NetworkDenied(OSError):
    """A hermetic test tried to reach a host outside tests.loopback_hosts."""


class TestTimeout(AssertionError):
    """A test ran past tests.script_timeout_ms."""


class Clock:
    """The injected clock: starts at tests.clock_start and moves only when a test advances it."""

    def __init__(self, start=None):
        text = (_state['clock_start'] or config.get('tests.clock_start')) if start is None else start
        self._now = datetime.fromisoformat(text.replace('Z', '+00:00')).astimezone(timezone.utc)

    def now(self):
        return self._now

    def timestamp(self):
        return self._now.timestamp()

    def advance(self, seconds):
        self._now += timedelta(seconds=seconds)
        return self._now


def clock():
    if _state['clock'] is None:
        _state['clock'] = Clock()
    return _state['clock']


def rng(salt=0):
    """A random source seeded from tests.random_seed (the module-level `random` is seeded too)."""
    seed = _state['seed'] if _state['seed'] is not None else config.get('tests.random_seed')
    return random.Random(seed + salt)


def _loopback(host):
    if _state['loopback'] is None:
        _state['loopback'] = config.get('tests.loopback_hosts')
    if host in _state['loopback']:
        return True
    import ipaddress
    if isinstance(host, bytes):
        host = host.decode('ascii', 'replace')
    try:
        return ipaddress.ip_address(str(host).split('%')[0]).is_loopback
    except ValueError:
        return False


def _check(address):
    if isinstance(address, tuple) and address:
        host = address[0]
    elif isinstance(address, (str, bytes)):
        return  # an AF_UNIX path
    else:
        host = address
    if not _loopback(host):
        raise NetworkDenied(f'hermetic test: network is denied (tests.network_allowed is false); refused {host!r}')


def _deny_network():
    connect, connect_ex, sendto = socket.socket.connect, socket.socket.connect_ex, socket.socket.sendto
    lookup = socket.getaddrinfo

    def guarded_connect(self, address):
        if self.family != socket.AF_UNIX:
            _check(address)
        return connect(self, address)

    def guarded_connect_ex(self, address):
        if self.family != socket.AF_UNIX:
            _check(address)
        return connect_ex(self, address)

    def guarded_sendto(self, data, *args):
        if self.family != socket.AF_UNIX and args:
            _check(args[-1])
        return sendto(self, data, *args)

    def guarded_lookup(host, *args, **kwargs):
        if host is not None and not _loopback(host):
            raise NetworkDenied(f'hermetic test: name resolution is denied; refused {host!r}')
        return lookup(host, *args, **kwargs)

    socket.socket.connect, socket.socket.connect_ex, socket.socket.sendto = guarded_connect, guarded_connect_ex, guarded_sendto
    socket.getaddrinfo = guarded_lookup


def bounded(run, limit_s):
    """`run` (a TestCase.run) that fails with TestTimeout once it has taken limit_s seconds.

    Wrappers nest (a second harness in the same process, a test timing a test): the deadline of an inner one is the earlier
    of its own and its outer's, and the outer's timer is re-armed when the inner one ends, so no layer ever extends another.
    The deadlines are shared through unittest.case, which every copy of this module patches."""
    def expired(signum, frame):
        raise TestTimeout(f'test ran past tests.script_timeout_ms ({round(limit_s * 1000)} ms)')

    @functools.wraps(run)
    def wrapper(self, result=None):
        deadlines = sys.modules['unittest.case'].__dict__.setdefault('_hermetic_deadlines', [])
        now = time.monotonic()
        deadline = min([now + limit_s, *deadlines[-1:]])
        previous = signal.signal(signal.SIGALRM, expired)
        signal.setitimer(signal.ITIMER_REAL, max(deadline - now, MIN_TIMER_S))
        deadlines.append(deadline)
        try:
            return run(self, result)
        finally:
            deadlines.pop()
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, previous)
            if deadlines and deadlines[-1] > time.monotonic():  # a deadline that passed inside is reported by the layer that hit it
                signal.setitimer(signal.ITIMER_REAL, deadlines[-1] - time.monotonic())

    return wrapper


def without_harness(env):
    """A copy of `env` for a child that is the toolchain bootstrap (scripts/cloud/setup.sh), which downloads by design: the
    hermetic sitecustomize directory is dropped from its PYTHONPATH. Nothing else under test may use this."""
    kept = [part for part in env.get('PYTHONPATH', '').split(os.pathsep) if part and Path(part).name != 'hermetic']
    clean = dict(env)
    if kept:
        clean['PYTHONPATH'] = os.pathsep.join(kept)
    else:
        clean.pop('PYTHONPATH', None)
    return clean


_PROXY_VARIABLES = ('HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'http_proxy', 'https_proxy', 'all_proxy')


def shell_env(env=None):
    """A copy of `env` for the gate's shell with the denial extended to it (GX-29): every Python child loads this harness
    (hermetic/sitecustomize.py), every Node child loads the Node hook (_NODE_HOOK), and OU_GATE_OFFLINE=1 tells the gate to
    use only what setup seeded (npm prefer-offline). Loopback stays reachable (PostgreSQL, e2e); the
    proxy variables are dropped, because a proxy listening on the loopback would otherwise carry the traffic out."""
    out = {key: value for key, value in (os.environ if env is None else env).items() if key not in _PROXY_VARIABLES}
    here = Path(__file__).resolve().parent / 'hermetic'
    python = [part for part in out.get('PYTHONPATH', '').split(os.pathsep) if part and part != str(here)]
    out['PYTHONPATH'] = os.pathsep.join([str(here), *python])
    node = out.get('NODE_OPTIONS', '').split()
    hook_file = Path(tempfile.gettempdir()) / f'ou-hermetic-{hashlib.sha256(_NODE_HOOK.encode()).hexdigest()}.cjs'
    if not hook_file.is_file():
        scratch = hook_file.with_suffix(f'.{os.getpid()}.tmp')
        scratch.write_text(_NODE_HOOK)
        scratch.replace(hook_file)
    hook = f'--require={hook_file}'
    out['NODE_OPTIONS'] = ' '.join([*(option for option in node if option != hook), hook])
    out['OU_HERMETIC_LOOPBACK'] = ','.join(config.get('tests.loopback_hosts'))
    out['OU_GATE_OFFLINE'] = '1'
    out['npm_config_prefer_offline'] = 'true'
    return out


def _patch_unittest(case, limit_s):
    current = case.TestCase.run
    _state['run'] = getattr(current, '__wrapped__', current)  # a second harness in the process (shell PYTHONPATH) must not time out the first
    case.TestCase.run = bounded(case.TestCase.run, limit_s)


class _AfterUnittest:
    """Patches TestCase.run the moment unittest.case is imported, so a process that never runs a test pays nothing."""

    def __init__(self, limit_s):
        self.limit_s = limit_s

    def find_spec(self, name, path=None, target=None):
        if name != 'unittest.case':
            return None
        import importlib.util
        sys.meta_path.remove(self)
        spec = importlib.util.find_spec(name)
        loader = spec.loader
        exec_module = loader.exec_module

        def patched(module):
            exec_module(module)
            sys.modules[name] = module
            _patch_unittest(module, self.limit_s)
        loader.exec_module = patched
        return spec


def store_env():
    """{OU_CONFIG_STORE: kind} for a child process whose environment a test builds: it reads the checkout's local
    configuration log, never the shared store (D-069 item 5). Merge it into every scrubbed environment."""
    return {'OU_CONFIG_STORE': _state['store'] or config.entry('tests.config_store')['default']}


_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC


def _trace_hook(event, args):
    """Records every file this process opens (GX-29, B-13): reads and writes apart, as absolute paths."""
    if event != 'open' or not _trace['on']:
        return
    path, mode, flags = args
    if isinstance(path, bytes):
        path = os.fsdecode(path)
    if not isinstance(path, str):
        return
    writing = bool(flags & _WRITE_FLAGS) if isinstance(flags, int) else False
    writing = writing or (isinstance(mode, str) and any(letter in mode for letter in 'wax+'))
    _trace['writes' if writing else 'reads'].add(os.path.abspath(path))


def _script_test(argv0):
    """(root, test path relative to root) when argv0 is scripts/tests/test_*.py of some checkout, else None."""
    script = Path(argv0).resolve() if argv0 else None
    if script is None or script.suffix != '.py' or not script.name.startswith('test_'):
        return None
    if script.parent.name != 'tests' or script.parent.parent.name != 'scripts':
        return None
    root = script.parent.parent.parent
    return root, script.relative_to(root).as_posix()


def _start_trace():
    """Arms the covers trace for a Python script test and every Python child that inherits its environment."""
    try:
        if config.get('gate-trace.covers_trace_mode') != 'report':
            return
    except Exception:  # a registry without the key (an older checkout) traces nothing
        return
    found = os.environ.get('OU_COVERS_TEST')
    if found:
        directory = os.environ.get('OU_COVERS_TRACE_DIR', '')
        if not directory or not os.path.isdir(directory):
            return
        _trace.update(root=Path(os.environ['OU_COVERS_ROOT']), test=found, dir=directory, owner=False)
    else:
        located = _script_test(sys.argv[0] if sys.argv else '')
        if located is None:
            return
        root, test = located
        directory = tempfile.mkdtemp(prefix='ou-covers-')
        os.environ.update(OU_COVERS_TEST=test, OU_COVERS_ROOT=str(root), OU_COVERS_TRACE_DIR=directory)
        _trace.update(root=root, test=test, dir=directory, owner=True)
    _trace['on'] = True
    sys.addaudithook(_trace_hook)
    atexit.register(_finish_trace)


def _finish_trace():
    _trace['on'] = False
    root = str(_trace['root'])
    mine = sorted(path[len(root) + 1:] for path in _trace['reads'] - _trace['writes']
                  if path.startswith(root + os.sep) and os.path.isfile(path))
    try:
        Path(_trace['dir'], f'{os.getpid()}.json').write_text(json.dumps(mine))
        if not _trace['owner']:
            return
        reads = sorted({path for item in Path(_trace['dir']).glob('*.json') for path in json.loads(item.read_text())})
        _report_trace(reads)
    except (OSError, ValueError):
        pass
    finally:
        if _trace['owner']:
            shutil.rmtree(_trace['dir'], ignore_errors=True)


def _report_trace(reads):
    """Prints the reads outside the test's declared covers to stderr. Report-only: never changes the exit status."""
    sys.path.insert(0, str(_LIB))
    try:
        import gate_script_tests
        found = gate_script_tests.trace_check(reads, _trace['test'], _trace['root'])
    except Exception as error:  # the report must never break a test
        print(f'covers trace: skipped ({type(error).__name__}: {error})', file=sys.stderr)
        return
    finally:
        sys.path.remove(str(_LIB))
    limit = config.get('gate-trace.covers_trace_max_listed')
    if not found['declared']:
        print(f'covers trace (report-only): {_trace["test"]} is in no covers manifest; {len(reads)} file(s) read', file=sys.stderr)
    elif found['under']:
        shown = found['under'][:limit]
        more = len(found['under']) - len(shown)
        print(f'covers trace (report-only): {_trace["test"]} read {len(found["under"])} file(s) outside its declared covers:',
              file=sys.stderr)
        for path in shown:
            print(f'  {path}', file=sys.stderr)
        if more:
            print(f'  … and {more} more', file=sys.stderr)


def install():
    if _state['installed']:
        return
    _state['installed'] = True
    with config.reading():  # GATE-SPEED F4: every process pays this; one registry stat for all its reads
        _install()


def _install():
    _state['store'] = config.entry('tests.config_store')['default']
    config.pin_store(_state['store'])  # before any config.get: no read of the forge
    # Every value the harness needs later is read now: sitecustomize drops the tooling's modules and path after install(),
    # and a later config.get would import the change store (forge_events) from a path that is gone.
    _state['seed'] = config.get('tests.random_seed')
    _state['clock_start'] = config.get('tests.clock_start')
    _state['loopback'] = config.get('tests.loopback_hosts')
    random.seed(_state['seed'])
    if not config.get('tests.network_allowed'):
        _deny_network()
    _start_trace()
    if hasattr(signal, 'setitimer'):
        limit_s = config.get('tests.script_timeout_ms') / 1000
        if 'unittest.case' in sys.modules:
            _patch_unittest(sys.modules['unittest.case'], limit_s)
        else:
            sys.meta_path.insert(0, _AfterUnittest(limit_s))


if __name__ == '__main__':
    if sys.argv[1:] == ['shell-env']:
        # eval "$(python3 scripts/lib/hermetic.py shell-env)" before a gate: the whole gate then runs with the network denied.
        base = dict(os.environ)
        done = shell_env(base)
        print('unset ' + ' '.join(key for key in _PROXY_VARIABLES if key in base))
        for key, value in done.items():
            if base.get(key) != value:
                print(f'export {key}={shlex.quote(value)}')
    else:
        sys.exit('usage: hermetic.py shell-env')
