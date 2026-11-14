"""The battery role: tier 3 on integration.advanced (plan v3 M6; D-065 (1) and (5), V7; D-068; D-069 items 3, 4, 6,
7 and 11).

Driven by events only, through the forge_events port. The repository log holds every `integration.advanced` the train
emits; a tip is pending while it is the newest advance and has no `battery.green` or `battery.red`. Coalescing: an
older advance that a newer one supersedes is never run, because tier 3 on the newer tip covers it. Replaying the log
rebuilds what is pending (D-069 item 4); nothing else holds battery state.

Tier 3 is the full battery on the tip (battery.tier3_command: `scripts/gate-local --tier3 --sha <tip>`), with a fresh
build cache and never a cached result (D-065 (5), plan v3 §7.3: the only cache tiers 2 and 3 could use needs the full
content key, and none is used here). WebKit and gate-db are not run: they run only at release (V7). The verdict is
`battery.green` or `battery.red`.

Red: batch bisection over the tips advanced since the last green tip (the `integration.advanced` history; each tip is
a commit that already exists, so nothing is built). The newest tip is known red; the first red tip names the culprit
batch and its PRs, emitted as `battery.culprit` to the lane and the maestro. At most battery.bisection_max_runs tier-3
runs; when they run out first, the batches still in doubt are named instead. The battery never reverts, pushes or
merges: the fix or the revert is the lane's next PR.

Green: the release criterion. The PRs merged since the last released tip (the advances after it, up to this tip, from
the log; never the count an advance carried when it was emitted, which a later release.ready may have made stale)
are counted against release.merged_prs_per_release; when they reach it, `release.ready` records the tip and its PRs.
It only records: no deploy, no preview, nothing reaches production, and WebKit and gate-db run in the release
pipeline that consumes it (roadmap step 8, D-054, V7), never here.

The role (D-065 (1), EVENTS.md "Transport v0"): whoever emits integration.advanced runs `scripts/battery run`, which
takes the battery's own lock (battery.lock_ref, leased for battery.lock_lease_s and renewed before every tier-3 run)
and runs until no newer tip is pending, then releases it and looks once more, so an advance whose producer found the
lock taken is never stranded (engine_role.LockedRole, shared with the train). While battery.enabled (an x-flag,
default off) is false the command does nothing; switching it on is a config.changed event (scripts/config set).

No run is retried (D-025). Telling a flake from a culprit is the quarantine's (M7, scripts/lib/quarantine.py,
`test.flaked`): the seam is Battery.red (with LockedRole.record for the runs), where a red verdict is final today;
feeding the battery's runs to quarantine.proven_flaky is the quarantine's next step, not this role's.

Base health signal (GX-32, contracts base.red.v1 / base.green.v1): tier 3 writes its report to its own
GATE_REPORT_DIR and the failing tests of every stage shape are read from it (defect_adapters). A red tip with failing
tests emits `base.red {tests, since, base_sha}` (`since` carried from the open base.red, else this tip); the first green
tip after a base.red emits `base.green {cleared}`. Adjudication (defect_detect.base_signal) excuses a listed test on
exactly that base sha. While defects.base_signal_enabled is false nothing is emitted.

Every tunable is a `battery.*` registry entry (config/registry/battery.json) read with config.get; every run and step
emits `engine.step.measured` through forge_events.measured with the injected clock.
"""
import argparse
import sys

import json
from pathlib import Path
import tempfile

import config
import defect_adapters
import engine_role
import forge_events

VERDICTS = ('battery.green', 'battery.red')
SIGNALS = ('base.red', 'base.green')
REPORT_DIR_ENV = 'GATE_REPORT_DIR'  # where gate-local writes stages.json and the stage logs


class BatteryError(RuntimeError):
    """The registry values cannot drive the battery role."""


class BatteryHalt(engine_role.RoleHalt):
    """The battery role must stop for a person (it lost its lock)."""


def advances(events):
    return [event for event in events if event['type'] == 'integration.advanced']


def pending_advance(events):
    """The newest integration.advanced when its tip has no battery verdict yet, else None (coalescing)."""
    found = advances(events)
    if not found:
        return None
    judged = {event['payload']['sha'] for event in events if event['type'] in VERDICTS}
    return None if found[-1]['payload']['sha'] in judged else found[-1]


def bisection_window(events, advance):
    """(the advances after the last green tip up to and including `advance`, oldest first; that green tip or None)."""
    found = advances(events)
    end = next(index for index, event in enumerate(found) if event['event_id'] == advance['event_id'])
    green = {event['payload']['sha'] for event in events if event['type'] == 'battery.green'}
    for index in range(end - 1, -1, -1):
        if found[index]['payload']['sha'] in green:
            return found[index + 1:end + 1], found[index]['payload']['sha']
    return found[:end + 1], None


def release_window(events, advance):
    """The PRs merged after the last tip a release.ready recorded, up to and including `advance`, oldest first."""
    found = advances(events)
    end = next(index for index, event in enumerate(found) if event['event_id'] == advance['event_id'])
    released = {event['payload']['sha'] for event in events if event['type'] == 'release.ready'}
    start = next((index + 1 for index in range(end, -1, -1) if found[index]['payload']['sha'] in released), 0)
    return list(dict.fromkeys(pr for event in found[start:end + 1] for pr in event['payload']['prs']))


def failing(result):
    return [result.stage] if not result.ok and result.stage else []


def open_red(events):
    """The newest base.red when no base.green came after it, else None."""
    found = [event for event in events if event['type'] in SIGNALS]
    return found[-1] if found and found[-1]['type'] == SIGNALS[0] else None


def report_failures(logs):
    """GX-32: the failing tests of a tier-3 report directory, every stage shape; none when there is no report."""
    try:
        report = json.loads((Path(logs) / 'stages.json').read_text())
    except (OSError, ValueError):
        return []
    found, _ = defect_adapters.failures(report, logs)
    return found


class Tier3Gate(engine_role.CommandGate):
    """Runs tier 3 on one integration tip and reports (ok, first failed stage, output tail)."""

    def __init__(self, root=None):
        super().__init__(root, config.get('battery.tier3_command'), config.get('battery.tier3_timeout_s'),
                         config.get('battery.tier3_log_chars'), 'tier 3', 'battery.tier3_timeout_s')
        self.failing_tests = []

    def run(self, commit, env=None):
        """The tier-3 run with its own report directory; the failing tests it reported are kept in failing_tests."""
        with tempfile.TemporaryDirectory(prefix='tier3-report-') as logs:
            result = super().run(commit, env=dict(env or {}, **{REPORT_DIR_ENV: logs}))
            self.failing_tests = [] if result.ok else report_failures(logs)
        return result


class Battery(engine_role.LockedRole):
    """One battery role over one repository: the forge port (the repository log and the lock) and tier 3."""

    Halt = BatteryHalt

    def __init__(self, adapter, clock, gate, repo=None):
        self.adapter, self.clock, self.gate = adapter, clock, gate
        self.bisection_max_runs = config.get('battery.bisection_max_runs')
        self.release_threshold = config.get('release.merged_prs_per_release')
        self.repo = repo or config.get('forge-events.repo')
        self.producer = config.get('battery.producer')
        self.step_prefix = config.get('battery.step_prefix')
        self.lock_ref = config.get('battery.lock_ref')
        self.lock_lease_s = config.get('battery.lock_lease_s')
        timeout = config.get('battery.tier3_timeout_s')
        if self.lock_lease_s <= timeout:
            raise BatteryError(f'battery.lock_lease_s {self.lock_lease_s} must exceed battery.tier3_timeout_s '
                               f'{timeout}: the lease is renewed only between tier-3 runs')

    def history(self):
        return self.port('history').read_recent(self.repo)  # D-085: the shared window

    def pending(self):
        return pending_advance(self.history()) is not None

    def drain(self, port):
        advance = pending_advance(self.history())
        while advance:
            self.run_tip(advance)
            advance = pending_advance(self.history())

    def run(self, owner):
        """The role: 'busy' (another owner holds the lock) or 'drained' (no newer tip is pending)."""
        return super().run(owner, 'pending')

    def run_tip(self, advance):
        """Tier 3 on one advanced tip, then its verdict. Returns True when green."""
        sha = advance['payload']['sha']
        port = self.port(f'{self.producer}:{sha}')
        with self.step(port, 'run', sha) as measurement:
            result = self.judge(port, 'tier3', sha)
            payload = dict(forge_events.subject(self.repo, None, sha), duration_ms=self.last_run_ms,
                           failing=failing(result))
            tests = list(getattr(self.gate, 'failing_tests', None) or [])
            if result.ok:
                port.emit('battery.green', payload)
                self.signal(port, sha, True, [])
                self.release(port, advance)
                return True
            measurement.result = 'fail'
            port.emit('battery.red', payload)
            self.signal(port, sha, False, tests)
            self.red(port, advance, result)
        return False

    def signal(self, port, sha, ok, tests):
        """GX-32: base.red for a red tip with failing tests, base.green for the first green tip after a base.red.
        A red tip whose failures name no test emits nothing (nothing could be excused by it). Returns the event."""
        if not config.get('defects.base_signal_enabled'):
            return None
        last = open_red(self.history())
        subject = forge_events.subject(self.repo, None, sha)
        if not ok and tests:
            since = last['payload']['since'] if last else sha
            return port.emit('base.red', dict(subject, base_sha=sha, since=since, tests=[
                {key: test[key] for key in ('id', 'stage', 'signature')} for test in tests]))
        if ok and last:
            return port.emit('base.green', dict(subject, base_sha=sha, cleared=[test['id'] for test in last['payload']['tests']]))
        return None

    def release(self, port, advance):
        """release.ready when the PRs since the last release reach the criterion. Returns the PRs it recorded."""
        prs = release_window(self.history(), advance)
        if len(prs) < self.release_threshold:
            return []
        port.emit('release.ready', dict(forge_events.subject(self.repo, None, advance['payload']['sha']), prs=prs,
                                        prs_since_release=len(prs)))
        return prs

    def red(self, port, advance, result):
        """A red tip. M7 seam: a red run proven flaky by the quarantine (quarantine.proven_flaky over the runs
        record() keeps) would be told apart here, before anything is blamed; until that is wired every red verdict
        stands and nothing is retried (D-025)."""
        if result.log:
            print(f'battery: tier 3 red on {advance["payload"]["sha"]}:\n{result.log}', file=sys.stderr)
        self.bisect(port, advance, result)

    def bisect(self, port, advance, result):
        """Name the first red tip since the last green one (battery.culprit). Returns the culprit advance or None."""
        sha = advance['payload']['sha']
        window, good = bisection_window(self.history(), advance)
        with self.step(port, 'bisection', sha) as measurement:
            found = engine_role.first_red(
                len(window), lambda index: self.judge(port, 'bisect', window[index]['payload']['sha']), result,
                self.bisection_max_runs)
            culprit = window[found.high]['payload'] if found.low == found.high else None
            if culprit is None:
                measurement.result = 'blocked'
            port.emit('battery.culprit', dict(
                forge_events.subject(self.repo, None, sha), good_sha=good,
                culprit_sha=culprit['sha'] if culprit else None, batch_id=culprit['batch_id'] if culprit else None,
                prs=culprit['prs'] if culprit else [], failing=failing(found.failing), runs=found.runs,
                candidates=[event['payload']['batch_id'] for event in window[found.low:found.high + 1]]))
        return culprit


def from_config():
    """The battery role over the registry's adapter and clock, this checkout and the real tier 3."""
    return Battery(forge_events.adapter_from_config(), forge_events.clock_from_config(), Tier3Gate())


def main(argv=None):
    parser = argparse.ArgumentParser(prog='scripts/battery', description='The battery role: tier 3 (plan v3 M6).')
    sub = parser.add_subparsers(dest='command', required=True)
    run = sub.add_parser('run', help='take the lock and run tier 3 until no newer tip is pending (off: does nothing)')
    run.add_argument('--owner', help='lock owner name (default: producer@host:pid)')
    sub.add_parser('pending', help='print the integration tip tier 3 would run next, if any')
    args = parser.parse_args(argv)
    if args.command == 'run' and not config.get('battery.enabled'):
        print('battery: off (battery.enabled is false); no tier 3 runs')
        return 0
    role = from_config()
    if args.command == 'pending':
        advance = pending_advance(role.history())
        print(f'{advance["payload"]["sha"]} batch {advance["payload"]["batch_id"]}' if advance else 'nothing pending')
        return 0
    try:
        print(f'battery: {role.run(args.owner or engine_role.default_owner(role.producer))}')
    except BatteryHalt as error:
        print(f'battery: halted: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
