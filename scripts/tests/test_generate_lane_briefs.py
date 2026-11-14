"""The lane-briefs target (D-236, lane 12): one brief per unit of the fluxo-amplo plan, rendered from its program.v1 block.
The committed briefs equal the regeneration, so a unit with no brief (a lane started without one) fails `generate --check`;
a plan with no units is refused. The synthetic plan checks the content without touching the committed tree. No network."""
from pathlib import Path
import json
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import generate  # noqa: E402
import generate_lane_briefs as briefs  # noqa: E402

TARGET = {'name': 'lane-briefs', 'output': 'docs/process/briefs/fluxo-amplo'}


def plan(units):
    body = '\n'.join(['```json program.v1', json.dumps({'units': units}), '```'])
    return 'intro\n\n' + body + '\n'


class Brief(unittest.TestCase):
    def test_a_brief_names_the_unit_its_owner_its_dependencies_and_its_done_criteria(self):
        text = plan([{'id': 'X1', 'title': 'the thing', 'owner': 'lane-9', 'model': 'lane-session', 'wave': 'early',
                      'depends_on': ['G1'], 'done': ['first', 'second']}])
        out = briefs.brief(briefs.units_of(text)[0])
        self.assertTrue(out.startswith('# X1: the thing\n'))
        self.assertIn('Owner: lane-9, model lane-session, wave early', out)
        self.assertIn('Depends on: G1', out)
        self.assertIn('- [ ] first\n- [ ] second\n', out)

    def test_a_unit_without_done_criteria_says_so_instead_of_an_empty_list(self):
        out = briefs.brief({'id': 'X2', 'title': 't', 'owner': 'o'})
        self.assertIn('Depends on: none', out)
        self.assertIn('(the plan names no done criteria)', out)

    def test_a_plan_without_a_program_block_or_units_is_refused(self):
        with self.assertRaises(briefs.BriefError):
            briefs.units_of('no block here')
        with self.assertRaises(briefs.BriefError):
            briefs.units_of(plan([]))


class Committed(unittest.TestCase):
    def test_every_unit_of_the_plan_has_its_brief_and_it_matches_the_regeneration(self):
        text = (ROOT / briefs.PLAN).read_text(encoding='utf-8')
        expected = briefs.render(ROOT, TARGET)
        self.assertEqual(len(expected), len(briefs.units_of(text)))
        for path, body in expected.items():
            file = ROOT / path
            self.assertTrue(file.is_file(), f'missing brief {path}: scripts/generate lane-briefs writes it')
            self.assertEqual(file.read_text(encoding='utf-8'), body, f'stale brief {path}')

    def test_the_target_is_declared_and_checked_by_generate(self):
        self.assertIn('lane-briefs', generate.targets(ROOT))
        self.assertEqual(generate.drift(ROOT, ['lane-briefs']), [])


if __name__ == '__main__':
    unittest.main()
