"""structure-check, idea-to-prod and the ship-verify fit-review refusal (STRUCTURE.md A4, A5, B5, C4, C5, D5).

Fixture repositories in a temporary directory; no network.
"""
import contextlib
from datetime import datetime
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import config  # noqa: E402
import structure  # noqa: E402
import train_git  # noqa: E402
import train_ownership  # noqa: E402
import regime  # noqa: E402

sys.path.insert(0, str(ROOT / 'scripts' / 'tests'))  # forge_doubles: the runner runs from here, a direct run does not


def setUpModule():
    """A direct run (python3 -m unittest) judges as the runner does (scripts/run test): the file store and no live exception
    regime (D-272), so the locks these tests assert refuse instead of being lifted."""
    global _PIN
    _PIN = (os.environ.get('OU_CONFIG_STORE'), config.store_kind())
    os.environ['OU_CONFIG_STORE'] = 'file'
    config.pin_store('file')
    regime.pin(False)


def tearDownModule():
    regime.pin(None)
    config.pin_store(_PIN[1])
    if _PIN[0] is None:
        os.environ.pop('OU_CONFIG_STORE', None)
    else:
        os.environ['OU_CONFIG_STORE'] = _PIN[0]

CAP = '''# CAP-003 — Ship any university
requested: 2026-10-22T10:00-03:00
requested-by: Daniel
status: done 2026-10-23
visual: no

## Target
idea-to-prod: 24h
The next university takes < 1 h of work.
'''
DECISIONS = '''# Register

| Id | Date | Decision | Invariant | Proof (test) | Status |
|---|---|---|---|---|---|
| D-001 | 2026-10-22 | Proven. | INV-1 | `src/a.test.ts` › "works" | proven |
| D-002 | 2026-10-20 | Planned. | INV-2 | (**test pending, S05**) | test pending |
'''
PLAN = '## Commit plan\n- [x] 1. One.\n- [x] 2. Two.\n- [ ] 3. Three.\n\n'
PLAN += ('## Cheapest useful effort\nAction: the gate run.\nCost: 5 min.\nRequirement: Daniel, to merge it.\n'
         'Cheaper rejected: the unit tests alone (they skip the stage).\n\n')  # EFFORT-STEP: every body carries the block
APPROVED = 'Summary.\n\nCapability: CAP-003\nInstances: A4\nPremises: none\nFit-Review: approved by A Torre (independent reviewer session, head 0e52a450) 2026-10-22\nClaude-Session: https://claude.ai/code/x\n'


ASSETS = json.dumps({'version': 1, 'entries': [
    {'category': 'doc', 'paths': ['docs/**'], 'protects': ['D-001'], 'retire': 'never: the constitution'},
]})


def write(root, files):
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)


class StructureCheck(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        write(self.root, {
            'docs/capabilities/CAP-003-ship-any-university.md': CAP,
            'docs/structure/assets.json': ASSETS,
            'docs/domain/DECISIONS.md': DECISIONS,
            'docs/process/STRUCTURE.md': '# Rites\n\n## C5. Decision to code\n\nSee [the register](../domain/DECISIONS.md#register), '
                                         '[web](https://example.test/x) and [C5](#c5-decision-to-code).\n\n```\n[not a link](missing.md)\n```\n',
        })
        self.addCleanup(self.tmp.cleanup)

    def check(self, *args):
        """The check in this process (GATE-SPEED F2): the subject is structure.main, which scripts/structure-check only
        execs; test_the_repository_passes_its_own_check keeps running the command itself."""
        out = io.StringIO()
        with patch.dict(os.environ), contextlib.redirect_stdout(out):
            os.environ.pop(structure.TREE_ONLY_ENV, None)
            code = structure.main(['--root', str(self.root), '--today', '2026-10-27', *args])
        return code, out.getvalue()

    def assert_fails(self, needle, *args):
        code, out = self.check(*args)
        self.assertEqual(code, 1, out)
        self.assertIn('FAIL', out)
        self.assertIn(needle, out)

    def test_a_valid_fixture_passes(self):
        code, out = self.check()
        self.assertEqual(code, 0, out)
        self.assertIn('1 capability file(s), 2 decision(s), 2 link(s); 0 premise(s); 0 error(s), 0 warning(s)', out)

    def test_premise_register_and_body_line(self):
        import shutil
        import premises
        shutil.copytree(ROOT / 'contracts', self.root / 'contracts')
        shape = premises.schema(self.root)
        folder = premises.register_dir(self.root)
        folder.mkdir(parents=True)

        def put(ident, slug, status, radius, answer=None):
            record = {'id': ident, 'slug': slug, 'statement': f'{slug} holds.', 'kind': 'process', 'scope': 'global',
                      'source': {'who': 'model', 'where': None, 'quote': None, 'at': None}, 'status': status,
                      'radius': radius, 'blast': {'reasons': [], 'if_wrong': 'x'}, 'validate': {'kind': 'none', 'how': None},
                      'answer': answer, 'dependents': premises.sealed([], []), 'supersedes': []}
            (folder / f'{slug}.yml').write_text(premises.dump(record, shape))
        put('P-01', 'open-high', 'inferred', 'high')
        put('P-02', 'open-medium', 'to-validate', 'medium')
        refuted = {'by': 'Daniel', 'at': None, 'value': 'refuted', 'quote': 'Não.', 'where': None, 'evidence': None,
                   'translation': None}
        put('P-03', 'said-no', 'refuted', 'low', refuted)
        body = self.root / 'body.md'
        for line, needle in [('Premises: P-01', 'P-01 has radius high and is inferred; it blocks this work'),
                             ('Premises: P-03', 'P-03 is refuted'), ('Premises: P-09', 'P-09 is not in')]:
            with self.subTest(line=line):
                body.write_text(PLAN + APPROVED.replace('Premises: none', line))
                self.assert_fails(needle, '--pr-body', str(body))
        body.write_text(PLAN + APPROVED.replace('Premises: none', 'Premises: P-02'))
        code, out = self.check('--pr-body', str(body))
        self.assertEqual(code, 0, out)
        self.assertIn('WARN Premises: P-02 has radius medium and is to-validate', out)
        body.write_text(PLAN + APPROVED.replace('Premises: none\n', ''))
        code, out = self.check('--pr-body', str(body))
        self.assertEqual(code, 0, out)
        self.assertIn('no "Premises: P-NN, ..." (or "Premises: none") line', out)
        self.assertIn('a warning in v0', out)
        self.assertIn('3 premise(s)', out)
        put('P-02', 'open-low-twin', 'inferred', 'low')
        self.assert_fails('open-medium.yml: id P-02 is also docs/process/premises/open-low-twin.yml')

    def git(self, *args):
        subprocess.run(['git', '-C', str(self.root), *args], check=True, capture_output=True,
                       env=dict(os.environ, GIT_AUTHOR_NAME='t', GIT_AUTHOR_EMAIL='t@x', GIT_COMMITTER_NAME='t',
                                GIT_COMMITTER_EMAIL='t@x', GIT_CONFIG_NOSYSTEM='1', HOME=str(self.root)))

    def baseline(self, files):
        entries = [{'category': 'doc', 'paths': ['docs/**'], 'protects': ['D-001'], 'retire': 'never: the constitution'},
                   {'category': 'script', 'paths': ['scripts/lib/absolute-literals-baseline/*.json'], 'protects': ['D-001'], 'retire': 'never: x'}]
        folder = self.root / 'scripts/lib/absolute-literals-baseline'
        for stale in folder.glob('*.json') if folder.is_dir() else []:
            stale.unlink()
        areas = {}
        for path, values in files.items():
            areas.setdefault(structure.census_area(path), {})[path] = values
        write(self.root, {**{f'scripts/lib/absolute-literals-baseline/{area}.json': json.dumps({'description': 'd', 'files': found})
                             for area, found in areas.items()},
                          'docs/structure/assets.json': json.dumps({'version': 1, 'entries': entries})})

    def test_d063_refuses_an_absolute_exception_list_that_grows_against_the_base(self):
        self.baseline({'products/demo/src/x/a.ts': {'number "0"': 2, 'string "x"': 1}})
        self.git('init', '-q'); self.git('add', '.'); self.git('commit', '-qm', 'base'); self.git('tag', 'base')
        self.baseline({'products/demo/src/x/a.ts': {'number "0"': 3, 'string "x"': 1}})
        self.assert_fails('number "0" allowed 2 times in base, 3 here; the list only shrinks per area (D-063, D-064 a)', '--base', 'base')
        self.baseline({'products/demo/src/x/a.ts': {'number "0"': 2, 'string "x"': 1, 'boolean "true"': 1}})
        self.assert_fails('boolean "true" allowed 0 times in base, 1 here', '--base', 'base')
        self.baseline({'products/demo/src/x/a.ts': {'number "0"': 1}, 'products/demo/src/x/moved.ts': {'number "0"': 1}})
        code, out = self.check('--base', 'base')
        self.assertEqual(code, 0, out)

    def test_d064a_the_exception_list_shrinks_per_area_and_value(self):
        self.baseline({'products/demo/src/admin/a.ts': {'boolean "true"': 1}, 'products/demo/scripts/b.ts': {'boolean "true"': 1}})
        self.git('init', '-q'); self.git('add', '.'); self.git('commit', '-qm', 'base'); self.git('tag', 'base')
        self.baseline({'products/demo/src/admin/a.ts': {'boolean "true"': 2}})
        self.assert_fails('absolute-literals-baseline/admin.json: boolean "true" allowed 1 times in base, 2 here; '
                          'the list only shrinks per area (D-063, D-064 a)', '--base', 'base')
        self.baseline({'products/demo/src/admin/moved.ts': {'boolean "true"': 1}})
        code, out = self.check('--base', 'base')
        self.assertEqual(code, 0, out)

    def shared(self, values, reasons=('two-areas',)):
        assets = json.loads((self.root / 'docs/structure/assets.json').read_text())
        if 'scripts/lib/*.json' not in assets['entries'][1]['paths']:
            assets['entries'][1]['paths'].append('scripts/lib/*.json')
        write(self.root, {'docs/structure/assets.json': json.dumps(assets), 'scripts/lib/shared-literals.json': json.dumps(
            {'description': 'd', 'reasons': {reason: 'why' for reason in reasons}, 'values': values})})

    def test_d064_refuses_a_value_of_two_areas_outside_the_common_catalog(self):
        self.baseline({'products/demo/src/admin/a.ts': {'string "lesson"': 1, 'number "0"': 1},
                       'products/demo/scripts/b.ts': {'string "lesson"': 1, 'number "0"': 1}, 'products/demo/src/admin/c.ts': {'string "x"': 1}})
        self.assert_fails('string "lesson" is written in 2 areas (admin, scripts) and is not in the common catalog')
        self.shared({'string "lesson"': 'unknown'})
        self.assert_fails('string "lesson" names the unknown reason "unknown"')
        self.shared({'string "lesson"': 'two-areas'})
        code, out = self.check()
        self.assertEqual(code, 0, out)

    def test_d064_the_registered_list_only_shrinks_and_a_fixed_value_only_warns(self):
        self.baseline({'products/demo/src/admin/a.ts': {'string "lesson"': 1}, 'products/demo/scripts/b.ts': {'string "lesson"': 1}})
        self.shared({'string "lesson"': 'two-areas'})
        self.git('init', '-q'); self.git('add', '.'); self.git('commit', '-qm', 'base'); self.git('tag', 'base')
        self.shared({'string "lesson"': 'two-areas', 'string "course"': 'two-areas'})
        self.assert_fails('string "course" is not registered in base; the list only shrinks (D-064 c)', '--base', 'base')
        self.baseline({'products/demo/src/admin/a.ts': {'string "lesson"': 1}})
        self.shared({'string "lesson"': 'two-areas'})
        code, out = self.check('--base', 'base')
        self.assertEqual(code, 0, out)
        self.assertIn('string "lesson" no longer spans 2+ areas', out)

    def test_rejects_a_capability_without_requested(self):
        write(self.root, {'docs/capabilities/CAP-003-ship-any-university.md': CAP.replace('requested: 2026-10-22T10:00-03:00\n', '')})
        self.assert_fails('CAP-003-ship-any-university.md: no "requested:" line')

    def test_d054_rejects_a_capability_approved_or_done_before_it_was_requested(self):
        for status in ('approved 2026-10-21', 'done 2026-10-21'):
            with self.subTest(status=status):
                write(self.root, {'docs/capabilities/CAP-003-ship-any-university.md': CAP.replace('done 2026-10-23', status)})
                self.assert_fails(f'"status: {status}" is before "requested: 2026-10-22T10:00-03:00"')
        write(self.root, {'docs/capabilities/CAP-003-ship-any-university.md': CAP.replace('done 2026-10-23', 'approved 2026-10-22')})
        self.assertEqual(self.check()[0], 0)

    def test_d054_rejects_a_malformed_condition_and_a_done_capability_with_an_open_one(self):
        cap = 'docs/capabilities/CAP-003-ship-any-university.md'
        met = 'condition: before-merge met 2026-10-23 — Daniel approves the migration\n'
        write(self.root, {cap: CAP.replace('visual: no\n', 'visual: no\n' + met)})
        self.assertEqual(self.check()[0], 0)
        write(self.root, {cap: CAP.replace('visual: no\n', 'visual: no\ncondition: before-merge pending — x\n')})
        self.assert_fails('"condition: before-merge pending — x" is not "condition: before-start|before-merge|before-production')
        write(self.root, {cap: CAP.replace('visual: no\n', 'visual: no\ncondition: before-production open — Daniel approves\n')})
        self.assert_fails('is done with an open before-production condition: Daniel approves')
        approved = CAP.replace('done 2026-10-23', 'approved 2026-10-22')
        write(self.root, {cap: approved.replace('visual: no\n', 'visual: no\ncondition: before-production open — Daniel approves\n')})
        self.assertEqual(self.check()[0], 0)

    def test_d054_rejects_a_pr_body_naming_a_capability_with_an_open_before_merge_condition(self):
        cap = 'docs/capabilities/CAP-003-ship-any-university.md'
        approved = CAP.replace('done 2026-10-23', 'approved 2026-10-22')
        body = self.root / 'body.md'
        body.write_text(PLAN + 'Capability: CAP-003\nInstances: A4\nFit-Review: not structural\nClaude-Session: x\n')
        write(self.root, {cap: approved.replace('visual: no\n', 'visual: no\ncondition: before-merge open — Daniel approves\n')})
        self.assert_fails('CAP-003 has an open before-merge condition: Daniel approves', '--pr-body', str(body))
        write(self.root, {cap: approved.replace('visual: no\n', 'visual: no\ncondition: before-merge met 2026-10-23 — Daniel approves\n')})
        self.assertEqual(self.check('--pr-body', str(body))[0], 0)

    def test_rejects_a_requested_time_without_offset(self):
        write(self.root, {'docs/capabilities/CAP-003-ship-any-university.md': CAP.replace('T10:00-03:00', ' 10am')})
        self.assert_fails('is not YYYY-MM-DDTHH:MM±HH:MM')

    def test_rejects_a_visual_capability_without_figma(self):
        visual = CAP.replace('visual: no', 'visual: yes                # needs Figma')
        write(self.root, {'docs/capabilities/CAP-003-ship-any-university.md': visual})
        self.assert_fails('"visual: yes" without a "figma:" node (D-006)')
        write(self.root, {'docs/capabilities/CAP-003-ship-any-university.md': visual.replace('\n\n## Target', '\nfigma: abc123 / 1:2\n\n## Target')})
        self.assertEqual(self.check()[0], 0)

    def test_rejects_a_decision_without_proof_or_pending_pr(self):
        write(self.root, {'docs/domain/DECISIONS.md': DECISIONS + '| D-003 | 2026-10-22 | Said in chat. | INV-3 | Fit review | rite |\n'})
        self.assert_fails('DECISIONS.md D-003: no linked proof (test) and no pending PR')

    def test_flags_test_pending_older_than_seven_days(self):
        code, out = self.check('--today', '2026-10-28')
        self.assertEqual(code, 0, out)
        self.assertIn('WARN DECISIONS.md D-002: test pending for 8 days', out)
        self.assertNotIn('WARN', self.check()[1])  # 7 days is not yet late

    def test_d069_every_principle_names_a_check_that_exists_in_this_checkout(self):
        """D-069: a principle without a machine check is not done. Each numbered item of the decision row is a principle
        of its reference, which has an `exists` (or `implemented`) row, and every engine file such a row names is here."""
        entry = next(line for line in (ROOT / 'docs/domain/DECISIONS.md').read_text().splitlines() if line.startswith('| D-069 |'))
        text = (ROOT / 'docs/process/principles/D-069.md').read_text().split('\n## Shared contract')[0]
        sections = dict(re.findall(r'^### (\d+)\. (.*?)(?=^### |\Z)', text, flags=re.M | re.S))
        self.assertEqual(list(sections), re.findall(r'\((\d+)\) ', entry))
        for section in sections.values():
            rows = [line for line in section.splitlines() if line.startswith('|') and not line.startswith('|---')]
            live = [row for row in rows if re.match(r'(exists|implemented)\b', row.rstrip(' |').rsplit('|', 1)[-1].strip())]
            with self.subTest(principle=section.splitlines()[0]):
                self.assertTrue(live, 'no check exists')
                for path in re.findall(r'`((?:scripts|contracts|config|services|units)/[^`\s<*]+)`', ''.join(live)):
                    self.assertTrue((ROOT / path).exists(), path)

    def test_rejects_a_relative_link_or_heading_that_does_not_resolve(self):
        page = (self.root / 'docs/process/STRUCTURE.md').read_text()
        write(self.root, {'docs/process/STRUCTURE.md': page.replace('DECISIONS.md#register', 'DECISION.md')})
        self.assert_fails('docs/process/STRUCTURE.md: link ../domain/DECISION.md does not resolve')
        write(self.root, {'docs/process/STRUCTURE.md': page.replace('#c5-decision-to-code', '#c6')})
        self.assert_fails('docs/process/STRUCTURE.md: link #c6 names a missing heading')

    def test_rejects_a_structural_pr_body_without_fit_review(self):
        body = self.root / 'body.md'
        for text, needle in [
            ('Summary.\n\nCapability: CAP-003\nInstances: A4\nClaude-Session: x\n', 'no "Fit-Review: approved by <owner> YYYY-MM-DD", "Fit-Review: not structural" or "Fit-Review: not reviewed'),
            ('Fit-Review: approved\nCapability: CAP-003\nInstances: A4\n', 'must name the reviewer, the independent reviewer session'),
            ('Fit-Review: approved by A Torre 2026-10-22\nCapability: CAP-003\nInstances: A4\n', 'must name the reviewer, the independent reviewer session'),
            ('Fit-Review: approved by A Torre (independent reviewer session) 2026-10-22\nCapability: CAP-003\nInstances: A4\n', 'must name the reviewer, the independent reviewer session'),
            ('Fit-Review: approved by A Torre 2026-10-22\nInstances: A4\n', 'no "Capability: CAP-NNN" line'),
            ('Fit-Review: approved by A Torre 2026-10-22\nCapability: CAP-003\n', 'no "Instances:" line'),
        ]:
            with self.subTest(needle=needle):
                body.write_text(text)
                self.assert_fails(needle, '--pr-body', str(body))
        body.write_text(APPROVED)
        self.assert_fails('plan: the PR body needs a D-022 commit plan checklist of at least 1 items', '--pr-body', str(body))
        # D-307 (Daniel 04/11 12:53 BRT): a plan has no maximum, so a PR is split by its content, never by a counter.
        # Twelve items, one per letter, more than the old ceiling of eight.
        long_plan = ('## Commit plan\n' + ''.join(f'- [ ] {n}. Item {n}.\n' for n, _ in enumerate('abcdefghijkl', start=1))
                     + '\n'
                     + PLAN[PLAN.index('## Cheapest useful effort'):])
        body.write_text(long_plan + APPROVED)
        code, out = self.check('--pr-body', str(body))
        self.assertEqual((code, 'plan:' in out), (0, False), out)
        body.write_text(PLAN + APPROVED)
        code, out = self.check('--pr-body', str(body))
        self.assertEqual((code, 'WARN' in out), (0, False), out)
        body.write_text(PLAN + APPROVED.replace('(independent reviewer session, head 0e52a450) 2026-10-22',
                                                '2026-10-22 (independent reviewer session, head 0e52a450)'))
        self.assertEqual(self.check('--pr-body', str(body))[0], 0)
        body.write_text(PLAN + 'Docs typo.\n\nFit-Review: not structural\n')
        code, out = self.check('--pr-body', str(body))
        self.assertEqual(code, 0, out)
        self.assertIn('WARN PR body has no "Claude-Session:" line (D-007)', out)

    def test_warns_above_the_size_budget_without_counting_tests(self):
        git = ['git', '-C', str(self.root), '-c', 'user.email=t@example.test', '-c', 'user.name=t', '-c', 'commit.gpgsign=false']
        inventory = json.loads(ASSETS)
        inventory['entries'].append({'category': 'script', 'paths': ['scripts/**'], 'protects': ['D-001'], 'retire': 'never: tooling'})
        write(self.root, {'docs/structure/assets.json': json.dumps(inventory), 'scripts/.keep': ''})
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)
        subprocess.run(git + ['add', '-A'], check=True)
        subprocess.run(git + ['commit', '-qm', 'base'], check=True)
        write(self.root, {'scripts/tests/big.test.sh': 'x\n' * 900, 'scripts/tool': 'x\n' * 600})
        subprocess.run(git + ['add', '-A'], check=True)
        subprocess.run(git + ['commit', '-qm', 'change'], check=True)
        self.assertNotIn('WARN size', self.check('--base', 'HEAD~1')[1])
        write(self.root, {'scripts/tool': 'x\n' * 601})
        subprocess.run(git + ['commit', '-qam', 'more'], check=True)
        code, out = self.check('--base', 'HEAD~2')
        self.assertEqual(code, 0, out)
        self.assertIn('WARN size: 601 changed lines without tests and generated files (D-008 budget 600)', out)


    def test_d064_a_catalog_of_the_manifest_is_not_counted_toward_the_size_budget(self):
        git = ['git', '-C', str(self.root), '-c', 'user.email=t@example.test', '-c', 'user.name=t', '-c', 'commit.gpgsign=false']
        inventory = json.loads(ASSETS)
        inventory['entries'].append({'category': 'script', 'paths': ['scripts/**'], 'protects': ['D-001'], 'retire': 'never: tooling'})
        manifest = json.dumps({'description': 'd', 'catalogs': {'products/demo/src/kernel/limits.ts': {'domains': ['limits'], 'holds': 'h'}}})
        write(self.root, {'docs/structure/assets.json': json.dumps(inventory), 'scripts/lib/literal-catalogs/kernel.json': manifest})
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)
        subprocess.run(git + ['add', '-A'], check=True)
        subprocess.run(git + ['commit', '-qm', 'base'], check=True)
        write(self.root, {'products/demo/src/kernel/limits.ts': 'x\n' * 900, 'scripts/tool': 'x\n' * 600})
        subprocess.run(git + ['add', '-A'], check=True)
        subprocess.run(git + ['commit', '-qm', 'change'], check=True)
        self.assertNotIn('WARN size', self.check('--base', 'HEAD~1')[1])
        self.assertEqual(structure.changed_lines(self.root, 'HEAD~1'), 600)


class IdeaToProd(unittest.TestCase):
    HEADER = 'capability   requested(-03:00)    live(-03:00)         idea→prod  PRs  fixed-cost  marginal  verdict'

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        prs = [
            {'number': 301, 'body': 'Capability: CAP-003\nFit-Review: approved by A Torre 2026-10-22', 'mergedAt': '2026-10-22T20:00:00Z'},
            {'number': 302, 'body': 'Capability: CAP-003', 'mergedAt': '2026-10-23T19:30:00Z', 'liveAt': '2026-10-23T19:40:00Z'},
            {'number': 303, 'body': 'Capability: CAP-004', 'mergedAt': '2026-10-23T19:40:00Z'},
            {'number': 304, 'body': 'Fixes CAP-003 wording\nFit-Review: not structural', 'mergedAt': '2026-10-24T10:00:00Z'},
        ]
        write(self.root, {'prs.json': json.dumps(prs), 'docs/capabilities/CAP-003-ship-any-university.md': CAP})

    def report(self, *args):
        result = subprocess.run(['bash', str(ROOT / 'scripts/idea-to-prod'), '--no-env-check', '--root', str(self.root), '--prs', str(self.root / 'prs.json'),
                                 '--now', '2026-10-25T12:00:00Z', *args], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.splitlines()

    def test_prints_the_expected_line_for_an_ok_delivery(self):
        self.assertEqual(self.report(), [
            self.HEADER,
            'CAP-003      2026-10-22 10:00     2026-10-23 16:40     30h40m     2    —           ≤1h       ok',
        ])

    def test_a_slow_delivery_names_the_investigation_to_open(self):
        write(self.root, {'docs/capabilities/CAP-004-add-an-area.md': CAP.replace('CAP-003', 'CAP-004').replace('24h', '12h'),
                          'docs/capabilities/INV-001-old.md': '# INV-001 about CAP-009\n'})
        lines = self.report()
        self.assertEqual(lines[2], 'CAP-004      2026-10-22 10:00     2026-10-23 16:40     30h40m     1    —           ≤1h       slow')
        self.assertEqual(lines[3], 'CAP-004: slow (30h40m > 2 × 12h); open docs/capabilities/INV-002-add-an-area.md: the question, '
                                   'then causes and the definitive structural solution in five instances, and the PRs that follow '
                                   'from it (STRUCTURE.md D5)')

    def test_open_capabilities_count_until_now_and_since_filters(self):
        write(self.root, {'docs/capabilities/CAP-003-ship-any-university.md': CAP.replace('status: done 2026-10-23', 'status: approved 2026-10-22')})
        self.assertEqual(self.report()[1], 'CAP-003      2026-10-22 10:00     —                    71h        2    —           ≤1h       slow')
        self.assertEqual(self.report('--since', '2026-10-26'), [self.HEADER])


HEAD = '27797033dac6120eb5b84a2d1ae88d4508b7cceb'
OLD = '0e52a4500ed5e039b852bfee41657839f02b377f'


def review(sha, verdict):
    return f'Independent fit review (reviewer session, head {sha}): {verdict}\n\nFindings.'


class ReviewErrors(unittest.TestCase):
    def test_d054_accepts_the_latest_approval_of_this_head(self):
        comments = [review(OLD, 'CHANGES_REQUESTED'), 'An unrelated comment.', review(HEAD, 'APPROVED')]
        self.assertEqual(structure.review_errors('Fit-Review: not structural', HEAD, comments), [])
        named = f'Fit-Review: approved by A Torre (independent reviewer session, head {HEAD[:8]}) 2026-10-25'
        self.assertEqual(structure.review_errors(named, HEAD, [review(HEAD[:8], 'APPROVED')]), [])

    def test_d054_refuses_a_trailer_naming_another_head(self):
        named = f'Fit-Review: approved by A Torre (independent reviewer session, head {OLD[:8]}) 2026-10-25'
        errors = structure.review_errors(named, HEAD, [review(HEAD, 'APPROVED')])
        self.assertEqual(len(errors), 1)
        self.assertIn(f'names head {OLD[:8]}, not the PR head', errors[0])

    def test_d054_refuses_a_short_or_quoted_review(self):
        claimed = f'Fit-Review: approved by A Torre (independent reviewer session, head {HEAD[:8]}) 2026-10-25'
        self.assertTrue(structure.review_errors(claimed, HEAD, [review(HEAD[:6], 'APPROVED')]))
        self.assertTrue(structure.review_errors(claimed, HEAD, ['> ' + review(HEAD, 'APPROVED')]))

    def test_d055_a_pr_without_a_review_step_needs_no_review_comment(self):
        for fit in ('not reviewed (Daniel 2026-10-25: no review step)', 'not structural'):
            with self.subTest(fit=fit):
                self.assertEqual(structure.review_errors(f'Fit-Review: {fit}', HEAD, []), [])
                self.assertEqual(structure.fit_review(f'Fit-Review: {fit}\nClaude-Session: x'), ([], []))

    def test_d055_a_claimed_approval_still_needs_its_review(self):
        claimed = f'Fit-Review: approved by A Torre (independent reviewer session, head {HEAD[:8]}) 2026-10-25'
        self.assertIn('no "Independent fit review', structure.review_errors(claimed, HEAD, [])[0])

    def test_d055_a_review_that_requests_changes_still_refuses(self):
        errors = structure.review_errors('Fit-Review: not reviewed (Daniel 2026-10-25: no review step)', HEAD,
                                         [review(HEAD, 'CHANGES_REQUESTED')])
        self.assertIn('latest independent fit review of head', errors[0])

    def test_d055_not_reviewed_must_say_who_when_and_why(self):
        for fit in ('not reviewed', 'not reviewed (Daniel)', 'not reviewed (2026-10-25: x)', 'not reviewed (Daniel 2026-10-25:)'):
            with self.subTest(fit=fit):
                errors, _ = structure.fit_review(f'Fit-Review: {fit}\nClaude-Session: x')
                self.assertIn('must say who decided, when and why', errors[0])


def git(root, *args):
    return subprocess.run(['git', '-C', str(root), '-c', 'user.email=t@example.com', '-c', 'user.name=T', *args],
                          capture_output=True, text=True, check=True).stdout.strip()


class TreeCache(unittest.TestCase):
    """GX-15 (B-11, P-42): the tree part is reused by content key; the metadata part always reruns."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'repo'
        write(self.root, {'docs/structure/assets.json': ASSETS, 'docs/domain/DECISIONS.md': DECISIONS})
        git(self.tmp.name, 'init', '-q', str(self.root))
        git(self.root, 'add', '-A')
        git(self.root, 'commit', '-q', '-m', 'Base')
        self.day = structure.date.fromisoformat('2026-10-27')
        patches = [patch.dict(os.environ, {structure.TREE_CACHE_ENV: str(Path(self.tmp.name) / 'cache')}),
                   patch.object(structure, 'tool_state', return_value=['scripts-tree', 'config-tree'])]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)
        self.calls = 0
        real = structure.tree_part

        def counted(*args):
            self.calls += 1
            return real(*args)
        self.tree_part = patch.object(structure, 'tree_part', side_effect=counted)
        self.tree_part.start()
        self.addCleanup(self.tree_part.stop)

    def run_part(self, base=None, day=None):
        lines = []
        result = structure.cached_tree_part(self.root, base, day or self.day, out=lines.append)
        return result, lines[-1]

    def twice(self):
        return [self.run_part()[1] for _ in ('first', 'second')]

    def test_an_unchanged_tree_reuses_the_recorded_pass(self):
        first, ran = self.run_part()
        second, cached = self.run_part()
        self.assertEqual(self.calls, 1)
        self.assertIn('structure tree: ran', ran)
        self.assertIn('structure tree: cached', cached)
        self.assertEqual(first, second)

    def test_the_installed_toolchain_link_is_ignored_but_untracked_source_is_not(self):
        (self.root / '.gitignore').write_text((ROOT / '.gitignore').read_text())
        git(self.root, 'add', '.gitignore')
        git(self.root, 'commit', '-q', '-m', 'Ignore installed tools')
        installed = Path(self.tmp.name) / 'installed'
        installed.mkdir()
        (self.root / '.toolchain').symlink_to(installed, target_is_directory=True)
        self.assertTrue(structure.clean(self.root))
        self.run_part()
        self.run_part()
        self.assertEqual(self.calls, 1)
        write(self.root, {'docs/untracked.md': 'Must be checked.\n'})
        self.assertFalse(structure.clean(self.root))

    def test_a_new_tree_another_day_or_base_runs_again(self):
        runs = [self.run_part(), self.run_part(day=structure.date.fromisoformat('2026-10-28'))]
        write(self.root, {'docs/new.md': 'New.\n'})
        git(self.root, 'add', '-A')
        git(self.root, 'commit', '-q', '-m', 'Head')
        runs += [self.run_part(), self.run_part(base='HEAD~1')]
        self.assertEqual(self.calls, len(runs))

    def test_a_dirty_checkout_or_tool_root_is_never_cached(self):
        write(self.root, {'docs/untracked.md': 'Draft.\n'})
        lines = self.twice()
        self.assertEqual(self.calls, len(lines))
        self.assertIn('no cache key', lines[-1])
        (self.root / 'docs/untracked.md').unlink()
        with patch.object(structure, 'tool_state', return_value=None):
            lines += self.twice()
        self.assertEqual(self.calls, len(lines))

    def test_the_switch_off_caches_nothing(self):
        real = structure.config.get
        with patch.object(structure.config, 'get',
                          side_effect=lambda name, *rest: False if name == 'structure.tree_cache_enabled' else real(name, *rest)):
            lines = self.twice()
        self.assertEqual(self.calls, len(lines))

    def test_cached_errors_still_fail_under_the_current_policy(self):
        self.tree_part.stop()
        failing = {'errors': ['links: broken'], 'warnings': [], 'counts': dict.fromkeys(
            ('caps', 'decisions', 'links', 'inventoried', 'recorded'), 0)}
        with patch.object(structure, 'tree_part', return_value=failing) as part, \
                patch.object(structure, 'metadata_part', return_value=([], [], None)), \
                patch.object(structure, '_lifted', side_effect=[True, False]), patch('builtins.print'):
            codes = [structure.main(['--root', str(self.root), '--today', self.day.isoformat()])
                     for _ in ('lifted', 'enforced')]
        self.assertEqual(codes, [0, 1])
        self.assertEqual(part.call_count, 1)
        self.assertEqual(self.run_part()[0]['errors'], failing['errors'])
        self.tree_part.start()

    def test_source_analysis_tracks_contents_and_all_filenames_but_not_unread_prose(self):
        write(self.root, {'scripts/probe.py': 'pass\n', 'docs/report.md': 'First measurement.\n'})
        git(self.root, 'add', '-A')
        git(self.root, 'commit', '-q', '-m', 'Source inputs')
        base = git(self.root, 'rev-parse', 'HEAD')
        with patch.object(structure, 'source_analysis_inputs', return_value={'scripts/probe.py'}), \
                patch.object(structure.config, 'overrides', return_value={}):
            first = structure.source_analysis_key(self.root, base)
            self.assertTrue(first)
            write(self.root, {'docs/report.md': 'Another measurement.\n'})
            self.assertEqual(structure.source_analysis_key(self.root, base), '')
            git(self.root, 'commit', '-qam', 'Publish measurement')
            self.assertEqual(structure.source_analysis_key(self.root, base), first)
            write(self.root, {'scripts/probe.py': 'raise RuntimeError()\n'})
            git(self.root, 'commit', '-qam', 'Source changed')
            second = structure.source_analysis_key(self.root, base)
            self.assertNotEqual(second, first)
            write(self.root, {'docs/new.md': 'New tracked path.\n'})
            git(self.root, 'add', '-A')
            git(self.root, 'commit', '-q', '-m', 'Tracked paths changed')
            self.assertNotEqual(structure.source_analysis_key(self.root, base), second)

    def test_source_analysis_includes_configured_markdown_inputs(self):
        files = ['docs/production.md', 'docs/scanned.md', 'docs/manifest.md', 'docs/decisions.md',
                 'docs/schema.md', 'docs/vendors.md', 'docs/vendor-schema.md', 'docs/aliases.md', 'docs/prose.md']
        values = dict(zip(('units.manifest_schema', 'units.decision_register', 'providers.vendor_catalog',
                           'providers.vendor_catalog_schema'),
                          ('docs/schema.md', 'docs/decisions.md', 'docs/vendors.md', 'docs/vendor-schema.md')))
        values['units.tsconfig_files'] = ['docs/aliases.md']
        with patch.object(structure.unit_check.units, 'production', return_value=(['docs/production.md'], [])), \
                patch.object(structure.config_check, 'engine_files', return_value=[('docs/scanned.md', '.py')]), \
                patch.object(structure.unit_check.units, 'manifest_files',
                             return_value=[self.root / 'docs/manifest.md']), \
                patch.object(structure.config, 'get', side_effect=lambda name, root: values[name]):
            self.assertEqual(structure.source_analysis_inputs(self.root, files), set(files) - {'docs/prose.md'})

    def test_source_diagnostics_reuse_retains_all_errors(self):
        failing = [[['source error'], []] for _ in ('config', 'literals', 'units', 'vendors', 'hygiene')]
        with patch.object(structure, 'source_analysis_key', return_value='source-key'), \
                patch.object(structure.python_source, 'checks', return_value=failing) as checks:
            first = structure.source_checks(self.root, 'HEAD', [])
            second = structure.source_checks(self.root, 'HEAD', [])
        self.assertEqual(checks.call_count, 1)
        self.assertEqual(first, second)
        self.assertEqual(first, failing)

    def test_the_metadata_part_always_reruns(self):
        with patch.object(structure, 'metadata_part', return_value=([], [], None)) as meta, \
                patch('builtins.print'):
            codes = [structure.main(['--root', str(self.root), '--today', '2026-10-27', '--pr', '1']) for _ in ('first', 'second')]
        self.assertEqual(codes, [0, 0])
        self.assertEqual(self.calls, 1)
        self.assertEqual(meta.call_count, len(codes))


class Clock:
    def now(self):
        return structure.datetime.fromisoformat('2026-10-27T22:00:00+00:00')


class MetadataPart(unittest.TestCase):
    """GX-15: `--metadata` runs the PR part alone and publishes pr.checked v1; the gate's tree-only mark skips it."""
    SHA, BASE = 'a' * len(structure.hashlib.sha1().hexdigest()), 'b' * len(structure.hashlib.sha1().hexdigest())
    PR = '7'

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        import forge_events
        self.forge = forge_events
        import forge_doubles
        self.port = forge_events.ForgeEvents(
            forge_events.RoutingAdapter(forge_doubles.origin(), {}, default=forge_events.MemoryAdapter()),
            Clock(), 'structure-check', 'pr-' + self.PR)
        self.pr = {'gated': {'sha': self.SHA}, 'body': 'Plan.\n\nPremises: P-42, P-46\n',
                   'base': {'ref': 'mod/roadmap-integration', 'merge_base': self.BASE}}

    def main(self, *args, meta=([], [], None), env=None):
        with patch.object(structure, 'tree_part', return_value={'errors': [], 'warnings': [], 'counts': dict.fromkeys(
                ('caps', 'decisions', 'links', 'inventoried', 'recorded'), 0)}) as tree, \
                patch.object(structure, 'metadata_part', return_value=meta) as part, \
                patch.dict(os.environ, env or {}), patch('builtins.print') as printed:
            code = structure.main(['--root', self.tmp.name, *args], port=self.port)
        return code, tree.call_count, part.call_count, ' '.join(str(call.args[0]) for call in printed.call_args_list)

    def events(self):
        return self.port.adapter.read(self.forge.Channel(structure.config.get('forge-events.repo'), int(self.PR)))

    def test_metadata_alone_runs_no_tree_module_and_publishes_pr_checked(self):
        code, tree, part, out = self.main('--pr', self.PR, '--metadata', meta=(['plan: no commit plan'], [], self.pr))
        self.assertEqual((code, tree, part), (1, 0, 1))
        self.assertIn('structure-check (metadata, PR #7): 1 error(s)', out)
        [event] = self.events()
        import event_contracts
        event_contracts.validate(event)
        self.assertEqual(event['type'], 'pr.checked')
        self.assertEqual(event['payload'], {'repo': structure.config.get('forge-events.repo'), 'pr': int(self.PR), 'sha': self.SHA,
                                            'unit': None, 'premises': ['P-42', 'P-46'], 'base_sha': self.BASE,
                                            'result': 'fail', 'errors': ['plan: no commit plan']})
        self.assertEqual(event['producer'], structure.config.get('structure.event_producer'))

    def test_a_pass_is_published_and_no_publish_or_no_pr_publishes_nothing(self):
        self.assertEqual(self.main('--pr', self.PR, '--metadata', meta=([], [], self.pr))[0], 0)
        self.assertEqual([event['payload']['result'] for event in self.events()], ['pass'])
        self.port.adapter.default.logs.clear()
        self.main('--pr', self.PR, '--metadata', '--no-publish', meta=([], [], self.pr))
        self.main('--metadata')
        self.assertEqual(self.events(), [])

    def test_a_publish_failure_never_changes_the_verdict(self):
        with patch.object(self.port, 'emit', side_effect=RuntimeError('forge down')):
            code, _, _, out = self.main('--pr', self.PR, '--metadata', meta=([], [], self.pr))
        self.assertEqual(code, 0)
        self.assertIn('pr.checked: not published (RuntimeError: forge down)', out)

    def test_the_gate_mark_runs_the_tree_part_only_in_its_own_tool_root(self):
        mine = {structure.TREE_ONLY_ENV: str(structure.ROOT)}
        code, tree, part, out = self.main('--pr', self.PR, env=mine)
        self.assertEqual((code, tree, part), (0, 1, 0))
        self.assertIn('structure-check (tree):', out)
        _, tree, part, _ = self.main('--pr', self.PR, env={structure.TREE_ONLY_ENV: self.tmp.name})
        self.assertEqual((tree, part), (1, 1))
        _, tree, part, _ = self.main('--pr', self.PR, '--metadata', env=mine)
        self.assertEqual((tree, part), (0, 1))


class GatedFetch(unittest.TestCase):
    def test_structure_check_judges_the_checkout_head_and_sha_overrides_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(['git', '-C', tmp, 'init', '-q'], check=True)
            subprocess.run(['git', '-C', tmp, '-c', 'user.email=t@example.com', '-c', 'user.name=T', 'commit', '-q',
                            '--allow-empty', '-m', 'Head'], check=True)
            head = subprocess.run(['git', '-C', tmp, 'rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip()
            with patch.object(structure.commit_check, 'fetch', return_value={}) as fetch:
                structure.gated_fetch(root, 1)
                structure.gated_fetch(root, 1, 'f' * len(head))
        self.assertEqual(fetch.call_args_list[0].args, (1, None, root))
        self.assertEqual(fetch.call_args_list[0].kwargs, {'head': head})
        self.assertEqual(fetch.call_args_list[-1].args, (1, 'f' * len(head), root))


class PlanCompletenessAtGate(unittest.TestCase):
    """GX-21: the `pr metadata` stage refuses an unticked plan item and an undecidable lane on the head itself."""

    BODY = '## Plan\n- [ ] 1. first\n- [ ] 2. second\n- [ ] 3. third\n'

    def test_the_615_shape_item_three_unticked_is_red_naming_it(self):
        commits = [{'message': 'a\n\nPlan: 1', 'files': ['a.py']}, {'message': 'b\n\nPlan: 2', 'files': ['b.py']}]
        errors = structure.plan_completeness_errors(self.BODY, commits)
        self.assertEqual(len(errors), 1)
        self.assertIn('item(s) 3 not ticked', errors[0])
        self.assertIn('edit the PR body', errors[0])
        self.assertIn('REAL commit', errors[0])
        self.assertIn('never an empty one', errors[0])

    def test_an_empty_commit_with_the_trailer_does_not_clear_it(self):
        commits = [{'message': 'a\n\nPlan: 1, 2', 'files': ['a.py']}, {'message': 'x\n\nPlan: 3', 'files': []}]
        self.assertIn('item(s) 3 not ticked', structure.plan_completeness_errors(self.BODY, commits)[0])

    def test_a_real_commit_for_every_item_is_green(self):
        commits = [{'message': 'a\n\nPlan: 1, 2, 3', 'files': ['a.py']}]
        self.assertEqual(structure.plan_completeness_errors(self.BODY, commits), [])

    def test_a_body_without_items_is_left_to_the_plan_count_check(self):
        self.assertEqual(structure.plan_completeness_errors('no plan', []), [])

    def test_d083_a_draft_head_is_judged_on_what_its_commits_delivered(self):
        """A serial PR is green on every commit while its plan is still a plan; the rest is a warning naming them."""
        commits = [{'message': 'a\n\nPlan: 1', 'files': ['a.py']}]
        errors, warnings = structure.plan_verdict(self.BODY, commits, draft=True)
        self.assertEqual(errors, [])
        self.assertEqual(len(warnings), 1)
        self.assertIn('item(s) 2, 3 not ticked', warnings[0])
        self.assertIn('D-083', warnings[0])

    def test_d083_a_ready_pr_is_refused_as_gx21_says(self):
        commits = [{'message': 'a\n\nPlan: 1', 'files': ['a.py']}]
        errors, warnings = structure.plan_verdict(self.BODY, commits, draft=False)
        self.assertEqual(errors, structure.plan_completeness_errors(self.BODY, commits))
        self.assertEqual(warnings, [])
        self.assertEqual(structure.plan_verdict(self.BODY, [{'message': 'a\n\nPlan: 1, 2, 3', 'files': ['a.py']}],
                                                draft=True), ([], []))

    LANE_MANIFESTS = {'engine': {'id': 'engine', 'owner': 'lane-a', 'paths': ['scripts/engine/**', 'scripts/census/**'],
                                 'shared': ['scripts/census/**']},
                      'admin': {'id': 'admin', 'owner': 'lane-b', 'paths': ['apps/admin/**', 'apps/tsconfig.json'],
                                'shared': ['apps/tsconfig.json']}}

    def lane_fixture(self, tmp):
        for unit, manifest in self.LANE_MANIFESTS.items():
            path = Path(tmp, 'units', unit, 'unit.json')
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps(manifest))
        subprocess.run(['git', '-C', tmp, 'init', '-q'], check=True)
        subprocess.run(['git', '-C', tmp, 'add', '-A'], check=True)
        subprocess.run(['git', '-C', tmp, '-c', 'user.email=t@example.com', '-c', 'user.name=T', 'commit', '-q', '-m', 'base'],
                       check=True)
        return train_ownership.UnitOwnership(train_git.GitWorkspace(Path(tmp)))

    def lane_errors(self, changed):
        with tempfile.TemporaryDirectory() as tmp:
            self.lane_fixture(tmp)
            return structure.lane_errors(Path(tmp), 'HEAD', changed)

    def test_a_change_across_lanes_is_refused_with_the_units_listed(self):
        errors = self.lane_errors(['scripts/engine/a.py', 'apps/admin/r.ts'])
        self.assertEqual(len(errors), 1)
        self.assertIn('lane undecidable', errors[0])
        self.assertIn('admin (lane-b), engine (lane-a)', errors[0])

    def test_one_lane_or_no_unit_is_decidable(self):
        self.assertEqual(self.lane_errors(['scripts/engine/a.py', 'scripts/engine/b.py']), [])
        self.assertEqual(self.lane_errors(['docs/free.md']), [])

    def test_lane_own_a_shared_path_alone_leaves_the_lane_decidable(self):
        self.assertEqual(self.lane_errors(['apps/admin/r.ts', 'scripts/census/admin.json']), [])
        self.assertEqual(self.lane_errors(['scripts/engine/a.py', 'apps/tsconfig.json']), [])

    def test_lane_own_a_shared_path_with_a_real_second_lane_is_still_refused(self):
        errors = self.lane_errors(['scripts/engine/a.py', 'apps/admin/r.ts', 'scripts/census/admin.json'])
        self.assertEqual(len(errors), 1)
        self.assertIn('admin (lane-b), engine (lane-a)', errors[0])

    def test_lane_own_a_change_of_only_shared_paths_has_no_lane(self):
        changed = ['scripts/census/admin.json', 'apps/tsconfig.json']
        self.assertEqual(self.lane_errors(changed), [])
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(self.lane_fixture(tmp).lane_of('HEAD', changed))

    def test_lane_own_a_shared_path_names_its_owner_and_never_refuses(self):
        """Sharing removes the ambiguity and the wait, never the owner (SHARED-NEEDS-NO-OWNER): owner_of() and units()
        still name lane-a's unit for its shared path, and refusals() never asks lane-a to approve it."""
        changed = ['apps/admin/r.ts', 'scripts/census/admin.json']
        with tempfile.TemporaryDirectory() as tmp:
            ownership = self.lane_fixture(tmp)
            self.assertEqual(ownership.lane_of('HEAD', changed), 'lane-b')
            self.assertEqual(ownership.owner_of('HEAD', 'scripts/census/admin.json'), ('engine', 'lane-a'))
            self.assertEqual(sorted(ownership.units('HEAD', changed)), ['admin', 'engine'])
            self.assertEqual(ownership.refusals('HEAD', changed, 'lane-b', lambda: self.fail('nobody is asked')), [])
            self.assertEqual(ownership.refusals('HEAD', ['scripts/engine/a.py', 'scripts/census/a.json'], 'lane-a', list), [])
            self.assertEqual(ownership.refusals('HEAD', ['scripts/engine/a.py', 'scripts/census/a.json'], 'lane-b', list),
                             [{'unit': 'engine', 'owner': 'lane-a', 'files': ['scripts/engine/a.py']}])

    def test_lane_own_lane_of_and_lane_errors_agree(self):
        """A change lane_of names a lane for is never refused, and a refused change has no lane (train_ownership)."""
        cases = {('scripts/engine/a.py',): 'lane-a', ('docs/free.md',): None,
                 ('apps/admin/r.ts', 'scripts/census/admin.json'): 'lane-b', ('scripts/census/admin.json',): None,
                 ('scripts/engine/a.py', 'apps/tsconfig.json'): 'lane-a',
                 ('scripts/engine/a.py', 'apps/admin/r.ts'): None,
                 ('scripts/engine/a.py', 'apps/admin/r.ts', 'apps/tsconfig.json'): None}
        refused = {('scripts/engine/a.py', 'apps/admin/r.ts'), ('scripts/engine/a.py', 'apps/admin/r.ts', 'apps/tsconfig.json')}
        with tempfile.TemporaryDirectory() as tmp:
            ownership = self.lane_fixture(tmp)
            for changed, lane in cases.items():
                self.assertEqual(ownership.lane_of('HEAD', list(changed)), lane, changed)
                self.assertEqual(bool(structure.lane_errors(Path(tmp), 'HEAD', list(changed))), changed in refused, changed)


class DecisionClock(unittest.TestCase):
    """S2 (D-196): a row from structure.decision_clock_from on has a number written once and a time not after the clock."""
    NOW = datetime.fromisoformat('2026-11-02T12:00:00+00:00')  # 09:00 on the 2nd in the rows' zone
    FIRST = config.get('structure.decision_clock_from')

    def errors(self, *stamps, first=None):
        number = self.FIRST if first is None else first
        rows = [[f'D-{number + index}', stamp] for index, stamp in enumerate(stamps)]
        return structure.clock_errors(rows, self.NOW)

    def test_a_time_before_the_clock_and_a_day_before_pass(self):
        self.assertEqual(self.errors('2026-11-02 08:59 BRT (x)', '2026-11-01 23:59 BRT', '2026-11-02 (x)'), [])

    def test_a_time_after_the_clock_is_refused_by_the_minute_and_by_the_day(self):
        found = self.errors('2026-11-02 09:01 BRT (x)', '2026-11-03 (x)')
        self.assertEqual(len(found), len(['minute', 'day']))
        self.assertIn('later than the clock (2026-11-02 09:00)', found[0])

    def test_a_number_written_twice_is_refused_but_not_before_the_first_checked_number(self):
        rows = [[f'D-{self.FIRST}', 'x'], [f'D-{self.FIRST}', 'x']]
        self.assertIn('written twice', ' '.join(structure.clock_errors(rows, self.NOW)))
        early = [[f'D-{self.FIRST - 1}', '2030-01-01 00:00 BRT']] * len(rows)
        self.assertEqual(structure.clock_errors(early, self.NOW), [])


class ExceptionRegime(unittest.TestCase):
    def test_a_refusal_becomes_a_named_warning_while_the_regime_lifts_the_lock(self):
        import structure
        errors, warnings = structure.under_regime(['FAIL one'], ['WARN kept'], True)
        self.assertEqual(errors, [])
        self.assertEqual(warnings, ['WARN kept', 'structure lock lifted by the exception regime: FAIL one'])

    def test_a_refusal_stays_a_refusal_outside_the_regime(self):
        import structure
        self.assertEqual(structure.under_regime(['FAIL one'], [], False), (['FAIL one'], []))

    def test_a_read_failure_is_not_lifted_while_a_rule_finding_beside_it_is(self):
        """GC (D-260, D-300): the regime is for rule debt, not for blindness."""
        import structure
        blind = structure.Blind('commit-check: PR #7 not readable (HTTP 500)')
        errors, warnings = structure.under_regime([blind, 'plan: no commit plan'], [], True)
        self.assertEqual(errors, [blind])
        self.assertEqual(warnings, ['structure lock lifted by the exception regime: plan: no commit plan'])

    def test_an_unreadable_pr_fails_the_metadata_stage_while_the_regime_is_active(self):
        import structure
        for failure in (RuntimeError('HTTP 500 /v1/events'), OSError('connection reset'), KeyError('head_ref')):
            with tempfile.TemporaryDirectory() as tmp, \
                    patch.object(structure, 'gated_fetch', side_effect=failure), \
                    patch.object(structure, '_lifted', return_value=True), \
                    patch('builtins.print') as printed:
                code = structure.main(['--root', tmp, '--pr', '7', '--metadata', '--no-publish'])
            out = ' '.join(str(call.args[0]) for call in printed.call_args_list)
            self.assertEqual(code, 1, out)
            self.assertIn('FAIL commit-check: PR #7 not readable', out)
            self.assertNotIn('lifted by the exception regime', out)

    def test_an_unreadable_review_fails_while_the_regime_is_active(self):
        import structure
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(structure, 'fetch_review', side_effect=RuntimeError('HTTP 500')), \
                patch.object(structure, '_lifted', return_value=True), patch('builtins.print') as printed:
            code = structure.main(['--root', tmp, '--review', '7', '--metadata', '--no-publish'])
        self.assertEqual(code, 1)
        self.assertIn('FAIL review: PR #7 not readable', ' '.join(str(call.args[0]) for call in printed.call_args_list))


class LiftedLock(unittest.TestCase):
    def test_without_the_regime_module_the_lock_stands(self):
        import structure
        with unittest.mock.patch.dict(sys.modules, {'regime': None}):
            self.assertFalse(structure._lifted('structure'))

    def test_the_lock_follows_the_regime_module(self):
        import structure
        fake = type('Regime', (), {'lifted': staticmethod(lambda lock: lock == 'structure')})
        with unittest.mock.patch.dict(sys.modules, {'regime': fake}):
            self.assertTrue(structure._lifted('structure'))


class ForgeMetricCommentsMigration(unittest.TestCase):
    def test_metric_preserves_latest_pass_in_its_original_comment_window(self):
        from unittest.mock import patch
        import forge_events
        import idea_to_prod
        import forge_doubles
        comments = [{'body': 'unrelated', 'created_at': 'early', 'author_association': None},
                    {'body': 'ship-tail ship-verify: pass', 'created_at': 'passed', 'author_association': None}]
        for answer, expected in ((comments, 'passed'), ([], None)):
            asked = []
            adapter = forge_doubles.origin(comments=lambda repo, number, answer=answer: asked.append(number) or answer)
            with patch.object(forge_events, 'adapter_from_config', return_value=adapter):
                self.assertEqual(idea_to_prod.GitHub().live_at({'number': 1}), expected)
            self.assertEqual(asked, [1])


class ForgeReviewMigration(unittest.TestCase):
    def test_review_preserves_body_head_and_comment_order(self):
        from unittest.mock import patch
        import forge_events
        import forge_doubles
        asked = []
        change = {'head': 'h', 'base': 'b', 'body': None}
        comments = [{'body': 'first'}, {'body': ''}, {'body': 'last'}]
        adapter = forge_doubles.origin(change=lambda repo, number: asked.append('change') or change,
                                       comments=lambda repo, number: asked.append('comments') or comments)
        with patch.object(forge_events, 'adapter_from_config', return_value=adapter):
            self.assertEqual(structure.fetch_review(1), ('', 'h', ['first', '', 'last']))
        self.assertEqual(asked, ['change', 'comments'])


# F113: the classes are fixture-repository work that waits on git, so one process ran them in series (25 s for 22 s of
# tests). A bare run starts these groups as side-by-side processes (about the longest group, 10 s); named classes run as is.
GROUPS = [
    ['StructureCheck'],
    ['TreeCache', 'PlanCompletenessAtGate'],
    ['IdeaToProd', 'ReviewErrors', 'MetadataPart', 'GatedFetch', 'DecisionClock', 'ExceptionRegime', 'LiftedLock',
     'ForgeMetricCommentsMigration', 'ForgeReviewMigration'],
]


def run_groups():
    names = {name for name, value in globals().items() if isinstance(value, type) and issubclass(value, unittest.TestCase)}
    assert names == {name for group in GROUPS for name in group}, 'GROUPS must list every test class'
    procs = [subprocess.Popen([sys.executable, __file__, *group], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
             for group in GROUPS]
    outs = [(proc.communicate()[0], proc) for proc in procs]
    for out, _ in outs:
        sys.stdout.write(out)
    return 1 if any(proc.returncode for _, proc in outs) else 0


if __name__ == '__main__':
    if len(sys.argv) == 1:
        sys.exit(run_groups())
    unittest.main()
