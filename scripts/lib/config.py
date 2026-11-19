"""Engine configuration registry reader (D-068, P-41). v0 shim; PR C0 extends it.

Each owner declares its parameters in config/registry/<owner>.json, a JSON Schema 2020-12 object that satisfies
contracts/config/registry.v1.json. get(name) returns a parameter's effective value: the registry default, overridden
by the change store (the append-only log of config.changed events on the forge_events port). set_value, unset, revert and history
change and audit it without touching code: every change records who, when and why, and is reversible. check()
validates every registry file: the meta-schema, the owner prefix, the default against the parameter's own schema, the
readers, and the refusal of anything that looks like a secret (only a secret's NAME may appear). Shell and .mjs read a
value with `python3 scripts/lib/config.py get <name>`; the command line is scripts/config, a thin shell over this
library, so an HTTP endpoint can call the same functions.
"""
import contextlib
import copy
from datetime import datetime, timedelta
import hashlib
import json
import math
import os
import pathlib
import re
import subprocess
import sys
import time

import json_schema

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_REGISTRY = _ROOT / "config" / "registry"
_META = pathlib.Path("contracts") / "config" / "registry.v1.json"
_ANNOTATION_KEYS = ("x-literal-names", "x-literal-sites")
_CHANGED = "config.changed"
_SNAPSHOT = "config.snapshot"
_PRODUCER = "config"
_STORE_KEYS = ("config.store_adapter", "config.store_dir", "config.store_cache_ttl_s",
               "config.store_cache_dir", "config.store_snapshot_after_events", "config.store_stale_max_s",
               "config.bootstrap_owners",
               "config.store_quarantine_log", "config.store_window_max")  # the store's own location, cache and reach: registry values only
_replaying = []  # set while the store replays: the port's own settings then read their registry values
_STORE_ENV = "OU_CONFIG_STORE"  # names the store's adapter for a process tree (the gate, an offline run)
REGISTRY_ONLY_ENV = "OU_CONFIG_REGISTRY_ONLY"  # D-335: the checkout the gate judges; its change store is never read
_registry_only_memo = {}  # ($OU_CONFIG_REGISTRY_ONLY, store base) -> whether that base is the judged checkout
_chosen = []  # (adapter, clock) a caller chose in process with use_adapter (a test's fake forge)
_pinned = []  # the store kind this process was pinned to (hermetic.install): wins over $OU_CONFIG_STORE
_shared = []  # set while shared() reads: the registry's own store, whatever the process tree pins
_memo = {}  # cache key -> (expires, events): one read of a remote store, shared by this process's config.get calls
_registry_memo = {}  # registry directory -> (signature, params, racy): one parse per process while no file changes
_checked = {}  # registry directory -> signature, stat once per outermost get/overrides call (_one_check)
_depth = [0]
_replay_memo = {}  # store key -> (source, overrides): one replay per read of the log (remote) or per log file state (file)


class ConfigError(KeyError):
    def __str__(self):
        return self.args[0] if self.args else ''


# The change store (D-068 (3), D-069 items 3 and 4): the config.changed log of the repository channel (pr null) on
# the forge_events port. Nothing is edited in place; a re-emitted change is a no-op (the port deduplicates by
# event_id); a revert is a new change; replay rebuilds every override.


class StoreError(RuntimeError):
    pass


class StoreUnavailable(StoreError):
    """The change store could not be read at all (the forge refused, rate-limited or did not answer); never a data error."""


class PortStore:
    """The config.changed log of one repository, read and written through a ForgeEvents port."""

    def __init__(self, port, repo, root=None):
        self.port, self.repo, self.root = port, repo, root
        self.window_missed = False

    def events(self):
        """The change log as far back as a replay needs: every event of a complete log, else the newest window that
        holds a snapshot, read deeper up to config.store_window_max records (never a truncated read)."""
        port = self.port
        try:
            found, complete = port.read_window(self.repo, None)
        except Exception as error:  # the port's own errors name the adapter and the event
            raise self._unavailable(error) from None
        if port.rejected:
            quarantine(port.rejected, self.root)
        kept = [event for event in found if event.get('type') in (_CHANGED, _SNAPSHOT)]
        tail, deepest = getattr(port.adapter, 'window', None), _entry('config.store_window_max', self.root)['default']
        while not complete and not any(event['type'] == _SNAPSHOT for event in kept) and tail and tail < deepest:
            # The window is the channel's newest records of every kind, so other events (plan notes) push the snapshot
            # out of it (03/11: every commit's regeneration refused). A deeper window, never the whole channel (D-085);
            # snapshot() then appends one so the next default window holds it again.
            tail = min(tail * 4, deepest)
            found, complete = port.read_window(self.repo, None, tail=tail)
            kept = [event for event in found if event.get('type') in (_CHANGED, _SNAPSHOT)]
            self.window_missed = True
        if not complete and not any(event['type'] == _SNAPSHOT for event in kept):
            raise StoreError('config: the newest window of the change store holds no config.snapshot and older '
                             'changes exist within config.store_window_max records; append a snapshot or raise it')
        return kept

    def append(self, kind, payload):
        return self.port.emit(kind, payload)

    def _unavailable(self, error):
        return StoreUnavailable(f'config: the change store cannot be read ({error})')


def quarantine(rejected, root=None):
    """ENV-FIX-PREMISE-BLAST (D-027): the log is append-only, so an envelope the port refuses (one premise.blast with an
    invalid producer reached the repository channel) is skipped, never fatal: one line per event id is appended to
    config.store_quarantine_log, said on stderr the first time this checkout sees it. Returns the ids first seen now."""
    path = _base(root) / _own("config.store_quarantine_log", root)
    try:
        held = {json.loads(line).get("event_id") for line in path.read_text(encoding="utf-8").splitlines() if line.strip()}
    except (OSError, ValueError):
        held = set()
    fresh = []
    for event, reason in rejected:
        ident = event.get("event_id") if isinstance(event, dict) else None
        ident = ident if isinstance(ident, str) else hashlib.sha256(json.dumps(event, sort_keys=True).encode()).hexdigest()
        if ident in held:
            continue
        held.add(ident)
        fresh.append({"event_id": ident, "type": event.get("type") if isinstance(event, dict) else None,
                      "reason": reason})
        print(f"config: quarantined an invalid event of the change store ({reason}); it stays in the append-only log "
              f"and is skipped (config.store_quarantine_log)", file=sys.stderr)
    if fresh:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as log:
                log.writelines(json.dumps(item, sort_keys=True) + "\n" for item in fresh)
        except OSError:
            pass  # a read-only checkout still reads the store; the next writable read records the quarantine
    return [item["event_id"] for item in fresh]


def changes(events):
    return [event for event in events if event.get('type') == _CHANGED]


def replay(events):
    """{name: value} of every parameter whose latest change sets a value; a null `new` returns it to the registry.
    Starts from the newest config.snapshot; the changes after the snapshot's `through` event are applied on top. A
    `through` older than the window read (a healed snapshot whose change other records pushed out, F35) means every
    change the window holds came after it, since `through` is the newest change the snapshot folded."""
    snapshots = [event for event in events if event.get('type') == _SNAPSHOT]
    overrides, rest = {}, events
    if snapshots:
        payload = snapshots[-1]['payload']
        ids = [event.get('event_id') for event in events]
        start = ids.index(payload['through']) + 1 if payload['through'] in ids else 0
        overrides, rest = dict(payload['overrides']), events[start:]
    for event in changes(rest):
        payload = event['payload']
        if payload['new'] is None:
            overrides.pop(payload['name'], None)
        else:
            overrides[payload['name']] = payload['new']
    return overrides


def latest(events, name):
    found = [event for event in changes(events) if event['payload']['name'] == name]
    return found[-1] if found else None


def _registry_dir(root):
    return _REGISTRY if root is None else pathlib.Path(root) / "config" / "registry"


_listing_memo = {}  # registry directory -> (directory stat, sorted .json names): the listing while the directory holds
_RACY_NS = 2_000_000_000  # a directory changed this close to its listing is listed again (coarse file-system clocks)
_now_ns = time.time_ns  # the clock the racy-clean rule compares stamps with; a test pins it (hermetic, D-069 item 5)


def _registry_names(directory, fresh=False):
    """The registry's .json file names, sorted. VAZÃO F1: a directory's mtime moves whenever a file is added, removed
    or renamed in it, so the listing is reused while the directory's stat holds. A file system stamps with a coarse
    clock, so a listing taken within _RACY_NS of the directory's mtime is never reused (git's racy-clean rule): a
    file added in the same tick is still seen."""
    held = None if fresh else _listing_memo.get(directory)
    stat = os.stat(directory)
    state = (stat.st_dev, stat.st_ino, stat.st_mtime_ns, stat.st_ctime_ns)
    if held is not None and held[0] == state:
        return held[1]
    names = tuple(sorted(name for name in os.listdir(directory) if name.endswith(".json")))
    if _now_ns() - stat.st_mtime_ns > _RACY_NS:
        _listing_memo[directory] = (state, names)
    else:
        _listing_memo.pop(directory, None)
    return names


def _registry_signature(directory):
    """The registry's file set with each file's mtime_ns, size and inode: a stat of each file, no read. The file set
    comes from _registry_names; a file it names that is gone is a change, so the directory is listed again."""
    for fresh in (False, True):
        try:
            names = _registry_names(directory, fresh)
        except FileNotFoundError:
            return None
        prefix, stat = f"{directory}{os.sep}", os.stat
        try:
            return tuple((name, found.st_mtime_ns, found.st_size, found.st_ino)
                         for name in names for found in (stat(prefix + name),))
        except FileNotFoundError:
            continue
    return None


def _params(root=None):
    """The registry as parsed, memoized per directory and re-read when a file is added, removed or rewritten. Shared:
    callers never mutate it (entry and _load hand out copies)."""
    directory = _registry_dir(root)
    held = _registry_memo.get(directory)
    if held is not None and _depth[0] and _checked.get(directory) == held[0]:
        return held[1]  # already checked by the call this one runs inside
    signature = _registry_signature(directory)
    if _depth[0]:
        _checked[directory] = signature
    if held is not None and held[0] == signature and not held[2]:
        return held[1]
    params = {}
    for path in sorted(directory.glob("*.json")):
        params.update(json.loads(path.read_text(encoding="utf-8"))["properties"])
    _registry_memo[directory] = (signature, params, _racy_files(signature))
    return params


def _racy_files(signature):
    """A registry file stamped within _RACY_NS of now makes its parse a snapshot for the block it serves, never a
    memo another call trusts (git's racy-clean rule): a same-size rewrite in the same coarse tick keeps the stat
    (the shadow on AWS, 04/11, test_config on the runner's disk). The extra parses are bounded by the window itself."""
    return bool(signature) and _now_ns() - max(found[1] for found in signature) <= _RACY_NS


def reading():
    """A block that reads the registry as it stands when the block starts (GATE-SPEED F3): every get inside stats the
    registry files once, not once per read. For a check that reads thousands of values and writes none (the structure
    check's tree part made 15,000 reads, each one 60 stats); a file changed inside the block is read after it."""
    return _one_check()


@contextlib.contextmanager
def _one_check():
    """Inside one get or overrides call the registry is stat'ed once, however many reads the store's setup makes."""
    _depth[0] += 1
    try:
        yield
    finally:
        _depth[0] -= 1
        if not _depth[0]:
            _checked.clear()


def invalidate():
    """Drop every in-process memo (the registry parse, the replayed overrides, the store read): the next read starts
    from the files and the log. The registry memo also refreshes itself when a registry file changes."""
    _registry_memo.clear()
    _listing_memo.clear()
    _checked.clear()
    _replay_memo.clear()
    _memo.clear()


def _load(root=None):
    return copy.deepcopy(_params(root))


def entry(name, root=None):
    """A parameter's registry entry; a name the registry does not declare is an error, never a fallback."""
    return copy.deepcopy(_entry(name, root))


def _entry(name, root=None):
    """The held entry itself, for this module's own reads that never change it (VAZÃO F1: a deep copy of a whole
    entry for each setting the store's setup reads was a third of a config.get)."""
    params = _params(root)
    if name not in params:
        raise ConfigError(f"config: {name} is not a registered parameter (config/registry/<owner>.json)")
    return params[name]


def get(name, root=None):
    """The effective value: the latest stored change of the parameter, else its registry default. While the store
    itself is being replayed, the settings it needs (the port's, the store's) read their registry values."""
    with _one_check():
        return _get(name, root)


def shared(name, root=None):
    """GATE-ON-PUSH R1: the effective value in the registry's shared store, whatever $OU_CONFIG_STORE or pin_store
    chose. For a switch a hook reads after the gate's verdict (D-069 item 5 pins the verdict's inputs, not its
    effects); an adapter chosen in process (use_adapter) still wins."""
    _shared.append(True)
    try:
        return get(name, root)
    finally:
        _shared.pop()


def _get(name, root):
    params = _params(root)
    if name not in params:
        raise ConfigError(f"config: {name} is not a registered parameter (config/registry/<owner>.json)")
    item = params[name]  # GATE-SPEED F3: read in place; only the value returned is copied, never the whole entry
    if _replaying or _bootstrap(name, root):
        return _copy(item["default"])
    values = _overrides(root, fresh=False)  # GATE-SPEED R3: read in place; only the value returned is copied
    if name not in values:
        return _copy(item["default"])
    errors = json_schema.validate(parameter_schema(item), values[name])
    if errors:
        raise ConfigError(f"config: the stored value of {name} no longer satisfies its schema ({errors[0]}); "
                          f"revert it with scripts/config history {name} and scripts/config revert <change>")
    return _copy(values[name])


_IMMUTABLE = (str, int, float, bool, type(None))


def _copy(value):
    """A value the caller may change: a JSON scalar is immutable and is handed out as is, a list or object is copied."""
    return value if type(value) in _IMMUTABLE else copy.deepcopy(value)


def _base(root):
    return _ROOT if root is None else pathlib.Path(root)


def _own(name, root):
    """The registry value of a config.* setting this module added later than `root`'s registry may be (a base-tip
    gate's tooling reads a head's registry): root's declaration, else this checkout's."""
    return (_params(root).get(name) or _params().get(name))["default"]


def _bootstrap(name, root):
    """NANO-UNBLOCK (D-070): a parameter of a bootstrap owner (config.bootstrap_owners) configures the machine before any
    session state exists, so it is its registry value and never costs a read of the shared store on the forge."""
    return name.split(".", 1)[0] in _own("config.bootstrap_owners", root)


@contextlib.contextmanager
def use_adapter(adapter, clock=None):
    """Route this process's change store through `adapter` (and `clock`) while the block runs: how a hermetic test
    selects its fake forge or local log explicitly, without touching the registry."""
    _chosen.append((adapter, clock))
    _memo.clear()
    _replay_memo.clear()
    try:
        yield adapter
    finally:
        _chosen.pop()
        _memo.clear()
        _replay_memo.clear()


def use_store_of(root):
    """Read another checkout's change store (its file log) in this process while the block runs, this checkout's registry
    still giving every default: how a tool run from a worktree of the base reads the box's own switches (GATE-INFRA 12,
    scripts/deliver --branch)."""
    import forge_events
    return use_adapter(forge_events.FileAdapter(pathlib.Path(root) / _entry("config.store_dir")["default"]))


def pin_store(kind):
    """Pin this process to one of the registry's store adapters, whatever its environment holds later (a hermetic test
    that clears os.environ keeps reading this checkout's local log)."""
    if kind not in _entry("config.store_adapter")["enum"]:
        raise ConfigError(f"config: {kind!r} is not a store adapter")
    _pinned[:] = [kind]
    _memo.clear()
    _replay_memo.clear()


def store_kind(root=None):
    """The adapter that holds the change store: $OU_CONFIG_STORE when a process tree names one of the registry's
    adapters (the gate reads `file`: its verdict depends on the head alone, D-069 item 5), else the registry's."""
    item = _entry("config.store_adapter", root)
    if _shared:
        return item["default"]
    if _pinned:
        return _pinned[0]
    chosen = os.environ.get(_STORE_ENV, "")
    if not chosen:
        return item["default"]
    if chosen not in item["enum"]:
        raise ConfigError(f"config: {_STORE_ENV}={chosen!r} is not a store adapter ({', '.join(item['enum'])})")
    return chosen


def store(root=None, clock=None, correlation_id=None):
    """The change store: the config.changed log on the forge_events port, with the adapter chosen in process
    (use_adapter), else the one store_kind names."""
    import forge_events  # the port imports this module; load it when the store is used
    if _chosen:
        adapter, chosen_clock = _chosen[-1]
        clock = clock or chosen_clock
    else:  # D-300: the file store is the only one; store_kind still refuses a name outside the registry's enum
        store_kind(root)
        adapter = forge_events.FileAdapter(_base(root) / _entry("config.store_dir", root)["default"])
    forge_events.checked_adapter(adapter, {'append', 'read'}, 'config store')
    port = forge_events.ForgeEvents(adapter, clock or forge_events.clock_from_config(), _PRODUCER,
                                    correlation_id or _PRODUCER)
    return PortStore(port, _entry("forge-events.repo")["default"], root)


def _events(root=None):
    _replaying.append(True)
    try:
        target = store(root)
        return _cached(target, root) if target.port.adapter.remote else target.events()
    finally:
        _replaying.pop()


# The read cache of a remote store (TR1, D-069 item 3): config.get on a flag must not cost a REST call per read. One
# read of the log serves every process of the checkout for config.store_cache_ttl_s (an in-process memo plus a
# snapshot file under config.store_cache_dir); a change through this checkout's store drops it first. Measured with
# the store's injected clock. The key holds the adapter, the repository and every forge-events registry value, so a
# moved channel is never served from an old read; an adapter chosen in process also keys on its identity. While the store
# cannot be read, the last read serves for config.store_stale_max_s past its expiry (_stale, NANO-UNBLOCK).


_key_memo = {}  # json of the key material -> its sha256: every get of a file store names the same key


def _cache_key(adapter, repo):
    material = json.dumps([type(adapter).__name__, repo, getattr(adapter, "cache_identity", None),
                           _forge_fingerprint()], sort_keys=True)
    key = _key_memo.get(material)
    if key is None:
        key = _key_memo[material] = hashlib.sha256(material.encode()).hexdigest()
    return key


_forge_memo = []  # (params, forge-events fingerprint) of the registry parse it was taken from


def _forge_fingerprint():
    params = _params()
    if not _forge_memo or _forge_memo[0] is not params:
        values = {name: item["default"] for name, item in sorted(params.items()) if name.startswith("forge-events.")}
        _forge_memo[:] = [params, hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()]
    return _forge_memo[1]


def _cache_file(root, key):
    return _base(root) / _entry("config.store_cache_dir", root)["default"] / f"{key}.json"


def _healed(target, root):
    """The log as a replay needs it (target.events()); a read that had to go past the default window heals it."""
    events = target.events()
    if target.window_missed and getattr(target.port.adapter, 'remote', False):
        # F26: the reader heals the window it had to read past, so the next readers find the snapshot in the default
        # window before it ages past config.store_window_max records; best effort (a reader without the events token
        # cannot append, and the read is already correct)
        try:
            _append_snapshot(target, events, root)
        except Exception as error:  # noqa: BLE001 - the read stands; the next reader with the token heals it
            print(f"config: the window held no snapshot and none could be appended ({error})", file=sys.stderr)
    return events


def _state(target, root):
    """{version, overrides, through}: the fold of the store's log (version None). The control plane's versioned key
    (VAZÃO F35) left with the control store adapter (D-300, SEMENTE §6: no double path)."""
    events = _healed(target, root)
    done = changes(events)
    return {"version": None, "overrides": replay(events), "through": done[-1]["event_id"] if done else None}


_READS = {"events": _healed, "state": _state}  # what a cached read of a remote store holds: the log, or the overrides


def _cached(target, root, what="events"):
    import forge_events
    key, now = f"{_cache_key(target.port.adapter, target.repo)}-{what}", target.port.clock.now()
    shareable = not _chosen or hasattr(target.port.adapter, "cache_identity")  # an in-process adapter names itself to share a file
    held = _memo.get(key) or (_read_cache(root, key) if shareable else None)
    if held and now < held[0]:
        return held[1]
    try:
        found = _READS[what](target, root)
    except StoreUnavailable as error:
        return _stale(held, now, error, root)
    expires = now + timedelta(seconds=_entry("config.store_cache_ttl_s", root)["default"])
    _memo[key] = (expires, found)
    if not shareable:
        return found
    path = _cache_file(root, key)
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(f".{os.getpid()}.tmp")
    partial.write_text(json.dumps({"key": key, "expires": forge_events.rfc3339(expires), "held": found}),
                       encoding="utf-8")
    partial.replace(path)
    return found


_stale_said = []  # set once this process has said on stderr that it serves an expired read


def _stale(held, now, error, root):
    """NANO-UNBLOCK (D-070): while the store cannot be read (a GitHub limit window, an outage), the last good read of this
    checkout serves for config.store_stale_max_s after it expired, said once per process on stderr; with no read held,
    or past that bound, the error stands. A data error of the log (StoreError) never reaches here."""
    late = (now - held[0]).total_seconds() if held else None
    if late is None or late > _own("config.store_stale_max_s", root):
        raise error
    if not _stale_said:
        _stale_said.append(True)
        print(f"{error}; config.get serves this checkout's last read of the store, expired {int(late)} s ago "
              f"(config.store_stale_max_s)", file=sys.stderr)
    return held[1]


def _read_cache(root, key):
    try:
        held = json.loads(_cache_file(root, key).read_text(encoding="utf-8"))
        if held["key"] == key:
            return datetime.fromisoformat(held["expires"].replace("Z", "+00:00")), held["held"]
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        pass  # a missing or unreadable snapshot is a cache miss: the log is read again
    return None


def _invalidate(root=None):
    """Drop this checkout's read of the store, so the next read (and a change's `old`) comes from the log."""
    _memo.clear()
    _replay_memo.clear()
    directory = _base(root) / _entry("config.store_cache_dir", root)["default"]
    for path in directory.glob("*.json") if directory.is_dir() else ():
        path.unlink(missing_ok=True)


def _log_state(adapter, repo):
    """What identifies the log a replay folded: the read itself for a remote store (held for config.store_cache_ttl_s
    by _cached), the log file's stat for the file adapter, else None (read and replayed every time)."""
    import forge_events
    if type(adapter) is not forge_events.FileAdapter:
        return None
    try:
        stat = adapter.path(forge_events.Channel(repo, None)).stat()
        return (stat.st_dev, stat.st_ino, stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size)
    except FileNotFoundError:
        return "absent"


def overrides(root=None):
    """{name: value} the change store sets. One replay serves every call while the log read is the same: a remote
    store's read within config.store_cache_ttl_s, or an unchanged file log; a change through this checkout drops it."""
    with _one_check():
        return _overrides(root)


def registry_only(root=None):
    """D-335: whether the change store of `root`'s checkout is ignored, every key then reading its registry default. The
    gate names the checkout it judges in $OU_CONFIG_REGISTRY_ONLY (scripts/verify-commit, and every process it spawns):
    a head's own .tower/config (a forced add, or a file a stage wrote) must not override a gate, budget or regime key.
    Another checkout (a test's temp root) keeps its own store, and an adapter chosen in process (use_adapter) still wins."""
    judged = os.environ.get(REGISTRY_ONLY_ENV, "")
    if not judged or _chosen:
        return False
    key = (judged, str(_base(root)))
    if key not in _registry_only_memo:
        _registry_only_memo[key] = pathlib.Path(judged).resolve() == _base(root).resolve()
    return _registry_only_memo[key]


def _overrides(root, fresh=True):
    """The folded overrides. fresh: a deep copy the caller may change (overrides()); else the held fold itself, which
    the caller only reads (_get copies the one value it returns): a deep copy of every override per registry read was
    a third of the structure check's time (GATE-SPEED audit R3). None while the gate judges this checkout (registry_only)."""
    if registry_only(root):
        return {}
    _replaying.append(True)
    try:
        # An unchanged local fold is pure data: constructing another journal port cannot refresh it. Observe its
        # file identity before consulting the existing replay memo; an actual read still uses the checked port.
        import forge_events
        adapter = _chosen[-1][0] if _chosen else (
            forge_events.FileAdapter(_base(root) / _entry("config.store_dir", root)["default"])
            if store_kind(root) == "file" else None)
        repo = _entry("forge-events.repo")["default"]
        if type(adapter) is forge_events.FileAdapter:
            source = _log_state(adapter, repo)
            key = (_cache_key(adapter, repo), str(_base(root)), str(adapter.directory))
            held = _replay_memo.get(key)
            if held is not None and held[0] == source:
                return copy.deepcopy(held[1]) if fresh else held[1]
        target = store(root)
        adapter = target.port.adapter
        state = None
        if adapter.remote:
            state = _cached(target, root, "state")  # the key's one row (F35), else the fold of the log
            source = state  # the same object while _cached serves one read of the store
        else:
            source = _log_state(adapter, target.repo)
        key = (_cache_key(adapter, target.repo), str(_base(root)), str(getattr(adapter, "directory", ""))) if source is not None else None
        held = _replay_memo.get(key) if key else None
        if held is not None and (held[0] is source if adapter.remote else held[0] == source):
            return copy.deepcopy(held[1]) if fresh else held[1]
        folded = state["overrides"] if state is not None else replay(target.events())
    finally:
        _replaying.pop()
    if key and not _racy(source):
        _replay_memo[key] = (source, folded)
    elif key:
        _replay_memo.pop(key, None)
    return copy.deepcopy(folded) if fresh else folded


def _racy(source):
    """A file log stamped within _RACY_NS of now is folded again on the next read (git's racy-clean rule, as for a
    directory's listing): a file system stamps with a coarse clock, so a rewrite of the same size in the same tick, its
    mtime put back, keeps the stat the fold was held by (the shadow on AWS, 04/11, test_config on the runner's disk)."""
    if not isinstance(source, tuple) or len(source) < 4:
        return False
    return _now_ns() - max(source[2], source[3]) <= _RACY_NS


def files(root=None):
    """{owner: (path, document)} for every registry file."""
    found = {}
    for path in sorted(_registry_dir(root).glob("*.json")):
        found[path.stem] = (path, json.loads(path.read_text(encoding="utf-8")))
    return found


def _entropy(text):
    counts = {char: text.count(char) for char in set(text)}
    return -sum(count / len(text) * math.log2(count / len(text)) for count in counts.values())


def secret_guard(root=None):
    """The settings secret_findings judges by, read once: check() judges every parameter with one read of them
    (GATE-SPEED F3; they were seven reads for each of 800 parameters)."""
    return {name: get(f"config.{name}", root) for name in (
        "guard_key_words", "guard_name_suffixes", "guard_name_pattern", "guard_value_patterns",
        "guard_entropy_min_length", "guard_entropy_min_bits", "guard_entropy_alphabet")}


def secret_findings(name, value, root=None, guard=None):
    """Why a parameter looks like a secret: its key names one, or its value has a secret's shape.
    A key may name a secret only when it holds the secret's NAME (an environment variable name). `guard` is
    secret_guard(root), read once by a caller that judges many parameters."""
    findings = []
    guard = guard or secret_guard(root)
    words = guard["guard_key_words"]
    holders = guard["guard_name_suffixes"]
    key = name.split(".", 1)[-1]
    if _names_secret(key, words):
        if not any(key.endswith(suffix) for suffix in holders):
            findings.append(f"{name}: the key names a secret; only a secret's name may be registered "
                            f"(a key ending in {' or '.join(holders)})")
        elif not (isinstance(value, str) and re.fullmatch(guard["guard_name_pattern"], value)):
            findings.append(f"{name}: a secret-name key holds {value!r}, not an environment variable name")
    patterns = [re.compile(pattern) for pattern in guard["guard_value_patterns"]]
    shortest = guard["guard_entropy_min_length"]
    bits = guard["guard_entropy_min_bits"]
    alphabet = re.compile(guard["guard_entropy_alphabet"])
    for text in _strings(value):
        if any(pattern.search(text) for pattern in patterns):
            findings.append(f"{name}: a value has the shape of a secret")
        elif len(text) >= shortest and alphabet.fullmatch(text) and _entropy(text) >= bits:
            findings.append(f"{name}: a value looks like a random secret ({len(text)} characters)")
    return findings


def _names_secret(key, words):
    """True when the key's snake_case segments contain a secret word's segments in order (max_tokens is not token)."""
    segments = key.split("_")
    for word in words:
        parts = word.split("_")
        if any(segments[index:index + len(parts)] == parts for index in range(len(segments))):
            return True
    return False


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)


def parameter_schema(item):
    """The JSON Schema a parameter's values satisfy: its entry without the registry annotations."""
    return {key: value for key, value in item.items() if key not in _ANNOTATION_KEYS}


def value_errors(name, value, root=None):
    """Why a value is not acceptable for a parameter: its schema, or a secret's shape."""
    item = entry(name, root)
    errors = [f"{name}: {error.removeprefix('$: ')}" for error in json_schema.validate(parameter_schema(item), value)]
    return errors + secret_findings(name, value, root)


def check(root=None):
    """Every error of the registry files: shape, owner, defaults, readers, secrets and duplicate names."""
    base = _ROOT if root is None else pathlib.Path(root)
    meta_path = base / _META
    if not meta_path.is_file():
        meta_path = _ROOT / _META
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    errors, seen = [], {}
    for owner, (path, document) in files(root).items():
        where = path.relative_to(base).as_posix()
        errors += [f"{where}: {error}" for error in json_schema.validate(meta, document)]
        if document.get("$id") != where:
            errors.append(f"{where}: $id is {document.get('$id')!r}, not its path")
        if document.get("x-owner") != owner:
            errors.append(f"{where}: x-owner is {document.get('x-owner')!r}, not the file name {owner!r}")
        for name, item in (document.get("properties") or {}).items():
            if not name.startswith(owner + "."):
                errors.append(f"{where}: {name} does not start with its owner {owner}.")
            if name in seen:
                errors.append(f"{where}: {name} is also declared in {seen[name]}")
            seen[name] = where
            if not isinstance(item, dict):
                continue
            errors += [f"{where}: {name} {error}" for error in json_schema.check_schema(parameter_schema(item))]
            if "default" in item:
                errors += [f"{where}: {name} default {error.removeprefix('$: ')}"
                           for error in json_schema.validate(parameter_schema(item), item["default"])]
            for reader in item.get("x-readers") or []:
                target = base / reader
                if not target.is_file():
                    errors.append(f"{where}: {name} names a reader that does not exist: {reader}")
    guard = secret_guard(root)
    for name in seen:
        try:
            errors += [f"{seen[name]}: {finding}"
                       for finding in secret_findings(name, _params(root)[name].get("default"), root, guard)]
        except ConfigError as error:
            errors.append(str(error))
            break
    return errors


class _At:
    """The injected clock frozen at one moment, so the envelope's occurred_at and the payload's `at` agree."""

    def __init__(self, moment):
        if moment.tzinfo is None:
            raise ConfigError("config: the clock must give an aware time")
        self.moment = moment

    def now(self):
        return self.moment


def _record(name, old, new, actor, reason, now, root, correlation_id=None, reverts=None):
    import forge_events
    clock = _At(now)
    payload = {**forge_events.subject(_entry("forge-events.repo")["default"], None, None),
               "name": name, "old": old, "new": new, "actor": actor, "reason": reason,
               "at": forge_events.rfc3339(clock.now())}
    if reverts:
        payload["reverts"] = reverts
    target = store(root, clock, correlation_id or f"{_PRODUCER}:{name}")
    _replaying.append(True)
    try:
        written = target.append(_CHANGED, payload)
    except Exception as error:  # a contract error of the port: the payload does not fit config.changed v1
        raise ConfigError(f"config: {error}") from None
    finally:
        _replaying.pop()
        _invalidate(root)
    try:
        snapshot(root, clock, correlation_id or f"{_PRODUCER}:{name}")
    except Exception as error:  # the change is recorded; a snapshot is derived and the next change tries again
        print(f"config: the change is recorded but no snapshot was appended ({error})", file=sys.stderr)
    return written


def snapshot(root=None, clock=None, correlation_id=None):
    """Append a config.snapshot of the store as it reads now, when its adapter is remote and more than
    config.store_snapshot_after_events changes follow the newest snapshot. Returns the envelope, else None."""
    target = store(root, clock, correlation_id or _PRODUCER)
    if not target.port.adapter.remote:
        return None
    return _append_snapshot(target, target.events(), root)


def _append_snapshot(target, found, root):
    """Append a config.snapshot of `found` (the events `target` just read) when enough changes follow the newest
    snapshot, or when the read had to go deeper than the default window for it (target.window_missed)."""
    folded = replay(found)
    snapshots = [event for event in found if event["type"] == _SNAPSHOT]
    through = snapshots[-1]["payload"]["through"] if snapshots else None
    ids = [event["event_id"] for event in found]
    pending = changes(found[ids.index(through) + 1:] if through else found)
    missed = target.window_missed  # the newest window held no snapshot: append one, even with nothing pending
    if not changes(found) or (len(pending) < _entry("config.store_snapshot_after_events", root)["default"] and not missed):
        return None
    import forge_events
    last = changes(found)[-1]
    count = (snapshots[-1]["payload"]["count"] if snapshots else 0) + len(pending)
    payload = {**forge_events.subject(_entry("forge-events.repo")["default"], None, None),
               "overrides": folded, "through": last["event_id"], "count": count,
               "at": forge_events.rfc3339(target.port.clock.now())}
    _replaying.append(True)
    try:
        return target.append(_SNAPSHOT, payload)
    finally:
        _replaying.pop()
        _invalidate(root)


def _changeable(name, root):
    item = entry(name, root)
    if name in _STORE_KEYS or name.startswith("forge-events."):
        raise ConfigError(f"config: {name} locates the change store itself; change it in its registry file")
    if _bootstrap(name, root):
        raise ConfigError(f"config: {name} configures the machine bootstrap (config.bootstrap_owners), which never reads "
                          f"the store; change it in its registry file")
    return item


def set_value(name, value, *, actor, reason, now, root=None, correlation_id=None):
    """Override a parameter without touching code. The value must satisfy the parameter's schema and not look like a
    secret; `now` is the injected clock's time; the event goes through the forge_events port."""
    _changeable(name, root)
    _invalidate(root)
    errors = value_errors(name, value, root)
    if errors:
        raise ConfigError("config: " + "; ".join(errors))
    if json_schema.canonical(value) == json_schema.canonical(get(name, root)):
        raise ConfigError(f"config: {name} is already {json_schema.canonical(value)}")
    return _record(name, overrides(root).get(name), value, actor, reason, now, root, correlation_id)


def unset(name, *, actor, reason, now, root=None, correlation_id=None):
    """Return a parameter to its registry default (a change whose `new` is null)."""
    _changeable(name, root)
    _invalidate(root)
    current = overrides(root)
    if name not in current:
        raise ConfigError(f"config: {name} has no stored value; it already reads its registry default")
    return _record(name, current[name], None, actor, reason, now, root, correlation_id)


def find_change(change, root=None):
    found = [event for event in changes(_events(root)) if event["event_id"].startswith(change)]
    if not change or len(found) != 1:
        raise ConfigError(f"config: {change!r} names {len(found)} changes; give a longer prefix of the change id")
    return found[0]


def revert(change, *, actor, reason, now, root=None, correlation_id=None):
    """Undo one change with a new change. Refused when a later change of the same parameter would be overwritten."""
    _invalidate(root)
    target = find_change(change, root)
    name = target["payload"]["name"]
    current = overrides(root).get(name)
    if json_schema.canonical(current) != json_schema.canonical(target["payload"]["new"]):
        last = latest(_events(root), name)
        raise ConfigError(f"config: {name} changed after {change} (latest {last['event_id'][:12]}); revert that first")
    restored = target["payload"]["old"]
    if restored is not None:
        errors = value_errors(name, restored, root)
        if errors:
            raise ConfigError("config: the earlier value no longer fits: " + "; ".join(errors))
    return _record(name, current, restored, actor, reason, now, root, correlation_id, target["event_id"])


def history(name=None, root=None):
    events = changes(_events(root))
    return [event for event in events if name is None or event["payload"]["name"] == name]


def describe(name, root=None):
    item = entry(name, root)
    owner = name.split(".", 1)[0]
    changes = history(name, root)
    return {"name": name, "owner": owner, "file": f"config/registry/{owner}.json", "value": get(name, root),
            "overridden": name in overrides(root), "changes": len(changes),
            "last_change": changes[-1]["event_id"] if changes else None, **item}


def listing(owner=None, root=None):
    current = overrides(root)
    return [{"name": name, "value": get(name, root), "default": item["default"], "unit": item["x-unit"],
             "overridden": name in current}
            for name, item in sorted(_load(root).items()) if owner is None or name.split(".", 1)[0] == owner]


def diff(root=None):
    """The parameters whose effective value differs from the registry, with the change that set each."""
    events = _events(root)
    out = []
    for name, value in sorted(replay(events).items()):
        default = _entry(name, root)["default"] if name in _params(root) else None
        last = latest(events, name)
        out.append({"name": name, "default": default, "value": value, "change": last["event_id"],
                    "actor": last["payload"]["actor"], "reason": last["payload"]["reason"],
                    "at": last["payload"]["at"], "registered": name in _params(root)})
    return out


def _registry_at(ref, root):
    """The registry's parameters as `ref` holds them: one git ls-tree and one git cat-file --batch for every aggregate
    (VAZÃO F1: a git show per file was 64 processes per call), in file-name order as before."""
    base = _base(root)
    listed = subprocess.run(["git", "-C", str(base), "ls-tree", "-z", f"{ref}:config/registry"],
                            capture_output=True, text=True)
    if listed.returncode != 0:
        return {}
    blobs = []
    for line in listed.stdout.split("\0"):
        head, _, file_name = line.partition("\t")
        if not file_name.endswith(".json"):
            continue  # D-095: config/registry/<owner>/ holds a split owner's sources; its aggregate is the .json beside it
        _mode, kind, oid = head.split()
        if kind != "blob":
            raise subprocess.CalledProcessError(128, ["git", "show", f"{ref}:config/registry/{file_name}"],
                                                stderr=f"config/registry/{file_name} is a {kind}, not a file")
        blobs.append((file_name, oid))
    params = {}
    if not blobs:
        return params
    shown = subprocess.run(["git", "-C", str(base), "cat-file", "--batch"], capture_output=True, check=True,
                           input="".join(f"{oid}\n" for _, oid in blobs).encode())
    out, at = shown.stdout, 0
    for file_name, oid in blobs:
        end = out.index(b"\n", at)
        header = out[at:end].split()
        if len(header) != 3 or header[1] != b"blob":
            raise subprocess.CalledProcessError(128, ["git", "cat-file", "--batch"],
                                                stderr=f"config/registry/{file_name}: {out[at:end].decode()}")
        size = int(header[2])
        params.update(json.loads(out[end + 1:end + 1 + size].decode("utf-8"))["properties"])
        at = end + 2 + size  # the blob, then the newline cat-file writes after it
    return params


def diff_ref(ref, root=None):
    """Registry defaults added, removed or changed since a git ref (a reviewed change of the files themselves)."""
    before, after = _registry_at(ref, root), _params(root)  # read only: the held parse, never a copy of it
    out = []
    for name in sorted(set(before) | set(after)):
        old, new = before.get(name, {}).get("default"), after.get(name, {}).get("default")
        if name not in before:
            out.append({"name": name, "kind": "added", "old": None, "new": new})
        elif name not in after:
            out.append({"name": name, "kind": "removed", "old": old, "new": None})
        elif json_schema.canonical(old) != json_schema.canonical(new):
            out.append({"name": name, "kind": "changed", "old": old, "new": new})
    return out


def main(argv):
    if len(argv) >= 2 and argv[0] == "get":
        # One name prints its value; several print {name: value}, so an .mjs reader pays one process for its settings.
        # A refusal is one line on stderr (a shell caller folds it into its own classified line), never a traceback.
        try:
            values = {name: get(name) for name in argv[1:]}
            print(json.dumps(values[argv[1]] if len(values) == 1 else values))
        except (ConfigError, StoreError) as error:
            sys.exit(" ".join(str(error).split()))
    else:
        sys.exit("usage: config.py get <name> [<name>...]")


if __name__ == "__main__":
    main(sys.argv[1:])
