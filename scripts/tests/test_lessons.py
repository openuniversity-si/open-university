"""The lessons registry (LR1). Fixture register in a temp directory, injected clock."""
import contextlib
from datetime import datetime, timedelta, timezone
import io
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import audit_chain  # noqa: E402
import config  # noqa: E402
import lessons  # noqa: E402
import forge_events  # noqa: E402


class FakeClock:
    def __init__(self):
        self.moment = datetime(2026, 10, 27, 3, 0, tzinfo=timezone.utc)

    def now(self):
        self.moment += timedelta(seconds=1)
        return self.moment


def cls(index=0):
    return config.get('lessons.classes')[index]


class Fixture(unittest.TestCase):
    def setUp(self):
        # Registry unit tests inject a journal double, not a compatible forge.
        self.enterContext(mock.patch.object(forge_events, '_require_compatibility'))
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        shutil.copytree(ROOT / 'contracts' / 'lessons', self.tmp / 'contracts' / 'lessons')
        self.clock = FakeClock()

    def add(self, title='Registry keys land with their reader', ref='F1', unit='KD1'):
        return lessons.add(self.tmp, title, unit, f'docs/units/{unit}/retro.md', 3, ref, cls(), config.get('lessons.kinds')[5],
                           'a helper refuses a reader that does not exist', config.get('lessons.owners')[1],
                           area=['config/registry/**'], clock=self.clock)

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = lessons.main(['--root', str(self.tmp), *argv], self.tmp)
        return code, out.getvalue(), err.getvalue()


class AddTest(Fixture):
    def test_add_creates_a_proposed_record_with_a_one_entry_trail(self):
        record, outcome = self.add()
        self.assertEqual(outcome, 'created')
        self.assertEqual(record['status'], config.get('lessons.statuses')[0])
        self.assertEqual([entry['action'] for entry in record['trail']], ['registered'])
        self.assertEqual(lessons.check(self.tmp)[1], [])

    def test_the_same_source_ref_and_title_is_a_dedup_not_a_second_record(self):
        first, _ = self.add()
        second, outcome = self.add(title='  registry KEYS land with their reader ')
        self.assertEqual((outcome, second['id']), ('exists', first['id']))
        self.assertEqual(len(lessons.load(self.tmp)[0]), 1)

    def test_a_class_outside_the_registry_is_refused(self):
        with self.assertRaises(lessons.LessonError):
            lessons.add(self.tmp, 't', 'KD1', 'r.md', 3, 'F1', 'not-a-class', config.get('lessons.kinds')[0], 'c',
                        config.get('lessons.owners')[0], clock=self.clock)


class LevelTest(Fixture):
    def test_a_new_lesson_defaults_to_the_registered_level_and_is_not_a_padrao_candidate(self):
        record, _ = self.add()
        self.assertEqual((record['level'], record['padrao_candidate']), (config.get('lessons.default_level'), False))

    def test_level_and_padrao_candidate_are_stored_and_read_back(self):
        record, _ = lessons.add(self.tmp, 'Applies to every venture', 'KD1', 'r.md', 5, 'L9', cls(), config.get('lessons.kinds')[0], 'c',
                                config.get('lessons.owners')[0], clock=self.clock, level=config.get('lessons.levels')[-1], padrao_candidate=True)
        loaded = lessons.load(self.tmp)[0][record['id']]
        self.assertEqual((loaded['level'], loaded['padrao_candidate']), (config.get('lessons.levels')[-1], True))
        self.assertEqual(lessons.check(self.tmp)[1], [])

    def test_a_level_outside_the_registry_is_refused(self):
        with self.assertRaises(lessons.LessonError):
            lessons.add(self.tmp, 't', 'KD1', 'r.md', 5, 'L1', cls(), config.get('lessons.kinds')[0], 'c', config.get('lessons.owners')[0],
                        clock=self.clock, level='galaxy')

    def test_a_record_written_before_the_fields_existed_is_still_valid(self):
        record, _ = self.add()
        path = lessons.paths(self.tmp, record['slug'])[0]
        path.write_text(''.join(line for line in path.read_text().splitlines(True) if not line.startswith(('level:', 'padrao_candidate:'))))
        self.assertEqual(lessons.check(self.tmp)[1], [])

    def test_cli_marks_a_padrao_candidate(self):
        code, out, _ = self.run_cli('add', '--no-emit', '--title', 'T', '--source-unit', 'KD1', '--source-retro', 'r.md', '--section', '5', '--ref', 'L1',
                                    '--class', cls(), '--kind', config.get('lessons.kinds')[0], '--change', 'c',
                                    '--owner', config.get('lessons.owners')[0], '--level', 'venture', '--padrao-candidate')
        self.assertEqual(code, 0)
        self.assertTrue(lessons.load(self.tmp)[0][out.split()[0]]['padrao_candidate'])


class LifecycleTest(Fixture):
    def test_apply_records_who_when_and_where_and_chains_the_trail(self):
        record, _ = self.add()
        done = lessons.apply(self.tmp, record['id'], 581, 'scripts/lib/x.py', by='engine-lane', clock=self.clock)
        self.assertEqual((done['status'], done['applied']['pr'], done['applied']['ref']), ('applied', 581, 'scripts/lib/x.py'))
        self.assertEqual([entry['action'] for entry in done['trail']], ['registered', 'applied'])
        self.assertEqual(lessons.check(self.tmp)[1], [])

    def test_a_forbidden_transition_is_refused(self):
        record, _ = self.add()
        lessons.retire(self.tmp, record['id'], 'superseded', clock=self.clock)
        with self.assertRaises(lessons.LessonError):
            lessons.apply(self.tmp, record['id'], 1, 'x', clock=self.clock)


class IntegrityTest(Fixture):
    def trail_path(self, record):
        return lessons.paths(self.tmp, record['slug'])[1]

    def test_an_edited_trail_entry_breaks_the_chain(self):
        record, _ = self.add()
        lessons.apply(self.tmp, record['id'], 1, 'x', clock=self.clock)
        path = self.trail_path(record)
        path.write_text(path.read_text().replace('"by": "lessons"', '"by": "someone"', 1))
        self.assertTrue(any('edited' in message for message in lessons.check(self.tmp)[1]))

    def test_a_removed_entry_breaks_the_chain(self):
        record, _ = self.add()
        lessons.apply(self.tmp, record['id'], 1, 'x', clock=self.clock)
        path = self.trail_path(record)
        path.write_text(path.read_text().splitlines(True)[1])
        self.assertTrue(any('chain' in message for message in lessons.check(self.tmp)[1]))

    def test_a_status_edited_by_hand_disagrees_with_the_trail(self):
        record, _ = self.add()
        path = lessons.paths(self.tmp, record['slug'])[0]
        path.write_text(path.read_text().replace('status: "proposed"', 'status: "retired"'))
        self.assertTrue(any('last trail entry' in message for message in lessons.check(self.tmp)[1]))

    def test_against_a_base_the_trail_may_only_grow(self):
        subprocess.run(['git', 'init', '-q', str(self.tmp)], check=True)
        record, _ = self.add()
        subprocess.run(['git', '-C', str(self.tmp), 'add', '-A'], check=True)
        subprocess.run(['git', '-C', str(self.tmp), '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-qm', 'base'], check=True)
        lessons.apply(self.tmp, record['id'], 1, 'x', clock=self.clock)
        self.assertEqual(lessons.check(self.tmp, 'HEAD')[1], [])
        self.trail_path(record).write_text('')
        self.assertTrue(any('append-only' in message for message in lessons.check(self.tmp, 'HEAD')[1]))

    def test_chain_helper_uses_the_algorithm_and_genesis_it_is_given(self):
        trail = audit_chain.append_entry([], 'x', 'registered', None, 'proposed', '', '2026-10-27T03:00:00Z', 'sha1', 'g')
        self.assertEqual(audit_chain.chain_errors(trail, 'n', 'sha1', 'g'), [])
        self.assertNotEqual(audit_chain.chain_errors(trail, 'n', 'sha256', 'g'), [])


class CliTest(Fixture):
    def test_add_list_apply_show_retire_check(self):
        code, out, _ = self.run_cli('add', '--title', 'A thing', '--no-emit', '--source-unit', 'KD1', '--source-retro', 'r.md', '--section', '5',
                                    '--ref', 'L1', '--class', cls(), '--kind', config.get('lessons.kinds')[0],
                                    '--change', 'do x', '--owner', config.get('lessons.owners')[0])
        self.assertEqual(code, 0)
        ident = out.split()[0]
        self.assertIn(ident, self.run_cli('list')[1])
        self.assertEqual(self.run_cli('apply', ident, '--no-emit', '--ref', 'x', '--pr', '5')[0], 0)
        self.assertIn('applied', self.run_cli('show', ident)[1])
        self.assertEqual(self.run_cli('retire', ident, '--no-emit', '--why', 'done')[0], 0)
        self.assertEqual(self.run_cli('check')[0], 0)

    def test_an_unknown_id_exits_2(self):
        self.assertEqual(self.run_cli('show', 'LR-000000')[0], 2)


class RepositoryTest(unittest.TestCase):
    def test_the_committed_register_is_valid(self):
        self.assertEqual(lessons.check(ROOT)[1], [])


if __name__ == '__main__':
    unittest.main()
