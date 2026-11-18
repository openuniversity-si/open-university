"""GATE-SPEED F4 (D-122): a fork of the warm server is the process `python3 <argv>` would have been. Hermetic."""
import io
import json
import os
import pathlib
import select
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

import config  # noqa: E402
import fork_server  # noqa: E402

TWO = 1 + 1  # small numbers built from 1, so no new literal enters the census
SEVEN = TWO * TWO + TWO + 1
PROBE = ("import json, os, sys; print(json.dumps({'argv': sys.argv, 'cwd': os.getcwd(), 'umask': os.umask(0),"
         " 'value': os.environ.get('PROBE_VALUE'), 'path0': sys.path[0], 'main': __name__,"
         " 'parent': open(f'/proc/{os.getppid()}/cmdline').read()}))")


class Server(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.base = pathlib.Path(cls._tmp.name)
        environ = {key: value for key, value in os.environ.items() if not key.startswith("OU_FORK_SERVER")}
        cls._started = fork_server.started(
            environ, [*config.get("gate.fork_server_preload"), "no_such_module_anywhere"],
            config.get("gate.fork_server_compiler"),
            config.get("gate.fork_server_start_s"), reuse=False)
        cls.overlay = cls._started.__enter__()
        cls.env = {**environ, **cls.overlay, "PROBE_VALUE": "from-the-caller"}

    @classmethod
    def tearDownClass(cls):
        cls._started.__exit__(None, None, None)
        cls._tmp.cleanup()

    def client(self, *args, **kwargs):
        return subprocess.run([self.overlay.get("OU_PYTHON", sys.executable), *args], env=kwargs.pop("env", self.env),
                              capture_output=True, text=True, **kwargs)

    def log(self):
        return (pathlib.Path(self.overlay[fork_server.SERVER]) / "log").read_text()

    def test_the_server_starts_where_a_compiler_is(self):
        self.assertTrue(self.overlay, "no fork server started on a box with a C compiler")
        self.assertEqual(self.overlay["PATH"].split(os.pathsep)[0],
                         str(pathlib.Path(self.overlay["OU_PYTHON"]).parent))

    def test_a_fork_is_the_process_python3_would_be(self):
        done = self.client("-c", PROBE, "one", "two", cwd=self.base)
        self.assertEqual(done.returncode, 0, done.stderr)
        seen = json.loads(done.stdout)
        self.assertIn("fork_server.py", seen["parent"])  # a fork, not an exec
        fresh = json.loads(subprocess.run([sys.executable, "-c", PROBE, "one", "two"], env=self.env, cwd=self.base,
                                          capture_output=True, text=True, check=True).stdout)
        for key in ("argv", "cwd", "umask", "value", "path0", "main"):
            self.assertEqual(seen[key], fresh[key], key)

    def test_a_script_runs_as_main_with_its_folder_first_on_the_path(self):
        script = self.base / "probe.py"
        script.write_text(PROBE + "\n")
        done = self.client(str(script), "x", cwd=self.base)
        seen = json.loads(done.stdout)
        self.assertEqual((seen["argv"], seen["path0"], seen["main"]), ([str(script), "x"], str(self.base), "__main__"))

    def test_a_fork_runs_the_sitecustomize_on_its_own_pythonpath(self):
        # the harness is a sitecustomize on PYTHONPATH; the server's start-up may have imported the image's own one
        folder = self.base / "customize"
        folder.mkdir(exist_ok=True)
        (folder / "sitecustomize.py").write_text("import os\nos.environ['PROBE_CUSTOMIZED'] = __file__\n")
        done = self.client("-c", "import os; print(os.environ.get('PROBE_CUSTOMIZED'))",
                           env={**self.env, "PYTHONPATH": str(folder)})
        self.assertEqual((done.returncode, done.stdout.strip()), (0, str(folder / "sitecustomize.py")), done.stderr)

    def test_a_module_and_a_program_on_stdin_run_like_python3(self):
        done = self.client("-m", "json.tool", input='{"a": 1}')
        self.assertEqual((done.returncode, json.loads(done.stdout)), (0, {"a": 1}))
        done = self.client("-", input="import sys\nprint('stdin', sys.argv)\n")
        self.assertEqual(done.stdout, "stdin ['-']\n")

    def test_exit_codes_and_uncaught_exceptions_are_the_interpreters(self):
        self.assertEqual(self.client("-c", f"import sys; sys.exit({SEVEN})").returncode, SEVEN)
        done = self.client("-c", "import sys; sys.exit('a message')")
        self.assertEqual((done.returncode, done.stderr), (1, "a message\n"))
        done = self.client("-c", "raise ValueError('boom')")
        self.assertEqual(done.returncode, 1)
        self.assertEqual(done.stderr.splitlines(), ["Traceback (most recent call last):",
                                                    '  File "<string>", line 1, in <module>', "ValueError: boom"])

    def test_a_signal_the_fork_dies_of_is_the_clients_status(self):
        done = self.client("-c", "import os, signal; os.kill(os.getpid(), signal.SIGTERM)")
        self.assertEqual(done.returncode, -signal.SIGTERM)

    def started(self):
        """A fork that reports its pid on a pipe once it runs, then waits on its stdin: (client process, fork pid)."""
        read, write = os.pipe()
        process = subprocess.Popen([self.overlay["OU_PYTHON"], "-c",
                                    f"import os, sys; os.write({write}, str(os.getpid()).encode()); os.close({write});"
                                    " sys.stdin.read()"], env=self.env, stdin=subprocess.PIPE, pass_fds=(write,))
        os.close(write)
        with os.fdopen(read, "rb") as reader:
            fork = int(reader.read())
        self.addCleanup(process.stdin.close)
        return process, fork

    def test_a_signal_sent_to_the_client_reaches_the_fork(self):
        process, _ = self.started()
        process.terminate()
        self.assertEqual(process.wait(), -signal.SIGTERM)

    def test_a_client_killed_takes_its_fork_with_it(self):
        process, fork = self.started()
        self.assertNotEqual(fork, process.pid)
        gone = os.pidfd_open(fork)  # readable once the fork has ended
        try:
            process.kill()
            process.wait()
            ready, _, _ = select.select([gone], [], [])  # blocks until the fork ends (the harness times a hang out)
        finally:
            os.close(gone)
        self.assertEqual(ready, [gone])

    def test_an_uncaught_interrupt_ends_the_fork_by_sigint(self):
        done = self.client("-c", "raise KeyboardInterrupt")
        self.assertEqual(done.returncode, -signal.SIGINT)
        self.assertIn("KeyboardInterrupt", done.stderr)

    def test_every_open_descriptor_reaches_the_fork_at_its_number(self):
        read, write = os.pipe()
        try:
            done = self.client("-c", f"import os; os.write({write}, b'through')", pass_fds=(write,))
            os.close(write)
            self.assertEqual((done.returncode, os.read(read, len(b"through") + 1)), (0, b"through"))
        finally:
            os.close(read)

    def test_what_the_fork_does_not_model_runs_the_real_interpreter(self):
        done = self.client("-E", "-c", "import sys; print(sys.flags.ignore_environment)")
        self.assertEqual((done.returncode, done.stdout), (0, "1\n"))
        self.assertIn("the option -E", self.log())
        changed = {**self.env, "PYTHONHASHSEED": str(SEVEN)}
        done = self.client("-c", "import os; print(os.environ['PYTHONHASHSEED'])", env=changed)
        self.assertEqual(done.stdout, f"{SEVEN}\n")
        self.assertIn("an interpreter variable differs", self.log())
        done = self.client(str(self.base / "absent.py"))
        self.assertEqual(done.returncode, TWO)  # python3's own "can't open file"
        self.assertIn("the script is not there", self.log())

    def test_the_shell_environment_keeps_the_client_first(self):
        shell = 'source scripts/cloud/env.sh && command -v python3 && echo "$OU_PYTHON"'
        done = subprocess.run(["bash", "-c", shell], cwd=ROOT, env=self.env, capture_output=True, text=True)
        self.assertEqual(done.stdout.split(), [self.overlay["OU_PYTHON"]] * TWO, done.stderr)
        outside = {key: value for key, value in self.env.items() if key != fork_server.SERVER}
        done = subprocess.run(["bash", "-c", shell], cwd=ROOT, env=outside, capture_output=True, text=True)
        self.assertNotEqual(done.stdout.split()[-1], self.overlay["OU_PYTHON"])  # OU_PYTHON: env.sh's own choice


class Judge(unittest.TestCase):
    """judge() in process: each reason the fork cannot be the process."""

    def setUp(self):
        self.server = {"uid": os.getuid(), "gid": os.getgid(), "pinned": [], "limits": fork_server._limits()}
        self.fds = []

    def tearDown(self):
        for fd in self.fds:
            os.close(fd)

    def job(self, argv, environ=None, standard=True):
        fds = []
        if standard:
            for target in (0, 1, TWO):
                fd = os.open(os.devnull, os.O_RDWR)
                self.fds.append(fd)
                fds.append((target, fd))
        cwd = os.open(".", os.O_RDONLY)
        self.fds.append(cwd)
        return fork_server.Job(os.getpid(), argv, environ or {}, 0, set(), set(), cwd, fds)

    def test_each_reason(self):
        uid, gid = self.server["uid"], self.server["gid"]
        self.assertIsNone(fork_server.judge(self.job(["python3", "-c", "pass"]), uid, gid, self.server))
        self.assertEqual(fork_server.judge(self.job(["python3", "-c", "pass"]), uid + 1, gid, self.server),
                         "another user")
        self.assertEqual(fork_server.judge(self.job(["python3", "-I", "x.py"]), uid, gid, self.server),
                         "the option -I")
        self.assertEqual(fork_server.judge(self.job(["python3", "-c"]), uid, gid, self.server), "-c without its argument")
        self.assertEqual(fork_server.judge(self.job(["python3", "-c", "pass"], {"PYTHONOPTIMIZE": "1"}), uid, gid,
                                           self.server), "an interpreter variable differs")
        self.assertIsNone(fork_server.judge(self.job(["python3", "-c", "pass"], {"PYTHONPATH": "x",
                                                                                 "PYTHONDONTWRITEBYTECODE": "1"}),
                                            uid, gid, self.server))
        self.assertEqual(fork_server.judge(self.job(["python3", "-c", "pass"], standard=False), uid, gid, self.server),
                         "a standard descriptor is closed")
        self.assertEqual(fork_server.judge(self.job(["python3", "missing.py"]), uid, gid, self.server),
                         "the script is not there")
        self.assertEqual(fork_server.judge(self.job([]), uid, gid, self.server), "no argv")

    def test_a_message_without_descriptors_is_not_a_request(self):
        server, client = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        with server, client:
            client.send(b"x")
            self.assertIsNone(fork_server._request(server))

    def test_a_terminal_a_folder_and_another_limit_run_the_real_interpreter(self):
        uid, gid = self.server["uid"], self.server["gid"]
        primary, secondary = os.openpty()
        self.fds += [primary, secondary]
        job = self.job(["python3", "-c", "pass"])
        job.fds[0] = (0, secondary)
        self.assertEqual(fork_server.judge(job, uid, gid, self.server), "a terminal")
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(fork_server.judge(self.job(["python3", folder]), uid, gid, self.server),
                             "the script is not a file")
        other = {**self.server, "limits": {**self.server["limits"], "RLIMIT_CORE": (0, 0)}}
        if other["limits"] != self.server["limits"]:
            self.assertEqual(fork_server.judge(self.job(["python3", "-c", "pass"]), uid, gid, other),
                             "a resource limit differs")

    def test_the_interpreter_found_like_python3_finds_itself(self):
        self.assertEqual(fork_server._executable("no-such-interpreter-here", {"PATH": ""}), sys.executable)
        self.assertEqual(fork_server._executable("./x", {}), os.path.abspath("./x"))

    def test_a_failing_customize_module_is_reported_and_skipped(self):
        with tempfile.TemporaryDirectory() as folder:
            pathlib.Path(folder, "broken_customize_probe.py").write_text("raise ValueError('broken')\n")
            sys.path.insert(0, folder)
            try:
                with mock.patch("sys.stderr", new_callable=io.StringIO) as err:
                    fork_server._customize("broken_customize_probe")
                    fork_server._customize("absent_customize_probe")
            finally:
                sys.path.remove(folder)
                sys.modules.pop("broken_customize_probe", None)
        self.assertEqual(err.getvalue(), "Error in broken_customize_probe; set PYTHONVERBOSE for traceback:\n"
                                         "ValueError: broken\n")

    def test_the_server_forgets_its_start_up_customize_modules(self):
        held = {name: sys.modules.get(name) for name in fork_server.CUSTOMIZE}
        try:
            for name in fork_server.CUSTOMIZE:
                sys.modules[name] = mock.sentinel.customize
            fork_server.forget_customize()
            self.assertEqual([name for name in fork_server.CUSTOMIZE if name in sys.modules], [])
        finally:
            for name, module in held.items():
                if module is not None:
                    sys.modules[name] = module

    def test_a_proc_mask_names_its_signals(self):
        self.assertEqual(fork_server._mask("0000000000000001"), {1})
        self.assertEqual(fork_server._mask(format((1 << (signal.SIGTERM - 1)) | 1, "x")), {1, int(signal.SIGTERM)})

    def test_pythonpath_is_absolute_and_an_empty_entry_is_the_working_directory(self):
        self.assertEqual(fork_server._entries({"PYTHONPATH": "rel" + os.pathsep}),
                         [os.path.abspath("rel"), os.getcwd()])
        self.assertEqual(fork_server._entries({}), [])


class Interpreter(unittest.TestCase):
    """env.sh puts the client ahead of the toolchain: the client execs the toolchain's python3, whatever the runner's PATH."""

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.toolchain = os.path.join(folder.name, ".toolchain")
        self.host = os.path.join(folder.name, "host")
        for place in (os.path.join(self.toolchain, "bin"), self.host):
            os.makedirs(place)
            path = os.path.join(place, "python3")
            pathlib.Path(path).touch()
            os.chmod(path, stat.S_IRWXU)
        patcher = mock.patch.dict(os.environ)
        patcher.start()
        self.addCleanup(patcher.stop)
        os.environ.pop(fork_server.PYTHON, None)

    def test_the_toolchain_wins_over_a_runner_path_without_it(self):
        found = fork_server.interpreter({"PATH": self.host}, self.toolchain)
        self.assertEqual(found, os.path.join(self.toolchain, "bin", "python3"))

    def test_no_toolchain_falls_back_to_the_tests_path(self):
        self.assertEqual(fork_server.interpreter({"PATH": self.host}, None), os.path.join(self.host, "python3"))
        missing = os.path.join(self.host, ".toolchain")
        self.assertEqual(fork_server.interpreter({"PATH": self.host}, missing), os.path.join(self.host, "python3"))

    def test_an_outer_runs_interpreter_is_kept(self):
        os.environ[fork_server.PYTHON] = "/outer/python3"
        self.assertEqual(fork_server.interpreter({"PATH": self.host}, self.toolchain), "/outer/python3")


class NoServer(unittest.TestCase):
    def test_a_box_without_the_compiler_runs_fresh_interpreters(self):
        with fork_server.started(dict(os.environ), [], "no-such-compiler-on-this-box", 1, reuse=False) as overlay:
            self.assertEqual(overlay, {})

    def test_a_server_that_does_not_listen_in_time_runs_fresh_interpreters(self):
        environ = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
        with fork_server.started(environ, [], config.get("gate.fork_server_compiler"), 0,
                                 reuse=False) as overlay:
            self.assertEqual(overlay, {})

    def test_the_server_says_ready_on_the_starters_pipe_and_closes_it(self):
        # F8b: the starter blocks on this pipe (select), woken by the byte or by the server's exit, never an interval
        reader, writer = os.pipe()
        try:
            with mock.patch.dict(os.environ, {fork_server.READY_FD: str(writer)}):
                fork_server._signal_ready()
                self.assertNotIn(fork_server.READY_FD, os.environ)
            self.assertEqual(os.read(reader, len(fork_server.READY) + 1), fork_server.READY.encode())
            self.assertEqual(os.read(reader, 1), b"")  # closed: the server's forks never inherit it
        finally:
            os.close(reader)

    def test_an_outer_runs_server_serves_an_inner_run(self):
        with tempfile.TemporaryDirectory() as folder:
            pathlib.Path(folder, fork_server.READY).touch()
            with mock.patch.dict(os.environ, {fork_server.SERVER: folder}):
                with fork_server.started(dict(os.environ), [], "cc", 1) as overlay:
                    self.assertEqual(overlay, {})


if __name__ == "__main__":
    unittest.main()
