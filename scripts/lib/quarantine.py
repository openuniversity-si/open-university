"""The flaky-test quarantine (plan v3 M7 as changed by v3.1 §3; D-025, D-065 V7, D-069 items 4, 5 and 8).

A flake is evidence already in the log, never an extra run: a test that failed and passed on the same sha. A green
tier-2 or battery run means every test passed on that exact content, so a red run on a sha that also has a green run
is a proven flake, and every test it names flaked there. flaked() finds them in the runs a caller already holds (the
train: its batch and bisection runs plus the green runs its `engine.step.measured` events record; the battery role,
M6, its own runs).

report() emits `test.flaked` and then, unless the test is already in quarantine, `test.quarantined`, owned by the owner
of the test's unit: U0's manifests through the train's ownership interface (train_ownership.UnitOwnership.owner_of),
or quarantine.unknown_owner while no manifest covers the test. The owner owes a stabilizing PR whose body names the
test on a `Stabilizes:` line; when it merges, release() emits `test.unquarantined`. Every quarantine event is on the
repository channel (pr null), so state() rebuilds the open quarantines by replaying that log alone; nothing else holds
them. A quarantined test stays blocking in every tier: this module changes no gate policy (D-025).

CLI: `scripts/quarantine list` prints the open quarantines from the log, marking those older than
quarantine.max_age_s as overdue (the maestro escalates them to the owner).
"""
import argparse
from collections import namedtuple
from datetime import datetime
import re
import sys

import config
import forge_events

Run = namedtuple('Run', 'sha ok tests log')
STABILIZES_LINE = re.compile(r'^Stabilizes:[ \t]*(.+?)[ \t]*$', re.M)


def failing_tests(result, fallback):
    """Test ids a red result names: its failing test files, else its failed stage, else `fallback`."""
    tests = tuple(getattr(result, 'tests', None) or ())
    return tests or ((result.stage,) if result.stage else (fallback,))


def proven_flaky(run, runs):
    """True when the red run's sha also has a green run among `runs`: none of its failures is evidence."""
    return not run.ok and any(other.ok and other.sha == run.sha for other in runs)


def flaked(runs):
    """[(sha, test, log)] of every test a red run names on a sha that also has a green run, in run order."""
    found, seen = [], set()
    for run in runs:
        if not proven_flaky(run, runs):
            continue
        for test in run.tests:
            if (run.sha, test) not in seen:
                seen.add((run.sha, test))
                found.append((run.sha, test, run.log))
    return found


def stabilized(body):
    """Test ids the body's `Stabilizes:` lines name (one per line, or several separated by commas)."""
    return [test.strip() for line in STABILIZES_LINE.findall(body or '') for test in line.split(',') if test.strip()]


def state(events):
    """{test: {sha, unit, owner, event_id, since}} of the open quarantines, from the repository log alone."""
    open_ = {}
    for event in forge_events.dedupe(events)[0]:
        payload = event['payload']
        if event['type'] == 'test.quarantined' and payload['test'] not in open_:
            open_[payload['test']] = {'sha': payload['sha'], 'unit': payload['unit'], 'owner': payload['owner'],
                                      'event_id': event['event_id'], 'since': event['occurred_at']}
        elif event['type'] == 'test.unquarantined' and \
                open_.get(payload['test'], {}).get('event_id') == payload['quarantined_event']:
            del open_[payload['test']]
    return open_


def overdue(open_, now):
    """Tests whose quarantine is older than quarantine.max_age_s at `now` (the injected clock): escalate them."""
    limit = config.get('quarantine.max_age_s')
    return sorted(test for test, item in open_.items()
                  if (now - datetime.fromisoformat(item['since'].replace('Z', '+00:00'))).total_seconds() > limit)


class Quarantine:
    """The quarantine over one repository: emits through the caller's forge_events port, owners through `owners`
    (a train_ownership.UnitOwnership, or None before any workspace exists: every owner is then unknown)."""

    def __init__(self, repo, owners=None):
        self.repo, self.owners = repo, owners
        self.unknown_owner = config.get('quarantine.unknown_owner')
        self.step_prefix = config.get('quarantine.step_prefix')
        self.test_roots = config.get('quarantine.test_roots')

    def owner(self, commit, test):
        """(unit, owner) of the test's file at the commit, trying each quarantine.test_roots prefix."""
        if self.owners is not None:
            for root in self.test_roots:
                unit, owner = self.owners.owner_of(commit, root + test)
                if owner:
                    return unit, owner
        return None, self.unknown_owner

    def open(self, port):
        """The open quarantines in the newest window of the repository log: the whole channel outgrows
        the journal window (#548). A quarantine older than the window stays open (not released by a merge),
        the safe direction."""
        return state(port.read_window(self.repo, None)[0])

    def report(self, port, flakes):
        """test.flaked for each (sha, test, log), then test.quarantined for each test not already in quarantine.
        Returns the tests newly quarantined."""
        if not flakes:
            return []
        quarantined = []
        with port.batched(), forge_events.measured(port, self.step_prefix + 'flaked', forge_events.subject(
                self.repo, None, flakes[0][0])):  # GX-FIX-forge-rate: one append for the whole loop
            open_ = self.open(port)
            for sha, test, log in flakes:
                unit, owner = self.owner(sha, test)
                subject = forge_events.subject(self.repo, None, sha, (), unit)
                evidence = port.emit('test.flaked', dict(subject, test=test, log=log))
                if test in open_:
                    continue
                port.emit('test.quarantined', dict(subject, test=test, owner=owner,
                                                   flaked_event=evidence['event_id']))
                open_[test] = {'owner': owner}
                quarantined.append(test)
        return quarantined

    def release(self, port, pr, lane_id, merge_sha, body):
        """test.unquarantined for each open quarantine the merged PR's body stabilizes, when its lane is the owner
        (or the owner is quarantine.unknown_owner, until U0's manifests name one). Returns the released tests."""
        named = stabilized(body)
        if not named:
            return []
        released = []
        with port.batched(), forge_events.measured(port, self.step_prefix + 'release',
                                                   forge_events.subject(self.repo, None, merge_sha)) as measurement:
            open_ = self.open(port)
            for test in named:
                item = open_.get(test)
                if item is None or item['owner'] not in (lane_id, self.unknown_owner):
                    continue
                port.emit('test.unquarantined', dict(forge_events.subject(self.repo, None, merge_sha, (), item['unit']),
                                                     test=test, owner=item['owner'],
                                                     quarantined_event=item['event_id'], stabilizing_pr=pr))
                released.append(test)
            if len(released) < len(named):
                measurement.result = 'blocked'
        return released


def render(open_, now):
    """One line per open quarantine, oldest first: test, owner, unit, since, and `overdue` past quarantine.max_age_s."""
    late = set(overdue(open_, now))
    return [f"{test}  owner={item['owner']}  unit={item['unit'] or '-'}  since={item['since']}"
            + ('  overdue' if test in late else '')
            for test, item in sorted(open_.items(), key=lambda pair: (pair[1]['since'], pair[0]))]


def main(argv=None):
    parser = argparse.ArgumentParser(prog='scripts/quarantine', description='The flaky-test quarantine (plan v3 M7).')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('list', help='print the open quarantines from the repository log')
    parser.parse_args(argv)
    clock = forge_events.clock_from_config()
    port = forge_events.ForgeEvents(forge_events.adapter_from_config(), clock, 'reader', 'quarantine')
    lines = render(state(port.read_recent(config.get('forge-events.repo'))), clock.now())  # D-085
    print('\n'.join(lines) if lines else 'quarantine: none open')
    return 0


if __name__ == '__main__':
    sys.exit(main())
