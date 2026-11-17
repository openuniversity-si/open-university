"""`.claude/settings.json`: the SessionStart hook stays, sessions never stall on a prompt, forbidden stays forbidden (D-070)."""
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parent.parent.parent
SETTINGS = json.loads((ROOT / '.claude' / 'settings.json').read_text())
PERMS = SETTINGS.get('permissions', {})
CORE = ['Bash', 'Edit', 'Write', 'Read', 'Glob', 'Grep', 'WebFetch', 'Task', 'TodoWrite']
SCHEDULING = ['CronCreate', 'CronDelete', 'mcp__claude-code-remote']
PROD = ['ship-tail', 'ship-verify', 'merge-phase', 'preview-deploy', 'production-check']
FORMS = ['scripts/', './scripts/', 'bash scripts/', 'bash ./scripts/']


def walk(node):
    if isinstance(node, dict):
        for key, value in node.items():
            yield key, value
            yield from walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from walk(value)


class ClaudeSettings(unittest.TestCase):
    def test_session_start_hook_kept(self):
        hook = SETTINGS['hooks']['SessionStart'][0]['hooks'][0]
        self.assertEqual((hook['type'], hook['command']), ('command', 'bash scripts/cloud/setup.sh'))
        self.assertIsInstance(hook['timeout'], int)  # the value itself is not pinned here: no literal outside the registry (LT1)

    def test_allow_covers_core_scheduling_and_github(self):
        allow = PERMS['allow']
        for name in CORE + SCHEDULING + ['mcp__github']:
            self.assertIn(name, allow)

    def test_deny_covers_prod_commands_in_every_form(self):
        deny = PERMS['deny']
        for script in PROD:
            for form in FORMS:
                self.assertIn(f'Bash({form}{script}:*)', deny)

    def test_deny_covers_force_push_and_workflows(self):
        deny = PERMS['deny']
        for rule in ['Bash(git push -f:*)', 'Bash(git push --force:*)', 'Bash(git push +*)', 'Bash(git push * +*)',
                     'Write(.github/workflows/**)', 'Edit(.github/workflows/**)']:
            self.assertIn(rule, deny)

    def test_no_bypass_anywhere(self):
        for key, value in walk(SETTINGS):
            self.assertNotIn('bypass', str(key).lower())
            self.assertNotIn('dangerously', str(key).lower())
            if key == 'defaultMode':
                self.assertNotIn('bypass', str(value).lower())
        self.assertNotIn('Bash(*)', PERMS['deny'] + [])  # a blanket deny would make the allow list moot


if __name__ == '__main__':
    unittest.main()
