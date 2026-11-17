"""The forge event port (D-065, plan v3 M2): every tool emits and reads delivery events here, never a forge API.

Callers build payloads (plain dicts that follow contracts/events/<type>.v<N>.json) and call ForgeEvents.emit;
consumers call ForgeEvents.read and replay. The port owns the envelope, the deterministic event id, validation on
emit and on read, deduplication and ordering. An adapter only stores and returns envelopes on a channel.

Journal interface (separate from the required forge operations below):
  remote                      True when the log lives off this machine (a read costs a round trip; readers may cache).
  append(channel, envelopes)  append the envelopes, in order, to the channel's log; never rewrite or delete.
  read(channel)               every envelope stored on the channel, in append order (unvalidated dicts).
  recent(channel)             optional: (envelopes, complete) for the newest window of the log; complete is True when
                              the window starts at the first envelope. A reader of a long log (the config store)
                              uses it with a snapshot event, never a truncated read.
  change(repo, number)        {'head': sha, 'base': sha, 'body': text} of a change (PR) for the subject.
Forge surface: operation_relations declares 21 _operation dispatches plus the adjacent
change pass-through (22 total). operation_demands declares consumer requirements and
per-adapter behavioral tests; the boundary refuses an unproven demand before effects
(D-285, C3). Method presence alone is not compatibility.
A channel is (repo, pr): one log per change, plus the repository log (pr None) for integration, train and
release events. Statuses, comments or refs are the adapter's choice; payloads never name them.

CLI (for shell and .mjs producers):
  forge_events.py emit <type> --payload JSON --producer NAME --correlation-id ID
  forge_events.py read [--pr N]     forge_events.py replay [--pr N]
"""
import argparse
from collections import namedtuple
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import fcntl
import importlib
import json
from pathlib import Path
import re
import sys

import branch_age
import config
import event_contracts
import operation_demands
import forge_requirements

ROOT = Path(__file__).resolve().parents[2]
Channel = namedtuple('Channel', 'repo pr')
PREMISES_LINE = re.compile(r'^Premises:[ \t]*(.*?)[ \t]*$', re.M)
PREMISE_ID = re.compile(r'\bP-\d{2,}\b')


class ForgeEventsError(RuntimeError):
    pass


class ForgeCompatibilityError(ForgeEventsError):
    """Required compatibility is invalid; consumers must not treat it as optional IO."""


def checked_adapter(adapter, operations, context):
    try:
        return forge_requirements.require_surface(adapter, operations, context)
    except operation_demands.CompatibilityError as error:
        raise ForgeCompatibilityError(str(error)) from None


def construct_adapter(name, operations, context):
    return checked_adapter(ADAPTERS[name](), operations, context)


class SystemClock:
    """UTC wall clock; the only place the port reads time. Tests inject their own object with now()."""

    def now(self):
        return datetime.now(timezone.utc)


CLOCKS = {'system-utc': SystemClock}


def clock_from_config():
    return CLOCKS[config.get('forge-events.clock')]()


def rfc3339(moment):
    if moment.tzinfo is None:
        raise ForgeEventsError('the injected clock must return an aware datetime')
    return moment.astimezone(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')


def premises_from_body(body):
    """The P-ids of the body's `Premises:` line (STRUCTURE.md B5, plan v3 §8.3)."""
    match = PREMISES_LINE.search(body or '')
    return list(dict.fromkeys(PREMISE_ID.findall(match.group(1)))) if match else []


def subject(repo, pr, sha, premises=(), unit=None):
    """The fields every payload carries (D-065): unit is null until U0 creates unit manifests."""
    return {'repo': repo, 'pr': pr, 'sha': sha, 'unit': unit, 'premises': list(premises)}


def unit_of(ownership, commit, files):
    """REC-1: the lower-case id of the one unit manifest at `commit` whose paths cover `files`, else None (no unit, or
    several: a change spanning units is not attributed here). `ownership` is a train_ownership.UnitOwnership, so the
    manifests and globs are its own; this module imports neither. Its units() names shared paths too: naming is not
    the refusal, which never asks about them (SHARED-NEEDS-NO-OWNER)."""
    touched = {unit.lower() for unit in ownership.units(commit, files)}
    return touched.pop() if len(touched) == 1 else None


class MemoryAdapter:
    """In-process log for tests and for a consumer replaying a log it already holds."""

    remote = False

    def __init__(self, changes=None):
        self.logs = {}
        self.changes = dict(changes or {})
        self.appends = 0
        self.statuses = []  # GX-17: every set_status call, in order (the fake of the status operation)

    def append(self, channel, envelopes):
        self.appends += 1
        self.logs.setdefault(tuple(channel), []).extend(json.loads(json.dumps(e)) for e in envelopes)

    def read(self, channel):
        return [json.loads(json.dumps(e)) for e in self.logs.get(tuple(channel), [])]

    def set_status(self, repo, sha, context, state, description, url=None):
        self.statuses.append({'repo': repo, 'sha': sha, 'context': context, 'state': state,
                              'description': description, 'url': url})

    def change(self, repo, number):
        if (repo, number) not in self.changes:
            raise ForgeEventsError(f'unknown change {repo}#{number}')
        return dict(self.changes[(repo, number)])


class FileAdapter:
    """Append-only JSON Lines per channel under a local directory (offline runs, local mirror). Locked appends."""

    remote = False

    def __init__(self, directory=None):
        self.directory = Path(directory or ROOT / config.get('forge-events.local_log_dir'))

    def path(self, channel):
        owner = channel.repo.replace('/', '__')
        return self.directory / owner / ('repository.jsonl' if channel.pr is None else f'pr-{channel.pr}.jsonl')

    def append(self, channel, envelopes):
        path = self.path(channel)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('a', encoding='utf-8') as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            for envelope in envelopes:
                handle.write(json.dumps(envelope, sort_keys=True, separators=(',', ':')) + '\n')

    def read(self, channel):
        path = self.path(channel)
        if not path.is_file():
            return []
        events = []
        for line in path.read_text(encoding='utf-8').splitlines():
            try:
                events.append(json.loads(line))
            except ValueError:
                events.append({'unreadable': line[:80]})
        return events

    def change(self, repo, number):
        raise ForgeEventsError('the file adapter holds no change metadata; pass premises to subject()')


HELD = None  # TRAIL-AFTER-LANDING: while a list, the trails an adapter writes aside are kept in it


def kept_aside(write):
    """Whether write (an adapter's trail, written aside) is kept for when the hold ends; False when nothing is held."""
    if HELD is None:
        return False
    HELD.append(write)
    return True


@contextmanager
def trails_held():
    """TRAIL-AFTER-LANDING: the trails an adapter writes aside in the block are written when it ends. tower/gate's
    success trail on Origin is a push to the journal's ref of the repository the landing merges into: written beside
    the landing (STATUS-TRAIL-ASIDE), the forge's merge took 7.06 and 7.15 s (#630, #631), against 1.4 to 5.0 s in the
    78 landings before it."""
    global HELD
    outer, HELD = HELD, []
    try:
        yield
    finally:
        held, HELD = HELD, outer
        for write in held:
            write()


# Verified by unit_map as selection relations, separate from static requires (D-283).
DYNAMIC_IMPORTS = ('_git_ref', '_origin', '_origin_readiness')


def _git_ref():
    # EVENTS-REF (E1, D-273): the git-ref log; a vendor module loads only when the registry selects it, by name
    return importlib.import_module('forge_git_ref').GitRefAdapter()


def _origin():
    # D-283: the Origin adapter, loaded by name like the others. The port does not know the vendor.
    return importlib.import_module('forge_origin').adapter_from_config()


# D-293: one forge, Origin; the GitHub adapter left the port (revises D-283). A future forge is a new adapter here.
ADAPTERS = {'file': FileAdapter, 'git-ref': _git_ref, 'origin': _origin}  # D-300: control left the event log


def _origin_readiness():
    # ORIGIN-FINISH R3: the forge module that answers its own credential_gaps, loaded by name like its adapter
    return importlib.import_module('forge_origin')


READINESS = {'origin': _origin_readiness}


def forge_gaps(cached_probe):
    """What the forge forge-events.adapter selects still needs on this machine, as preflight lines: its credential,
    its client and its reach (names, never values). A forge without a readiness module (file) needs nothing. Never a
    fallback to another forge."""
    loader = READINESS.get(config.get('forge-events.adapter'))
    return list(loader().credential_gaps(cached_probe)) if loader else []


class BoardAdapter:
    """BOARD (CANALE2): the log of the board kinds is `log` (the git-ref log), and every append of them refreshes the
    board's sections that hold those kinds (forge_board.Board, one comment per section, edited in place). A board write that
    fails never fails the append: the record is already on the log, and the next append refreshes the section."""

    def __init__(self, log, board, sections, render):
        self.log, self.board, self.sections, self.render = log, board, dict(sections), render
        self.remote = log.remote
        self.failures = []

    def append(self, channel, envelopes):
        envelopes = list(envelopes)
        self.log.append(channel, envelopes)
        if channel.pr is not None:
            return  # the board shows the repository's state; a PR's events stay on the log
        kinds = {envelope['type'] for envelope in envelopes}
        touched = {key: section for key, section in self.sections.items() if kinds & set(section)}
        if not touched:
            return
        events = self.log.recent(channel)[0] if getattr(self.log, 'recent', None) else self.log.read(channel)
        try:
            self.board.refresh(self.render(touched, events))
        except RuntimeError as error:
            self.failures.append(str(error))

    def read(self, channel):
        return self.log.read(channel)

    @property
    def recent(self):
        return getattr(self.log, 'recent', None)


class RoutingAdapter:
    """GX-FIX-forge-rate (D-070): the configured adapter, except the kinds forge-events.file_kinds stores elsewhere
    (measurement events in the local file log, off issue comments). A read returns the main log, then the routed logs
    of the same channel; every other operation is the main adapter's."""

    def __init__(self, main, routes, default=None):
        """CANALE7: with `default` (forge-events.log_adapter), every kind not routed goes to it instead of the main
        adapter, which keeps the forge's other operations (change, merge, status)."""
        self.main, self.routes, self.default = main, dict(routes), default
        for log in self._logs():
            checked_adapter(log, forge_requirements.JOURNAL, 'routing journal')
        if default is None:
            checked_adapter(main, forge_requirements.JOURNAL, 'routing main journal')
        self.remote = main.remote

    def _logs(self):
        logs = list(self.routes.values()) + ([self.default] if self.default is not None else [])
        return list({id(adapter): adapter for adapter in logs}.values())

    def route(self, kind):
        """GX-FIX-forge-rate-2 (D-070): the adapter that stores `kind`; its own log is the dedupe window and the read
        of that kind, so a file-routed kind never costs a forge read either."""
        return self.routes.get(kind, self.default if self.default is not None else self.main)

    def append(self, channel, envelopes):
        groups = {}
        for envelope in envelopes:
            target = self.route(envelope['type'])
            groups.setdefault(id(target), (target, []))[1].append(envelope)
        for target, items in groups.values():
            target.append(channel, items)

    def read(self, channel):
        if self.default is not None:  # the log left the main adapter: its history is not read from the forge again
            return [event for log in self._logs() for event in log.read(channel)]
        return self.main.read(channel) + [event for log in self._logs() for event in log.read(channel)]

    @property
    def recent(self):
        main = getattr(self.default if self.default is not None else self.main, 'recent', None)
        if main is None:
            return None
        others = [log for log in self._logs() if log is not self.default]

        def window(channel):
            events, complete = main(channel)
            return events + [event for log in others for event in log.read(channel)], complete
        return window

    def __getattr__(self, name):
        return getattr(self.main, name)


def adapter_of_observation(observation):
    """PR-OBSERVATION: the forge's adapter over what the live service read of one PR (GET /v1/pr-observation/<id>):
    the Origin adapter's own mapping of those answers, loaded by name like the others."""
    return _origin_readiness().ObservedAdapter(observation, config.get('forge-events.repo'))  # the vendor's module, by name


def adapter_from_config():
    """The port's adapter: forge-events.adapter, with file_kinds in the local file log (D-070) and, when
    forge-events.board_issue names the board's issue, the board kinds on the git-ref log and the board (CANALE2)."""
    name = config.get('forge-events.adapter')
    _require_compatibility(name, operation_demands.callers())
    demand = forge_requirements.for_consumers(operation_demands.callers())
    main = construct_adapter(name, demand.active() | (forge_requirements.JOURNAL if name == 'file' else set()),
                             'configured forge')
    if name == 'file':
        return main
    kinds = config.get('forge-events.file_kinds')
    log = construct_adapter('file', forge_requirements.JOURNAL, 'file kinds journal') if kinds else None
    routes = {kind: log for kind in kinds}
    issue = config.get('forge-events.board_issue')
    if issue:
        board = board_adapter(issue)
        routes.update({kind: board for section in board.sections.values() for kind in section})
    log = config.get('forge-events.log_adapter')
    if log != name:  # CANALE7: every event kind on the log adapter; the main adapter keeps the forge's other operations
        return RoutingAdapter(main, routes, default=construct_adapter(log, forge_requirements.JOURNAL, 'default journal'))
    checked_adapter(main, forge_requirements.JOURNAL, 'main journal')
    return RoutingAdapter(main, routes) if routes else main


def journal_from_config():
    """GITHUB-DIARY (the final review of the transition, 15/11): the port's journal alone, for the callers that only
    append events and read them back (scripts/plan note, plan input). That is forge-events.log_adapter, the git-ref log
    on the source of truth's remote, with forge-events.file_kinds in the local file log as adapter_from_config routes
    them. adapter_from_config also builds the forge's main adapter, forge-events.adapter, whose Origin adapter refuses a
    GitHub remote ("github.com: git remote is not an Origin git host"): with D-314 every plan note failed there."""
    log = config.get('forge-events.log_adapter')
    journal = construct_adapter(log, forge_requirements.JOURNAL, 'journal')
    kinds = config.get('forge-events.file_kinds')
    if not kinds or log == 'file':
        return journal
    routed = construct_adapter('file', forge_requirements.JOURNAL, 'file kinds journal')
    return RoutingAdapter(journal, {kind: routed for kind in kinds})


def board_adapter(issue):
    """BOARD (CANALE2): the board kinds' adapter for the board on `issue` of forge-events.repo."""
    import forge_board
    import forge_git_ref
    # ORIGIN-FINISH R2: the board's comments come from the selected forge, never a named one; a forge without
    # issue_comments refuses the board before any effect
    forge = construct_adapter(config.get('forge-events.adapter'), {'issue_comments'}, 'board comments')
    comments = forge.issue_comments(config.get('forge-events.repo'), issue)  # the provider's port (E7)
    board = forge_board.Board(comments, config.get('forge-events.board_comment_max_chars'), forge_git_ref.GitRefs(),
                              config.get('forge-events.board_overflow_ref'), config.get('forge-events.git_ref_attempts'))
    sections = {item['section']: item['kinds'] for item in config.get('forge-events.board_sections')}
    return BoardAdapter(construct_adapter('git-ref', forge_requirements.JOURNAL, 'board journal'), board, sections, forge_board.render)


def dedupe(events):
    """(first occurrence of each event_id in log order, the later duplicates)."""
    seen, unique, duplicates = set(), [], []
    for event in events:
        (duplicates if event['event_id'] in seen else unique).append(event)
        seen.add(event['event_id'])
    return unique, duplicates


def ordering_violations(events):
    """Adjacent pairs, in log order, whose occurred_at goes backwards: a consumer sees reordering here."""
    def moment(event):
        return datetime.fromisoformat(event['occurred_at'].replace('Z', '+00:00'))
    return [(a, b) for a, b in zip(events, events[1:]) if moment(b) < moment(a)]


def default_version(kind, versions):
    """The version emitted when the caller names none: a type's registry pin (gate-contracts.<type>_version), else its newest.
    The registry default is read directly: building an event must not read the config store, which is itself events."""
    try:
        return config.entry('gate-contracts.' + kind.replace('.', '_') + '_version')['default']
    except config.ConfigError:
        return max(versions)


def _require_compatibility(adapter, consumers, operation=None, conditions=()):
    try:
        consumers = tuple(consumers)
        document = operation_demands.load()
        classified = dict(document, consumers={path: sorted(forge_requirements.for_consumers([path]).active(conditions))
                                               for path in consumers if path in document['consumers']})
        operation_demands.require(adapter, consumers, operation, classified)
    except operation_demands.CompatibilityError as error:
        raise ForgeCompatibilityError(str(error)) from None


class ForgeEvents:
    def __init__(self, adapter, clock, producer, correlation_id, schemas=None, consumer=None, conditions=()):
        self.adapter, self.clock, self.producer, self.correlation_id = adapter, clock, producer, correlation_id
        self.consumer, self.conditions = consumer, frozenset(conditions)
        self._preflight()
        self.schemas = schemas or event_contracts.registry()
        self.rejected = []
        self._held = None  # the envelopes of an open batched() scope
        self._mirrored = set()  # event ids also written to the repository channel (REC-1)

    def _preflight(self, operation=None):
        consumers = [self.consumer] if self.consumer else operation_demands.callers()
        main = self.adapter.main if isinstance(self.adapter, RoutingAdapter) else self.adapter
        self.compatibility_unknowns = [path for path in consumers
                                       if path not in operation_demands.load()['consumers']]
        if self.consumer and self.compatibility_unknowns:
            raise ForgeEventsError(f'unknown demand {self.consumer}')
        demand = forge_requirements.for_consumers(consumers)
        name = operation_demands.adapter_name(main)
        if name.startswith('unknown:'):
            self.compatibility_unknowns.append(name)
        _require_compatibility(name, consumers, operation, self.conditions)
        checked_adapter(self.adapter, demand.active(self.conditions) | ({operation} if operation else set()), 'forge flow')

    def build(self, kind, payload, version=None):
        versions = event_contracts.catalog(self.schemas.directory).get(kind)
        if not versions:
            raise ForgeEventsError(f'unknown event type {kind}')
        if version is not None and version not in versions:
            raise event_contracts.ContractError(f'unknown event {kind} v{version}')
        envelope = {'type': kind, 'version': version or default_version(kind, versions), 'occurred_at': rfc3339(self.clock.now()),
                    'producer': self.producer, 'correlation_id': self.correlation_id, 'payload': payload}
        envelope['event_id'] = event_contracts.event_id(self.producer, kind,
                                                        event_contracts.natural_key(envelope, self.schemas))
        return event_contracts.validate(envelope, self.schemas)

    def emit(self, kind, payload, version=None, repository=False):
        """Validate and append one event; an event already on the channel is a no-op. Returns the envelope.
        Inside batched() the event is held and published with the others when the scope ends. `repository` (REC-1)
        also writes it to the repository channel, in the same publish, besides the PR's own channel."""
        self._preflight()
        envelope = self.build(kind, payload, version)
        if repository:
            self._mirrored.add(envelope['event_id'])
        if getattr(self, '_held', None) is not None:
            self._held.append(envelope)
            return envelope
        return self.publish([envelope])[0]

    @contextmanager
    def batched(self):
        """GX-FIX-forge-rate (D-070): every emit inside the scope (a per-item loop, measured() steps) is published
        once at its end, one append per channel, even when the body raises. Nested scopes join the outer one."""
        self._preflight()
        if getattr(self, '_held', None) is not None:
            yield self
            return
        self._held = []
        try:
            yield self
        finally:
            held, self._held = self._held, None
            if held:
                self.publish(held)

    def publish(self, envelopes):
        """Append built envelopes in one write per channel, skipping ids the channel already holds."""
        self._preflight()
        by_target = {}
        for envelope in envelopes:
            event_contracts.validate(envelope, self.schemas)
            channels = [Channel(envelope['payload']['repo'], envelope['payload']['pr'])]
            if envelope['event_id'] in self._mirrored and channels[0].pr is not None:
                channels.append(Channel(channels[0].repo, None))
            target = self._target(envelope['type'])
            for channel in channels:
                _, _, items = by_target.setdefault((channel, id(target)), (channel, target, []))
                items.append(envelope)
        for channel, target, items in by_target.values():
            held = {event.get('event_id') for event in self._window(channel, target)[0]}
            fresh, _ = dedupe([event for event in items if event['event_id'] not in held])
            if fresh:
                target.append(channel, fresh)
                self.evaluate_branch_age(channel, fresh)
        return envelopes

    def _target(self, kind):
        """The adapter that stores `kind` (a RoutingAdapter's route), else the port's adapter."""
        route = getattr(self.adapter, 'route', None)
        return route(kind) if callable(route) else self.adapter

    def _window(self, channel, adapter=None, tail=None):
        adapter = adapter or self.adapter
        recent = getattr(adapter, 'recent', None)
        if not recent:
            return adapter.read(channel), True
        return recent(channel, tail) if tail else recent(channel)

    def read_window(self, repo, pr=None, kinds=None, tail=None):
        """(valid events, complete): the newest window of a channel when the adapter offers one, else the whole log.
        With `kinds`, only those types, from the one log that stores them all when there is one (as read does).
        Invalid entries go to self.rejected."""
        self._preflight()
        source = self._source(kinds)
        found, complete = self._window(Channel(repo, pr), source, tail)
        valid = []
        for event in found:
            if kinds and event.get('type') not in kinds:
                continue
            try:
                valid.append(event_contracts.validate(event, self.schemas))
            except (event_contracts.ContractError, KeyError, TypeError) as error:
                self.rejected.append((event, str(error)))
        return dedupe(valid)[0], complete

    def read_recent(self, repo, pr=None, kinds=None):
        """The one shared windowed read (D-085, GATE-TRAIN-SERVICES R4): the valid, deduplicated events of the newest
        forge-events.window_pages pages of a channel, in log order. Every module that read the repository channel
        whole reads it here, so a read costs the newest comments, not the channel's length."""
        return self.read_window(repo, pr, kinds)[0]

    def _source(self, kinds):
        """The one log that stores every kind of `kinds` (GX-FIX-forge-rate-2), else the port's adapter."""
        if kinds:
            targets = {id(self._target(kind)): self._target(kind) for kind in kinds}
            if len(targets) == 1:
                return next(iter(targets.values()))
        return self.adapter

    def evaluate_branch_age(self, channel, fresh):
        """D-069 item 11 (P-32): a trigger event just appended may make its branch stale. Runs on the event only."""
        if channel.pr is None:
            return
        triggers = [event for event in fresh if branch_age.is_trigger(event)]
        if not triggers:
            return
        events = self.read(channel.repo, channel.pr)
        for trigger in triggers:
            payload = branch_age.evaluate(events, trigger, self.clock.now())
            if payload is not None:
                self.emit('branch.stale', payload)

    def read(self, repo, pr=None, strict=False, kinds=None):
        """Valid, deduplicated events of a channel in log order. Invalid entries go to self.rejected (or raise).
        With `kinds`, only those types, read from the one log that stores them all when there is one (GX-FIX-forge-rate-2:
        a file-routed kind is read from the file log, never from the forge)."""
        self._preflight()
        source = self._source(kinds)
        valid = []
        for event in source.read(Channel(repo, pr)):
            if kinds and event.get('type') not in kinds:
                continue
            try:
                valid.append(event_contracts.validate(event, self.schemas))
            except (event_contracts.ContractError, KeyError, TypeError) as error:
                if strict:
                    raise
                self.rejected.append((event, str(error)))
        return dedupe(valid)[0]

    # Forge operations beyond the log (D-069 item 7): the train (M3) reads changes and merges only through these.
    # An adapter that lacks one (the file adapter) refuses it by name.

    def _operation(self, name):
        self._preflight(name)
        operation = getattr(self.adapter, name, None)
        if operation is None:
            raise ForgeEventsError(f'the {type(self.adapter).__name__} has no {name} operation')
        return operation

    def change(self, repo, number):
        # Adjacent direct pass-through: the same evidence rule, outside the dispatches.
        self._preflight('change')
        return self.adapter.change(repo, number)

    def closed_changes(self, repo, since=None):
        """[{number, body, merged_at}] of merged closed changes, in provider order.
        since is an optional inclusive RFC 3339 bound; callers must not rely on order.
        """
        return list(self._operation('closed_changes')(repo, since))

    def open_changes(self, repo, base):
        """Numbers of the open changes that target the branch `base`."""
        return list(self._operation('open_changes')(repo, base))

    def open_pulls(self, repo, base=None):
        """[{number, head_ref, head_sha, draft}] of the open changes, drafts included (TX01, the pre-push overlap)."""
        return [dict(pull) for pull in self._operation('open_pulls')(repo, base)]

    def merge(self, repo, number, head_sha):
        """Merge the change as a merge commit only if its head is still head_sha; returns the merge commit."""
        return self._operation('merge')(repo, number, head_sha)

    def approvals(self, repo, number):
        """Identities whose latest review of the change approves it (the ownership check, D-069 item 8)."""
        return list(self._operation('approvals')(repo, number))

    # Change operations of the push and stall guard (X1): replay-branch and stall-report reach a change's metadata,
    # commits, pushes and comments only through these.

    def pull(self, repo, number):
        """{number, title, body, state ('open'|'closed'|'merged'), head_ref, head_sha, base_ref} of a change.
        Optional additive fields: merge_sha (only when merged, otherwise None), created_at, draft."""
        return dict(self._operation('pull')(repo, number))

    def change_commits(self, repo, number):
        """[{sha, parents, message}] of the change's own commits, in the forge's order (oldest first)."""
        return list(self._operation('change_commits')(repo, number))

    def change_files(self, repo, number):
        """[{filename}] of every file changed by the PR, across all pages."""
        return list(self._operation('change_files')(repo, number))

    def commit_files(self, repo, sha):
        """[{filename}] of a commit; fallback when the local checkout is unavailable."""
        return list(self._operation('commit_files')(repo, sha))

    def compare(self, repo, base, head):
        """{merge_base, behind_by} for base...head; unsupported adapters must refuse."""
        return dict(self._operation('compare')(repo, base, head))

    def force_pushes(self, repo, branch):
        """[{before, after, timestamp}] of recorded force pushes; absence of capability refuses."""
        return list(self._operation('force_pushes')(repo, branch))

    def find_change(self, repo, head_ref):
        """Number of the latest change, in any state, whose head is the branch head_ref; None when there is none."""
        return self._operation('find_change')(repo, head_ref)

    def open_change(self, repo, head_ref, base_ref, title, body):
        """Open a change of head_ref into base_ref; returns its number."""
        return self._operation('open_change')(repo, head_ref, base_ref, title, body)

    def close_change(self, repo, number):
        self._operation('close_change')(repo, number)

    def comment(self, repo, number, body):
        """Post a plain comment (not an event) on a change."""
        self._operation('comment')(repo, number, body)

    def upsert_comment(self, repo, number, first_line, body, **options):
        """GV1: edit in place the comment of a change that opens with first_line, else create it; returns its id."""
        return self._operation('upsert_comment')(repo, number, first_line, body, **options)

    def set_status(self, repo, sha, context, state, description, url=None, landing=False):
        """GX-17: set the commit status `context` of a head to pending, success, failure or error. Raises when the forge
        refuses (an identity without the right to write statuses); the caller decides if that is fatal. CHECK-IN-LANDING:
        with landing, what the adapter answers (the body a landing posts, or None once published)."""
        return self._operation('set_status')(repo, sha, context, state, description, url,
                                             **({'landing': True} if landing else {}))

    def comments(self, repo, number):
        """[{body, created_at, author_association}] of a change's comments, oldest first, event comments included."""
        return list(self._operation('comments')(repo, number))

    def calls(self):
        """{sent, not_modified}: the forge requests this process sent, and how many the forge answered unchanged
        (GATE-ON-PUSH R4). An adapter that counts nothing refuses it by name."""
        return dict(self._operation('calls')())

    def pushes(self, repo, branch):
        """[{before, after, timestamp}] of the pushes to a branch, newest first, as the forge recorded them."""
        return list(self._operation('pushes')(repo, branch))

    def lock(self, repo, name, owner, lease_s):
        """Take, renew or take over (when expired) the named lock for lease_s seconds; False when another owner
        holds it. The instants come from the injected clock; the adapter compares them, never its own clock."""
        operation = self._operation('lock')
        moment = self.clock.now()
        return operation(repo, name, owner, rfc3339(moment),
                         rfc3339(moment + timedelta(seconds=lease_s)))

    def unlock(self, repo, name, owner, died=None):
        """Release the named lock if owner holds it. `died` (TRAIN-TEMP-FIX R1): the one-line reason a run that raised
        leaves on the release record, the durable trace of a death; passed to the adapter only when there is one."""
        operation = self._operation('unlock')
        if died:
            operation(repo, name, owner, died=died)
        else:
            operation(repo, name, owner)


def step_payload(subject_fields, step, duration_ms, result, retries=0, tokens_in=0, tokens_out=0, model=None,
                 provider=None):
    """engine.step.measured v1 payload (SHARED CONTRACT v3 §4) for a step another runner already timed."""
    return dict(subject_fields, step=step, duration_ms=int(duration_ms), tokens_in=tokens_in, tokens_out=tokens_out,
                model=model, provider=provider, result=result, retries=retries)


class Measurement:
    """What a measured step may report besides its time: result (ok|fail|blocked), retries, tokens, model."""

    def __init__(self):
        self.result, self.retries, self.tokens_in, self.tokens_out = 'ok', 0, 0, 0
        self.model = self.provider = None


@contextmanager
def measured(port, step, subject_fields):
    """Time a step with the port's injected clock and emit engine.step.measured (D-069 item 6).

    An exception marks the step fail and still emits before it propagates; the body may set result 'blocked'.
    Usable as `with measured(...) as m:` or as a decorator.
    """
    measurement = Measurement()
    start = port.clock.now()
    try:
        yield measurement
    except BaseException:
        measurement.result = 'fail'
        raise
    finally:
        elapsed = port.clock.now() - start
        port.emit('engine.step.measured', step_payload(
            subject_fields, step, elapsed.total_seconds() * 1000, measurement.result, measurement.retries,
            measurement.tokens_in, measurement.tokens_out, measurement.model, measurement.provider))


QueueEntry = namedtuple('Entry', 'pr sha unit premises lane_id ready_at evidence')
OUT_OF_QUEUE = ('pr.conflicted', 'pr.ejected', 'pr.merged', 'pr.refused')


def queue_entry(events, head):
    """The PR's merge-queue entry from its own log and current head, or None when it is not waiting for the train (TR1):
    its latest `pr.ready` names the head, rests on a `gate.passed` of that head on the same log, and no later
    `pr.conflicted`, `pr.ejected`, `pr.merged` or `pr.refused` names it. A predicate over the log, so it lives with the
    log (D-322): the train (train_queue, delivery) and the coordinator (planning) both read it."""
    ready = [event for event in events if event['type'] == 'pr.ready']
    if not ready:
        return None
    latest = ready[-1]
    sha = latest['payload']['sha']
    if sha != head:
        return None  # pushed after pr.ready: it leaves the queue until a new pr.ready (pr.pushed)
    if any(event['type'] in OUT_OF_QUEUE and event['payload']['sha'] == sha for event in events):
        return None
    evidence = latest['payload']['evidence']
    if not any(event['type'] == 'gate.passed' and event['event_id'] == evidence and event['payload']['sha'] == sha
               for event in events):
        return None  # pr.ready must rest on a passed gate of this exact head on the same log
    payload = latest['payload']
    return QueueEntry(payload['pr'], sha, payload['unit'], tuple(payload['premises']), payload['lane_id'],
                      latest['occurred_at'], evidence)


def new_pr_state():
    return {'head': None, 'gates': {}, 'ready': None, 'merged': None, 'conflicted': [], 'ejected': []}


def apply(state, event):
    """Fold one event into the per-PR state; the live consumer and replay use this same step."""
    payload, kind = event['payload'], event['type']
    if payload.get('pr') is None:
        return state
    pr = state.setdefault(payload['pr'], new_pr_state())
    if payload.get('sha'):
        pr['head'] = payload['sha']
    if kind in ('gate.passed', 'gate.failed'):
        pr['gates'].setdefault(payload['sha'], {})[payload['plan']] = {
            'verdict': kind.split('.')[1], 'event_id': event['event_id'], 'at': event['occurred_at']}
    elif kind == 'pr.ready':
        pr['ready'] = payload['sha']
    elif kind == 'pr.merged':
        pr['merged'] = payload['merge_sha']
    elif kind == 'pr.conflicted':
        pr['conflicted'].append(payload['tip_sha'])
    elif kind == 'pr.ejected':
        pr['ejected'].append(payload['batch_id'])
    return state


def replay(events):
    """Per-PR gate and merge state rebuilt from the log alone (D-069 item 4). Same log, same state."""
    state = {}
    for event in dedupe(events)[0]:
        apply(state, event)
    return state


def gate_slow(verdicts):
    """gate.slow fields when the median tier-1 time of the last gate.slow_window_events verdicts exceeds
    gate.slow_median_s (EVENTS.md), else None. Emitting it needs the repository channel (the train, M3)."""
    window = config.get('gate.slow_window_events')
    tier1 = [e for e in verdicts if e['type'] in ('gate.passed', 'gate.failed') and e['payload']['tier'] == 1][-window:]
    if len(tier1) < window:
        return None
    totals = sorted(sum(stage['duration_ms'] for stage in e['payload']['stages']) for e in tier1)
    middle = len(totals) // 2
    median = totals[middle] if len(totals) % 2 else (totals[middle - 1] + totals[middle]) // 2
    if median <= config.get('gate.slow_median_s') * 1000:
        return None
    per_stage = {}
    for event in tier1:
        for stage in event['payload']['stages']:
            per_stage[stage['name']] = per_stage.get(stage['name'], 0) + stage['duration_ms']
    return {'median_ms': median, 'window': window,
            'slowest_stages': sorted(per_stage, key=lambda name: (-per_stage[name], name))}


def gate_evidence(state, pr, sha, plan):
    """event_id of the gate.passed for this exact head and plan, or None: what replaces `.dev.pass` as evidence."""
    verdict = state.get(pr, {}).get('gates', {}).get(sha, {}).get(plan)
    return verdict['event_id'] if verdict and verdict['verdict'] == 'passed' else None


def main(argv=None):
    parser = argparse.ArgumentParser(prog='forge_events.py')
    sub = parser.add_subparsers(dest='command', required=True)
    emit = sub.add_parser('emit')
    emit.add_argument('type')
    emit.add_argument('--payload', required=True)
    emit.add_argument('--producer', required=True)
    emit.add_argument('--correlation-id', required=True)
    for name in ('read', 'replay'):
        sub.add_parser(name).add_argument('--pr', type=int)
    args = parser.parse_args(argv)
    repo = config.get('forge-events.repo')
    if args.command == 'emit':
        port = ForgeEvents(adapter_from_config(), clock_from_config(), args.producer, args.correlation_id)
        print(port.emit(args.type, json.loads(args.payload))['event_id'])
        return 0
    port = ForgeEvents(adapter_from_config(), clock_from_config(), 'reader', 'cli')
    events = port.read(repo, args.pr)
    for event, reason in port.rejected:
        print(f'forge_events: rejected entry: {reason}', file=sys.stderr)
    result = events if args.command == 'read' else replay(events)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    sys.exit(main())
