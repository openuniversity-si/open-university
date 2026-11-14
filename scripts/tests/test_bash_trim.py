"""F80: the PostToolUse hook keeps a short Bash output and trims a long one to its head, its tail and a range hint."""
import io
import json
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import bash_trim  # noqa: E402


def event(stdout, stderr='', tool='Bash', **extra):
    response = {'stdout': stdout, 'stderr': stderr, 'interrupted': False, 'isImage': False, **extra}
    return {'hook_event_name': 'PostToolUse', 'tool_name': tool, 'tool_input': {'command': 'cat big'},
            'tool_response': response}


def run(payload, max_bytes=None):
    out = io.StringIO()
    bash_trim.hook(io.StringIO(json.dumps(payload)), out, max_bytes)
    return json.loads(out.getvalue()) if out.getvalue() else None


LIMIT = bash_trim.limit()
LINES = LIMIT  # ~32 bytes a line: about 32 times the threshold, like a whole-file cat
LONG = ''.join(f'line {n:05d} of the whole-file cat\n' for n in range(1, LINES + 1))
SLACK = len(bash_trim.HINT) + len(bash_trim.HINT)  # the hint and the gap markers on top of the kept bytes


class BashTrimTests(unittest.TestCase):
    def test_a_short_output_is_left_unchanged(self):
        self.assertIsNone(run(event('ok\n', 'warn\n'), LIMIT))
        self.assertIsNone(run(event('x' * LIMIT), LIMIT))

    def test_a_long_output_keeps_head_and_tail_with_a_range_hint(self):
        answer = run(event(LONG), LIMIT)
        output = answer['hookSpecificOutput']
        self.assertEqual(output['hookEventName'], 'PostToolUse')
        trimmed = output['updatedToolOutput']
        self.assertEqual(set(trimmed), {'stdout', 'stderr', 'interrupted', 'isImage'})
        text = trimmed['stdout']
        self.assertLess(len(text.encode()), LIMIT + SLACK)
        self.assertTrue(text.startswith('line 00001 '))
        self.assertIn(f'line {LINES:05d} of the whole-file cat\n', text)
        self.assertIn('bytes omitted', text)
        self.assertNotIn(f'line {LINES >> 1:05d} ', text)
        hint = text.rstrip('\n').splitlines()[-1]
        self.assertIn('rg -n', hint)
        self.assertIn("sed -n 'a,bp'", hint)
        for line in text.splitlines()[:-1]:  # cut on line ends: no half lines around the gap
            self.assertTrue(line.startswith('line ') or 'omitted' in line, line)

    def test_stderr_shares_the_budget_and_is_trimmed_too(self):
        trimmed = run(event(LONG, LONG), LIMIT)['hookSpecificOutput']['updatedToolOutput']
        self.assertLess(len(trimmed['stdout'].encode()) + len(trimmed['stderr'].encode()), LIMIT + SLACK)
        self.assertIn('bytes omitted', trimmed['stderr'])

    def test_other_tools_images_and_bad_input_pass_through(self):
        self.assertIsNone(run(event(LONG, tool='Read'), LIMIT))
        self.assertIsNone(run(event(LONG, isImage=True), LIMIT))
        out = io.StringIO()
        self.assertEqual(bash_trim.hook(io.StringIO('not json'), out), 0)
        self.assertEqual(out.getvalue(), '')

    def test_the_threshold_comes_from_the_registry(self):
        registry = json.loads((ROOT / 'config/registry/flow/flow.bash_trim_bytes.json').read_text())
        self.assertEqual(LIMIT, registry['default'])
        self.assertIsNone(run(event('y' * LIMIT)))
        self.assertIsNotNone(run(event('y' * (LIMIT + 1))))

    def test_the_hook_script_and_its_registration(self):
        done = subprocess.run([str(ROOT / 'scripts/hooks/bash-trim')], input=json.dumps(event(LONG)),
                              capture_output=True, text=True, check=True)
        self.assertIn('updatedToolOutput', done.stdout)
        settings = json.loads((ROOT / '.claude/settings.json').read_text())
        entries = settings['hooks']['PostToolUse']
        self.assertTrue(any(entry.get('matcher') == 'Bash' and hook['command'] == 'bash scripts/hooks/bash-trim'
                            for entry in entries for hook in entry['hooks']))


if __name__ == '__main__':
    unittest.main()
