"""Claude Code cloud adapter of the launcher port: the only engine module that starts a cloud session with the CLI.

One launch is `<coordinator.launcher_argv> <brief>`; the new session id is the first match of
coordinator.launcher_session_pattern in the output. The runner is injected so tests need no CLI.

preflight() probes every flag of coordinator.launcher_argv against `<command> --help` before any launch, so a flag the
CLI does not have fails at preflight, not at the first launch of an idle lane (D-206 (d), L1).
"""
import re
import subprocess

import config


class ClaudeLauncherError(RuntimeError):
    pass


class ClaudeCloudLauncher:
    name = 'claude'

    def __init__(self, runner=subprocess.run):
        self.argv = list(config.get('coordinator.launcher_argv'))
        self.pattern = re.compile(config.get('coordinator.launcher_session_pattern'))
        self.timeout = config.get('coordinator.launcher_timeout_s')
        self.runner = runner

    def preflight(self):
        """Refuses a launch argv whose flags the command's --help does not list (D-206 (d))."""
        flags = sorted({token.split('=', 1)[0] for token in self.argv[1:] if token.startswith('--')})
        if not flags:
            return
        done = self.runner(self.argv[:1] + ['--help'], capture_output=True, text=True, timeout=self.timeout)
        text = (done.stdout or '') + (done.stderr or '')
        missing = [flag for flag in flags if not re.search(re.escape(flag) + r'(?![\w-])', text)]
        if missing:
            raise ClaudeLauncherError(f'launch argv {" ".join(self.argv)} names flags that {self.argv[0]} --help does not list: '
                                      f'{", ".join(missing)}; fix coordinator.launcher_argv (D-206 (d))')

    def launch(self, request):
        done = self.runner(self.argv + [request.brief], capture_output=True, text=True, timeout=self.timeout)
        found = self.pattern.search(done.stdout or '')
        if done.returncode != 0 or not found:
            raise ClaudeLauncherError(f'launch of {request.unit} failed: exit {done.returncode}, no session id')
        return found.group(0)
