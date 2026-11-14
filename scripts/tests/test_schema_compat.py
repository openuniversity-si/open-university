"""The schema compat stage (D-068 (5), D-069 item 2, P-07): contract shape, additive change within a version, version
succession, retirement and registry compatibility against the base, and the stage's wiring in the gate.

Fixture git repositories in a temporary directory; no network, no clock.
"""
import contextlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import gate_areas  # noqa: E402
import gate_policy  # noqa: E402
import json_schema  # noqa: E402
import schema_compat  # noqa: E402

COPIED = ('contracts/config/registry.v1.json', 'contracts/events/config.changed.v1.json', 'config/registry/config.json',
          'config/registry/contracts.json', 'config/registry/generate.json')
EVENT = 'contracts/events/config.changed.v1.json'


def train(**extra):
    batch = {'type': 'integer', 'default': 8, 'minimum': 1, 'x-unit': 'count', 'description': 'PRs per batch.',
             'x-readers': []}
    batch.update(extra)
    return {'$schema': json_schema.DIALECT, '$id': 'config/registry/train.json', 'x-owner': 'train',
            'x-schema-version': 1, 'type': 'object', 'additionalProperties': False,
            'properties': {'train.batch_size': batch}}


class Repo(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        for name in COPIED:
            (self.root / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(ROOT / name, self.root / name)
        self.write('config/registry/train.json', train())
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name, content):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content if isinstance(content, str) else json.dumps(content))

    def read(self, name):
        return json.loads((self.root / name).read_text())

    def commit(self, message='base'):
        git = ['git', '-C', str(self.root), '-c', 'user.name=t', '-c', 'user.email=t@example.invalid']
        subprocess.run(git + ['add', '-A'], check=True)
        subprocess.run(git + ['commit', '-qm', message], check=True)
        return subprocess.run(git + ['rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip()

    def check(self, base=None):
        subprocess.run(['git', '-C', str(self.root), 'add', '-A'], check=True)
        return '\n'.join(schema_compat.check(self.root, base))

    def version(self, document, number):
        path = EVENT.replace('.v1.json', f'.v{number}.json')
        self.write(path, {**document, '$id': path})
        return path


class Shape(Repo):
    def test_a_contract_is_versioned_identified_and_inside_the_subset(self):
        self.write('contracts/events/thing.json', {'$schema': json_schema.DIALECT, '$id': 'contracts/events/thing.json'})
        self.write('contracts/events/other.v1.json', {'$schema': json_schema.DIALECT, '$id': 'x', 'dependentRequired': {}})
        self.write('contracts/events/schemas.lock.json', [])
        errors = self.check()
        self.assertIn('contracts/events/thing.json: a contract is named contracts/<area>/<name>.v<N>.json', errors)
        self.assertIn("contracts/events/other.v1.json: $id is 'x', not its path", errors)
        self.assertIn('dependentRequired', errors)
        self.assertNotIn('schemas.lock.json', errors)

    def test_a_contract_that_is_not_json_is_named_and_the_rest_are_still_judged(self):
        self.write('contracts/events/broken.v1.json', '{not json')
        self.write('contracts/events/thing.json', {'$schema': json_schema.DIALECT, '$id': 'contracts/events/thing.json'})
        errors = self.check()
        self.assertIn('contracts/events/broken.v1.json: not JSON (', errors)
        self.assertIn('contracts/events/thing.json: a contract is named', errors)

    def test_the_repository_contracts_pass_without_a_base(self):
        self.assertEqual(schema_compat.check(ROOT), [])


class Additive(Repo):
    def test_an_existing_version_changes_only_additively(self):
        base = self.commit()
        document = self.read(EVENT)
        document['properties']['extra'] = {'type': 'string'}
        self.write(EVENT, document)
        self.assertEqual(self.check(base), '')
        document['required'].append('extra')
        self.write(EVENT, document)
        self.assertIn('incompatible change', self.check(base))

    def test_a_removed_definition_is_a_breaking_change(self):
        document = {**self.read(EVENT), '$defs': {'who': {'type': 'string'}, 'old': {'type': 'string'}}}
        self.write(EVENT, document)
        base = self.commit()
        self.write(EVENT, {**document, '$defs': {'who': {'type': 'string'}}})
        self.assertIn('$defs/old: removed without a revision that marked it deprecated', self.check(base))
        self.write(EVENT, {**document, '$defs': {'who': {'type': 'string'}, 'old': {'type': 'string', 'deprecated': True}}})
        base = self.commit('deprecate')
        self.write(EVENT, {**document, '$defs': {'who': {'type': 'string'}}})
        self.assertEqual(self.check(base), '')


class Succession(Repo):
    def test_a_breaking_change_is_a_new_version_that_follows_the_last(self):
        base = self.commit()
        document = self.read(EVENT)
        document['required'].append('extra')
        document['properties']['extra'] = {'type': 'string'}
        self.version(document, 2)
        self.assertEqual(self.check(base), '')
        skipped = self.version(document, 4)
        self.assertIn(f'{skipped}: a new version follows contracts/events/config.changed.v3.json', self.check(base))

    def test_a_version_whose_predecessor_was_retired_stays_valid(self):
        self.version(self.read(EVENT), 2)
        (self.root / EVENT).unlink()
        base = self.commit()
        self.write('contracts/events/config.changed.v2.json', {**self.read('contracts/events/config.changed.v2.json'),
                                                               'description': 'still v2'})
        self.assertEqual(self.check(base), '')


class Retirement(Repo):
    def test_a_version_is_deleted_only_when_nothing_but_generated_files_names_it(self):
        self.write('scripts/lib/generated/contracts_events_config_changed_v1.py', f'# from {EVENT}\n')
        base = self.commit()
        (self.root / EVENT).unlink()
        self.assertEqual(self.check(base), '')
        shutil.copy(ROOT / EVENT, self.root / EVENT)
        self.write('scripts/lib/reader.py', f'SCHEMA = "{EVENT}"\n')
        base = self.commit('reader')
        (self.root / EVENT).unlink()
        self.assertIn(f'{EVENT}: deleted while scripts/lib/reader.py still reference it', self.check(base))


class Registry(Repo):
    """D-289: a parameter leaves when the tree proves nothing reads it; a key still named somewhere needs the
    deprecated revision first."""

    def test_a_split_object_parameter_is_not_an_independent_registry_owner(self):
        fragment = 'config/registry/train/train.object.json'
        self.write(fragment, {'type': 'object', 'properties': {'nested': {'type': 'string'}}})
        base = self.commit('split parameter')
        self.write(fragment, {'type': 'object', 'properties': {}})
        # Registry compatibility judges the effective generated owner, which has not changed here.
        # Generated drift independently refuses a fragment/owner mismatch.
        self.assertEqual(self.check(base), '')

    def test_a_parameter_with_no_reader_leaves_in_one_revision(self):
        base = self.commit()
        self.write('config/registry/train.json', {**train(), 'properties': {}})
        self.assertEqual(self.check(base), '')

    def test_a_parameter_a_source_still_names_cannot_leave(self):
        self.write('scripts/lib/reader.py', 'import config\nBATCH = config.get("train.batch_size")\n')
        base = self.commit('reader')
        self.write('config/registry/train.json', {**train(), 'properties': {}})
        self.assertIn('train.batch_size: removed while scripts/lib/reader.py still name it', self.check(base))

    def test_a_test_that_still_names_the_parameter_counts_as_a_reader(self):
        self.write('scripts/tests/test_reader.py', 'from config import get\nBATCH = get("train.batch_size")\n')
        base = self.commit('reader')
        self.write('config/registry/train.json', {**train(), 'properties': {}})
        self.assertIn('scripts/tests/test_reader.py still name it', self.check(base))

    def test_prose_and_generated_modules_are_not_readers(self):
        self.write('docs/note.md', 'The parameter train.batch_size sets the batch.\n')
        self.write('scripts/lib/generated/train_types.py', "BATCH = 'train.batch_size'\n")
        base = self.commit('prose')
        self.write('config/registry/train.json', {**train(), 'properties': {}})
        self.assertEqual(self.check(base), '')


class Stage(Repo):
    STAGE = 'schema compat'

    def test_the_command_prints_its_errors_and_exits_one(self):
        self.write('contracts/events/thing.json', {'$schema': json_schema.DIALECT, '$id': 'contracts/events/thing.json'})
        self.check()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = schema_compat.main(['--root', str(self.root)])
        self.assertEqual(code, 1)
        self.assertIn('FAIL contracts/events/thing.json: a contract is named', out.getvalue())
        self.assertIn('(no base: shape only); 1 error(s)', out.getvalue())

    def test_the_stage_runs_on_every_plan_with_the_pr_base(self):
        self.assertIn(self.STAGE, gate_policy.PREREQUISITES)
        for plan in (gate_areas.plan_for(['docs/x.md']), gate_areas.plan_for(['products/demo/src/ui/x.tsx'])):
            self.assertIn(self.STAGE, plan['stages'])
        self.assertIn(f'launch step_cached_by_inputs "{self.STAGE}" "$root" "${{base:-}}" "$tool_root/scripts/schema-compat" ${{base:+--base "$base"}}',
                      (ROOT / 'scripts/gate-local').read_text())


if __name__ == '__main__':
    unittest.main()
