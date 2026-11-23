"""The cycle's turn guard (I-0d1c3a25): the Stop hook blocks a turn's end while the cycle is on, unless STOP: <reason>.

Verifies: REQ-owner-stop-closed-list
"""
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'lib'))
import config  # noqa: E402
import cycle_stop  # noqa: E402
from unittest import mock  # noqa: E402


def transcript(directory, *texts):
    path = Path(directory) / 'session.jsonl'
    rows = [{'type': 'user', 'message': {'role': 'user', 'content': 'go'}}]
    rows += [{'type': 'assistant', 'message': {'role': 'assistant', 'content': [{'type': 'text', 'text': text}]}}
             for text in texts]
    rows.append({'type': 'assistant', 'message': {'role': 'assistant', 'content': [{'type': 'tool_use', 'name': 'Bash'}]}})
    path.write_text('\n'.join(json.dumps(row) for row in rows) + '\nnot json\n')
    return str(path)


class CycleStopTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.marker = Path(self.tmp.name) / '.gate' / 'cycle.on'

    def run_hook(self, event):
        out = io.StringIO()
        cycle_stop.hook(io.StringIO(json.dumps(event)), out, self.marker)
        return json.loads(out.getvalue()) if out.getvalue() else None

    def test_without_the_marker_every_stop_is_allowed(self):
        self.assertIsNone(self.run_hook({'transcript_path': transcript(self.tmp.name, 'Summary: done.')}))

    def test_on_a_summary_is_blocked_once_with_the_vigias_question_not_a_slogan(self):
        cycle_stop.main(['on'], self.marker)
        answer = self.run_hook({'transcript_path': transcript(self.tmp.name, 'Summary: PR merged. Next bottleneck: X.')})
        self.assertEqual(answer['decision'], 'block')
        self.assertIn('standing determination', answer['reason'])
        self.assertEqual(cycle_stop.default_determination(), config.get('flow.cycle_determination'))
        self.assertNotIn('concluir o motor AWS ponta a ponta', answer['reason'])
        self.assertIn(cycle_stop.default_determination(), answer['reason'])
        self.assertIn('short status', answer['reason'])
        self.assertNotIn('step 3', answer['reason'])
        self.assertNotIn('find the next bottleneck', answer['reason'])

    def test_default_determination_reads_flow_cycle_determination_from_registry(self):
        cycle_stop.main(['on'], self.marker)
        with mock.patch.object(cycle_stop.config, 'get', return_value='close the active program unit') as get:
            answer = self.run_hook({'last_assistant_message': 'Summary.'})
        get.assert_called_once_with('flow.cycle_determination')
        self.assertIn('close the active program unit', answer['reason'])

    def test_the_marker_text_names_the_determination(self):
        self.marker.parent.mkdir(parents=True, exist_ok=True)
        self.marker.write_text('finish the AWS engine end to end\n')
        answer = self.run_hook({'last_assistant_message': 'Status: waiting on the deploy.'})
        self.assertIn('finish the AWS engine end to end', answer['reason'])

    def test_on_a_closed_list_stop_is_allowed_and_the_last_text_is_the_one_read(self):
        cycle_stop.main(['on'], self.marker)
        path = transcript(self.tmp.name, 'Summary first.', 'STOP: credential — CURSOR_API_KEY is absent')
        self.assertIsNone(self.run_hook({'transcript_path': path}))
        self.assertIsNone(self.run_hook({'last_assistant_message': 'STOP: quota'}))
        self.assertEqual(self.run_hook({'last_assistant_message': 'STOP: tired'})['decision'], 'block')
        self.assertEqual(self.run_hook({'last_assistant_message': 'I will STOP: quota later'})['decision'], 'block')

    def test_a_continued_stop_is_allowed_so_the_hook_cannot_loop(self):
        cycle_stop.main(['on'], self.marker)
        self.assertIsNone(self.run_hook({'stop_hook_active': True, 'last_assistant_message': 'Summary.'}))

    def test_a_missing_transcript_or_a_bad_event_still_blocks_while_on(self):
        cycle_stop.main(['on'], self.marker)
        self.assertEqual(self.run_hook({'transcript_path': '/nonexistent/x.jsonl'})['decision'], 'block')
        out = io.StringIO()
        cycle_stop.hook(io.StringIO('not json'), out, self.marker)
        self.assertEqual(json.loads(out.getvalue())['decision'], 'block')

    def test_off_removes_the_marker(self):
        cycle_stop.main(['on'], self.marker)
        cycle_stop.main(['off'], self.marker)
        self.assertFalse(self.marker.exists())
        self.assertEqual(cycle_stop.main(['bogus'], self.marker), 2)


if __name__ == '__main__':
    unittest.main()
