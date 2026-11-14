"""The registry's gate check (D-068 (6)): literals of registered parameters in the engine paths, inline fallbacks,
literal sites that only shrink, and the structure-check wiring (contract compatibility: test_schema_compat.py).

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
from unittest import mock
import ast

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import config_check  # noqa: E402
import json_schema  # noqa: E402
import structure  # noqa: E402
import python_source  # noqa: E402

COPIED = ('contracts/config/registry.v1.json', 'contracts/events/config.changed.v1.json', 'config/registry/config.json')


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
        policy = json.loads((self.root / 'config/registry/config.json').read_text())
        for item in policy['properties'].values():
            item['x-readers'] = []  # the readers live in the real checkout, not in the fixture
        policy['properties']['config.store_adapter']['default'] = 'file'  # the fixture's own log, never the forge
        self.write('config/registry/config.json', policy)
        self.write('config/registry/train.json', train())
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name, content):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content if isinstance(content, str) else json.dumps(content))

    def commit(self, message='base'):
        git = ['git', '-C', str(self.root), '-c', 'user.name=t', '-c', 'user.email=t@example.invalid']
        subprocess.run(git + ['add', '-A'], check=True)
        subprocess.run(git + ['commit', '-qm', message], check=True)
        return subprocess.run(git + ['rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip()

    def check(self, base=None):
        subprocess.run(['git', '-C', str(self.root), 'add', '-A'], check=True)
        errors, warnings = config_check.check(self.root, base)
        return '\n'.join(errors), '\n'.join(warnings)


class Literals(Repo):
    def test_a_registered_parameter_spelled_as_a_python_literal_fails(self):
        self.write('scripts/lib/merge.py', 'TRAIN_BATCH_SIZE = 8\n'
                                           'def run(train_batch_size=8):\n    return go(train_batch_size=8)\n'
                                           'LIMITS = {"train_batch_size": 8}\n'
                                           'A, TRAIN_BATCH_SIZE = 1, 8\n')
        errors, _ = self.check()
        for line in (1, 2, 3, 4, 5):
            self.assertIn(f'scripts/lib/merge.py:{line}: ', errors)
        self.assertIn('read it with config.get("train.batch_size")', errors)

    def test_the_bare_key_counts_only_in_the_owners_files(self):
        self.write('scripts/lib/train.py', 'batch_size = 8\n')
        self.write('scripts/lib/pager.py', 'batch_size = 100\nper_page = 100\ntimeout = 180\n')
        errors, _ = self.check()
        self.assertIn('scripts/lib/train.py:1: batch_size spells the registered parameter train.batch_size', errors)
        self.assertNotIn('pager.py', errors)

    def test_a_reader_and_a_name_reference_are_not_literals(self):
        self.write('scripts/lib/train.py', 'import config\nbatch_size = config.get("train.batch_size")\n'
                                           'BATCH_SIZE_NAME = "train.batch_size"\nbatch_size_name = "train.batch_size"\n')
        self.assertEqual(self.check()[0], '')

    def test_an_inline_fallback_fails(self):
        self.write('scripts/lib/lane.py', 'import config\nsize = config.get("train.batch_size") or 8\n')
        self.write('scripts/lane.sh', 'size="$(python3 scripts/lib/config.py get train.batch_size || echo 8)"\n')
        errors, _ = self.check()
        self.assertIn('scripts/lib/lane.py:2: an inline fallback after reading train.batch_size', errors)
        self.assertIn('scripts/lane.sh:1: an inline fallback after reading train.batch_size', errors)

    def test_shell_javascript_and_extensionless_scripts_are_read(self):
        self.write('scripts/lib/train.sh', 'TRAIN_BATCH_SIZE=8\nsize="${TRAIN_BATCH_SIZE:-8}"\n'
                                           'ok="$(python3 scripts/lib/config.py get train.batch_size)"\n')
        self.write('scripts/lib/train.mjs', 'const TRAIN_BATCH_SIZE = 8;\nconst options = { train_batch_size: 8 };\n'
                                            'const other = { batchSize: 8 };\n')
        self.write('scripts/train-run', '#!/usr/bin/env bash\nexport TRAIN_BATCH_SIZE=8\n')
        errors, _ = self.check()
        for where in ('train.sh:1:', 'train.sh:2:', 'train.mjs:1:', 'train.mjs:2:', 'scripts/train-run:2:'):
            self.assertIn(where, errors)
        self.assertNotIn('train.sh:3:', errors)
        self.assertNotIn('train.mjs:3:', errors)

    def test_tests_are_scanned_and_generated_types_and_other_trees_are_not(self):
        self.write('scripts/tests/test_train.py', 'TRAIN_BATCH_SIZE = 8\n')  # LT1: tests are engine files too
        self.write('scripts/lib/generated/train.py', 'TRAIN_BATCH_SIZE = 8\n')
        self.write('products/demo/src/train.py', 'TRAIN_BATCH_SIZE = 8\n')
        errors, _ = self.check()
        self.assertIn('scripts/tests/test_train.py:1: TRAIN_BATCH_SIZE spells the registered parameter', errors)
        self.assertNotIn('generated', errors)
        self.assertNotIn('products/demo', errors)

    EVERY_FORM = ('TRAIN_BATCH_SIZE = 8  # found: assignment\n'
                  'A, TRAIN_BATCH_SIZE = 1, -8  # found: tuple, negative\n'
                  'self.train_batch_size: int = 8  # found: annotated attribute\n'
                  'go(train_batch_size="8")  # found: keyword, string\n'
                  'def f(a, train_batch_size=8): pass  # found: default\n'
                  'def h(*, TRAIN_BATCH_SIZE=True): pass  # found: keyword-only default\n'
                  'g = lambda train_batch_size=8: 0  # found: lambda default\n'
                  'd = {"train_batch_size": 8.5}  # found: dict key\n'
                  'size = config.get("train.batch_size") or 8  # found: fallback\n'
                  'TRAIN_BATCH_SIZE = None  # not a value\n'
                  'TRAIN_BATCH_SIZE = b"8"  # not a value\n'
                  'TRAIN_BATCH_SIZE_NAME = "x"  # another name\n'
                  'TRAIN_BATCH_SIZE = "train.batch_size"  # a reference\n'
                  'other = config.get("train.other") or 8  # not a registry read\n'
                  'x = get(name) or 8  # not a registry read\n')

    def test_candidates_carry_every_form_without_the_registry_and_judge_to_the_findings(self):
        params = {'train.batch_size': {}}
        names = config_check.Names(params)
        candidates = config_check.python_candidates(self.EVERY_FORM)
        self.assertEqual(json.loads(json.dumps(candidates)), candidates)  # what a cache keeps is the same answer
        found = config_check.judge_candidates('scripts/lib/merge.py', candidates, names, params)
        self.assertEqual(found, config_check.python_findings('scripts/lib/merge.py', self.EVERY_FORM, names, params))
        expected = [number for number, line in enumerate(self.EVERY_FORM.splitlines(), start=1) if '# found' in line]
        self.assertEqual(sorted(line for line, *_ in found), expected)
        self.assertIn(('or', 'train.batch_size', 'fallback'), [tuple(hit[1:]) for hit in found])
        self.assertEqual(config_check.judge_candidates('scripts/lib/merge.py', candidates, config_check.Names({}), {}), [])
        self.assertEqual(config_check.python_candidates('def broken(:\n'), [])

    def test_the_repository_engine_paths_hold_no_unlisted_literal(self):
        errors, _ = config_check.check_literals(ROOT)
        self.assertEqual(errors, [])


class CandidateCache(Repo):
    """F21: the candidates are kept by content; the answer is the uncached one whatever the cache holds."""

    def setUp(self):
        super().setUp()
        self.cache = self.root.parent / f'{self.root.name}-cache'
        patched = mock.patch.dict('os.environ', {config_check.LITERAL_CACHE_ENV: str(self.cache)})
        patched.start()
        self.addCleanup(patched.stop)
        self.addCleanup(shutil.rmtree, self.cache, True)

    def entries(self):
        return sorted(path for path in self.cache.rglob('*') if path.is_file()) if self.cache.is_dir() else []

    def extractions(self):
        """The errors of one check and how many sources were extracted (not read from the cache) for it."""
        with mock.patch.object(config_check, 'python_candidates', wraps=config_check.python_candidates) as extract:
            errors = self.check()[0]
        return errors, extract.call_count

    def test_a_planted_literal_is_found_cold_warm_and_uncached(self):
        self.write('scripts/lib/merge.py', 'TRAIN_BATCH_SIZE = 8\n')
        cold, extracted = self.extractions()
        self.assertEqual(extracted, 1)
        self.assertEqual(len(self.entries()), 1)
        warm, extracted = self.extractions()
        self.assertEqual((warm, extracted), (cold, 0))
        self.assertIn('scripts/lib/merge.py:1: TRAIN_BATCH_SIZE spells the registered parameter', warm)
        with mock.patch.dict('os.environ', {config_check.LITERAL_CACHE_ENV: ''}):
            self.assertEqual(self.extractions(), (cold, 1))
        self.write('scripts/lib/merge.py', 'TRAIN_BATCH_SIZE = 8\nTRAIN_BATCH_SIZE = 9\n')  # new content, new key
        changed, extracted = self.extractions()
        self.assertEqual(extracted, 1)
        self.assertIn('scripts/lib/merge.py:2: ', changed)

    def test_a_registry_change_is_judged_on_cached_candidates(self):
        self.write('scripts/lib/legacy.py', 'PLAN_SIZE = 8\n')
        self.assertEqual(self.extractions(), ('', 1))
        self.write('config/registry/train.json', train(**{'x-literal-names': ['PLAN_SIZE']}))
        errors, extracted = self.extractions()
        self.assertEqual(extracted, 0)
        self.assertIn('scripts/lib/legacy.py:1: PLAN_SIZE spells the registered parameter train.batch_size', errors)

    def test_a_corrupt_entry_or_a_new_extractor_is_extracted_again(self):
        self.write('scripts/lib/merge.py', 'TRAIN_BATCH_SIZE = 8\n')
        expected = self.extractions()[0]
        for entry in self.entries():
            entry.write_text('[["value", "one", "TRAIN_BATCH_SIZE"]]')
        self.assertEqual(self.extractions(), (expected, 1))
        self.assertEqual(self.extractions(), (expected, 0))  # the entry was rewritten
        with mock.patch.object(config_check, '_EXTRACTOR', ['another extractor']):
            self.assertEqual(self.extractions(), (expected, 1))


class Sites(Repo):
    LEGACY = 'SIZE = 8\nTRAIN_BATCH_SIZE = 8\n'

    def test_a_listed_site_passes_and_a_stale_one_warns(self):
        self.write('scripts/lib/legacy.py', self.LEGACY)
        self.write('config/registry/train.json', train(**{'x-literal-sites': ['scripts/lib/legacy.py:TRAIN_BATCH_SIZE',
                                                                              'scripts/lib/gone.py:TRAIN_BATCH_SIZE']}))
        errors, warnings = self.check()
        self.assertEqual(errors, '')
        self.assertIn('lists scripts/lib/gone.py:TRAIN_BATCH_SIZE, which no longer spells it', warnings)

    def test_an_alias_names_a_legacy_identifier(self):
        self.write('scripts/lib/legacy.py', 'PLAN_SIZE = 8\n')
        self.write('config/registry/train.json', train(**{'x-literal-names': ['PLAN_SIZE']}))
        self.assertIn('PLAN_SIZE spells the registered parameter train.batch_size', self.check()[0])

    def test_the_site_list_only_shrinks_against_the_base(self):
        self.write('scripts/lib/legacy.py', self.LEGACY)
        self.write('config/registry/train.json', train(**{'x-literal-sites': ['scripts/lib/legacy.py:TRAIN_BATCH_SIZE']}))
        base = self.commit()
        self.write('scripts/lib/fresh.py', 'TRAIN_BATCH_SIZE = 8\n')
        self.write('config/registry/train.json', train(**{'x-literal-sites': ['scripts/lib/legacy.py:TRAIN_BATCH_SIZE',
                                                                              'scripts/lib/fresh.py:TRAIN_BATCH_SIZE']}))
        self.assertIn('x-literal-sites gains scripts/lib/fresh.py:TRAIN_BATCH_SIZE', self.check(base)[0])

    def test_registering_a_parameter_may_list_a_literal_the_base_already_had(self):
        self.write('config/registry/train.json', train())
        self.write('scripts/lib/legacy.py', self.LEGACY)
        base = self.commit()
        self.write('config/registry/train.json', {**train(), 'properties': {
            **train()['properties'], 'train.size': {'type': 'integer', 'default': 8, 'x-unit': 'count',
                                                    'description': 'A size.', 'x-readers': [],
                                                    'x-literal-names': ['SIZE'],
                                                    'x-literal-sites': ['scripts/lib/legacy.py:SIZE']}}})
        self.write('scripts/lib/legacy.py', self.LEGACY.replace('TRAIN_BATCH_SIZE = 8\n', ''))
        self.assertEqual(self.check(base)[0], '')


class StructureCheckWiring(Repo):
    def test_generated_types_and_contracts_are_their_stages_not_the_structure_checks(self):
        self.write('scripts/lib/generated/config_registry_train.py', 'stale = True\n')
        self.write('contracts/events/thing.json', {'$schema': json_schema.DIALECT})
        self.assertEqual(self.check()[0], '')

    def test_structure_check_fails_on_a_registered_literal(self):
        self.write('scripts/lib/merge.py', 'TRAIN_BATCH_SIZE = 8\n')
        self.check()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = structure.main(['--root', str(self.root)])
        self.assertEqual(code, 1)
        self.assertIn('FAIL scripts/lib/merge.py:1: TRAIN_BATCH_SIZE spells the registered parameter', out.getvalue())


class SyntaxSnapshot(unittest.TestCase):
    def test_repeated_checks_parse_once_and_keep_standard_walk_order(self):
        text = 'value = fn(1)\n'
        expected = [type(node) for node in ast.walk(ast.parse(text))]
        with mock.patch.object(ast, 'parse', wraps=ast.parse) as parse, python_source.snapshot():
            first = python_source.parse(text)
            self.assertIs(first, python_source.parse(text))
            self.assertEqual([type(node) for node in python_source.walk(first)], expected)
            self.assertEqual([type(node) for node in python_source.walk(first)], expected)
            parse.assert_called_once()

    def test_changed_text_and_a_new_run_never_reuse_old_syntax(self):
        with python_source.snapshot():
            before = python_source.parse('value = 1')
            after = python_source.parse('value = -1')
            self.assertIsNot(before, after)
        with python_source.snapshot():
            self.assertIsNot(before, python_source.parse('value = 1'))

    def test_type_selection_preserves_standard_breadth_first_order_without_duplicates(self):
        with python_source.snapshot():
            tree = python_source.parse('def call(value):\n    return other(value + 1)\n')
            expected = list(ast.walk(tree))
            for kinds in ((ast.AST,), (ast.Call,), (ast.expr, ast.Constant), (ast.AST, ast.Call)):
                self.assertEqual(list(python_source.select(tree, *kinds)),
                                 [node for node in expected if isinstance(node, kinds)])

    def test_an_exception_closes_the_snapshot(self):
        with self.assertRaises(RuntimeError):
            with python_source.snapshot():
                before = python_source.parse('value = 1')
                raise RuntimeError('end the run')
        self.assertIsNot(before, python_source.parse('value = 1'))


if __name__ == '__main__':
    unittest.main()
