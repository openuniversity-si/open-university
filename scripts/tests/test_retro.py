#!/usr/bin/env python3
"""RETRO-API: the session-log store keeps bytes exactly, refuses a wrong shape and a secret, never overwrites."""
import json
from pathlib import Path
import hashlib
import io
import uuid
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))

import retro  # noqa: E402

TRANSCRIPT = (b'{"type":"user","sessionId":"s1","message":"hello"}\n'
              b'{"type":"assistant","sessionId":"s1","message":"caf\xc3\xa9"}\n')


def fake_token():
    """A GitHub-token-shaped value built at run time, so no literal token sits in the repo or a transcript."""
    return 'gh' + 'p_' + hashlib.sha256(b'retro fixture, not a credential').hexdigest()


class Store(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_keeps_the_bytes_after_one_header_line(self):
        header = retro.store('U1', 's1', 'transcript', '/x/s1.jsonl', TRANSCRIPT, root=self.root)
        raw = (self.root / header['path']).read_bytes()
        first, rest = raw.split(b'\n', 1)
        self.assertEqual(rest, TRANSCRIPT)
        stored = json.loads(first)
        self.assertEqual((stored['unit'], stored['session'], stored['bytes'], stored['stored']),
                         ('U1', 's1', len(TRANSCRIPT), 'bytes'))
        self.assertEqual(stored['sha256'], retro.sha256(TRANSCRIPT))
        self.assertEqual(header['path'], 'logs/U1/s1.jsonl')

    def test_never_overwrites_a_taken_name(self):
        retro.store('U1', 's1', 'transcript', 'a', TRANSCRIPT, root=self.root)
        grown = TRANSCRIPT + b'{"type":"user","sessionId":"s1"}\n'
        second = retro.store('U1', 's1', 'transcript', 'a', grown, root=self.root)
        self.assertEqual(second['path'], f'logs/U1/s1.{retro.sha256(grown)}.jsonl')
        self.assertTrue((self.root / 'logs/U1/s1.jsonl').read_bytes().endswith(TRANSCRIPT))

    def test_over_the_ceiling_keeps_a_pointer_never_a_truncation(self):
        with mock.patch.object(retro, 'max_file_bytes', return_value=len(TRANSCRIPT) - 1):
            header = retro.store('U1', 's1', 'transcript', '/x/s1.jsonl', TRANSCRIPT, root=self.root)
        raw = (self.root / header['path']).read_bytes()
        self.assertEqual(raw.count(b'\n'), 1)
        self.assertEqual(json.loads(raw)['stored'], 'pointer')
        self.assertEqual(json.loads(raw)['bytes'], len(TRANSCRIPT))

    def test_refuses_what_is_not_a_transcript(self):
        for data in (b'', b'not json\n', b'[1, 2]\n', b'{"no_type": 1}\n', b'\xff\xfe'):
            with self.assertRaises(retro.Refused):
                retro.store('U1', 's1', 'transcript', 'bad', data, root=self.root)
        self.assertFalse((self.root / 'logs').exists())

    def test_motor_record_is_text(self):
        header = retro.store('U1', 's1', 'motor', 'sessions.log', b'21:00 U1 launched\n', root=self.root)
        self.assertEqual(header['path'], 'logs/U1/s1.motor.log')

    def test_refuses_an_id_that_is_not_plain(self):
        for unit, session in (('../x', 's1'), ('U1', 'a/b'), ('', 's1')):
            with self.assertRaises(retro.Refused):
                retro.store(unit, session, 'transcript', 'a', TRANSCRIPT, root=self.root)

    def test_secret_is_refused_by_rule_and_offset_never_by_value(self):
        token = fake_token()
        data = TRANSCRIPT + json.dumps({'type': 'user', 'message': f'token {token}'}).encode() + b'\n'
        with self.assertRaises(retro.Refused) as caught:
            retro.store('U1', 's1', 'transcript', 'leak.jsonl', data, root=self.root)
        message = str(caught.exception)
        self.assertIn('carries a secret', message)
        self.assertIn(f"line {len(TRANSCRIPT.splitlines()) + 1}:", message)
        self.assertNotIn(token, message)
        self.assertNotIn(token.split('_', 1)[1], message)
        self.assertFalse((self.root / 'logs').exists())

    def test_the_turn_attribution_uuid_is_not_a_secret_under_its_own_key_only(self):
        turn = str(uuid.uuid5(uuid.NAMESPACE_URL, 'retro fixture turn'))
        line = json.dumps({'type': 'user', 'clientPlatform': 'claude_code_cli', 'turnAttributionKey': turn})
        header = retro.store('U1', 's1', 'transcript', 'real.jsonl', line.encode() + b'\n', root=self.root)
        self.assertEqual(header['stored'], 'bytes')
        other = json.dumps({'type': 'user', 'serviceApiKey': turn}).encode() + b'\n'
        with self.assertRaises(retro.Refused) as caught:
            retro.store('U1', 's2', 'transcript', 'leak.jsonl', other, root=self.root)
        self.assertNotIn(turn, str(caught.exception))

    def test_no_scanner_means_no_store(self):
        with mock.patch.object(retro, '_gitleaks', return_value=None):
            with self.assertRaises(retro.Refused):
                retro.store('U1', 's1', 'transcript', 'a', TRANSCRIPT, root=self.root)


class Index(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_one_line_per_stored_file_and_none_for_known_bytes(self):
        entry = retro.keep('U1', 's1', 'transcript', '/x/s1.jsonl', TRANSCRIPT, root=self.root)
        self.assertEqual(sorted(entry), ['bytes', 'kind', 'path', 'received_at', 'session', 'sha256', 'source',
                                         'stored', 'unit'])
        self.assertIsNone(retro.keep('U2', 's9', 'transcript', '/y/s9.jsonl', TRANSCRIPT, root=self.root))
        self.assertEqual(retro.indexed(self.root), [entry])
        self.assertEqual([p.name for p in (self.root / 'logs').rglob('*') if p.is_file()], ['s1.jsonl'])

    def test_new_bytes_add_a_line(self):
        retro.keep('U1', 's1', 'transcript', 'a', TRANSCRIPT, root=self.root)
        retro.keep('U1', 's1', 'motor', 'sessions.log', b'21:00 U1 launched\n', root=self.root)
        self.assertEqual([line['kind'] for line in retro.indexed(self.root)], ['transcript', 'motor'])

    def test_a_refused_file_leaves_no_index_line(self):
        with self.assertRaises(retro.Refused):
            retro.keep('U1', 's1', 'transcript', 'bad', b'not json\n', root=self.root)
        self.assertEqual(retro.indexed(self.root), [])


class Ingest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.root, self.home, self.motor = base / 'store', base / 'claude', base / 'motor'
        project = self.home / 'projects' / '-work-the-tower'
        project.mkdir(parents=True)
        self.mine = (b'{"type":"user","sessionId":"s1","gitBranch":"mod/u-one"}\n'
                     b'{"type":"assistant","sessionId":"s1","gitBranch":"mod/u-one"}\n')
        (project / 's1.jsonl').write_bytes(self.mine)
        (project / 's2.jsonl').write_bytes(b'{"type":"user","sessionId":"s2","gitBranch":"mod/other"}\n')
        self.motor.mkdir()
        (self.motor / 'sessions.log').write_bytes(b'20:00 U-ONE launched s1\n20:01 U-ONE-X launched\n20:02 OTHER\n')
        (self.motor / 'U-ONE.capture.txt').write_bytes(b'$ claude\n')

    def tearDown(self):
        self.tmp.cleanup()

    def run_ingest(self, **extra):
        out = io.StringIO()
        ok = retro.ingest('U-ONE', root=self.root, home=self.home, motor=self.motor, out=out, **extra)
        return ok, out.getvalue().splitlines()

    def test_takes_the_unit_transcript_and_motor_records_once(self):
        ok, lines = self.run_ingest()
        self.assertTrue(ok)
        self.assertEqual([line.split(' ', 1)[0] for line in lines], ['took', 'took', 'took'])
        index = retro.indexed(self.root)
        self.assertEqual([entry['kind'] for entry in index], ['transcript', 'motor', 'motor'])
        self.assertEqual(index[0]['session'], 's1')
        self.assertEqual((self.root / index[0]['path']).read_bytes().split(b'\n', 1)[1], self.mine)
        self.assertEqual((self.root / index[-1]['path']).read_bytes().split(b'\n', 1)[1], b'20:00 U-ONE launched s1\n')
        ok, again = self.run_ingest()
        self.assertTrue(ok)
        self.assertEqual([line.split(' ', 1)[0] for line in again], ['skipped', 'skipped', 'skipped'])
        self.assertEqual(retro.indexed(self.root), index)

    def test_a_named_session_and_an_absent_motor(self):
        out = io.StringIO()
        retro.ingest('U-ONE', session='s2', root=self.root, home=self.home, motor=self.motor / 'none', out=out)
        self.assertEqual([entry['session'] for entry in retro.indexed(self.root)], ['s2'])
        self.assertIn('is not on this box', out.getvalue())

    def test_no_transcript_is_said_plainly(self):
        out = io.StringIO()
        retro.ingest('U-ONE', session='missing', root=self.root, home=self.home, motor=self.motor / 'none', out=out)
        self.assertIn('no transcript for U-ONE session missing', out.getvalue())
        self.assertEqual(retro.indexed(self.root), [])


class Receive(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.root = self.base / 'store'

    def tearDown(self):
        self.tmp.cleanup()

    def test_accepts_a_transcript_file_and_stdin_once(self):
        path = self.base / 'handed.jsonl'
        path.write_bytes(TRANSCRIPT)
        out = io.StringIO()
        self.assertTrue(retro.receive('U1', 's1', str(path), root=self.root, out=out))
        self.assertTrue(retro.receive('U1', 's1', root=self.root, stdin=io.BytesIO(TRANSCRIPT), out=out))
        self.assertEqual([line.split(' ', 1)[0] for line in out.getvalue().splitlines()], ['took', 'skipped'])
        self.assertEqual(len(retro.indexed(self.root)), 1)

    def test_refuses_a_file_that_is_not_a_log_and_one_that_is_missing(self):
        path = self.base / 'notes.md'
        path.write_bytes(b'# not a log\n')
        out = io.StringIO()
        self.assertFalse(retro.receive('U1', 's1', str(path), root=self.root, out=out))
        self.assertFalse(retro.receive('U1', 's1', str(self.base / 'absent'), root=self.root, out=out))
        self.assertIn('not a transcript log (line 1 is not JSON)', out.getvalue())
        self.assertIn('cannot be read', out.getvalue())
        self.assertEqual(retro.indexed(self.root), [])

    def test_the_command_exits_one_on_refusal(self):
        path = self.base / 'notes.md'
        path.write_bytes(b'# not a log\n')
        with mock.patch.dict('os.environ', {'TOWER_RETRO_STORE': str(self.root)}), \
                mock.patch('sys.stdout', io.StringIO()):
            self.assertEqual(retro.main(['receive', '--unit', 'U1', '--session', 's1', '--path', str(path)]), 1)


if __name__ == '__main__':
    unittest.main()
