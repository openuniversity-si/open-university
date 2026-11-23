"""The exception regime (D-260, docs/process/exception-regime.md): one recorded state, one question.

`lifted(lock)` is True when the regime is active and `lock` is not one of the kept locks (money, other people), so a lock
asks it instead of reading a message. `lift(lock, ...)` is the call a lock makes when it would have refused: it prints the
warning naming the lock and the regime's decision and emits the `lock.lifted` event; it returns whether the lock lifted.
Nothing is silent. The state is the registry keys `regime.exception_*`; this module never writes it.
"""
from datetime import timezone

import config

FIELDS = ('active', 'granted_by', 'granted_at', 'reason', 'exit', 'kept')  # regime.exception_<field>, one registry key each
EVENT = 'lock.lifted'
PRODUCER = 'regime'
_JUDGE = []  # the judges' view of `active`, set by pin(): scripts/lib/hermetic/sitecustomize.py pins it for script tests


def pin(active):
    """The judges' view of the regime. `pin(False)` makes a script test judge every lock as its rule is written, whatever the
    live registry holds (D-272); `pin(None)` gives the registry's view back. Only the script tests' hermetic hook pins it."""
    _JUDGE[:] = [] if active is None else [bool(active)]


def state(shared=False):
    """The regime as recorded: {active, granted_by, granted_at, reason, exit, kept}. One registry key per field, because the
    registry keeps objects for translated text. A pinned judge sees `active` as pinned; the other fields are the registry's.
    `shared` reads the registry's shared store whatever the process pins (config.shared), the way gate.bypass is read: the
    gate pins its store to `file`, which does not hold the shared `regime.exception_kept` (I-ddaca17c)."""
    read = config.shared if shared else config.get
    recorded = {field: read(f'regime.exception_{field}') for field in FIELDS}
    if _JUDGE:
        recorded['active'] = _JUDGE[0]
    return recorded


def lifted(lock, recorded=None):
    """True when the regime is active and `lock` is not kept. A kept lock never lifts, whatever else is recorded."""
    recorded = state() if recorded is None else recorded
    return bool(recorded.get('active')) and lock not in recorded.get('kept', [])


def warning(lock, recorded):
    return (f"regime: the lock '{lock}' is lifted by the exception regime granted by {recorded.get('granted_by')} "
            f"at {recorded.get('granted_at')} (exit: {recorded.get('exit')})")


def lift(lock, sha, lane, port, repo, pr=None, out=print, recorded=None):
    """If `lock` lifts: print the warning, emit `lock.lifted` through `port` (a forge_events.ForgeEvents) and return True.
    Otherwise do nothing and return False, so the caller refuses as it always did."""
    recorded = state() if recorded is None else recorded
    if not lifted(lock, recorded):
        return False
    out(warning(lock, recorded))
    moment = port.clock.now()
    if moment.tzinfo is None:
        raise ValueError('the injected clock must return an aware datetime')
    stamped = moment.astimezone(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')
    payload = {'repo': repo, 'pr': pr, 'sha': sha, 'unit': None, 'premises': [],
               'lock': lock, 'lane': lane, 'time': stamped}
    port.emit(EVENT, payload)
    return True
