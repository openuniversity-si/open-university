"""Incidents (D-231): an opened incident is listed as open, closing it with its fix removes it from the list, and the same kind,
text and time give the same id (no second record). A temporary folder; no git, no network.

Verifies: REQ-owner-stop-closed-list
"""
from pathlib import Path
import json
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import incident  # noqa: E402

FIXTURE = json.loads((ROOT / 'scripts' / 'tests' / 'fixtures' / 'incident.json').read_text())


class Register(unittest.TestCase):
    def test_an_opened_incident_is_listed_and_a_closed_one_is_not(self):
        with tempfile.TemporaryDirectory() as tmp:
            identifier = incident.open_incident(tmp, FIXTURE['kind'], FIXTURE['text'], FIXTURE['time'])
            self.assertEqual(incident.listing(tmp), [identifier])
            incident.close(tmp, identifier, FIXTURE['fix'])
            self.assertEqual(incident.listing(tmp), [])

    def test_the_same_incident_gets_the_same_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = incident.open_incident(tmp, FIXTURE['kind'], FIXTURE['text'], FIXTURE['time'])
            second = incident.open_incident(tmp, FIXTURE['kind'], FIXTURE['text'], FIXTURE['time'])
            self.assertEqual(first, second)
            self.assertEqual(len(list((Path(tmp) / incident.FOLDER).glob('I-*.md'))), 1)

    def test_list_rows_carry_id_state_and_cause_and_show_prints_the_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            identifier = incident.open_incident(tmp, FIXTURE['kind'], FIXTURE['text'], FIXTURE['time'])
            self.assertEqual(incident.rows(tmp), [f'{identifier}\topen\t(none yet)'])
            path = Path(tmp) / incident.FOLDER / f'{identifier}.md'
            path.write_text(path.read_text().replace('## Case\n(to be decided)', '## Case\nroot cause here\nmore'))
            self.assertEqual(incident.rows(tmp), [f'{identifier}\topen\troot cause here'])
            self.assertIn('root cause here', incident.show(tmp, identifier))

    def test_snapshot_exports_metadata_only_and_merges_existing_entries(self):
        import contextlib
        import io
        with tempfile.TemporaryDirectory() as tmp:
            prior = {'id': 'I-00000001', 'kind': 'owner-stop', 'time': '2026-11-15T10:00:00Z', 'status': 'closed'}
            snap_path = Path(tmp) / incident.SNAPSHOT
            snap_path.parent.mkdir(parents=True, exist_ok=True)
            snap_path.write_text(json.dumps({'source': 'seed', 'at': '2026-11-15T12:00:00Z', 'incidents': [prior]}))
            identifier = incident.open_incident(tmp, FIXTURE['kind'], FIXTURE['text'], FIXTURE['time'])
            incident.write_snapshot(tmp, now='2026-11-19T12:00:00Z')
            raw = snap_path.read_text()
            self.assertNotIn(FIXTURE['text'], raw, 'snapshot carries metadata only, never incident prose')
            loaded = json.loads(raw)
            self.assertEqual(loaded['at'], '2026-11-19T12:00:00Z')
            self.assertTrue(loaded['observed'])
            by_id = {entry['id']: entry for entry in loaded['incidents']}
            self.assertEqual(set(by_id), {'I-00000001', identifier})
            self.assertEqual(by_id[identifier], {'id': identifier, 'kind': FIXTURE['kind'],
                                                 'time': FIXTURE['time'], 'status': 'open'})
            incident.close(tmp, identifier, FIXTURE['fix'])
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(incident.main(['snapshot'], root=tmp), 0)
            after = json.loads(snap_path.read_text())
            self.assertTrue(after['observed'])
            self.assertEqual({entry['id']: entry['status'] for entry in after['incidents']},
                             {'I-00000001': 'closed', identifier: 'closed'})

    def test_snapshot_without_local_folder_stays_unobserved_and_preserves_prior_stamp(self):
        with tempfile.TemporaryDirectory() as tmp:
            snap_path = incident.write_snapshot(tmp, now='2026-11-22T18:00:00Z')
            empty = json.loads(snap_path.read_text())
            self.assertEqual((empty['at'], empty['observed'], empty['incidents']), (None, False, []))
            seeded = {'source': 'seed', 'at': '2026-11-20T12:00:00Z', 'observed': True, 'incidents': [
                {'id': 'I-00000001', 'kind': 'owner-stop', 'time': '2026-11-20T10:00:00Z', 'status': 'closed'}]}
            snap_path.write_text(json.dumps(seeded))
            incident.write_snapshot(tmp, now='2026-11-22T18:00:00Z')
            kept = json.loads(snap_path.read_text())
            self.assertEqual((kept['at'], kept['observed'], kept['incidents']),
                             ('2026-11-20T12:00:00Z', True, seeded['incidents']))



class NeverPublished(unittest.TestCase):
    def test_the_records_folder_is_ignored_by_git(self):
        """The public tree leaves docs/operations/ out (D-314): a record stays on the machine and is never committed."""
        import subprocess
        done = subprocess.run(['git', 'check-ignore', '-q', f'{incident.FOLDER}/I-00000000.md'], cwd=ROOT, check=False)
        self.assertEqual(done.returncode, 0)

    def test_tracked_snapshot_carries_metadata_only(self):
        """D-350: config/validation/incidents.json is public metadata-only (id, kind, time, status), never prose."""
        data = json.loads((ROOT / incident.SNAPSHOT).read_text())
        self.assertIsInstance(data.get('incidents'), list)
        self.assertIsInstance(data.get('observed'), bool)
        allowed = {'id', 'kind', 'time', 'status'}
        for entry in data['incidents']:
            self.assertEqual(set(entry), allowed)

if __name__ == '__main__':
    unittest.main()
