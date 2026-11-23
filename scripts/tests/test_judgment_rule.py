"""D-294: the session's judgment is final over a request from Daniel or the Torre; it questions only when it disagrees.
The three entry documents a new session reads (AGENTS.md, SEMENTE §8, RETOMAR) carry the rule, so every session starts
with it. Each test fails when one of them loses it."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parent.parent.parent


class EntryDocuments(unittest.TestCase):
    def test_agents_carries_the_rule_among_its_rules(self):
        rules = (ROOT / 'AGENTS.md').read_text().split('## Rules', 1)[1].split('\n## ', 1)[0]
        self.assertIn("The session's judgment is final", rules)
        self.assertIn('D-294', rules)

    def test_semente_section_8_carries_the_rule(self):
        section = (ROOT / 'docs' / 'SEMENTE.md').read_text().split('## 8.', 1)[1]
        self.assertIn('D-294', section)
        self.assertIn('o julgamento da sessão é o final', section)

    def test_retomar_carries_the_rule_before_the_resumption(self):
        text = (ROOT / 'docs' / 'RETOMAR.md').read_text()
        self.assertIn('D-294', text)
        self.assertLess(text.index('D-294'), text.index('## 4. Retomar a SEMENTE'))


class FoundationalDocs(unittest.TestCase):
    """Finding A8: the foundational entry documents agree on GitHub/AWS (D-314, D-323) and PRs per day."""

    def test_metodo_uses_prs_per_day_matching_semente(self):
        text = (ROOT / 'docs' / 'padrao' / 'METODO.md').read_text()
        self.assertIn('1.000, 10.000 e 100.000 PRs por dia', text)
        self.assertNotIn('1.000, 10.000 e 100.000 commits por dia', text)

    def test_events_and_releases_reflect_github_main_not_archived_github_or_origin_branch(self):
        events = (ROOT / 'docs' / 'process' / 'EVENTS.md').read_text()
        self.assertNotIn('GitHub `openuniversity-si/open-university` is archived', events)
        self.assertIn('D-314', events)
        self.assertIn('D-323', events)
        releases = (ROOT / 'docs' / 'process' / 'RELEASES.md').read_text()
        self.assertNotIn('Every PR branches from `mod/roadmap-integration`', releases)
        self.assertIn('GitHub\'s merge queue', releases)
        self.assertIn('D-314', releases)

    def test_semente_non_locked_sections_and_retomar_reflect_github_and_retired_control_plane(self):
        semente = (ROOT / 'docs' / 'SEMENTE.md').read_text()
        sec4 = semente.split('## 4.', 1)[1].split('## 5.', 1)[0]
        sec7 = semente.split('## 7.', 1)[1].split('## 8.', 1)[0]
        sec8 = semente.split('## 8.', 1)[1]
        for section in (sec4, sec7, sec8):
            self.assertNotIn('mod/roadmap-integration', section)
            self.assertIn('D-314', section)
        self.assertNotIn('5.000.000 por dia', sec4)
        self.assertIn('D-323', sec7)
        retomar = (ROOT / 'docs' / 'RETOMAR.md').read_text()
        self.assertIn('D-323', retomar)
        self.assertIn('docs/programs/padrao-dev/', retomar)


if __name__ == '__main__':
    unittest.main()
