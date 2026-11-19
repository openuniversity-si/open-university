"""scripts/supply (PADRAO-DEV F7c, D-320): the Fornecimento system's readers, its check and its audit. Hermetic: the
audit's runner is injected, every repository but the last class is a temporary one.

Verifies: REQ-chain-verified
"""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import model  # noqa: E402
import supply  # noqa: E402

LOCK = """lockfileVersion: '9.0'

importers:

  .:
    dependencies:
      left-pad:
        specifier: 1.3.0
        version: 1.3.0

packages:

  '@scope/kit@2.0.1':
    resolution: {integrity: sha512-abc}

  left-pad@1.3.0:
    resolution: {integrity: sha512-def}

  loose@0.1.0:
    resolution: {tarball: https://example.invalid/loose.tgz}

snapshots:

  left-pad@1.3.0: {}
"""

WORKFLOW = """jobs:
  web:
    services:
      postgres:
        image: postgres:18
    steps:
      - uses: actions/checkout@v4
      - uses: actions/cache@0123456789abcdef0123456789abcdef01234567
      - uses: ./local-action
"""


def write(root, path, data):
    target = Path(root) / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(data if isinstance(data, str) else json.dumps(data))


def audit_report(*advisories):
    return {'advisories': {str(number): advisory for number, advisory in enumerate(advisories)}}


def advisory(package, severity, versions, ghsa='GHSA-aaaa-bbbb-cccc', patched='>=9.9.9'):
    return {'id': 1, 'github_advisory_id': ghsa, 'module_name': package, 'severity': severity, 'title': 't',
            'vulnerable_versions': '<9.9.9', 'patched_versions': patched, 'findings': [{'version': v} for v in versions]}


class Readers(unittest.TestCase):
    def test_a_lockfile_package_is_pinned_by_its_integrity_and_scoped_names_keep_their_scope(self):
        found = {(entry['name'], entry['version']): entry['pinned'] for entry in supply.lock_packages(LOCK, 'x')}
        self.assertEqual(found, {('@scope/kit', '2.0.1'): True, ('left-pad', '1.3.0'): True, ('loose', '0.1.0'): False})

    def test_an_action_is_pinned_by_a_commit_and_an_image_by_a_digest_never_by_a_tag(self):
        found = {(entry['ecosystem'], entry['name'], entry['version']): entry['pinned']
                 for entry in supply.workflow_parts(WORKFLOW, 'w.yml')}
        self.assertEqual(found, {('image', 'postgres', '18'): False, ('action', 'actions/checkout', 'v4'): False,
                                 ('action', 'actions/cache', '0123456789abcdef0123456789abcdef01234567'): True})
        digest = supply.workflow_parts('    image: postgres:18@sha256:' + 'a' * len('0123456789abcdef'), 'w')
        self.assertTrue(digest[0]['pinned'])

    def test_a_pip_requirement_is_pinned_only_with_its_hash(self):
        found = supply.pip_parts('boto3==1.0.0\nrich[x]==2.0 --hash=sha256:ab\n# c==1\nloose>=1\n', 'r.txt')
        self.assertEqual([(entry['name'], entry['pinned']) for entry in found], [('boto3', False), ('rich', True)])

    def test_a_hash_locked_file_pins_each_requirement_by_its_continued_hash_lines(self):
        # D-335: the form uv and pip-compile write (--generate-hashes): the hashes on the lines a backslash continues
        text = ('# header\nanyio==4.16.0 \\\n    --hash=sha256:aa \\\n    --hash=sha256:bb\n'
                "tzdata==2026.6 ; sys_platform == 'win32' \\\n    --hash=sha256:cc\nloose==1.0\n")
        found = supply.pip_parts(text, 'r.txt')
        self.assertEqual([(entry['name'], entry['version'], entry['pinned']) for entry in found],
                         [('anyio', '4.16.0', True), ('tzdata', '2026.6', True), ('loose', '1.0', False)])

    def test_a_component_named_by_two_files_is_one_entry_pinned_only_if_both_pin_it(self):
        root = Path(tempfile.mkdtemp(prefix='supply-'))
        self.addCleanup(shutil.rmtree, root)
        write(root, '.github/workflows/a.yml', '      - uses: actions/checkout@v4\n')
        write(root, 'services/runner/github/b.yml', '      - uses: actions/checkout@v4\n')
        found = [entry for entry in supply.dependencies(root) if entry['ecosystem'] == 'action']
        self.assertEqual([entry['sources'] for entry in found], [['.github/workflows/a.yml', 'services/runner/github/b.yml']])


class Check(unittest.TestCase):
    """The check over a temporary repository: one lockfile, one workflow, suppliers for both ecosystems."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix='supply-check-'))
        self.addCleanup(shutil.rmtree, self.root)
        write(self.root, 'apps/site/pnpm-lock.yaml', LOCK)
        write(self.root, 'config/supply/suppliers/SUP-npm.json', {'id': 'SUP-npm', 'ecosystems': ['npm']})

    def snapshot(self, *advisories):
        report = audit_report(*advisories)
        run = lambda command, cwd, capture_output, text: subprocess.CompletedProcess(command, 1, json.dumps(report), '')
        made = supply.audit(self.root, run=run, now='2026-11-17T00:00:00Z')
        write(self.root, supply.SNAPSHOT, made)
        return made

    def test_no_snapshot_with_a_lockfile_is_refused_and_a_fresh_one_passes(self):
        self.assertIn('no audit snapshot', supply.check(self.root)[0])
        self.snapshot()
        self.assertEqual(supply.check(self.root), [])

    def test_a_lockfile_changed_after_the_snapshot_is_refused(self):
        self.snapshot()
        write(self.root, 'apps/site/pnpm-lock.yaml', LOCK + '\n')
        self.assertIn('taken on other lockfiles', supply.check(self.root)[0])

    def test_a_high_advisory_affecting_is_refused_and_a_low_one_is_only_measured(self):
        self.snapshot(advisory('left-pad', 'high', ['1.3.0']), advisory('loose', 'low', ['0.1.0'], ghsa='GHSA-low'))
        errors = supply.check(self.root, today='2026-11-17')
        self.assertEqual(len(errors), 1)
        self.assertIn('high advisory on left-pad 1.3.0 is affecting', errors[0])
        self.assertEqual(supply.measure(self.root, today='2026-11-17')['advisories'], {'affecting:high': 1, 'affecting:low': 1})

    def test_an_exemption_holds_until_its_deadline_and_must_name_an_advisory_the_snapshot_has(self):
        self.snapshot(advisory('left-pad', 'critical', ['1.3.0']))
        exemption = {'id': 'ADV-ghsa-aaaa-bbbb-cccc', 'reason': 'r', 'deadline': '2026-11-30', 'owner': 'o'}
        write(self.root, 'config/supply/exemptions/ADV-ghsa-aaaa-bbbb-cccc.json', exemption)
        self.assertEqual(supply.check(self.root, today='2026-11-30'), [])
        self.assertIn('is affecting', supply.check(self.root, today='2026-12-01')[0])
        # D-336: in force it keeps the check quiet, but only a decision that accepts it makes the advisory exempted
        advisory_ = supply.read_snapshot(self.root)['advisories'][0]
        self.assertEqual(supply.advisory_state(advisory_, exemption, '2026-11-30'), 'affecting')
        self.assertEqual(supply.advisory_state(advisory_, {**exemption, 'authorized_by': 'D-9'}, '2026-11-30'), 'exempted')
        self.assertEqual(supply.advisory_state(advisory_, {**exemption, 'authorized_by': 'D-9'}, '2026-12-01'), 'affecting')
        write(self.root, 'config/supply/exemptions/ADV-ghsa-gone.json', {**exemption, 'id': 'ADV-ghsa-gone'})
        self.assertTrue(any('does not have; remove it' in error for error in supply.check(self.root, today='2026-11-30')))

    def test_an_exemption_without_its_reason_breaks_its_contract(self):
        self.snapshot(advisory('left-pad', 'high', ['1.3.0']))
        write(self.root, 'config/supply/exemptions/ADV-ghsa-aaaa-bbbb-cccc.json',
              {'id': 'ADV-ghsa-aaaa-bbbb-cccc', 'deadline': '2026-11-30', 'owner': 'o'})
        self.assertTrue(any('reason' in error for error in supply.check(self.root, today='2026-11-17')))

    def test_a_component_of_an_ecosystem_no_supplier_names_is_refused(self):
        self.snapshot()
        write(self.root, '.github/workflows/a.yml', '      - uses: actions/checkout@v4\n')
        self.assertEqual(supply.check(self.root), ['ecosystem action: no supplier in config/supply/suppliers names it'])

    def test_an_untracked_lockfile_is_not_the_tree_s(self):
        import subprocess
        (self.root / 'apps/site').mkdir(parents=True, exist_ok=True)
        (self.root / 'apps/site/pnpm-lock.yaml').write_text('lockfileVersion: 9.0\n')
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)
        subprocess.run(['git', '-C', str(self.root), 'add', 'apps/site/pnpm-lock.yaml'], check=True)
        (self.root / '.claude/worktrees/agent/apps/site').mkdir(parents=True)
        (self.root / '.claude/worktrees/agent/apps/site/pnpm-lock.yaml').write_text('lockfileVersion: 9.0\n')
        self.assertEqual(supply.lockfiles(self.root), ['apps/site/pnpm-lock.yaml'])

    def test_the_audit_merges_one_advisory_found_in_two_lockfiles(self):
        write(self.root, 'apps/other/pnpm-lock.yaml', LOCK)
        made = self.snapshot(advisory('left-pad', 'high', ['1.3.0']))
        self.assertEqual(made['advisories'][0]['lockfiles'], ['apps/other/pnpm-lock.yaml', 'apps/site/pnpm-lock.yaml'])
        self.assertEqual(sorted(made['lockfiles']), ['apps/other/pnpm-lock.yaml', 'apps/site/pnpm-lock.yaml'])

    def test_an_audit_that_gives_no_report_stops_rather_than_writing_an_empty_snapshot(self):
        run = lambda command, cwd, capture_output, text: subprocess.CompletedProcess(command, 1, '', 'offline')
        with self.assertRaises(RuntimeError):
            supply.audit(self.root, run=run)

    def test_the_model_reads_a_vulnerable_component_supplied_by_its_supplier_and_its_advisory(self):
        self.snapshot(advisory('left-pad', 'high', ['1.3.0']))
        deps = {item['id']: item for item in model.read_dependencies(self.root)}
        self.assertEqual(deps['DEP:npm:left-pad@1.3.0']['state'], 'vulnerable')
        self.assertEqual(deps['DEP:npm:loose@0.1.0']['state'], 'unpinned')
        self.assertEqual(deps['DEP:npm:@scope/kit@2.0.1']['links'], [{'type': 'supplied-by', 'target': 'SUP-npm'}])
        advisories = model.read_advisories(self.root)
        self.assertEqual([(item['state'], item['links']) for item in advisories],
                         [('affecting', [{'type': 'affects', 'target': 'DEP:npm:left-pad@1.3.0'}])])

    def test_a_supplier_is_judged_an_account_by_its_budget_and_a_registry_by_what_it_supplies(self):
        """STD-supply-supplier-answers (D-335): the warnings that make a supplier non-conformant."""
        def sup(id, kind, **body):
            return {'id': id, 'type': 'SUP', 'state': body.pop('state', 'active'), 'fingerprint': 'f', 'links': [],
                    'body': {'id': id, 'kind': kind, **body}}
        found = {item['id']: item for item in (
            sup('SUP-paid', 'account', budget='REQ-cap'), sup('SUP-free', 'account'),
            sup('SUP-lost', 'account', budget='REQ-gone'), sup('SUP-used', 'registry'), sup('SUP-idle', 'platform'),
            sup('SUP-old', 'registry', state='retired'), sup('SUP-only-removed', 'registry'),
            {'id': 'REQ-cap', 'type': 'REQ', 'state': 'approved', 'fingerprint': 'f', 'links': []},
            {'id': 'DEP:npm:a@1', 'type': 'DEP', 'state': 'in-use', 'fingerprint': 'f',
             'links': [{'type': 'supplied-by', 'target': 'SUP-used'}]},
            {'id': 'DEP:npm:b@1', 'type': 'DEP', 'state': 'removed', 'fingerprint': 'f',
             'links': [{'type': 'supplied-by', 'target': 'SUP-only-removed'}]})}
        self.assertEqual(sorted(line.split(':', 1)[0] for line in model.supply_findings(found)),
                         ['SUP-free', 'SUP-idle', 'SUP-lost', 'SUP-only-removed'])
        self.assertTrue(model.judged(model.metamodel(ROOT), 'SUP'))


class RealRepository(unittest.TestCase):
    """The gate check: this tree's lockfiles were audited as they are, and no high or critical advisory is affecting."""

    def test_the_supply_check_of_this_repository_passes(self):
        self.assertEqual(supply.check(ROOT), [])


if __name__ == '__main__':
    unittest.main()
