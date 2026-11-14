"""The plan tick (D-065 V4): registry, derivation from commits, pr.ready. Fixtures and temporary repositories, no network."""
import contextlib
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))

import config  # noqa: E402
import plan_tick  # noqa: E402
import event_contracts  # noqa: E402
import forge_events  # noqa: E402
sys.path.insert(0, str(Path(__file__).resolve().parent))  # the tests' own helpers
import forge_pin  # noqa: E402
import pr_ready  # noqa: E402

REGISTRY = ROOT / 'config' / 'registry' / 'plan-tick.json'
SECRET_WORDS = ('token', 'secret', 'password', 'credential', 'api_key', 'apikey')


class Registry(unittest.TestCase):
    def setUp(self):
        self.schema = json.loads(REGISTRY.read_text())

    def test_owner_and_schema_language(self):
        self.assertEqual(self.schema['$schema'], 'https://json-schema.org/draft/2020-12/schema')
        self.assertEqual(self.schema['x-owner'], 'plan-tick')
        self.assertEqual(self.schema['additionalProperties'], False)

    def test_every_key_is_typed_documented_and_read(self):
        types = {'string': str, 'integer': int, 'number': (int, float), 'boolean': bool, 'array': list}
        for name, spec in self.schema['properties'].items():
            with self.subTest(name=name):
                self.assertTrue(name.startswith('plan-tick.'))
                self.assertIn(spec['type'], types)
                self.assertIsInstance(spec['default'], types[spec['type']])
                self.assertTrue(spec['description'].strip())
                self.assertTrue(spec['x-readers'])
                self.assertFalse(any(word in name.lower() for word in SECRET_WORDS), 'secrets never go in the registry')

    def test_config_reader_returns_the_registered_default(self):
        for name, spec in self.schema['properties'].items():
            with self.subTest(name=name):
                self.assertEqual(config.get(name), spec['default'])

    def test_config_cli_prints_json(self):
        done = subprocess.run([sys.executable, str(ROOT / 'scripts/lib/config.py'), 'get', 'plan-tick.required_gate_kind'],
                              capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(json.loads(done.stdout), 'dev')


BODY = '## Commit plan\n- [ ] 1. Add the parser.\n- [x] 2. Add the reader.\n- [ ] 3. Wire the CLI.\n* not a plan item\n'


def git(root, *args):
    env = {'GIT_AUTHOR_NAME': 'fixture', 'GIT_AUTHOR_EMAIL': 'fixture@example.invalid',
           'GIT_COMMITTER_NAME': 'fixture', 'GIT_COMMITTER_EMAIL': 'fixture@example.invalid', 'PATH': '/usr/bin:/bin'}
    return subprocess.run(['git', '-C', str(root), *args], capture_output=True, text=True, check=True, env=env).stdout


def run_main(main, argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = main(argv)
    return code, out.getvalue()


def make_repo(root, messages):
    git(root, 'init', '-q', '-b', 'main')
    (root / 'f').write_text('base\n')
    git(root, 'add', 'f')
    git(root, 'commit', '-q', '-m', 'Base')
    git(root, 'branch', 'base-ref')
    for index, message in enumerate(messages):
        (root / 'f').write_text(f'{index}\n')
        git(root, 'commit', '-qam', message)


class Derivation(unittest.TestCase):
    def test_items_are_read_in_order_and_the_box_is_ignored(self):
        self.assertEqual(plan_tick.plan_items(BODY), [(1, 'Add the parser.'), (2, 'Add the reader.'), (3, 'Wire the CLI.')])

    def test_a_trailer_ticks_the_items_it_names(self):
        self.assertEqual(plan_tick.ticked_by(['Add it\n\nPlan: 1\n', 'Wire it\n\nPlan: 2, 3\n']), {1, 2, 3})

    def test_text_in_the_middle_of_a_line_does_not_tick(self):
        self.assertEqual(plan_tick.ticked_by(['Add it\n\nSee Plan: 2 above.\n']), set())

    def test_a_hand_ticked_box_is_not_a_tick(self):
        items = plan_tick.checklist(BODY, ['Add it\n\nPlan: 1\n'])
        self.assertEqual([done for _, _, done in items], [True, False, False])

    def test_commit_messages_are_read_from_the_range_oldest_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_repo(root, ['First\n\nPlan: 1\n', 'Second\n\nPlan: 2\n'])
            messages = plan_tick.commit_messages('base-ref', root)
        self.assertEqual([message.splitlines()[0] for message in messages], ['First', 'Second'])

    def test_cli_prints_the_derived_checklist_and_checks_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_repo(root, ['First\n\nPlan: 1\n', 'Second\n\nPlan: 2\n'])
            (root / 'body.md').write_text(BODY)
            command = ['--body', str(root / 'body.md'), '--base', 'base-ref', '--root', str(root)]
            code, printed = run_main(plan_tick.main, command)
            checked, _ = run_main(plan_tick.main, command + ['--check'])
        self.assertEqual(code, 0, printed)
        self.assertIn('[x] 1. Add the parser.', printed)
        self.assertIn('[x] 2. Add the reader.', printed)
        self.assertIn('[ ] 3. Wire the CLI.', printed)
        self.assertIn('plan tick: 2/3 derived from 2 commit(s)', printed)
        self.assertEqual(checked, 1)


SHA = 'a' * 40
REPO = config.get('forge-events.repo')
FIXED = datetime(2026, 10, 26, 12, 0, 0, tzinfo=timezone.utc)


class FixedClock:
    def now(self):
        return FIXED


def gate_passed(sha=SHA, plan='dev', pr=7):
    payload = forge_events.subject(REPO, pr, sha, ['P-18'])
    payload.update({'tier': 1, 'plan': plan, 'missing_stages': [], 'input_hash': 'd' * 64,
                    'stages': [{'name': 'lint', 'result': 'PASS', 'duration_ms': 1200, 'class': None}]})
    return payload


class PrReady(unittest.TestCase):
    def port(self, adapter):
        return forge_events.ForgeEvents(adapter, FixedClock(), 'plan-tick', 'pr-7')

    def test_pr_ready_cites_the_passed_gate_of_the_head(self):
        adapter = forge_events.MemoryAdapter()
        events = self.port(adapter)
        passed = events.emit('gate.passed', gate_passed())
        ready = pr_ready.emit_ready(events, REPO, 7, SHA, ['P-18'], 'dev', 'engine-lane')
        self.assertEqual(ready['type'], 'pr.ready')
        self.assertEqual(ready['payload']['evidence'], passed['event_id'])
        self.assertEqual(ready['payload']['premises'], ['P-18'])
        self.assertEqual(ready['payload']['lane_id'], 'engine-lane')
        event_contracts.validate(ready, event_contracts.registry())

    def test_no_passed_gate_for_the_head_refuses(self):
        adapter = forge_events.MemoryAdapter()
        events = self.port(adapter)
        events.emit('gate.passed', gate_passed(sha='b' * 40))
        with self.assertRaises(pr_ready.GateNotPassed):
            pr_ready.emit_ready(events, REPO, 7, SHA, [], 'dev')
        with self.assertRaises(pr_ready.GateNotPassed):
            pr_ready.emit_ready(events, REPO, 7, SHA, [], 'db')

    def test_re_emitting_the_same_head_is_a_no_op(self):
        adapter = forge_events.MemoryAdapter()
        events = self.port(adapter)
        events.emit('gate.passed', gate_passed())
        first = pr_ready.emit_ready(events, REPO, 7, SHA, [], 'dev')
        second = pr_ready.emit_ready(events, REPO, 7, SHA, [], 'dev')
        self.assertEqual(first['event_id'], second['event_id'])
        ready = [event for event in events.read(REPO, 7) if event['type'] == 'pr.ready']
        self.assertEqual(len(ready), 1)


PARSER = 1
TESTS = PARSER + PARSER
WIRING = TESTS + PARSER
RETRO = WIRING + PARSER
GX21_BODY = ''.join(f'- [ ] {number}. {text}\n' for number, text in
                    ((PARSER, 'parser'), (TESTS, 'tests'), (WIRING, 'wiring'), (RETRO, 'RETRO')))
RETRO_FILE = 'docs/units/GX21/retro.md'


def commit(message, files, *numbers):
    trailer = f'\n\nPlan: {", ".join(map(str, numbers))}' if numbers else ''
    return {'message': message + trailer, 'files': files}


class RealCommitsTick(unittest.TestCase):
    """GX-21: only a commit that changes a file ticks an item; the #615 shape (one item unticked)."""

    def test_an_empty_commit_ticks_nothing(self):
        commits = [commit('a', ['a.py'], PARSER), commit('b', [], TESTS, WIRING)]
        self.assertEqual(plan_tick.ticked_by_commits(commits), {PARSER})
        self.assertEqual(plan_tick.unticked(GX21_BODY, commits), [TESTS, WIRING, RETRO])

    def test_a_retro_only_commit_ticks_only_the_retro_item(self):
        only = [commit('r', [RETRO_FILE], PARSER, RETRO)]
        self.assertEqual(plan_tick.unticked(GX21_BODY, only), [PARSER, TESTS, WIRING])
        mixed = [commit('r', [RETRO_FILE, 'a.py'], PARSER, RETRO)]
        self.assertEqual(plan_tick.unticked(GX21_BODY, mixed), [TESTS, WIRING])

    def test_a_commit_without_a_file_list_counts_as_before(self):
        self.assertEqual(plan_tick.ticked_by_commits([{'message': f'x\n\nPlan: {TESTS}'}]), {TESTS})

    def test_git_allow_empty_commit_does_not_tick(self):
        with tempfile.TemporaryDirectory() as tmp:
            def git(*args):
                subprocess.run(['git', '-C', tmp, '-c', 'user.name=t', '-c', 'user.email=t@t', *args], check=True,
                               capture_output=True)
            git('init', '-q', '-b', 'main')
            git('commit', '-q', '--allow-empty', '-m', 'base')
            Path(tmp, 'a.txt').write_text('a')
            git('add', 'a.txt')
            git('commit', '-q', '-m', f'real\n\nPlan: {PARSER}')
            git('commit', '-q', '--allow-empty', '-m', f'empty\n\nPlan: {TESTS}')
            commits = plan_tick.commits_with_files('main~2', Path(tmp))
            self.assertEqual([c['files'] for c in commits], [['a.txt'], []])
            self.assertEqual(plan_tick.unticked(GX21_BODY, commits), [TESTS, WIRING, RETRO])


MANIFESTS = {'engine-config': {'id': 'engine-config', 'owner': 'engine-lane', 'paths': ['scripts/engine/**']},
             'admin-api': {'id': 'admin-api', 'owner': 'admin-lane', 'lane': 'admin-lane', 'paths': ['apps/admin/**']}}


class LaneOf(unittest.TestCase):
    """pr_ready.lane_of: the lane of the head's changes by the manifests at the merge base (train_ownership rule)."""

    def lane(self, changed, manifests_on_branch=None):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            git(root, 'init', '-q', '-b', 'base')
            for unit, manifest in MANIFESTS.items():
                (root / 'units' / unit).mkdir(parents=True)
                (root / 'units' / unit / 'unit.json').write_text(json.dumps(manifest))
            git(root, 'add', '-A')
            git(root, 'commit', '-q', '-m', 'base')
            git(root, 'checkout', '-q', '-b', 'head')
            for path in changed + (manifests_on_branch or []):
                (root / path).parent.mkdir(parents=True, exist_ok=True)
                (root / path).write_text(json.dumps({'id': 'x', 'owner': 'rogue-lane', 'paths': ['**']}))
            git(root, 'add', '-A')
            git(root, 'commit', '-q', '-m', 'change')
            return pr_ready.lane_of(root, 'base', 'HEAD')

    def test_a_single_lane_change_gets_that_lane(self):
        self.assertEqual(self.lane(['scripts/engine/a.py', 'scripts/engine/b.py']), 'engine-lane')
        self.assertEqual(self.lane(['apps/admin/route.ts']), 'admin-lane')

    def test_a_change_across_lanes_gets_no_lane_so_the_train_still_refuses_it(self):
        self.assertIsNone(self.lane(['scripts/engine/a.py', 'apps/admin/route.ts']))

    def test_an_unknown_file_names_no_lane_and_does_not_hide_a_known_one(self):
        self.assertIsNone(self.lane(['docs/free.md']))
        self.assertEqual(self.lane(['docs/free.md', 'scripts/engine/a.py']), 'engine-lane')

    def test_a_manifest_added_by_the_head_does_not_choose_its_lane(self):
        self.assertIsNone(self.lane(['docs/free.md'], ['units/rogue/unit.json']))


class PrReadyCli(unittest.TestCase):
    def test_an_unticked_item_refuses_before_any_event_is_read(self):
        body = '## Commit plan\n- [ ] 1. One.\n- [ ] 2. Two.\n- [ ] 3. Three.\n'
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_repo(root, ['One\n\nPlan: 1\n', 'Two\n\nPlan: 2\n'])
            (root / 'body.md').write_text(body)
            with forge_pin.origin():
                code, printed = run_main(pr_ready.main, ['--pr', '7', '--body', str(root / 'body.md'),
                                                         '--base', 'base-ref', '--root', str(root)])
        self.assertEqual(code, 1)
        self.assertIn('items not ticked by a commit: 3', printed)


if __name__ == '__main__':
    unittest.main()
