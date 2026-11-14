"""The checkout's git hooks (D-222 (5), the pre-commit hook that regenerates derived files): core.hooksPath must point at this
repository's .githooks, or no versioned hook runs here. The installation belongs to engine-push-guard (push_guard.py install,
called by scripts/cloud/env.sh); this test fails until that installation has run in the checkout.
"""
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parent.parent.parent
HOOKS = '.githooks'


def hooks_path(root):
    """core.hooksPath of the checkout at root, or '' when it is unset."""
    done = subprocess.run(['git', '-C', str(root), 'config', '--get', 'core.hooksPath'], capture_output=True, text=True)
    return done.stdout.strip()


class Checkout(unittest.TestCase):
    def test_core_hookspath_points_at_the_versioned_hooks(self):
        self.assertEqual(hooks_path(ROOT), HOOKS,
                         'core.hooksPath is not .githooks: no versioned hook runs in this checkout (lane 5, engine-push-guard)')


if __name__ == '__main__':
    unittest.main()
