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


if __name__ == '__main__':
    unittest.main()
