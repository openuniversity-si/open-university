"""The lane-digest target (VAZÃO F78): lane.md's Rules digest block, copied to docs/process/lane-digest.md, at most
1.5 KB, carrying every rule a lane needs to deliver. The live digest equals its regeneration, so a digest left stale by
an edit of lane.md fails here and in `generate --check`. No network."""
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import generate  # noqa: E402
import generate_lane_digest as digest  # noqa: E402

LANE = '# The lane\n\n## The delivery contract\nx\n\n## Rules digest (F78)\nWhy.\n\n```digest\n1. rule\n```\n\n## Other\n'
# One phrase per rule a lane cannot deliver without (F78): worktree and toolchain, trailers and plan, pr-body and the
# effort block, test-suite once, deliver, no fila.md edits, the token budget.
RULES = ('scripts/lane worktree', '.toolchain', 'mod/roadmap-integration', 'Plan: N', 'Co-Authored-By:',
         'Claude-Session: <session>', 'scripts/pr-body --title --action --cost --requirement --cheaper', 'commit-check --pr-body', 'Cheapest useful effort',
         'Action:', 'Cost:', 'Requirement:', 'Cheaper rejected:', 'Premises:', 'Fit-Review:',
         'test-suite --changed` once', 'scripts/deliver --open --branch', 'Never edit fila.md', 'tokens a call', 'tail -20',
         'config/registry/<area>/', 'One unit per lane', 'frictions.jsonl')


class Digest(unittest.TestCase):
    def test_the_digest_is_the_block_under_its_heading_with_a_generated_header(self):
        self.assertEqual(digest.digest(LANE), digest.HEADER + '1. rule\n')

    def test_a_missing_block_or_an_oversized_digest_is_refused(self):
        with self.assertRaises(digest.DigestError):
            digest.digest('# The lane\n\n```digest\n1. not under the heading\n```\n')
        with self.assertRaises(digest.DigestError):
            digest.digest(LANE.replace('1. rule', 'x' * digest.limit()))

    def test_render_without_lane_md_expects_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(digest.render(tmp, {}), {})


class LiveDigest(unittest.TestCase):
    def test_the_committed_digest_is_current_small_and_carries_every_rule(self):
        self.assertEqual(generate.drift(ROOT, names={'lane-digest'}), [])
        text = (ROOT / digest.OUTPUT).read_text(encoding='utf-8')
        self.assertLessEqual(len(text.encode('utf-8')), digest.limit(ROOT))
        for rule in RULES:
            self.assertIn(rule, text, rule)


if __name__ == '__main__':
    unittest.main()
