"""The CI runner port (D-069 item 7, plan v3.1 R1): the engine runs a PR's gate here, never a CI vendor.

Adapter interface:
  name                  the runner id (`local`).
  run(pr, report_dir)   run the gate of the PR checked out in the working tree and wait for it to exit; a GateRun
                        with the exit code and one Stage per gate stage (name, exit, duration_ms) from report_dir.
providers.ci_runner picks the adapter. The only adapter is the local gate runner (ci_local.py), which runs the same
command on a laptop and in a provider cloud session (D-069 item 12). GitHub Actions is never an adapter (AGENTS.md:
no GitHub Actions or third-party CI); the vendor catalog lists it with no adapter, so any use fails the vendor check.
"""
from collections import namedtuple
from pathlib import Path
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402

Stage = namedtuple('Stage', 'name exit duration_ms')
GateRun = namedtuple('GateRun', 'runner exit stages report_dir')


class CIRunnerError(RuntimeError):
    pass


def _local():
    from adapters import ci_local  # the runner module loads only when the registry selects it
    return ci_local.LocalGateRunner()


ADAPTERS = {'local': _local}


def runner(name=None):
    name = name or config.get('providers.ci_runner')
    if name not in ADAPTERS:
        raise CIRunnerError(f'unknown CI runner {name}')
    return ADAPTERS[name]()


def passed(run):
    return run.exit == 0 and all(stage.exit == 0 for stage in run.stages)
