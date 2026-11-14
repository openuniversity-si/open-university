"""The session launcher port (D-069 CO1): the coordinator starts a unit's session here, never a vendor CLI.

Adapter interface (what the Claude Code cloud CLI implements today; the box-side launcher stays outside the repo):
  name              the adapter id (`claude`).
  launch(request)   start one cloud session with the brief; the session id it reports.
LaunchRequest carries the unit, the attempt, the model and the rendered brief. DryRunLauncher starts nothing and returns
no session; coordinator.launcher_default picks the adapter when a caller names none.
"""
from collections import namedtuple
from pathlib import Path
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402

LaunchRequest = namedtuple('LaunchRequest', 'unit attempt model brief')


class LauncherError(RuntimeError):
    pass


class DryRunLauncher:
    name = 'dry-run'

    def __init__(self):
        self.requests = []

    def preflight(self):
        return None

    def launch(self, request):
        self.requests.append(request)
        return None


def _claude():
    from adapters import launcher_claude  # the vendor module loads only when the registry selects it
    return launcher_claude.ClaudeCloudLauncher()


ADAPTERS = {'claude': _claude}


def adapter(name=None):
    name = name or config.get('coordinator.launcher_default')
    if name not in ADAPTERS:
        raise LauncherError(f'unknown launcher {name}; adapters: {sorted(ADAPTERS)}')
    return ADAPTERS[name]()
