"""No module under scripts/lib writes git data through REST (the class fix behind forge_git_ref). It reads every module, so it
has its own wrapper and covers: a change to any of them runs this one test, and none of the others."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parent.parent.parent


class NoRestGitDataWrite(unittest.TestCase):
    """The class fix: no module under scripts/lib writes git data (trees, commits, refs, blobs, tags) through REST; the
    proxy refuses it (audit.md), so a ref moves only through forge_git_ref."""

    WRITE = re.compile(r"""(?:rest|_request)\(\s*'(?:POST|PATCH|PUT|DELETE)',\s*f?'[^']*/git/(?:trees|commits|refs|blobs|tags)""")
    FROZEN = {}  # D-293: the last archived REST git-data writer left with the GitHub client.

    def test_no_rest_git_data_write(self):
        found = {}
        for path in sorted((ROOT / 'scripts' / 'lib').rglob('*.py')):
            count = len(self.WRITE.findall(path.read_text()))
            if count:
                found[path.name] = count
        self.assertEqual(found, self.FROZEN)


if __name__ == '__main__':
    unittest.main()
