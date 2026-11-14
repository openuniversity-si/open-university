"""Incidents (D-231): an opened incident is listed as open, closing it with its fix removes it from the list, and the same kind,
text and time give the same id (no second record). A temporary folder; no git, no network.
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


if __name__ == '__main__':
    unittest.main()
