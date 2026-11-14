"""scripts/deliver: gate on the exact head, merge with --expect-head, base refreshed, PR/s printed. Hermetic: a fake run."""
from pathlib import Path
import subprocess
import sys
import contextlib
import fcntl
import json
import os
import tempfile
import threading
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import deliver  # noqa: E402

DELIVER_BATCH_READING = deliver.batch_reading  # the real reading, before a test patches it

HEAD = 'a' * 40
BASE = deliver.config.get('train.base_branch')
TREE = 'f' * len(HEAD)  # the tree id git merge-tree prints first
PORT = {'TOWER_PORT_URL': 'port-of-the-test', 'TOWER_PORT_TOKEN': 'token-of-the-test'}  # the shadow's port, faked
LOCKED = (f"error: cannot lock ref 'refs/remotes/origin/{BASE}': is at {'9' * 40} but expected {'1' * 40}")


class Fake:
    def __init__(self, pushed=HEAD, gate=0, merge=0):
        self.answers = {'rev-parse --abbrev-ref': (0, 'feat/x'), 'rev-parse HEAD': (0, HEAD),
                        'rev-parse origin/feat/x': (0, HEAD), 'worktree add': (0, ''),
                        'ls-remote': (0, f'{pushed}\trefs/heads/feat/x' if pushed else ''),
                        'gate-dev': (gate, 'GATE: PASSED' if gate == 0 else 'GATE: FAILED'),
                        'pr view': (0, json.dumps({'baseRef': BASE})),
                        'pr merge': (merge, 'Merged pull request #7\n  Merge commit: ' + 'b' * 40),
                        'flow-metrics': (0, 'day raw\nlast 10 merges in 600 s: 0.0167 PR/s, ladder step 1 reached')}
        self.calls, self.cwds, self.sequences = [], [], {}

    def __call__(self, argv, cwd=None, **_kwargs):
        line = ' '.join(argv)
        self.calls.append(line)
        self.cwds.append((line, cwd))
        # the longest matching key wins, so a specific `ls-remote origin refs/heads/<base>` beats the generic `ls-remote`
        queued = max((item for item in self.sequences.items() if item[0] in line and item[1]), key=lambda i: len(i[0]), default=None)
        if queued:
            code, text, *err = queued[1].pop(0)
            return subprocess.CompletedProcess(argv, code, text, err[0] if err else '')
        matched = [answer for key, answer in self.answers.items() if key in line] \
            and max(((key, answer) for key, answer in self.answers.items() if key in line), key=lambda i: len(i[0]))[1]
        code, text = matched or (0, '')
        return subprocess.CompletedProcess(argv, code, text, '')


HERMETIC = []


CHECKS = []  # EMERGENCY-EXIT-CHECK: the heads whose green box verdict was published as tower/gate
REAL_BOX_CHECK = deliver.box_check


def setUpModule():
    """No test of this module reaches the real port or writes the real cache, whatever the session's environment
    names: the port's variables are gone, the cache is a throwaway folder and a shadow never starts. A test that wants
    the port names it (PORT) with its own cache, and one that wants to see a shadow start patches SPAWN itself. The
    configuration's changes come from an empty store, whatever this checkout's own holds (GATE-INFRA 12: on 04/11 a
    delivery.judge infra set in the checkout turned 38 of these tests to the infrastructure's path)."""
    cache, store = tempfile.TemporaryDirectory(), tempfile.TemporaryDirectory()
    bare = {name: value for name, value in os.environ.items() if not name.startswith('TOWER_PORT_')}
    for patcher in (mock.patch.dict(os.environ, dict(bare, XDG_CACHE_HOME=cache.name), clear=True),
                    mock.patch.object(deliver, 'SPAWN', lambda argv, **options: None),
                    # EMERGENCY-EXIT-CHECK: no test publishes a real tower/gate; the one that tests the publish names it
                    mock.patch.object(deliver, 'box_check', lambda head, seconds, out: CHECKS.append(head)),
                    deliver.config.use_store_of(store.name)):
        if hasattr(patcher, 'start'):
            patcher.start()
            HERMETIC.append(patcher.stop)
        else:  # the configuration's empty store, held for the module
            patcher.__enter__()
            HERMETIC.append(lambda held=patcher: held.__exit__(None, None, None))
    HERMETIC.extend([cache.cleanup, store.cleanup])
    # The registry's default is the switch (infra since 08/11). The box's path, which these tests exercise, is this empty store's
    # own value; a test of the infrastructure's path names it (judged_by_infra, Switches).
    from datetime import datetime
    deliver.config.set_value('delivery.judge', 'box', actor='the tests', reason='the tests exercise the box path',
                             now=datetime.fromisoformat('2026-11-08T00:00:00+00:00'))


def tearDownModule():
    while HERMETIC:
        HERMETIC.pop()()

class FrontAuthOnce(unittest.TestCase):
    """FRONT-AUTH-ONCE (critério 3): the front's ls-remote of the base took 1.9 to 2.6 s, ~2 s of them git's credential
    dance; with the credentials asked once, ahead, and given in git's environment, one request (0.34 to 0.58 s)."""

    def tearDown(self):
        deliver.FORGE_AUTH.clear()

    def test_the_credentials_are_asked_once_and_go_to_the_network_calls_in_the_environment_never_argv(self):
        asked = []

        def run(argv, **options):
            asked.append((argv, options))
            if argv[:3] == ['git', 'remote', 'get-url']:
                return subprocess.CompletedProcess(argv, 0, 'https://forge.example/o/r.git\n', '')
            return subprocess.CompletedProcess(argv, 0, 'protocol=https\nhost=forge.example\nusername=u\npassword=p\n', '')
        deliver.prefetch_auth('origin', Path('/x'), run=run).join()
        self.assertEqual(asked[1][0], ['git', 'credential', 'fill'])
        self.assertEqual(asked[1][1]['input'], 'url=https://forge.example/o/r.git\n\n')
        seen = []

        def calls(argv, **options):
            seen.append((argv, options.get('env')))
            return subprocess.CompletedProcess(argv, 0, 'abc\trefs/heads/b\n', '')
        self.assertEqual(deliver.output(calls, ['git', 'ls-remote', 'origin', 'refs/heads/b'], '/x')[1], 'abc\trefs/heads/b')
        env = seen[0][1]
        self.assertEqual((env['GIT_CONFIG_KEY_0'], env['GIT_CONFIG_VALUE_0'], env['GIT_CONFIG_KEY_1']),
                         ('credential.helper', '', 'http.extraHeader'))
        self.assertEqual(env['GIT_CONFIG_VALUE_1'], 'Authorization: Basic dTpw')  # base64 of u:p
        self.assertNotIn('dTpw', ' '.join(seen[0][0]))  # never on the command line
        seen.clear()
        deliver.output(calls, ['git', 'rev-parse', 'HEAD'], '/x')  # a local call: no credentials
        deliver.output(calls, ['git', 'ls-remote', 'other', 'refs/heads/b'], '/x')  # another remote: none asked
        self.assertEqual([env for _, env in seen], [None, None])

    def test_a_call_the_header_did_not_pass_goes_again_the_old_way_and_a_local_remote_asks_nothing(self):
        deliver.FORGE_AUTH['origin'] = {'GIT_CONFIG_COUNT': '1', 'GIT_CONFIG_KEY_0': 'http.extraHeader',
                                        'GIT_CONFIG_VALUE_0': 'Authorization: Basic x'}
        seen = []

        def calls(argv, **options):
            seen.append(options.get('env') is not None)
            return subprocess.CompletedProcess(argv, 0 if options.get('env') is None else 128, 'tip\n', 'denied')
        self.assertEqual(deliver.output(calls, ['git', 'fetch', '--quiet', 'origin', 'b'], '/x'), (0, 'tip', 'denied'))
        self.assertEqual(seen, [True, False])  # with the header refused, the helper's way
        deliver.FORGE_AUTH.clear()
        asked = []

        def run(argv, **options):
            asked.append(argv)
            return subprocess.CompletedProcess(argv, 0, '/tmp/a-local-repo\n', '')
        deliver.prefetch_auth('origin', Path('/x'), run=run).join()
        self.assertEqual((asked, deliver.FORGE_AUTH), ([['git', 'remote', 'get-url', 'origin']], {}))  # no https: no helper


class DeliverTests(unittest.TestCase):
    PR = 7

    def setUp(self):
        self.pause, deliver.FETCH_PAUSE = deliver.FETCH_PAUSE, 0
        # never the box's real lock: the gate running this suite holds it (F23)
        self.enterContext(mock.patch.object(deliver, 'box_gate', lambda out=print, **_: contextlib.nullcontext()))
        # never a real shadow on the infrastructure, even in a session whose environment names the port
        self.enterContext(mock.patch.object(deliver, 'SPAWN', lambda argv, **options: None))

    def tearDown(self):
        deliver.FETCH_PAUSE = self.pause

    def go(self, fake):
        lines = []
        return deliver.deliver(self.PR, run=fake, out=lines.append), lines

    def test_a_green_head_is_merged_with_its_exact_sha_and_the_rate_is_printed(self):
        fake = Fake()
        code, lines = self.go(fake)
        self.assertEqual(code, 0)
        self.assertIn(f'origin pr merge 7 --expect-head 7={HEAD}', fake.calls)
        self.assertTrue(any(call.startswith('git merge --quiet --ff-only origin/') for call in fake.calls))
        self.assertIn('0.0167 PR/s', lines[-1])
        self.assertIn('Merge commit', lines[0])

    def test_the_box_s_green_verdict_is_published_as_the_required_check_before_the_merge(self):
        # EMERGENCY-EXIT-CHECK: the rehearsal of 11/11: the box judged green and the forge refused the merge, `Required
        # status checks are missing`: only the infrastructure's judge published tower/gate
        import gate_status
        order, fake = [], Fake()
        real = fake.__class__.__call__

        def hooks(sha, publisher=None, log=None, mode='infra'):
            return (lambda: order.append('pending'),
                    lambda ok, red, seconds: order.append(('check', sha, mode, ok, red)))

        def run(argv, **options):
            if list(argv[1:3]) == ['pr', 'merge']:
                order.append('merge')
            return real(fake, argv, **options)
        with mock.patch.object(gate_status, 'check_hooks', hooks), mock.patch.object(deliver, 'box_check', REAL_BOX_CHECK):
            code = deliver.deliver(self.PR, run=run, out=lambda line: None)
        self.assertEqual((code, order), (0, [('check', HEAD, 'box', True, []), 'merge']))
        del CHECKS[:]
        red = Fake(gate=1)
        self.assertEqual(self.go(red)[0], 1)
        self.assertEqual(CHECKS, [])  # a red gate publishes nothing and merges nothing
        with mock.patch.object(gate_status, 'check_hooks', lambda *a, **k: None), \
                mock.patch.object(deliver, 'box_check', REAL_BOX_CHECK):
            self.assertEqual(self.go(Fake())[0], 0)  # gate.check_run_enabled off: nothing to publish, the merge as before

    def test_a_pr_whose_base_is_not_the_integration_branch_is_refused_with_the_fix(self):
        for wrong in ('main', None):
            fake = Fake()
            fake.answers['pr view'] = (0, json.dumps({'baseRef': wrong})) if wrong else (1, '')
            code, lines = self.go(fake)
            self.assertEqual(code, 2)
            self.assertFalse(any('gate-dev' in c or 'pr merge' in c or c.startswith('git fetch') for c in fake.calls))
            if wrong:
                self.assertIn(f'Fix: origin pr edit {self.PR} --base {BASE}', lines[0])
                self.assertIn('targets main', lines[0])

    def test_an_unpushed_head_is_refused_before_the_gate(self):
        fake = Fake(pushed='c' * 40)
        code, lines = self.go(fake)
        self.assertEqual(code, 2)
        self.assertFalse(any('gate-dev' in call for call in fake.calls))
        self.assertIn('push first', lines[-1])

    def judged_by_infra(self, verdict=None, cancelled=None, refused=None):
        """delivery.judge infra, with the infrastructure's land answering `verdict` (or refusing)."""
        import gate_infra
        real, landed = deliver.config.get, []
        self.enterContext(mock.patch.object(
            deliver.config, 'get', lambda key, *rest: 'infra' if key == 'delivery.judge' else real(key, *rest)))

        def land(pr, head, base, ref, base_ref, root=None, **_options):
            landed.append((pr, head, ref, base_ref))
            if refused:
                raise refused
            return verdict, cancelled
        self.enterContext(mock.patch.object(gate_infra, 'land', land))
        return landed

    def test_with_the_infrastructure_as_judge_a_green_head_is_landed_by_it_and_the_box_gate_never_runs(self):
        merged = 'c' * len(HEAD)
        landed = self.judged_by_infra({'verdict': 'green', 'seconds': float('42.5'), 'checks': len('seven'),
                                       'from_cache': 1, 'red': [], 'landing': {'result': {'merge_sha': merged}}})
        fake = Fake()
        code, lines = self.go(fake)
        self.assertEqual((code, landed), (0, [(self.PR, HEAD, 'feat/x', BASE)]))
        self.assertIn(f'Merge commit: {merged}', lines)
        self.assertFalse([call for call in fake.calls if 'gate-dev' in call or 'pr merge' in call])

    def test_with_the_infrastructure_as_judge_a_red_head_merges_nothing(self):
        self.judged_by_infra({'verdict': 'red', 'red': ['stage:schema compat'], 'landing': {'state': 'cancelled'}})
        fake = Fake()
        code, lines = self.go(fake)
        self.assertEqual(code, 1)
        self.assertTrue(any('red (stage:schema compat); nothing merged' in line for line in lines))
        self.assertFalse([call for call in fake.calls if 'pr merge' in call])

    def test_with_the_infrastructure_as_judge_a_late_verdict_cancels_the_landing(self):
        self.judged_by_infra({'verdict': 'late', 'red': [], 'landing': {'id': 'the-landing'}}, cancelled={'ok': True})
        code, lines = self.go(Fake())
        self.assertEqual(code, 1)
        self.assertTrue(any('landing was cancelled' in line for line in lines))

    def test_with_the_infrastructure_as_judge_and_no_port_nothing_is_gated_or_merged(self):
        self.judged_by_infra(refused=RuntimeError('delivery.judge is infra but the port is not configured'))
        fake = Fake()
        code, lines = self.go(fake)
        self.assertEqual(code, len(('refused', 'before any merge')))
        self.assertTrue(any('port is not configured' in line for line in lines))
        self.assertFalse([call for call in fake.calls if 'gate-dev' in call or 'pr merge' in call])

    def test_the_shadow_starts_beside_the_gate_only_when_the_port_is_configured(self):
        started = []
        self.enterContext(mock.patch.object(deliver, 'SPAWN', lambda argv, **options: started.append((argv, options))))
        bare = {name: value for name, value in os.environ.items() if not name.startswith('TOWER_PORT_')}
        with mock.patch.dict(os.environ, bare, clear=True):
            code, _ = self.go(Fake())
        self.assertEqual((code, started), (0, []))
        with tempfile.TemporaryDirectory() as cache, mock.patch.dict(os.environ, dict(PORT, XDG_CACHE_HOME=cache)):
            code, lines = self.go(Fake())
        (argv, options), = started
        self.assertEqual((code, argv[1:], options['start_new_session']),
                         (0, ['shadow', '--pr', str(self.PR), '--head', HEAD], True))
        self.assertTrue(argv[0].endswith('scripts/gate-infra'))
        self.assertTrue(any('in shadow' in line for line in lines))

    def test_a_shadow_that_does_not_start_never_stops_the_delivery(self):
        def refuse(argv, **_options):
            raise OSError('no such file')
        self.enterContext(mock.patch.object(deliver, 'SPAWN', refuse))
        with tempfile.TemporaryDirectory() as cache, mock.patch.dict(os.environ, dict(PORT, XDG_CACHE_HOME=cache)):
            code, lines = self.go(Fake())
        self.assertEqual(code, 0)
        self.assertTrue(any('did not start' in line for line in lines))

    def test_the_box_keeps_its_verdict_beside_the_shadows_for_the_head_both_judge(self):
        # GATE-INFRA 4 (P5 F3): scripts/medir pairs box-<pr>-<head>.json with the shadow's pr-<pr>-<head>.json
        prefix = deliver.config.get('gate.class_line_prefix')
        with tempfile.TemporaryDirectory() as cache, mock.patch.dict(os.environ, dict(PORT, XDG_CACHE_HOME=cache)):
            code, _ = self.go(Fake())
            kept = Path(cache) / 'the-tower' / 'gate-infra' / f'box-{self.PR}-{HEAD}.json'
            green = json.loads(kept.read_text())
            fake = Fake(gate=1)
            fake.answers['gate-dev'] = (1, '\n'.join([f'{prefix} lint\tcode', 'GATE: FAILED']))
            self.go(fake)
            red = json.loads(kept.read_text())
        self.assertEqual((code, green['pr'], green['head'], green['verdict'], green['red']),
                         (0, str(self.PR), HEAD, 'green', []))
        self.assertGreaterEqual(green['seconds'], 0)  # MEDIR 5: the gate's own time, beside the shadow's
        self.assertEqual((red['verdict'], red['red']), ('red', ['lint']))
        bare = {name: value for name, value in os.environ.items() if not name.startswith('TOWER_PORT_')}
        with tempfile.TemporaryDirectory() as cache, mock.patch.dict(os.environ, dict(bare, XDG_CACHE_HOME=cache),
                                                                       clear=True):
            self.go(Fake())
            self.assertFalse((Path(cache) / 'the-tower' / 'gate-infra').exists())  # no shadow, nothing to pair

    def test_a_red_gate_merges_nothing(self):
        fake = Fake(gate=1)
        code, lines = self.go(fake)
        self.assertEqual(code, 1)
        self.assertFalse(any('pr merge' in call for call in fake.calls))
        self.assertIn('nothing merged', lines[-1])

    def red_gate(self, *lines):
        fake = Fake(gate=1)
        fake.answers['gate-dev'] = (1, '\n'.join([*lines, 'GATE: FAILED']))
        return self.go(fake)

    def test_a_red_gate_shows_the_last_class_of_each_red_stage(self):
        prefix = deliver.config.get('gate.class_line_prefix')
        code, lines = self.red_gate(f'{prefix} script tests\tcode', f'{prefix} lint\tenv', f'{prefix} script tests\tbase')
        self.assertEqual(code, 1)
        self.assertIn(f'deliver: class base (script tests): {deliver.gate_classify.ACTIONS["base"]}', lines)
        self.assertIn(f'deliver: class env (lint): {deliver.gate_classify.ACTIONS["env"]}', lines)
        self.assertEqual(lines[-1], f'deliver: the gate failed on {HEAD[:12]}; nothing merged')

    def test_a_gate_red_only_on_the_base_keeps_the_pr_queued(self):
        prefix = deliver.config.get('gate.class_line_prefix')
        code, lines = self.red_gate(f'{prefix} script tests\tcode', f'{prefix} script tests\tbase')
        self.assertEqual(code, 1)
        self.assertEqual(lines[-1], "deliver: #7 stays queued: its red is the base's, not its own (F73); nothing merged")

    def test_a_gate_with_no_class_line_is_not_base(self):
        self.assertFalse(deliver.base_red('GATE: FAILED'))
        self.assertEqual(deliver.gate_classify.classes('GATE: FAILED'), {})

    def test_a_refused_merge_stops_before_the_base_moves(self):
        fake = Fake(merge=1)
        code, _lines = self.go(fake)
        self.assertEqual(code, 1)
        self.assertFalse(any('checkout' in call for call in fake.calls))

    def test_a_refused_merge_prints_what_origin_said_on_stdout_and_stderr(self):
        fake = Fake()
        fake.sequences = {'pr merge': [(1, 'merge blocked: required check pending', 'error: not mergeable')]}
        code, lines = self.go(fake)
        self.assertEqual(code, 1)
        self.assertIn('error: not mergeable\nmerge blocked: required check pending', lines[-1])

    def test_a_silent_refusal_prints_its_exit_code_and_the_conflicting_paths(self):
        fake = Fake()
        fake.sequences = {'pr merge': [(1, '', '')],
                          'merge-tree --write-tree --name-only': [(1, TREE + '\nscripts/a.py\ndocs/b.md\n\nCONFLICT ...')]}
        code, lines = self.go(fake)
        self.assertEqual(code, 1)
        self.assertIn(f'git merge-tree --write-tree --name-only {HEAD} origin/{BASE}', fake.calls)
        self.assertTrue(lines[-1].endswith(' refused: exit 1, no output; conflicting paths: scripts/a.py, docs/b.md'), lines)


    def test_a_branch_is_delivered_from_its_own_worktree_and_the_checkout_is_left_alone(self):
        fake, lines = Fake(), []
        with tempfile.TemporaryDirectory() as directory:
            code = deliver.deliver(7, root=Path(directory), run=fake, out=lines.append, branch='feat/x')
            tree = str(Path(directory) / '.gate' / 'deliver' / 'pr-7')
        self.assertEqual(code, 0, lines)
        self.assertIn(f'git worktree add --quiet --detach {tree} {HEAD}', fake.calls)
        self.assertIn(('scripts/gate-dev --pr 7', tree), fake.cwds)
        self.assertFalse(any(call.startswith('git checkout') for call in fake.calls))
        self.assertFalse(any(call.startswith(('git branch', 'git merge --quiet --ff-only')) for call in fake.calls))
        self.assertEqual(fake.calls[-1], f'git worktree remove --force {tree}')

    def test_a_failed_branch_delivery_keeps_its_worktree_for_the_reports(self):
        fake, lines = Fake(gate=1), []
        with tempfile.TemporaryDirectory() as directory:
            code = deliver.deliver(7, root=Path(directory), run=fake, out=lines.append, branch='feat/x')
            tree = str(Path(directory) / '.gate' / 'deliver' / 'pr-7')
        self.assertEqual(code, 1)
        self.assertEqual([call for call in fake.calls if 'worktree remove' in call], [f'git worktree remove --force {tree}'])
        self.assertIn(f'deliver: kept {tree} for its reports', lines)

    def branch_run(self, fake):
        lines = []
        with tempfile.TemporaryDirectory() as directory:
            code = deliver.deliver(7, root=Path(directory), run=fake, out=lines.append, branch='feat/x')
        return code, lines

    def test_with_base_fetches_the_base_only_when_the_shared_git_lacks_its_tip(self):
        # BASE-TIP-BY-LS-REMOTE: another lane, the push or the pre-gate fetched origin/<base> seconds ago (2.2 s, #654)
        tip = 'e' * 40
        def fetches(have):
            fake = Fake()
            fake.answers[f'ls-remote origin refs/heads/{BASE}'] = (0, f'{tip}\trefs/heads/{BASE}')
            fake.answers[f'rev-parse --verify --quiet origin/{BASE}'] = (0, have)
            fake.answers['merge-base --is-ancestor'] = (0, '')  # the base is already an ancestor: nothing to merge
            head, code = deliver._with_base('/tree', 'feat/x', HEAD, 'origin', BASE, fake, lambda *_: None)
            return (head, code), [c for c in fake.calls if c.startswith(f'git fetch --quiet origin {BASE}')]
        answer, fetched = fetches(tip)  # the shared .git already at the tip
        self.assertEqual((answer, fetched), ((HEAD, 0), []))
        answer, fetched = fetches('9' * 40)  # a stale local ref: the fetch runs
        self.assertEqual((answer, len(fetched)), ((HEAD, 0), 1))

    def test_a_head_behind_the_base_gets_the_base_merged_and_pushed_before_the_gate(self):
        fake = Fake()
        merged = 'd' * 40
        # the shared .git has no origin/<base> yet: the fetch runs (the default fake answers ls-remote with feat/x's line)
        fake.sequences = {'merge-base --is-ancestor': [(1, '')], 'rev-parse HEAD': [(0, merged)]}
        code, lines = self.branch_run(fake)
        self.assertEqual(code, 0, lines)
        merge = next(i for i, call in enumerate(fake.calls) if call.startswith('git merge --quiet --no-edit'))
        push = next(i for i, call in enumerate(fake.calls) if call.startswith('git push --quiet --no-verify origin HEAD:refs/heads/feat/x'))
        gate = next(i for i, call in enumerate(fake.calls) if 'gate-dev' in call)
        self.assertLess(merge, push)
        self.assertLess(push, gate)
        self.assertIn(f'origin pr merge 7 --expect-head 7={merged}', fake.calls)

    def test_a_base_that_moved_during_the_gate_is_judged_again(self):
        fake = Fake()
        base = 'origin/' + deliver.config.get('train.base_branch')
        fake.sequences = {f'rev-parse {base}': [(0, 'e' * 40), (0, 'f' * 40), (0, 'f' * 40), (0, 'f' * 40)]}
        code, lines = self.branch_run(fake)
        self.assertEqual(code, 0, lines)
        self.assertEqual(sum(1 for call in fake.calls if 'gate-dev' in call), 2)
        self.assertTrue(any('judging #7 again' in line for line in lines))

    def test_a_base_that_does_not_merge_is_aborted_and_nothing_lands(self):
        fake = Fake()
        fake.sequences = {'merge-base --is-ancestor': [(1, '')], 'merge --quiet --no-edit': [(1, 'CONFLICT')]}
        code, lines = self.branch_run(fake)
        self.assertEqual(code, 1)
        self.assertIn('git merge --abort', fake.calls)
        self.assertFalse(any('gate-dev' in call or 'pr merge' in call for call in fake.calls))

    def test_a_base_that_does_not_merge_names_its_conflicting_paths(self):
        fake = Fake()
        fake.sequences = {'merge-base --is-ancestor': [(1, '')], 'merge --quiet --no-edit': [(1, '', '')],
                          'diff --name-only --diff-filter=U': [(0, 'scripts/lib/deliver.py\nfila.md')]}
        code, lines = self.branch_run(fake)
        self.assertEqual(code, 1)
        self.assertLess(fake.calls.index('git diff --name-only --diff-filter=U'), fake.calls.index('git merge --abort'))
        said = next(line for line in lines if 'does not merge' in line)
        self.assertIn(f'feat/x does not merge with origin/{BASE}: conflicting paths: scripts/lib/deliver.py, fila.md;', said)

    def test_without_an_unmerged_index_the_conflicts_come_from_merge_tree(self):
        fake = Fake()
        fake.sequences = {'merge-base --is-ancestor': [(1, '')], 'merge --quiet --no-edit': [(1, '', '')],
                          'merge-tree --write-tree --name-only HEAD': [(1, TREE + '\nREADME.md\n\nAuto-merging')]}
        code, lines = self.branch_run(fake)
        self.assertEqual(code, 1)
        self.assertIn('conflicting paths: README.md;', next(line for line in lines if 'does not merge' in line))

    def test_merge_tree_reads_no_paths_from_a_clean_merge(self):
        clean = Fake()
        clean.sequences = {'merge-tree': [(0, TREE)]}
        self.assertEqual(deliver.conflicts(clean, '.', 'a', 'b'), [])

    def test_a_refused_fetch_of_the_branch_stops_before_the_gate(self):
        fake = Fake()
        fake.sequences = {'fetch --quiet origin feat/x': [(128, '', "fatal: couldn't find remote ref feat/x")]}
        code, lines = self.branch_run(fake)
        self.assertEqual(code, 2)
        self.assertFalse(any(key in call for call in fake.calls for key in ('rev-parse', 'worktree add', 'gate-dev')))
        self.assertIn('nothing gated or merged', lines[-1])

    def test_a_fetch_that_loses_the_ref_lock_race_is_tried_again(self):
        fake = Fake()
        fake.sequences = {f'fetch --quiet origin {BASE}': [(1, '', LOCKED), (0, '')]}
        code, lines = self.branch_run(fake)
        self.assertEqual(code, 0, lines)
        fetches = [call for call in fake.calls if call == f'git fetch --quiet origin {BASE}']
        self.assertEqual(len(fetches), 4)  # the lost race and its retry before the gate, after the gate, after the merge

    def test_a_refused_fetch_of_the_base_before_the_gate_merges_nothing(self):
        fake = Fake()
        fake.sequences = {f'fetch --quiet origin {BASE}': [(1, '', LOCKED)] * deliver.FETCH_TRIES}
        code, lines = self.branch_run(fake)
        self.assertEqual(code, 1)
        self.assertFalse(any('merge-base' in call or 'gate-dev' in call or 'pr merge' in call for call in fake.calls))
        self.assertIn('nothing merged', lines[-2])

    def test_a_refused_fetch_of_the_base_after_the_gate_merges_nothing(self):
        fake = Fake()
        fake.sequences = {f'fetch --quiet origin {BASE}': [(0, ''), (128, '', 'fatal: unable to access origin')]}
        code, lines = self.branch_run(fake)
        self.assertEqual(code, 1)
        self.assertEqual(sum(1 for call in fake.calls if 'gate-dev' in call), 1)
        self.assertFalse(any('pr merge' in call for call in fake.calls))
        self.assertIn('after the gate failed', lines[-2])

    def test_a_merge_whose_refresh_fetch_fails_succeeds_with_a_warning(self):
        fake = Fake()
        fake.sequences = {f'fetch --quiet origin {BASE}': [(1, '', LOCKED)] * deliver.FETCH_TRIES}
        code, lines = self.go(fake)
        self.assertEqual(code, 0, lines)
        self.assertEqual(sum(1 for call in fake.calls if 'fetch' in call), deliver.FETCH_TRIES)
        self.assertFalse(any(call.startswith(('git checkout', 'git merge')) for call in fake.calls))
        self.assertTrue(any(line.startswith('deliver: warning: merged, but fetching') for line in lines))
        self.assertIn('0.0167 PR/s', lines[-1])

    def test_a_merged_branch_whose_refresh_fetch_fails_succeeds_with_a_warning(self):
        fake = Fake()
        fake.sequences = {f'fetch --quiet origin {BASE}': [(0, ''), (0, '')] + [(1, '', LOCKED)] * deliver.FETCH_TRIES}
        code, lines = self.branch_run(fake)
        self.assertEqual(code, 0, lines)
        self.assertTrue(any('warning: merged' in line and 'cannot lock ref' in line for line in lines))

    def test_the_body_comes_from_the_commits_plan_trailers_and_prose(self):
        title, body = deliver.pr_body([('a: first', 'Why.\n\nPlan: 1\n\nCo-Authored-By: x <y>'), ('b: second', 'Plan: 2'),
                                       ('c: more of one', 'Plan: 1')], 'made by a bot')
        self.assertEqual(title, 'a: first')
        self.assertIn('Why.\n\n## Plano de commits\n- [ ] 1. a: first\n- [ ] 2. b: second\n', body)
        self.assertNotIn('Co-Authored-By', body)
        self.assertIn(deliver.FIT_REVIEW, body)
        self.assertTrue(body.rstrip().endswith('made by a bot'))

    def test_open_returns_the_open_pr_or_opens_one_from_the_commits(self):
        fake = Fake()
        fake.answers['pr list'] = (0, '#41  open  a title  feat/x')
        self.assertEqual(deliver.open_pr('feat/x', run=fake, out=lambda line: None), 41)
        self.assertFalse(any('pr create' in call for call in fake.calls))
        fake = Fake()
        fake.answers['pr list'] = (0, 'No matching changes')
        fake.answers['git log --reverse'] = (0, 'a: first\x1fWhy.\n\nPlan: 1\n\x1e')
        fake.answers['pr create'] = (0, 'Created pull request #42 in o/r.')
        self.assertEqual(deliver.open_pr('feat/x', run=fake, out=lambda line: None), 42)
        create = next(call for call in fake.calls if 'pr create' in call)
        self.assertIn('-t a: first', create)
        self.assertIn('-H feat/x', create)

    def test_a_branch_without_open_finds_its_pr_and_never_opens_one(self):
        fake, lines = Fake(), []
        fake.answers['pr list'] = (0, '#41  open  a title  feat/x')
        self.assertEqual(deliver.open_pr('feat/x', run=fake, out=lines.append, create=False), 41)
        fake = Fake()
        fake.answers['pr list'] = (0, 'No matching changes')
        self.assertIsNone(deliver.open_pr('feat/x', run=fake, out=lines.append, create=False))
        self.assertFalse(any('pr create' in call or 'git log' in call for call in fake.calls))
        self.assertIn('has no open PR', lines[-1])

    def test_a_base_held_by_another_worktree_is_not_checked_out_and_warns_nothing(self):
        fake = Fake()
        fake.answers['worktree list'] = (0, f'worktree /elsewhere/the-tower\nHEAD {HEAD}\nbranch refs/heads/{BASE}\n')
        fake.answers[f'checkout --quiet {BASE}'] = (1, '')
        code, lines = self.go(fake)
        self.assertEqual(code, 0, lines)
        self.assertFalse(any(call.startswith(('git checkout', 'git merge --quiet')) for call in fake.calls))
        self.assertFalse(any('warning' in line for line in lines))

    def test_open_finds_a_draft_pr_too(self):
        fake = Fake()
        fake.sequences['pr list'] = [(0, 'No matching changes'), (0, '#43  draft  a title  feat/x')]
        self.assertEqual(deliver.open_pr('feat/x', run=fake, out=lambda line: None), 43)
        self.assertTrue(any('-s draft' in call for call in fake.calls))
        self.assertFalse(any('pr create' in call for call in fake.calls))

    def test_open_refuses_a_body_the_structure_check_fails_and_opens_nothing(self):
        fake = Fake()
        fake.answers['pr list'] = (0, 'No matching changes')
        fake.answers['git log --reverse'] = (0, 'a: first\x1fWhy.\n\nPlan: 1\n\x1e')
        fake.answers['structure-check'] = (1, 'PASS other\nFAIL body: no plan\nWARN x')
        lines = []
        self.assertIsNone(deliver.open_pr('feat/x', run=fake, out=lines.append))
        self.assertFalse(any('pr create' in call for call in fake.calls))
        self.assertIn('FAIL body: no plan', lines)
        check = next(call for call in fake.calls if 'structure-check' in call)
        self.assertIn('--pr-body', check)


TRAIN_RUN = ['scripts/train', 'run']


class BoxBatch(unittest.TestCase):
    """F36: with delivery.batch auto a branch delivery waits in the box queue and leads or follows a batch."""

    def setUp(self):
        self.pause, deliver.FETCH_PAUSE = deliver.FETCH_PAUSE, 0
        self.addCleanup(setattr, deliver, 'FETCH_PAUSE', self.pause)
        self.queue = Path(tempfile.mkdtemp())
        self.home = Path(tempfile.mkdtemp())
        self.rows = []

        @contextlib.contextmanager
        def gate(out=print, **_kwargs):
            row = {}
            yield row
            self.rows.append(row)

        self.enterContext(mock.patch.object(deliver, 'box_gate', gate))
        self.enterContext(mock.patch.object(deliver.box_queue, 'folder', lambda directory=None: self.queue))
        self.mode = 'auto'
        get = deliver.config.get
        self.enterContext(mock.patch.object(deliver.config, 'get',
                                            lambda key, *a, **k: self.mode if key == 'delivery.batch' else get(key, *a, **k)))
        self.reading = {'ready': True, 'why': None}
        self.enterContext(mock.patch.object(deliver, 'batch_reading', lambda: self.reading))

    MINE = DeliverTests.PR  # this delivery's PR; OTHER is the delivery waiting beside it
    OTHER = MINE + 1
    OTHER_HEAD = 'c' * len(HEAD)

    def go(self, fake):
        lines = []
        return deliver.deliver(self.MINE, root=self.home, run=fake, out=lines.append, branch='feat/x'), lines

    def other(self):
        """Another live delivery waiting (this test process stands for it)."""
        deliver.box_queue.enqueue(self.OTHER, f'feat/{self.OTHER}', self.OTHER_HEAD, pid=deliver.os.getpid(), at=0)

    def leader(self, fake, outcome='merged', resolve=None):
        """The train run --box answer: it writes the results of `resolve` and prints its batch line."""
        def train(argv, cwd=None, **kwargs):
            fake.calls.append(' '.join(argv))
            fake.envs.append(kwargs.get('env') or {})
            for pr in resolve:
                head = HEAD if pr == self.MINE else self.OTHER_HEAD
                deliver.box_queue.write_result(pr, head, outcome, batch_id='b-1', merge_sha='m' * len(HEAD), detail='unit tests')
            batch = {'id': 'b-1', 'prs': [self.MINE, self.OTHER], 'runs': 1,
                     'merged': list(resolve) if outcome == 'merged' else []}
            return subprocess.CompletedProcess(argv, 0, 'box: batch ' + json.dumps(batch) + '\n', '')
        return train

    def fake(self, outcome='merged', resolve=None):
        resolve = (self.MINE, self.OTHER) if resolve is None else resolve
        fake = Fake()
        fake.envs = []
        fake.answers = dict(fake.answers)
        original = fake.__call__
        train = self.leader(fake, outcome, resolve)
        return fake, (lambda argv, cwd=None, **kwargs: train(argv, cwd, **kwargs) if argv[:len(TRAIN_RUN)] == TRAIN_RUN
                      else original(argv, cwd, **kwargs))

    def test_off_writes_no_entry_and_takes_the_single_path(self):
        self.mode = 'off'
        fake, run = self.fake()
        self.other()
        code, _lines = self.go(run)
        self.assertEqual(code, 0)
        self.assertIn(f'scripts/gate-dev --pr {self.MINE}', fake.calls)
        self.assertFalse(any(call.startswith('scripts/train') for call in fake.calls))

    def test_two_waiting_lead_one_batch_and_its_result_is_the_answer(self):
        fake, run = self.fake()
        self.other()
        code, lines = self.go(run)
        self.assertEqual(code, 0, lines)
        self.assertIn('scripts/train run --box', fake.calls)
        self.assertNotIn(f'scripts/gate-dev --pr {self.MINE}', fake.calls, 'the batch was the gate')
        self.assertTrue(fake.envs[0].get(deliver.box_queue.HELD_ENV), 'the leader passes the held lock down')
        self.assertEqual(self.rows[-1]['batch']['id'], 'b-1', 'the batch goes to the lock log')
        self.assertEqual([row['pr'] for row in deliver.box_queue.entries()], [self.OTHER], 'its own entry leaves')

    def test_a_result_left_by_an_earlier_leader_answers_without_a_gate(self):
        fake, run = self.fake()
        deliver.box_queue.write_result(self.MINE, HEAD, 'ejected', batch_id='b-0', detail='unit tests')
        code, lines = self.go(run)
        self.assertEqual(code, 1)
        self.assertFalse(any(call.startswith(('scripts/gate-dev', 'scripts/train')) for call in fake.calls))
        self.assertTrue(any('ejected in batch b-0' in line for line in lines), lines)

    def test_one_waiting_takes_the_single_path(self):
        fake, run = self.fake()
        code, _lines = self.go(run)
        self.assertEqual(code, 0)
        self.assertIn(f'scripts/gate-dev --pr {self.MINE}', fake.calls)
        self.assertFalse(any(call.startswith('scripts/train') for call in fake.calls))

    def test_a_reading_not_ready_takes_the_single_path_with_others_waiting(self):
        self.reading = {'ready': False, 'why': 'box busy 48% < 70%'}
        fake, run = self.fake()
        self.other()
        code, lines = self.go(run)
        self.assertEqual(code, 0, lines)
        self.assertIn(f'scripts/gate-dev --pr {self.MINE}', fake.calls)
        self.assertFalse(any(call.startswith('scripts/train') for call in fake.calls), 'F64: no batch while not ready')
        self.assertTrue(any('the batch is not ready (box busy 48% < 70%)' in line for line in lines), lines)

    def test_a_reading_that_fails_is_not_ready(self):
        self.enterContext(mock.patch.dict(sys.modules, {'flow_metrics': mock.Mock(
            measured_batch_reading=mock.Mock(side_effect=OSError('no lock log')))}))
        reading = DELIVER_BATCH_READING()
        self.assertFalse(reading['ready'])
        self.assertIn('no lock log', reading['why'])

    def test_a_batch_that_did_not_resolve_the_leader_leaves_it_the_single_path(self):
        fake, run = self.fake(resolve=(self.OTHER,))
        self.other()
        code, lines = self.go(run)
        self.assertEqual(code, 0, lines)
        self.assertIn('scripts/train run --box', fake.calls)
        self.assertIn(f'scripts/gate-dev --pr {self.MINE}', fake.calls)



class Wrapper(unittest.TestCase):
    """scripts/deliver --branch: the wrapper's fetch of the base is tried again on a lost ref lock race (F64 follow-up)."""

    def wrapper(self, fetch_errors):
        top = Path(tempfile.mkdtemp())
        (top / 'scripts').mkdir()
        (top / 'scripts' / 'deliver').write_text((ROOT / 'scripts' / 'deliver').read_text())
        (top / 'scripts' / 'lib').symlink_to(ROOT / 'scripts' / 'lib')
        bin_dir = top / 'bin'
        bin_dir.mkdir()
        (top / 'errors').write_text(''.join(line + '\n' for line in fetch_errors))
        git = bin_dir / 'git'
        git.write_text(f"""#!/usr/bin/env bash
echo "$*" >> {top}/calls
if [[ " $* " == *" fetch "* ]]; then
  n=$(grep -c ' fetch ' {top}/calls)
  err="$(sed -n "${{n}}p" {top}/errors)"
  [[ -z "$err" ]] && exit 0
  echo "$err" >&2; exit 1
fi
exit 7
""")
        git.chmod(0o755)
        env = dict(deliver.os.environ, PATH=f'{bin_dir}:{deliver.os.environ["PATH"]}')
        env.pop('DELIVER_FROM_BASE', None)
        done = subprocess.run(['bash', str(top / 'scripts' / 'deliver'), '--pr', '7', '--branch', 'feat/x'],
                              capture_output=True, text=True, env=env, timeout=60)
        fetches = [line for line in (top / 'calls').read_text().splitlines() if ' fetch ' in f' {line} ']
        return done, fetches

    def test_a_lost_lock_race_is_fetched_again(self):
        done, fetches = self.wrapper([LOCKED, LOCKED])
        self.assertEqual(len(fetches), 3, done.stderr)
        self.assertEqual(done.returncode, 7, 'past the fetch it reaches the base worktree step')

    def test_another_failure_stops_at_once(self):
        done, fetches = self.wrapper(['fatal: could not read from remote repository'])
        self.assertEqual((len(fetches), done.returncode), (1, 1))
        self.assertIn('could not read', done.stderr)


class Switches(unittest.TestCase):
    """GATE-INFRA 12: a branch delivery runs the base's deliver from its worktree, and reads the box's switches from the
    checkout that invoked it (on 04/11 delivery.judge infra, set in the checkout, never reached the base worktree)."""

    def test_the_wrapper_names_the_invoking_checkout_to_the_bases_deliver(self):
        self.assertIn('DELIVER_FROM_BASE=1 DELIVER_CONFIG_ROOT="$here" exec "$tree/scripts/deliver" "$@"',
                      (ROOT / 'scripts' / 'deliver').read_text())

    def test_the_invoking_checkouts_store_decides_the_judge_and_without_it_the_process_own(self):
        before = deliver.config.get('delivery.judge')  # the module's own store holds box (setUpModule)
        self.assertEqual(before, 'box')
        with tempfile.TemporaryDirectory() as checkout:  # a checkout whose store never set it: the registry default (infra)
            with deliver.switches({'DELIVER_CONFIG_ROOT': checkout}):
                self.assertEqual(deliver.config.get('delivery.judge'), 'infra')
            with deliver.switches({}):
                self.assertEqual(deliver.config.get('delivery.judge'), before)
        self.assertEqual(deliver.config.get('delivery.judge'), before)


class BoxGate(unittest.TestCase):
    """VAZÃO F23: one gate at a time on the box; a second delivery waits for the lock and says so."""

    def setUp(self):
        self.lock = Path(tempfile.mkdtemp()) / 'sub' / 'gate.lock'
        self.lock.parent.mkdir()  # held() opens it before the holder thread may have created it

    def held(self):
        with open(self.lock, 'a') as other:
            try:
                fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return True
            fcntl.flock(other, fcntl.LOCK_UN)
            return False

    def test_the_gate_runs_inside_the_lock_and_releases_it(self):
        self.lock.parent.rmdir()  # box_gate creates the folder itself
        lines = []
        with deliver.box_gate(lines.append, self.lock):
            self.assertTrue(self.held())
        self.assertFalse(self.held())
        self.assertEqual(lines, [])  # no wait, nothing printed

    def test_a_second_delivery_waits_for_the_first_and_says_how_long(self):
        lines, release = [], threading.Event()

        def first():
            with deliver.box_gate(lambda line: None, self.lock):
                release.wait(5)

        holder = threading.Thread(target=first)
        holder.start()
        while not self.held():
            pass
        threading.Timer(0.2, release.set).start()
        with deliver.box_gate(lines.append, self.lock):
            self.assertTrue(release.is_set())
        holder.join()
        self.assertIn('waiting for it', lines[0])
        self.assertRegex(lines[1], r'the box is free after \d+ s')

    def test_a_long_wait_prints_progress_and_the_place_in_the_queue(self):
        """F132: a line when the wait starts (with the place) and one per `every` s, so the log is never silent."""
        lines, release = [], threading.Event()

        def first():
            with deliver.box_gate(lambda line: None, self.lock):
                release.wait(5)

        holder = threading.Thread(target=first)
        holder.start()
        while not self.held():
            pass
        threading.Timer(0.4, release.set).start()
        with mock.patch.object(deliver.box_queue, 'position', return_value=(2, 3)):
            with deliver.box_gate(lines.append, self.lock, pr=9, every=0.1, poll=0.02):
                pass
        holder.join()
        self.assertIn('place 2 of 3 in the box queue', lines[0])
        progress = [line for line in lines if 'still waiting' in line]
        self.assertTrue(progress)
        self.assertIn('place 2 of 3', progress[0])
        self.assertRegex(lines[-1], r'the box is free after \d+ s')

    def test_the_place_in_the_queue_counts_live_entries_oldest_first(self):
        folder = self.lock.parent / 'q'
        box_queue = deliver.box_queue
        box_queue.enqueue(5, 'a', 'h', folder, pid=os.getpid(), at=1)
        box_queue.enqueue(6, 'b', 'h', folder, pid=os.getpid(), at=2)
        self.assertEqual(box_queue.position(6, folder), (2, 2))
        self.assertIsNone(box_queue.position(7, folder))

    def test_the_pr_rate_is_read_after_the_lock_is_released(self):
        events = []

        @contextlib.contextmanager
        def lock(out=print, **_):
            events.append('taken')
            yield
            events.append('released')

        fake = Fake()
        original = fake.__call__

        def run(argv, **kwargs):
            if 'flow-metrics' in ' '.join(argv):
                events.append('metrics')
            return original(argv, **kwargs)

        with mock.patch.object(deliver, 'box_gate', lock):
            self.assertEqual(deliver.deliver(7, root=Path(tempfile.mkdtemp()), run=run, out=lambda line: None), 0)
        self.assertEqual(events, ['taken', 'released', 'metrics'])

    def test_the_ledger_is_refreshed_after_the_lock_and_a_failure_is_a_warning(self):
        events = []

        @contextlib.contextmanager
        def lock(out=print, **_):
            events.append('taken')
            yield
            events.append('released')

        for code, warned in ((0, False), (1, True)):
            events.clear()
            fake, lines = Fake(), []
            fake.answers['usage --lanes'] = (code, 'no subagents directory')
            original = fake.__call__

            def run(argv, **kwargs):
                if 'scripts/usage' in argv:
                    events.append('ledger')
                return original(argv, **kwargs)

            with mock.patch.object(deliver, 'box_gate', lock):
                self.assertEqual(deliver.deliver(7, root=Path(tempfile.mkdtemp()), run=run, out=lines.append), 0)
            self.assertEqual(events, ['taken', 'released', 'ledger'])
            self.assertIn('scripts/usage --lanes --write', fake.calls)
            self.assertEqual(any('ledger refresh' in line and 'warning' in line for line in lines), warned)

    def test_a_refused_merge_refreshes_no_ledger(self):
        fake = Fake(merge=1)
        with mock.patch.object(deliver, 'box_gate', lambda out=print, **_: contextlib.nullcontext()):
            self.assertEqual(deliver.deliver(7, root=Path(tempfile.mkdtemp()), run=fake, out=lambda line: None), 1)
        self.assertFalse(any('scripts/usage' in call for call in fake.calls))

    def test_a_batch_joins_its_line_of_the_log(self):
        log = self.lock.parent / 'log.jsonl'
        with deliver.box_gate(lambda line: None, self.lock, pr=BoxBatch.MINE, log=str(log)) as row:
            row['batch'] = {'id': 'b-1', 'runs': 1}
        line = json.loads(log.read_text())
        self.assertEqual((line['pr'], line['batch']['id']), (BoxBatch.MINE, 'b-1'))

    def test_each_hold_of_the_lock_is_logged_with_its_wait(self):
        log = self.lock.parent / 'lock.jsonl'
        ticks = iter([10.0, 25.0])
        spent = iter([2.0, 40.46])
        with deliver.box_gate(lambda line: None, self.lock, clock=lambda: next(ticks), pr=7, log=str(log), wall=lambda: 1000.0,
                              cpu=lambda: next(spent), vcpus=lambda: 4):
            pass
        row = json.loads(log.read_text())
        self.assertEqual(row, {'pr': 7, 'waited_s': 0.0, 'held_s': 15.0, 'at': 1000, 'cpu_s': 38.5, 'vcpus': 4})

    def test_the_cpu_of_the_holds_children_joins_its_line(self):
        """F71: the CPU the hold's children spent (getrusage(RUSAGE_CHILDREN) user + system, read before and after) is
        the line's cpu_s. The counters, the clock and the CPUs are faked: real CPU and wall time move under a parallel
        test-suite and made this test flaky (DX)."""
        log = self.lock.parent / 'lock.jsonl'
        usage = iter([mock.Mock(ru_utime=10.0, ru_stime=2.0), mock.Mock(ru_utime=11.5, ru_stime=2.5)])
        ticks = iter([100.0, 103.0])
        with mock.patch.object(deliver.resource, 'getrusage', side_effect=lambda who: next(usage)) as getrusage:
            with deliver.box_gate(lambda line: None, self.lock, pr=7, log=str(log), clock=lambda: next(ticks),
                                  wall=lambda: 0.0, vcpus=lambda: 2):
                pass
        getrusage.assert_called_with(deliver.resource.RUSAGE_CHILDREN)
        row = json.loads(log.read_text())
        self.assertEqual((row['cpu_s'], row['held_s'], row['vcpus']), (2.0, 3.0, 2))

    def test_a_hold_without_a_pr_writes_no_line(self):
        log = self.lock.parent / 'lock.jsonl'
        with deliver.box_gate(lambda line: None, self.lock, log=str(log)):
            pass
        self.assertFalse(log.exists())

    def test_the_lock_spans_the_base_merge_the_gate_and_the_merge(self):
        events = []

        @contextlib.contextmanager
        def lock(out=print, **_):
            events.append('taken')
            yield
            events.append('released')

        fake = Fake()
        original = fake.__call__

        def run(argv, **kwargs):
            line = ' '.join(argv)
            if 'gate-dev' in line or 'pr merge' in line or 'merge --no-edit' in line:
                events.append(('gate' if 'gate-dev' in line else 'merge') + (' locked' if events.count('taken') > events.count('released') else ' free'))
            return original(argv, **kwargs)

        with mock.patch.object(deliver, 'box_gate', lock):
            self.assertEqual(deliver.deliver(7, root=Path(tempfile.mkdtemp()), run=run, out=lambda line: None), 0)
        self.assertEqual(events[0], 'taken')
        self.assertEqual(events[-1], 'released')
        self.assertTrue(all(item.endswith('locked') for item in events[1:-1]), events)
        self.assertIn('gate locked', events)
        self.assertIn('merge locked', events)


class Diary(unittest.TestCase):
    """F60: a merged unit gets one diary note and one closed-row record; --close-queue takes the rows out."""

    def setUp(self):
        self.dir = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.closed = self.dir / 'closed.jsonl'
        self.enterContext(mock.patch.object(deliver, 'QUEUE_CLOSED', self.closed))
        self.enterContext(mock.patch.object(deliver, 'box_gate', lambda out=print, **_: contextlib.nullcontext()))

    def merged(self, subject):
        fake = Fake()
        fake.answers = {'git log -1 --format=%s': (0, subject), **fake.answers}
        lines = []
        code = deliver.deliver(7, run=fake, out=lines.append)
        return code, fake, lines

    def test_a_merged_unit_gets_one_note_and_one_record(self):
        code, fake, lines = self.merged('F60: deliver closes the queue row (#7)')
        self.assertEqual(code, 0)
        notes = [call for call in fake.calls if call.startswith('scripts/plan note')]
        self.assertEqual(len(notes), 1)
        self.assertIn(f"--from F60 --affects F60 --pr 7 --kind engine --evidence {'b' * 40}", notes[0])
        self.assertEqual([json.loads(line)['unit'] for line in self.closed.read_text().splitlines()], ['F60'])
        self.assertIn('0.0167 PR/s', lines[-1])

    def test_a_parenthesised_unit_counts_and_a_queue_batch_does_not(self):
        self.assertEqual(self.merged('tests: the probe runs once (VAZÃO F51) (#7)')[0], 0)
        _, fake, _ = self.merged('docs: queue batch (F60, F61 enter) (#7)')
        self.assertFalse(any(call.startswith('scripts/plan') for call in fake.calls))
        self.assertEqual([json.loads(line)['unit'] for line in self.closed.read_text().splitlines()], ['F51'])

    def test_the_unit_pattern_takes_one_named_unit_and_skips_queue_batches(self):
        def unit(subject):
            found = deliver.UNIT.search(subject)
            return found and (found.group(1) or found.group(2))
        self.assertEqual(unit('F57: the script-test map drops modules_required (D-292) (#151)'), 'F57')
        self.assertEqual(unit('F57 PR 2: the rest of the map (#170)'), 'F57')
        self.assertEqual(unit('VAZÃO F58: the whole suite enters the box lock log (#157)'), 'F58')
        self.assertEqual(unit('tests: the probe runs once (VAZÃO F51) (#148)'), 'F51')
        self.assertEqual(unit('deliver: a docs-only delivery is gated outside the box lock (F62, D-301) (#163)'), 'F62')
        self.assertEqual(unit('deliver: hand the delivery over to a box batch when there is a queue (F36) (#149)'), 'F36')
        self.assertFalse(unit('docs: queue batch (F60, F61 enter); AGENTS: no manual action a third time (#152)'))
        self.assertFalse(unit('docs: queue rows F62, F64-F71 (#161)'))
        self.assertFalse(unit('rules: three domains, a thin manager, short-lived coordinators (#153)'))

    def test_the_unit_comes_from_this_prs_merge_not_the_bases_newest_unit_merge(self):
        """DX (#192 after #190): the base already has an F-unit merge on top; this PR's `DF:` title writes nothing."""
        fake = Fake()
        theirs = 'c' * 40
        fake.answers = {f"git log -1 --format=%s {'b' * 40}": (0, 'DF: derive defect fields on load (#7)'),
                        'git log': (0, 'F70: the box turns the batch train on (#190)'),
                        f'rev-parse origin/{BASE}': (0, theirs), **fake.answers}
        lines = []
        self.assertEqual(deliver.deliver(7, run=fake, out=lines.append), 0)
        self.assertFalse(any(call.startswith('scripts/plan') for call in fake.calls))
        self.assertFalse(self.closed.exists())
        self.assertFalse(any('noted in the diary' in line for line in lines))

    def test_a_unit_title_on_top_of_another_unit_merge_credits_its_own_unit(self):
        fake = Fake()
        fake.answers = {f"git log -1 --format=%s {'b' * 40}": (0, 'F81: a lane bootstraps in one call (#7)'),
                        'git log': (0, 'F70: the box turns the batch train on (#190)'), **fake.answers}
        self.assertEqual(deliver.deliver(7, run=fake, out=lambda _: None), 0)
        self.assertEqual([json.loads(line) for line in self.closed.read_text().splitlines()],
                         [{'unit': 'F81', 'pr': 7, 'merge': 'b' * 40}])

    def test_a_merge_subject_naming_another_pr_writes_nothing(self):
        lines = []
        self.assertIsNone(deliver.diary(7, [f"Merge commit: {'c' * 40}"], self.dir,
                                        self._log('F70: x (#190)'), lines.append))
        self.assertFalse(self.closed.exists())
        self.assertIn('is #190, not #7', lines[-1])

    def _log(self, subject):
        fake = Fake()
        fake.answers = {'git log -1 --format=%s': (0, subject), **fake.answers}
        return fake

    def test_a_failed_note_is_a_warning_after_the_merge(self):
        fake = Fake()
        fake.answers = {'git log -1 --format=%s': (0, 'F60: x'), 'scripts/plan': (1, ''), **fake.answers}
        lines = []
        self.assertEqual(deliver.deliver(7, run=fake, out=lines.append), 0)
        self.assertTrue(any('diary note for F60 failed' in line for line in lines))

    def test_close_queue_takes_only_recorded_rows_out_and_twice_is_a_no_op(self):
        queue = self.dir / deliver.QUEUE
        queue.parent.mkdir(parents=True)
        queue.write_text('| # | U |\n|---|---|\n| F37 | a |\n| F60 | b |\n| F61 | c |\n')
        self.closed.write_text('{"unit": "F60", "pr": 7, "merge": "b"}\nnot json\n{"unit": "F99"}\n')
        self.assertEqual(deliver.close_queue(self.dir, out=lambda _: None), ['F60'])
        self.assertEqual(queue.read_text(), '| # | U |\n|---|---|\n| F37 | a |\n| F61 | c |\n')
        self.assertEqual(deliver.close_queue(self.dir, out=lambda _: None), [])


class DocsOnly(unittest.TestCase):
    """F62 (D-301): a docs-only branch delivery is gated and merged without the box lock; the rest keeps it."""

    def setUp(self):
        self.pause, deliver.FETCH_PAUSE = deliver.FETCH_PAUSE, 0
        self.addCleanup(setattr, deliver, 'FETCH_PAUSE', self.pause)
        self.locked = []

        @contextlib.contextmanager
        def gate(out=print, **_):
            self.locked.append(True)
            yield {}
        self.enterContext(mock.patch.object(deliver, 'box_gate', gate))
        self.enterContext(mock.patch.object(deliver.box_queue, 'enqueue', lambda *_: None))
        self.enterContext(mock.patch.object(deliver.box_queue, 'leave', lambda *_: None))
        self.enterContext(mock.patch.object(deliver.box_queue, 'result', lambda *_: None))
        self.enterContext(mock.patch.object(deliver.box_queue, 'entries', lambda: []))

    def run_with(self, paths):
        fake = Fake()
        fake.answers = {'diff --name-only': (0, '\n'.join(paths)), **fake.answers}
        lines = []
        with tempfile.TemporaryDirectory() as directory:
            code = deliver.deliver(7, root=Path(directory), run=fake, out=lines.append, branch='feat/x')
        return code, fake, lines

    def test_lockless_reads_the_area_plan(self):
        self.assertTrue(deliver.lockless(['docs/research/box.md', 'README.md']))
        self.assertFalse(deliver.lockless(['docs/programs/vazao/fila.md']))  # a script test covers it
        self.assertFalse(deliver.lockless([]))
        self.assertFalse(deliver.lockless(['docs/a.md', 'scripts/lib/deliver.py']))
        self.assertFalse(deliver.lockless(['scripts/README.md']))
        self.assertFalse(deliver.lockless(['config/registry/delivery.json']))
        self.assertFalse(deliver.lockless(['no-such-area/file.bin']))

    def test_a_docs_only_delivery_gates_and_merges_on_the_exact_head_without_the_lock(self):
        code, fake, lines = self.run_with(['docs/research/box.md'])
        self.assertEqual(code, 0, lines)
        self.assertEqual(self.locked, [])
        self.assertIn('scripts/gate-dev --pr 7', fake.calls)
        self.assertIn(f'origin pr merge 7 --expect-head 7={HEAD}', fake.calls)
        self.assertIn('outside the box lock (D-301)', lines[0])

    def test_a_docs_only_delivery_judges_again_when_the_base_moves(self):
        fake = Fake()
        fake.answers = {'diff --name-only': (0, 'docs/a.md'), **fake.answers}
        fake.sequences = {'rev-parse origin/mod': [(0, '1' * 40), (0, '2' * 40), (0, '2' * 40), (0, '2' * 40)]}
        lines = []
        with tempfile.TemporaryDirectory() as directory:
            code = deliver.deliver(7, root=Path(directory), run=fake, out=lines.append, branch='feat/x')
        self.assertEqual(code, 0, lines)
        self.assertEqual(self.locked, [])
        self.assertEqual(sum(call == 'scripts/gate-dev --pr 7' for call in fake.calls), 2)
        self.assertTrue(any('moved' in line and 'judging #7 again' in line for line in lines))

    def test_a_code_delivery_keeps_the_lock(self):
        code, fake, lines = self.run_with(['scripts/lib/deliver.py', 'docs/a.md'])
        self.assertEqual(code, 0, lines)
        self.assertEqual(self.locked, [True])
        self.assertFalse(any('outside the box lock' in line for line in lines))


class CliOnPath(unittest.TestCase):
    """F81: deliver finds the Origin CLI in origin-client.cli_dirs when the lane did not export PATH."""

    def test_the_cli_off_path_is_appended_from_the_listed_dirs(self):
        cli = deliver.config.get('origin-client.cli')
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp, 'bin')
            folder.mkdir()
            (folder / cli).touch(mode=0o700)
            environ = {'PATH': str(Path(tmp, 'empty'))}
            real = deliver.config.get
            listed = mock.patch.object(deliver.config, 'get', lambda key, *a: [str(folder)]
                                       if key == 'origin-client.cli_dirs' else real(key, *a))
            with listed:
                self.assertEqual(deliver.cli_on_path(environ), str(folder / cli))
                self.assertEqual(environ['PATH'].split(':')[-1], str(folder))
                self.assertEqual(deliver.cli_on_path(environ), cli)  # on PATH now: nothing appended again
            self.assertEqual(environ['PATH'].count(str(folder)), 1)


class QuietDeliverTests(unittest.TestCase):
    """VAZÃO F79: the default console of scripts/deliver is the merge and PR/s lines on green, every line on red."""

    def run_quiet(self, code, said):
        folder = Path(self.enterContext(tempfile.TemporaryDirectory()))
        shown = []

        def fake(pr, branch=None, out=print):
            for line in said:
                out(line)
            return code
        with mock.patch.object(deliver, 'deliver', fake):
            result = deliver.quiet_deliver(7, 'b', log_dir=folder, show=shown.append)
        return result, shown, (folder / 'pr-7.log').read_text()

    def test_green_prints_the_merge_and_the_pr_per_second_lines_and_the_log_path(self):
        said = ['deliver: gate on abc', 'gate: stage 1 ok', 'Merge commit: ' + 'b' * 40, 'last 10 merges: 0.0167 PR/s']
        code, shown, log = self.run_quiet(0, said)
        self.assertEqual(code, 0)
        self.assertEqual(shown[:2], said[2:])
        self.assertTrue(shown[-1].startswith('deliver: full log '))
        self.assertEqual(log.splitlines(), said)

    def test_red_prints_every_line(self):
        said = ['deliver: gate on abc', 'FAIL scripts/tests/x.test.sh']
        code, shown, _ = self.run_quiet(1, said)
        self.assertEqual((code, shown[:2]), (1, said))


if __name__ == '__main__':
    unittest.main()
