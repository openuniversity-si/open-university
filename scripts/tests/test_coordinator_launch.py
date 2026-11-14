"""The coordinator's launch adapter (D-069 CO1): brief rendering, lessons port, launcher port. No CLI, no network."""
from collections import namedtuple
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import config  # noqa: E402
import coordinator  # noqa: E402
import coordinator_launch  # noqa: E402
import forge_events  # noqa: E402
import lessons  # noqa: E402
import program  # noqa: E402
from adapters import launcher, launcher_claude  # noqa: E402

PLAN = program.load('reach-1000-prs-per-day')
UNIT = dict(next(unit for unit in PLAN['units'] if unit['id'] == 'CO1'), area=['scripts/lib/coordinator*.py'])


def setUpModule():
    unittest.enterModuleContext(config.use_adapter(forge_events.MemoryAdapter()))


class FakeLessons:
    def __init__(self):
        self.asked = []

    def for_area(self, paths):
        self.asked.append(list(paths))
        return ['LR-1 [rule] commit small']

    def candidates(self, unit_ids):
        return []


class Padrao(unittest.TestCase):
    def test_every_manifest_rule_loads_in_order(self):
        version, rules = coordinator_launch.padrao()
        self.assertEqual(version, config.get('coordinator.padrao_version'))
        self.assertEqual([name for name, _ in rules][:2], ['save-often', 'decide-then-report'])
        self.assertTrue(all(text for _, text in rules))

    def test_the_two_named_texts_are_in_the_repo(self):
        texts = dict(coordinator_launch.padrao()[1])
        self.assertIn('Never hold more than one green step unpushed', texts['save-often'])
        self.assertIn('Ending a turn with "this is a decision for the owner" is a failure.', texts['decide-then-report'])


class Brief(unittest.TestCase):
    def test_brief_has_unit_padrao_lessons_and_defects(self):
        lessons = FakeLessons()
        text = coordinator_launch.render_brief(PLAN, UNIT, 2, lessons)
        self.assertIn('# Unit CO1', text)
        self.assertIn('attempt 2', text)
        self.assertIn('Depends on: KD1, GS1, GV1, TR1, LR1.', text)
        self.assertIn(f"## Padrão {config.get('coordinator.padrao_version')}", text)  # the active version, D-115
        self.assertIn('Never hold more than one green step unpushed', text)
        self.assertIn('- LR-1 [rule] commit small', text)
        self.assertEqual(lessons.asked, [['scripts/lib/coordinator*.py']])
        self.assertIn('## Known defects', text)

    def test_null_lessons_say_none(self):
        text = coordinator_launch.render_brief(PLAN, UNIT, 1)
        self.assertIn('## Applied lessons\nNone.', text)

    def test_defect_lines_obey_the_limit(self):
        self.assertEqual(coordinator_launch.defect_lines(limit=0), [])
        self.assertLessEqual(len(coordinator_launch.defect_lines()), config.get('coordinator.brief_defects_limit'))

    def test_briefs_for_every_unit_not_merged(self):
        # B1 (D-204): a unit stays briefed after its start; a merged unit has no brief to print.
        rows = [{'id': 'CO1', 'stage': 'running'}, {'id': 'CO2', 'stage': 'merged'}]
        self.assertEqual(list(coordinator_launch.briefs_for(PLAN, rows)), ['CO1'])


class Lr1Adapter(unittest.TestCase):
    """The real LR1 registry (scripts/lib/lessons.py, lessons_brief.py) on a temporary register, no fakes."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        shutil.copytree(ROOT / 'contracts' / 'lessons', self.tmp / 'contracts' / 'lessons')

    def add(self, title, unit, area, candidate):
        record, _ = lessons.add(self.tmp, title, unit, f'docs/units/{unit}/retro.md', 5, 'F1', config.get('lessons.classes')[0],
                                config.get('lessons.kinds')[0], 'change the template', config.get('lessons.owners')[0],
                                area=area, padrao_candidate=candidate)
        return record

    def test_applied_lessons_for_the_unit_area_reach_the_brief(self):
        record = self.add('Name the area', 'GV1', ['scripts/lib/coordinator*.py'], False)
        lessons.apply(self.tmp, record['id'], 1, 'a ref')
        port = coordinator_launch.Lr1Lessons(self.tmp)
        self.assertEqual(len(port.for_area(['scripts/lib/coordinator.py'])), 1)
        self.assertEqual(port.for_area(['docs/x.md']), [])
        text = coordinator_launch.render_brief(PLAN, UNIT, 1, port)
        self.assertIn(record['id'], text)

    def test_padrao_candidates_of_the_programs_units_are_listed(self):
        mine = self.add('Change the Padrao', 'GV1', [], True)
        self.add('Local only', 'GV1', [], False)
        self.add('Other program', 'ZZ9', [], True)
        found = coordinator_launch.Lr1Lessons(self.tmp).candidates([unit['id'] for unit in PLAN['units']])
        self.assertEqual(len(found), 1)
        self.assertIn(mine['id'], found[0])

    def test_the_checkout_registry_loads_through_the_port(self):
        self.assertIsInstance(coordinator_launch.lessons_port(), coordinator_launch.Lr1Lessons)


class Launcher(unittest.TestCase):
    Done = namedtuple('Done', 'returncode stdout stderr', defaults=('',))

    def test_claude_cloud_adapter_runs_the_registered_argv_and_reads_the_session(self):
        calls = []

        def runner(argv, **options):
            calls.append((argv, options))
            return self.Done(0, 'started session_01ABC for you')
        session = launcher_claude.ClaudeCloudLauncher(runner).launch(launcher.LaunchRequest('CO1', 1, 'm', 'the brief'))
        self.assertEqual(session, 'session_01ABC')
        self.assertEqual(calls[0][0], config.get('coordinator.launcher_argv') + ['the brief'])
        self.assertEqual(calls[0][1]['timeout'], config.get('coordinator.launcher_timeout_s'))

    def test_failed_launch_raises(self):
        for done in (self.Done(1, 'session_01ABC'), self.Done(0, 'nothing')):
            with self.assertRaises(launcher_claude.ClaudeLauncherError):
                launcher_claude.ClaudeCloudLauncher(lambda argv, **options: done).launch(launcher.LaunchRequest('CO1', 1, 'm', 'b'))

    def test_preflight_refuses_a_flag_the_cli_does_not_list(self):
        # D-206 (d): a stale flag fails before the first launch. The probe is the command's --help (the runner here).
        def runner(argv, **options):
            return self.Done(0, 'Usage: claude [options] [prompt]\n  --print  print and exit\n  --model <m>  model')
        with self.assertRaises(launcher_claude.ClaudeLauncherError) as raised:
            launcher_claude.ClaudeCloudLauncher(runner).preflight()
        self.assertIn('--remote', str(raised.exception))

    def test_preflight_passes_when_every_flag_is_listed(self):
        def runner(argv, **options):
            return self.Done(0, 'Usage: claude [options]\n  --remote  start a cloud session\n')
        launcher_claude.ClaudeCloudLauncher(runner).preflight()

    def test_dry_run_launcher_records_and_starts_nothing(self):
        dry = launcher.DryRunLauncher()
        self.assertIsNone(dry.launch(launcher.LaunchRequest('CO1', 1, 'm', 'b')))
        self.assertEqual(len(dry.requests), 1)

    def test_unknown_adapter_is_refused(self):
        with self.assertRaises(launcher.LauncherError):
            launcher.adapter('nope')

    def test_dry_run_cli_prints_briefs_without_launching(self):
        done = subprocess.run([sys.executable, str(ROOT / 'scripts' / 'lib' / 'coordinator.py'), 'run', 'reach-1000-prs-per-day',
                               '--events', '/dev/null', '--briefs'], capture_output=True, text=True,
                              env={'OU_CONFIG_STORE': 'file', 'PATH': '/usr/bin:/bin'})
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn('===== brief GD1 =====', done.stdout)


if __name__ == '__main__':
    unittest.main()
