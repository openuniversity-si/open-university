"""ENGINE-REPO (the migration to GitHub, 14/11/2026): the engine's repository on its forge comes from configuration:
TOWER_ENGINE_REPO, else the service's `engine.repo` datum (written through PUT /v1/config, seen live), else the public
default. Hermetic: fake settings, no database."""
from pathlib import Path
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'infra' / 'service'))
from tower_infra import config_data, engine, fullrun, merge_ready, observations, pregate, prewarm  # noqa: E402

OTHER = 'some-owner/some-repo'


class Settings:
    def __init__(self, value):
        self.value = value

    def get(self, name):
        assert name == 'engine.repo'
        return self.value


class TheRepository(unittest.TestCase):
    def setUp(self):
        self.addCleanup(engine.use, Settings(None))
        engine.use(Settings(None))

    def test_the_default_is_the_public_repository_and_the_registrys(self):
        self.assertEqual(engine.repo({}), 'openuniversity-si/open-university')
        self.assertEqual(config_data.SPEC['engine.repo'][1], engine.DEFAULT)

    def test_the_environment_wins_then_the_settings_then_the_default(self):
        settings = Settings(OTHER)
        engine.use(settings)
        self.assertEqual(engine.repo({}), OTHER)
        self.assertEqual(engine.repo({engine.ENV: 'env-owner/env-repo'}), 'env-owner/env-repo')
        settings.value = 'changed/live'  # a write the service sees on tower_config: no restart
        self.assertEqual(engine.repo({}), 'changed/live')

    def test_a_value_that_is_not_owner_slash_name_is_ignored(self):
        engine.use(Settings('not a repo'))
        self.assertEqual(engine.repo({engine.ENV: ' '}), engine.DEFAULT)
        with self.assertRaises(ValueError):
            config_data.validate('engine.repo', 'not a repo')
        self.assertEqual(config_data.validate('engine.repo', OTHER), OTHER)

    def test_the_looks_follow_it_unless_one_is_given(self):
        engine.use(Settings(OTHER))
        looks = [pregate.Pregate(), fullrun.FullRun(create=lambda *a: None, cancel=lambda *a: None),
                 merge_ready.Look(object()), observations.Observer(object())]
        self.assertEqual({look.repo for look in looks}, {OTHER})
        self.assertEqual(pregate.Pregate(repo='given/one').repo, 'given/one')
        self.assertEqual(prewarm.Prewarm.repo.fget(type('P', (), {'_repo': None})()), OTHER)

    def test_no_look_reads_a_hard_coded_repository_any_more(self):
        service = ROOT / 'infra' / 'service' / 'tower_infra'
        for path in sorted(service.glob('*.py')):
            if path.name in ('engine.py', 'config_data.py'):
                continue
            text = path.read_text(encoding='utf-8')
            self.assertFalse(re.findall(r"'openuniversity-si/open-university'", text), path.name)
            self.assertNotIn('repo=REPO', text, path.name)

    def test_the_service_hands_its_settings_over(self):
        main = (ROOT / 'infra' / 'service' / 'tower_infra' / '__main__.py').read_text(encoding='utf-8')
        self.assertIn('engine.use(settings)', main)


if __name__ == '__main__':
    unittest.main()
