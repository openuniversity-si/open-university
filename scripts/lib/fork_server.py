#!/usr/bin/env python3
"""GATE-SPEED F4 (D-122): one warm interpreter per suite run; every Python process a script test starts is a fork of it.

A fresh `python3` under the hermetic harness pays about 50 ms of CPU before its first line (the interpreter's start-up
and the standard library the harness and the engine import); a cold run starts about 900 of them. The server imports
the standard library once, freezes its heap and listens on a private UNIX socket. The client (`fork-shim.c`, installed
as `python3` first on the tests' PATH) connects and hands over its working directory and every open descriptor
(SCM_RIGHTS); the server reads the rest of the process from /proc/<client> (argv, environment, umask, signal state,
limits), forks, and the child becomes what `python3 <argv>` would have been, in a fresh interpreter's order:
descriptors, environment, `sys.argv`, `sitecustomize` (the harness), then `sys.path[0]`, then `__main__`. The server
sends the child's pid and, when it ends, its wait status; the client forwards the signals it receives and exits the
same way the child did. Whatever the fork does not model (another user, an interpreter flag, a `PYTHON*` variable
other than PYTHONPATH and PYTHONDONTWRITEBYTECODE, a terminal, a resource limit, a script that is not a file) is
answered "exec the real interpreter".

  fork_server.py serve <dir> [<module> ...]   listen on <dir>/socket; <dir>/ready appears once it listens

The client's environment names the server and the real interpreter: OU_FORK_SERVER (<dir>) and OU_FORK_SERVER_PYTHON.
"""
import contextlib
import gc
import json
import os
from pty import STDERR_FILENO, STDIN_FILENO, STDOUT_FILENO
import select
import selectors
import signal
import socket
import shutil
import struct
import subprocess
import sys
import tempfile
import time

SERVER = 'OU_FORK_SERVER'  # the server's directory: <dir>/socket, <dir>/bin/python3 (the client), <dir>/ready
PYTHON = 'OU_FORK_SERVER_PYTHON'  # the real interpreter the client execs when the server says so
SOCKET, READY, BIN = 'socket', 'ready', 'bin'
READY_FD = 'OU_FORK_SERVER_READY_FD'  # the pipe the server writes READY on once it listens; the starter blocks on it
FALLBACK, STARTED, EXITED = b'F', b'P', b'X'
STATUS = '<i'  # a pid or a wait status after STARTED and EXITED
TARGET = '<i'  # each descriptor number the client holds, in the order of its SCM_RIGHTS (after its cwd)
CREDENTIALS = '3i'  # SO_PEERCRED: pid, uid, gid
# variables a fork cannot take from its client: they shaped the server's interpreter at start-up
SAME_VARIABLES = ('PYTHON', 'LC_', 'LANG', 'COVERAGE_PROCESS_START')
FREE_VARIABLES = ('PYTHONPATH', 'PYTHONDONTWRITEBYTECODE')
_HERE = os.path.abspath(__file__)
STANDARD = (STDIN_FILENO, STDOUT_FILENO, STDERR_FILENO)
ARGUMENT = len(['python3', '-c'])  # where the argument of -c or -m (and serve's <dir>) is in argv


class Job:
    """What a fork runs: the client's process as /proc and its descriptors describe it."""

    def __init__(self, pid, argv, environ, umask, ignored, blocked, cwd, fds):
        self.pid, self.argv, self.environ, self.umask = pid, argv, environ, umask
        self.ignored, self.blocked, self.cwd, self.fds = ignored, blocked, cwd, fds


def _proc(pid, name):
    with open(f'/proc/{pid}/{name}', 'rb') as handle:
        return handle.read()


def _mask(value):
    """The signals of a /proc status mask (hexadecimal, bit n-1 for signal n)."""
    bits = int('0x' + value, 0)
    return {number for number in range(1, bits.bit_length() + 1) if bits >> (number - 1) & 1}


def _status(pid):
    fields = {}
    for line in _proc(pid, 'status').decode().splitlines():
        key, _, value = line.partition(':')
        fields[key] = value.strip()
    return int('0o' + fields['Umask'], 0), _mask(fields['SigIgn']), _mask(fields['SigBlk'])


def _limits(pid=None):
    import resource
    names = sorted(name for name in dir(resource) if name.startswith('RLIMIT_'))
    if pid is None:
        return {name: resource.getrlimit(getattr(resource, name)) for name in names}
    return {name: resource.prlimit(pid, getattr(resource, name)) for name in names}


def _pinned(environ):
    """The variables a fork must share with the server, as a sorted list."""
    return sorted((key, value) for key, value in environ.items()
                  if key.startswith(SAME_VARIABLES) and key not in FREE_VARIABLES)


def _option(argv):
    """The interpreter option argv[1] is (`-c`, `-m`, `-`, ...), or None."""
    return argv[1] if len(argv) > 1 and argv[1].startswith('-') else None


def _script(argv):
    """argv[1] when it names a script (not an option, not stdin), else None."""
    return argv[1] if len(argv) > 1 and not argv[1].startswith('-') else None


def judge(job, uid, gid, server):
    """Why the fork cannot be this process (a sentence), or None when it can. `server` is the server's own
    {'uid', 'gid', 'pinned', 'limits'}."""
    if (uid, gid) != (server['uid'], server['gid']):
        return 'another user'
    argv = job.argv
    if not argv:
        return 'no argv'
    if len(argv) > 1 and argv[1].startswith('-') and argv[1] not in ('-c', '-m', '-'):
        return f'the option {argv[1]}'
    if _option(argv) in ('-c', '-m') and len(argv) <= ARGUMENT:
        return f'{argv[1]} without its argument'
    if _pinned(job.environ) != server['pinned']:
        return 'an interpreter variable differs'
    if _limits(job.pid) != server['limits']:
        return 'a resource limit differs'
    targets = {target for target, _ in job.fds}
    if not set(STANDARD) <= targets:
        return 'a standard descriptor is closed'
    if any(os.isatty(fd) for target, fd in job.fds if target in STANDARD):
        return 'a terminal'
    script = _script(argv)
    if script is not None:
        try:
            import stat
            if not stat.S_ISREG(os.stat(script, dir_fd=job.cwd).st_mode):
                return 'the script is not a file'
        except OSError:
            return 'the script is not there'
    return None


def _environ(raw):
    out = {}
    for item in raw.split(b'\0'):
        if b'=' in item:
            key, _, value = item.partition(b'=')
            out[os.fsdecode(key)] = os.fsdecode(value)
    return out


def _request(conn):
    """The client's process: (Job, uid, gid), or None when the message is not a request."""
    pid, uid, gid = struct.unpack(CREDENTIALS, conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED,
                                                               struct.calcsize(CREDENTIALS)))
    size = struct.calcsize(TARGET)
    message, fds, _, _ = socket.recv_fds(conn, os.sysconf('SC_PAGE_SIZE'), os.sysconf('SC_PAGE_SIZE') // size)
    targets = [value for (value,) in struct.iter_unpack(TARGET, message[:len(message) - len(message) % size])]
    if not fds or len(targets) != len(fds) - 1:
        for fd in fds:
            os.close(fd)
        return None
    try:
        argv = [os.fsdecode(part) for part in _proc(pid, 'cmdline').split(b'\0')[:-1]]
        umask, ignored, blocked = _status(pid)
        environ = _environ(_proc(pid, 'environ'))
    except (OSError, KeyError, ValueError):
        for fd in fds:
            os.close(fd)
        return None
    return Job(pid, argv, environ, umask, ignored, blocked, fds[0], list(zip(targets, fds[1:]))), uid, gid


def _close(job):
    for fd in [job.cwd, *(fd for _, fd in job.fds)]:
        os.close(fd)


CUSTOMIZE = ('sitecustomize', 'usercustomize')  # site.py's start-up modules: each fork imports its own


def forget_customize():
    """Drop the customize modules the server's own start-up imported (a sandbox image ships a sitecustomize.py in the
    standard library), so a fork's `_customize` imports the one its own sys.path finds, as a fresh interpreter does:
    otherwise the import is a no-op and the harness on the test's PYTHONPATH never runs (no hermetic rules, no pins)."""
    for name in CUSTOMIZE:
        sys.modules.pop(name, None)


def serve(folder, preload=()):
    """Listen on <folder>/socket and fork per request. Returns only in a fork: the Job it is to become."""
    forget_customize()
    for name in preload:
        try:
            __import__(name)
        except ImportError:
            pass
    # the environment the server was started with: the interpreter adds LC_CTYPE to os.environ (PEP 538)
    started = _environ(_proc('self', 'environ'))
    server = {'uid': os.getuid(), 'gid': os.getgid(), 'pinned': _pinned(started), 'limits': _limits()}
    path = os.path.join(folder, SOCKET)
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
    listener.bind(path)
    listener.listen(socket.SOMAXCONN)
    selector = selectors.DefaultSelector()
    selector.register(listener, selectors.EVENT_READ, None)
    children = {}  # pid -> (connection, pidfd)
    gc.collect()
    gc.freeze()  # the heap every fork shares: the collector never touches (and so never copies) its pages
    with open(os.path.join(folder, READY), 'w'):
        pass
    _signal_ready()
    try:
        while True:
            for key, _ in selector.select():
                if key.data is None:
                    job = _accept(listener, selector, children, server)
                    if job is not None:  # this is the fork
                        _leave(listener, selector, children)
                        return job
                elif key.data[0] == 'exit':
                    _ended(key.data[1], selector, children)
                else:  # the client's connection: readable means it ended before its process did
                    pid = key.data[1]
                    selector.unregister(key.fileobj)
                    _kill(pid)
    finally:
        if not _forked(children):
            for pid in list(children):
                _kill(pid)
            for pid in list(children):
                os.waitpid(pid, 0)
            selector.close()
            listener.close()
            for name in (SOCKET, READY):
                try:
                    os.unlink(os.path.join(folder, name))
                except FileNotFoundError:
                    pass


_PARENT = os.getpid()


def _forked(children):
    return os.getpid() != _PARENT


def _kill(pid):
    for target in (-pid, pid):  # its process group, then itself when it has not made its group yet
        try:
            os.kill(target, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass


def _accept(listener, selector, children, server):
    conn, _ = listener.accept()
    request = _request(conn)
    if request is None:
        conn.close()
        return None
    job, uid, gid = request
    reason = judge(job, uid, gid, server)
    if reason is not None:
        print(f'fork-server: {job.pid} execs the interpreter: {reason}', file=sys.stderr, flush=True)
        _close(job)
        conn.send(FALLBACK)
        conn.close()
        return None
    pid = os.fork()
    if pid == 0:
        conn.close()
        return job
    _close(job)
    conn.send(STARTED + struct.pack(STATUS, pid))
    pidfd = os.pidfd_open(pid)
    children[pid] = (conn, pidfd)
    selector.register(pidfd, selectors.EVENT_READ, ('exit', pid))
    selector.register(conn, selectors.EVENT_READ, ('client', pid))
    return None


def _ended(pid, selector, children):
    conn, pidfd = children.pop(pid)
    selector.unregister(pidfd)
    os.close(pidfd)
    _, status = os.waitpid(pid, 0)
    try:
        selector.unregister(conn)
    except KeyError:
        pass  # the client had already gone
    try:
        conn.send(EXITED + struct.pack(STATUS, status))
    except OSError:
        pass
    conn.close()


def _leave(listener, selector, children):
    """In the fork: drop the server's sockets before the descriptors are rebuilt."""
    for conn, pidfd in children.values():
        conn.close()
        os.close(pidfd)
    children.clear()
    selector.close()
    listener.close()


def _descriptors(job):
    """Each descriptor of the client at its own number, and nothing else; the working directory is the client's."""
    os.fchdir(job.cwd)
    floor = max([job.cwd, *(target for target, _ in job.fds), *(fd for _, fd in job.fds)]) + 1
    import fcntl
    moved = [(target, fcntl.fcntl(fd, fcntl.F_DUPFD_CLOEXEC, floor)) for target, fd in job.fds]
    keep = {fd for _, fd in moved}
    for name in os.listdir('/proc/self/fd'):
        fd = int(name)
        if fd not in keep:
            try:
                os.close(fd)
            except OSError:
                pass  # the listing's own descriptor
    for target, fd in moved:
        os.dup2(fd, target)
        os.close(fd)


def _signals(job):
    for number in signal.valid_signals():
        if number in (signal.SIGKILL, signal.SIGSTOP):
            continue
        if number in job.ignored:
            signal.signal(number, signal.SIG_IGN)
        elif number == signal.SIGINT:
            signal.signal(number, signal.default_int_handler)
        elif number not in (signal.SIGPIPE, signal.SIGXFSZ):  # a fresh interpreter ignores these two
            signal.signal(number, signal.SIG_DFL)
    signal.pthread_sigmask(signal.SIG_SETMASK, job.blocked)


def _stdio():
    """New standard streams over descriptors 0-2, as a fresh interpreter builds them (seekable or not, a pipe or a file)."""
    import io
    streams, buffered = [], not sys.stdout.write_through  # PYTHONUNBUFFERED is pinned: the server's own streams say
    for fd, mode, old in zip(STANDARD, ('r', 'w', 'w'), (sys.stdin, sys.stdout, sys.stderr)):
        buffer = io.open(fd, mode + 'b', -1 if buffered or mode == 'r' else 0, closefd=False)
        stream = io.TextIOWrapper(buffer, encoding=old.encoding, errors=old.errors, newline='\n',
                                  line_buffering=buffered and (fd == STDERR_FILENO or buffer.isatty()),
                                  write_through=not buffered)
        stream.mode = mode
        streams.append(stream)
    sys.stdin, sys.stdout, sys.stderr = streams
    sys.__stdin__, sys.__stdout__, sys.__stderr__ = streams


def _entries(environ):
    """PYTHONPATH as a fresh interpreter puts it on sys.path: each entry absolute, an empty one the working directory."""
    value = environ.get('PYTHONPATH', '')
    return [os.path.abspath(entry) for entry in value.split(os.pathsep)] if value else []


def _executable(argv0, environ):
    if os.sep in argv0:
        return os.path.abspath(argv0)
    for folder in environ.get('PATH', os.defpath).split(os.pathsep):
        candidate = os.path.join(folder or '.', argv0)
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return os.path.abspath(candidate)
    return sys.executable


def _customize(name):
    """site.py's execsitecustomize/execusercustomize: a missing module is silent, a failing one prints and goes on."""
    try:
        __import__(name)
    except ImportError as error:
        if error.name != name:
            print(f'Error in {name}; set PYTHONVERBOSE for traceback:\n{type(error).__name__}: {error}',
                  file=sys.stderr)
    except Exception as error:  # noqa: BLE001 - what site.py does
        print(f'Error in {name}; set PYTHONVERBOSE for traceback:\n{type(error).__name__}: {error}', file=sys.stderr)


def become(job, base_path):
    """In the fork: rebuild a fresh `python3 <argv>` from the client's state; returns the run's exit code."""
    gc.enable()
    _signals(job)
    os.setpgid(0, 0)
    _descriptors(job)
    os.umask(job.umask)
    os.environ.clear()
    os.environ.update(job.environ)
    import time
    time.tzset()
    if 'tempfile' in sys.modules:
        sys.modules['tempfile'].tempdir = None
    sys.dont_write_bytecode = bool(job.environ.get('PYTHONDONTWRITEBYTECODE'))
    _stdio()
    argv = job.argv
    sys.orig_argv = list(argv)
    sys.executable = _executable(argv[0], job.environ)
    script = _script(argv)
    if _option(argv) in ('-c', '-m'):
        sys.argv = [argv[1], *argv[ARGUMENT + 1:]]
    elif _option(argv) == '-':
        sys.argv = argv[1:]
    else:
        sys.argv = argv[1:] or ['']
    sys.path[:] = _entries(job.environ) + base_path
    _customize('sitecustomize')
    import site
    if site.ENABLE_USER_SITE:
        _customize('usercustomize')
    if script is not None:
        sys.path.insert(0, os.path.dirname(os.path.realpath(script)))
    elif _option(argv) == '-m':
        sys.path.insert(0, os.getcwd())
    else:
        sys.path.insert(0, '')
    return _main(argv, script)


def _main(argv, script):
    import types
    main = types.ModuleType('__main__')
    main.__dict__['__builtins__'] = __builtins__
    sys.modules['__main__'] = main
    try:
        if _option(argv) == '-m':
            import runpy
            runpy._run_module_as_main(argv[ARGUMENT], alter_argv=True)
        else:
            if script is not None:
                import importlib.machinery
                with open(script, 'rb') as handle:
                    source = handle.read()
                main.__file__, main.__cached__ = script, None
                main.__loader__ = importlib.machinery.SourceFileLoader('__main__', script)
                name = script
            elif _option(argv) == '-c':
                main.__loader__ = importlib_loader()
                source, name = argv[ARGUMENT], '<string>'
            else:
                main.__loader__ = importlib_loader()
                source, name = sys.stdin.buffer.read(), '<stdin>'
            exec(compile(source, name, 'exec'), main.__dict__)
    except SystemExit as stop:
        return stop.code
    except BaseException as error:  # noqa: BLE001 - a fresh interpreter prints it and exits 1
        trace = error.__traceback__
        while trace is not None and trace.tb_frame.f_code.co_filename in (_HERE, '<frozen runpy>'):
            trace = trace.tb_next
        sys.excepthook(type(error), error.with_traceback(trace), trace)
        if isinstance(error, KeyboardInterrupt):
            sys.stdout.flush()
            sys.stderr.flush()
            signal.signal(signal.SIGINT, signal.SIG_DFL)
            os.kill(os.getpid(), signal.SIGINT)
        return 1
    return 0


def importlib_loader():
    import importlib.machinery
    return importlib.machinery.BuiltinImporter


def interpreter(environ, toolchain=None):
    """The real interpreter the client execs: an outer run's (OU_FORK_SERVER_PYTHON), else the toolchain's python3 when
    `toolchain` has one, else python3 on the tests' PATH. scripts/cloud/env.sh puts the client ahead of the toolchain and
    promises it execs the toolchain's interpreter, so a runner started without env.sh (gate_test_cache.py run by hand)
    must not hand the tests the host's python3 behind the client."""
    if os.environ.get(PYTHON):
        return os.environ[PYTHON]
    pinned = os.path.join(toolchain, BIN, 'python3') if toolchain else None
    if pinned and os.access(pinned, os.X_OK):
        return pinned
    return shutil.which('python3', path=environ.get('PATH')) or sys.executable


@contextlib.contextmanager
def started(environ, preload, compiler, start_s, reuse=True, toolchain=None):
    """One fork server for a suite run: yields the variables its tests get (the client first on PATH, the server, the
    real interpreter), or {} when there is none to start (no compiler, no pidfd, a server that did not listen within
    start_s) or an outer run's server already serves this one. The starter blocks on a pipe the server writes READY on
    (READY_FD), woken by that write or by the server's exit (end of file), never by an interval. `environ`: the tests'
    own; `toolchain`: the checkout's .toolchain, whose python3 is the real interpreter (interpreter())."""
    if reuse and os.environ.get(SERVER) and os.path.exists(os.path.join(os.environ[SERVER], READY)):
        yield {}
        return
    built = shutil.which(compiler)
    if built is None or not hasattr(os, 'pidfd_open'):
        yield {}
        return
    folder = tempfile.mkdtemp(prefix='ou-fork-server-')
    client = os.path.join(folder, BIN, 'python3')
    process = None
    try:
        os.mkdir(os.path.join(folder, BIN))
        source = os.path.join(os.path.dirname(_HERE), 'fork-shim.c')
        real = interpreter(environ, toolchain)
        made = subprocess.run([built, '-O2', f'-DREAL_PYTHON={json.dumps(real)}', '-o', client, source],
                              capture_output=True, text=True, check=False)
        if made.returncode == 0:
            # the server never runs a sitecustomize (the harness): each fork runs its own, with its own environment
            entries = [entry for entry in environ.get('PYTHONPATH', '').split(os.pathsep)
                       if entry and not os.path.exists(os.path.join(entry, 'sitecustomize.py'))]
            server_env = {**environ, 'PYTHONPATH': os.pathsep.join(entries)}
            if not server_env['PYTHONPATH']:
                del server_env['PYTHONPATH']
            reader, writer = os.pipe()
            try:
                with open(os.path.join(folder, 'log'), 'w') as log:
                    process = subprocess.Popen([real, _HERE, 'serve', folder, *preload],
                                               env={**server_env, READY_FD: str(writer)}, pass_fds=(writer,),
                                               stdin=subprocess.DEVNULL, stdout=log, stderr=log)
                os.close(writer)
                writer = None
                select.select([reader], [], [], start_s)  # READY, the server's exit (EOF) or start_s
            finally:
                if writer is not None:
                    os.close(writer)
                os.close(reader)
        if process is None or not os.path.exists(os.path.join(folder, READY)):
            yield {}
            return
        yield {SERVER: folder, PYTHON: real, 'OU_PYTHON': client,
               'PATH': os.pathsep.join([os.path.dirname(client), environ.get('PATH', os.defpath)])}
    finally:
        if process is not None:
            process.terminate()
            process.wait()
        shutil.rmtree(folder, ignore_errors=True)


def main(argv):
    if len(argv) <= ARGUMENT or argv[1] != 'serve':
        sys.exit('usage: fork_server.py serve <dir> [<module> ...]')
    folder, preload = argv[ARGUMENT], argv[ARGUMENT + 1:]
    own = set(_entries(os.environ))
    base_path = [entry for entry in sys.path[1:] if entry not in own]
    signal.signal(signal.SIGTERM, _stop)
    job = serve(folder, preload)
    return become(job, base_path)


def _signal_ready():
    """Tells the starter the server listens: one byte on the READY_FD pipe, then closes it (started())."""
    fd = os.environ.pop(READY_FD, '')
    if not fd.isdigit():
        return
    try:
        os.write(int(fd), READY.encode())
    except OSError:
        pass
    finally:
        os.close(int(fd))


def _stop(_number, _frame):
    raise SystemExit(0)


def _measured():
    """The coverage guard measures the server, and each fork goes on measuring itself: coverage.py writes a fork's data
    to its own file once the pid differs (CoverageData._start_using), and the harness's process_startup() is then a
    no-op."""
    if os.environ.get('COVERAGE_PROCESS_START'):
        try:
            import coverage
            coverage.process_startup()
        except ImportError:
            pass


if __name__ == '__main__':
    _measured()
    sys.exit(main(sys.argv))
