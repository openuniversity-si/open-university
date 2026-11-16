"""PR-OBSERVATION, part 2 (docs/operations/aws.md 22.9): `pr metadata` judges what the live service read of the PR with
the forge's key (GET /v1/pr-observation), through the Origin adapter's own mapping (forge_origin.ObservedAdapter), with no
credential and no reflog of the lane; the gate asks the port for it (gate_infra.metadata_of). Hermetic."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import commit_check  # noqa: E402
import config  # noqa: E402
import forge_events  # noqa: E402
import forge_origin_client  # noqa: E402
import gate_infra  # noqa: E402

REPO = config.get('forge-events.repo')


def git(root, *args):
    return subprocess.run(['git', '-C', str(root), '-c', 'user.name=t', '-c', 'user.email=t@t', *args],
                          capture_output=True, text=True, check=True).stdout.strip()


def observation(head, base_sha, message='unit: a change\n\nPlan: 1', forced=False):
    return {'head': head, 'pull': {'number': 7, 'title': 't', 'body': 'the body', 'state': 'open', 'draft': False,
                                   'createdAt': '2026-11-13T00:00:00Z', 'head': {'ref': 'units/x', 'sha': head},
                                   'base': {'ref': 'mod/base'}},
            'commits': [{'sha': head, 'parents': [{'sha': base_sha}], 'commit': {'message': message}}],
            'comments': [{'body': 'a comment', 'createdAt': '2026-11-13T00:01:00Z'}], 'files': [{'filename': 'b.txt'}],
            'compare': {'mergeBaseCommit': {'sha': base_sha}, 'behindBy': 0},
            'pushes': [{'before': '0' * 40, 'after': head, 'timestamp': '2026-11-13T00:00:30Z', 'forced': forced}]}


class TheObservedAdapter(unittest.TestCase):
    def test_the_port_maps_the_observation_as_it_maps_origins_live_answers_and_refuses_what_it_does_not_hold(self):
        seen = observation('a' * 40, 'b' * 40, forced=True)
        port = forge_events.ForgeEvents(forge_events.adapter_of_observation(seen), forge_events.clock_from_config(),
                                        'commit-check', 'pr-7', consumer='scripts/lib/commit_check.py')
        self.assertEqual(port.pull(REPO, 7)['head_ref'], 'units/x')
        self.assertEqual(port.change_commits(REPO, 7), [{'sha': 'a' * 40, 'parents': ['b' * 40],
                                                         'message': 'unit: a change\n\nPlan: 1'}])
        self.assertEqual(port.comments(REPO, 7)[0]['body'], 'a comment')
        self.assertEqual(port.compare(REPO, 'mod/base', 'a' * 40), {'merge_base': 'b' * 40, 'behind_by': 0})
        self.assertEqual(len(port.pushes(REPO, 'units/x')), 1)
        self.assertEqual(len(port.force_pushes(REPO, 'units/x')), 1)
        self.assertEqual(port.change_files(REPO, 7), [{'filename': 'b.txt'}])  # OBSERVATION-FILES: a merged PR's own list
        older = forge_events.ForgeEvents(forge_events.adapter_of_observation({k: v for k, v in seen.items() if k != 'files'}),
                                         forge_events.clock_from_config(), 'commit-check', 'pr-7',
                                         consumer='scripts/lib/commit_check.py')
        for refused in (lambda: port.pull(REPO, 8), lambda: port.compare(REPO, 'mod/base', 'c' * 40),
                        lambda: older.change_files(REPO, 7), lambda: port.pushes(REPO, 'units/y')):
            with self.assertRaises(Exception):
                refused()

    def test_commit_check_reads_the_pr_from_the_observation_and_never_the_forge(self):
        with tempfile.TemporaryDirectory() as tmp:
            git(tmp, 'init', '-q')
            Path(tmp, 'a.txt').write_text('a\n')
            git(tmp, 'add', '.')
            git(tmp, 'commit', '-qm', 'base')
            base = git(tmp, 'rev-parse', 'HEAD')
            Path(tmp, 'b.txt').write_text('b\n')
            git(tmp, 'add', '.')
            git(tmp, 'commit', '-qm', 'unit: a change')
            head = git(tmp, 'rev-parse', 'HEAD')
            with mock.patch.object(forge_origin_client, '_run_cli', side_effect=AssertionError('the forge was asked')):
                pr = commit_check.fetch(7, root=tmp, head=head, observation=observation(head, base))
        self.assertEqual((pr['body'], pr['gated']['sha'], pr['files']), ('the body', head, ['b.txt']))
        self.assertEqual(pr['commits'][0]['files'], ['b.txt'])
        self.assertEqual(pr['pushes'][0]['after'], head)


class Port:
    def __init__(self, states=None, refuse=None):
        self.states, self.refuse, self.calls = list(states or []), refuse, []

    def call(self, method, path, body=None):
        self.calls.append((method, path, body))
        if self.refuse:
            raise gate_infra.Refused(self.refuse, 'no')
        if method == 'POST':
            return {'id': '9', 'state': 'asked'}
        return self.states.pop(0)


class Run:
    def __init__(self, code=0, text='structure-check (metadata, PR #7): 0 error(s), 0 warning(s)'):
        self.code, self.text, self.commands, self.observations = code, text, [], []

    def __call__(self, command, **_):
        self.commands.append(command)
        if '--observation' in command:
            self.observations.append(json.loads(Path(command[command.index('--observation') + 1]).read_text()))
        return subprocess.CompletedProcess(command, self.code, self.text, '')


class TheGatesAsk(unittest.TestCase):
    def test_the_metadata_is_judged_on_what_the_live_service_read(self):
        run, seen = Run(), observation('a' * 40, 'b' * 40)
        port = Port([{'state': 'asked'}, {'state': 'observed', 'head': 'a' * 40,
                                          'observation': {k: v for k, v in seen.items() if k != 'head'}}])
        ok, _ = gate_infra.metadata_of(7, 'base', run=run, sleep=lambda _: None, port=port, head='a' * 40)
        self.assertTrue(ok)
        self.assertEqual(port.calls[0], ('POST', '/v1/pr-observation', {'pr': 7, 'head': 'a' * 40}))
        self.assertEqual(run.observations, [seen])

    def test_a_port_without_the_route_leaves_the_lanes_read_and_a_failed_read_is_a_forge_that_did_not_answer(self):
        run = Run()
        ok, _ = gate_infra.metadata_of(7, 'base', run=run, sleep=lambda _: None, port=Port(refuse=404), head='a' * 40)
        self.assertEqual((ok, '--observation' in run.commands[0]), (True, False))
        failed = [{'state': 'failed', 'why': 'RuntimeError: origin api failed: 503'}] * 20
        run = Run()
        real, pinned = gate_infra.config.get, {'gate-infra.call_retries': 2, 'gate-infra.call_backoff_s': 0.0,
                                               'gate-infra.metadata_blind_wait_s': 1.0}
        with mock.patch.object(gate_infra.config, 'get', side_effect=lambda name, *rest: pinned.get(name) if name in pinned
                               else real(name, *rest)):
            ok, text = gate_infra.metadata_of(7, 'base', run=run, sleep=lambda _: None, jitter=lambda a, b: 0.0,
                                              port=Port(failed), head='a' * 40)
        self.assertFalse(ok)
        self.assertEqual(run.commands, [])  # nothing judged on a read that did not happen
        self.assertIn('the live service could not read it', text)
        self.assertIn('the PR was not judged', text)


if __name__ == '__main__':
    unittest.main()
