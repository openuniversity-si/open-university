"""The gate verdicts every reader accepts (GX-09, D-070): gate.passed and gate.failed at every locked contract version.

The accepted versions are read from the contract catalog (contracts/events, event_contracts.catalog), never named in a
reader: "readers accept every locked version" (event_contracts), so v3 and v4 are accepted today and a new locked
version needs no reader edit. pr_ready, slo and stall_report select verdicts through this module only. A tier-2/3
verdict (v4, pr null) is accepted here; replay and the per-PR readers skip it because it names no PR.
"""
from functools import lru_cache
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

import event_contracts  # noqa: E402

TYPES = ('gate.passed', 'gate.failed')


@lru_cache(maxsize=None)
def _catalog(directory):
    return event_contracts.catalog(directory)


def accepted_versions(kind, directory=None):
    """The locked versions of a verdict type, oldest first; () for a type that is not a gate verdict."""
    if kind not in TYPES:
        return ()
    return tuple(sorted(_catalog(str(directory or event_contracts.directory())).get(kind, {})))


def is_verdict(event, directory=None):
    """True for a gate.passed or gate.failed envelope whose version is a locked one."""
    return event.get('type') in TYPES and event.get('version') in accepted_versions(event['type'], directory)


def verdicts(events, directory=None):
    """The accepted gate verdicts of `events`, in their order."""
    return [event for event in events if is_verdict(event, directory)]


def accepted(events, directory=None):
    """`events` without the gate verdicts of a version no contract locks; every other event is kept, in order."""
    return [event for event in events if event.get('type') not in TYPES or is_verdict(event, directory)]
