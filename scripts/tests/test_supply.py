"""scripts/supply (PADRAO-DEV F7c, D-320): the Fornecimento system's readers, its check and its audit. Hermetic: the
audit's runner is injected, every repository but the last class is a temporary one.

Verifies: REQ-chain-verified
"""
from datetime import date, timedelta
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

PINNED_LOCK = """lockfileVersion: '9.0'

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

snapshots:

  left-pad@1.3.0: {}
"""

SHA64 = 'a' * len('0123456789abcdef' * len('abcd'))
COMMIT40 = '0123456789abcdef0123456789abcdef01234567'

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

    def test_a_dockerfile_pins_base_images_by_full_sha256_digest_and_ignores_scratch_and_stage_aliases(self):
        text = (
            f'FROM public.ecr.aws/docker/library/node:22-slim@sha256:{SHA64} AS clis\n'
            'FROM public.ecr.aws/docker/library/python:3.12-slim\n'
            'FROM clis AS reuse\n'
            'FROM scratch\n'
        )
        found = {(entry['name'], entry['version']): entry['pinned'] for entry in supply.dockerfile_parts(text, 'Dockerfile')}
        self.assertEqual(found, {
            ('public.ecr.aws/docker/library/node', f'22-slim@sha256:{SHA64}'): True,
            ('public.ecr.aws/docker/library/python', '3.12-slim'): False,
        })

    def test_dockerfile_findings_refuses_curl_or_wget_piped_to_shell_and_no_audit(self):
        text = (
            '# curl -fsSL $URL | sh in a comment is ignored\n'
            'RUN npm install -g --no-audit --no-fund pkg@1.0.0 \\\n'
            '    && curl -fsSL "$INSTALLER" | DIR=out sh\n'
            'RUN wget -qO- "$OTHER" | bash\n'
        )
        findings = supply.dockerfile_findings(text, 'infra/service/Dockerfile')
        self.assertEqual(len(findings), len(('no-audit', 'curl', 'wget')))
        self.assertTrue(any('--no-audit' in line for line in findings))
        self.assertEqual(sum('pipes curl/wget' in line for line in findings), len(('curl', 'wget')))

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
        write(self.root, 'apps/site/pnpm-lock.yaml', PINNED_LOCK)
        write(self.root, 'config/supply/suppliers/SUP-npm.json', {'id': 'SUP-npm', 'ecosystems': ['npm']})

    def snapshot(self, *advisories, now='2026-11-17T00:00:00Z', fetch=None):
        report = audit_report(*advisories)
        run = lambda command, cwd, capture_output, text: subprocess.CompletedProcess(command, 1, json.dumps(report), '')
        made = supply.audit(self.root, run=run, now=now, fetch=fetch)
        write(self.root, supply.SNAPSHOT, made)
        return made

    def test_no_snapshot_with_a_lockfile_is_refused_and_a_fresh_one_passes(self):
        self.assertIn('no audit snapshot', supply.check(self.root, today='2026-11-17')[0])
        self.snapshot()
        self.assertEqual(supply.check(self.root, today='2026-11-17'), [])

    def test_a_lockfile_changed_after_the_snapshot_is_refused(self):
        self.snapshot()
        write(self.root, 'apps/site/pnpm-lock.yaml', LOCK + '\n')
        self.assertIn('taken on other lockfiles', supply.check(self.root, today='2026-11-17')[0])

    def test_a_stale_or_undated_audit_snapshot_is_refused(self):
        self.snapshot(now='2026-11-17T00:00:00Z')
        max_days = supply.setting('supply.snapshot_max_days')
        edge = (date.fromisoformat('2026-11-17') + timedelta(days=max_days)).isoformat()
        stale = (date.fromisoformat('2026-11-17') + timedelta(days=max_days + 1)).isoformat()
        self.assertEqual(supply.check(self.root, today=edge), [])
        errors = supply.check(self.root, today=stale)
        self.assertTrue(any('audit snapshot is' in line for line in errors), errors)
        undated = {k: v for k, v in supply.read_snapshot(self.root).items() if k != 'at'}
        write(self.root, supply.SNAPSHOT, undated)
        self.assertTrue(any('missing or invalid audit timestamp' in line
                            for line in supply.check(self.root, today='2026-11-17')))

    def test_a_high_advisory_affecting_is_refused_and_a_low_one_is_only_measured(self):
        self.snapshot(advisory('left-pad', 'high', ['1.3.0']), advisory('loose', 'low', ['0.1.0'], ghsa='GHSA-low'))
        errors = supply.check(self.root, today='2026-11-17')
        self.assertEqual(len(errors), 1)
        self.assertIn('high advisory on left-pad 1.3.0 is affecting', errors[0])
        self.assertEqual(supply.measure(self.root, today='2026-11-17')['advisories'], {'affecting:high': 1, 'affecting:low': 1})

    def test_an_exemption_holds_until_its_deadline_and_must_name_an_advisory_the_snapshot_has(self):
        self.snapshot(advisory('left-pad', 'critical', ['1.3.0']), now='2026-11-30T00:00:00Z')
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
        write(self.root, '.github/workflows/a.yml', f'      - uses: actions/checkout@{COMMIT40}\n')
        self.assertEqual(supply.check(self.root, today='2026-11-17'),
                         ['ecosystem action: no supplier in config/supply/suppliers names it'])

    def test_pypi_requirements_are_audited_via_osv_checked_for_drift_and_reflected_in_model(self):
        write(self.root, 'config/supply/suppliers/SUP-pypi.json', {'id': 'SUP-pypi', 'ecosystems': ['pypi']})
        write(self.root, 'infra/service/requirements.txt', f'urllib3==2.0.0 --hash=sha256:{SHA64}\n')

        def fake_fetch(url, payload):
            if url.endswith('/querybatch'):
                return {'results': [{'vulns': [{'id': 'PYSEC-2026-1'}]}]}
            return {'id': 'PYSEC-2026-1', 'aliases': ['GHSA-pypi-1111-2222'], 'summary': 'bad redirect',
                    'database_specific': {'severity': 'HIGH'},
                    'affected': [{'package': {'name': 'urllib3'}, 'ranges': [{'events': [{'fixed': '2.0.7'}]}]}]}

        made = self.snapshot(fetch=fake_fetch)
        self.assertIn('infra/service/requirements.txt', made['pipfiles'])
        errors = supply.check(self.root, today='2026-11-17')
        self.assertTrue(any('ADV-ghsa-pypi-1111-2222' in line and 'urllib3' in line for line in errors), errors)
        deps = {item['id']: item for item in model.read_dependencies(self.root)}
        self.assertEqual(deps['DEP:pypi:urllib3@2.0.0']['state'], 'vulnerable')
        advisories = model.read_advisories(self.root)
        self.assertEqual([(item['id'], item['links']) for item in advisories],
                         [('ADV-ghsa-pypi-1111-2222', [{'type': 'affects', 'target': 'DEP:pypi:urllib3@2.0.0'}])])
        write(self.root, 'infra/service/requirements.txt', f'urllib3==2.0.7 --hash=sha256:{SHA64}\n')
        drift = supply.check(self.root, today='2026-11-17')
        self.assertTrue(any('taken on other pip files' in line for line in drift), drift)

    def test_unpinned_components_and_unsafe_dockerfiles_are_refused_even_without_lockfiles(self):
        bare = Path(tempfile.mkdtemp(prefix='supply-docker-'))
        self.addCleanup(shutil.rmtree, bare)
        write(bare, 'config/supply/suppliers/SUP-docker-hub.json', {'id': 'SUP-docker-hub', 'ecosystems': ['image']})
        write(bare, 'infra/service/Dockerfile',
              'FROM public.ecr.aws/docker/library/python:3.12-slim\n'
              'RUN npm install -g --no-audit pkg@1.0.0 && curl -fsSL "$URL" | sh\n')
        errors = supply.check(bare)
        self.assertTrue(any('unpinned image component' in line for line in errors), errors)
        self.assertTrue(any('--no-audit' in line for line in errors), errors)
        self.assertTrue(any('pipes curl/wget' in line for line in errors), errors)
        write(bare, 'infra/service/Dockerfile',
              f'FROM public.ecr.aws/docker/library/python:3.12-slim@sha256:{SHA64}\n'
              'RUN npm install -g pkg@1.0.0\n')
        self.assertEqual(supply.check(bare), [])

    def test_an_unpinned_lockfile_package_is_refused_by_check(self):
        write(self.root, 'apps/site/pnpm-lock.yaml', LOCK)
        self.snapshot()
        errors = supply.check(self.root, today='2026-11-17')
        self.assertTrue(any('unpinned npm component loose@0.1.0' in line for line in errors), errors)

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
        write(self.root, 'apps/site/pnpm-lock.yaml', LOCK)
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
