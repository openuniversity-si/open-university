"""The gate and the train as the default configuration of our management (engine-gate-infra; GATE-INFRA 1, P5 F1).

config/management/gate-train.json carries ARQUITETURA-ALVO §7 rule by rule: the text of each row, the infrastructure
mechanism that carries it, the work.job parameters our management sets for it, where today's rule lives and its value.
These tests check that no rule of §7 is missing or added, that each mechanism exists in the infrastructure (every job
parameter is a column of work.job and every selector key one the route function reads), and that every source and
registry key it names exists, so the migration of P5 loses no rule. No network.
"""
import json
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG = ROOT / 'config/management/gate-train.json'
TARGET = ROOT / 'docs/arquitetura-referencia/ARQUITETURA-ALVO.md'
MIGRATION = ROOT / 'infra/db/migrations/0001_work_log.sql'
AREAS = ROOT / 'scripts/lib/gate-areas.json'
REGISTRY = ROOT / 'config/registry'
COMMENT = re.compile(r'--[^\n]*')
CONSTRAINTS = {'unique', 'foreign', 'check', 'primary', 'constraint'}


def table_rows(text, header):
    """The cells of each row of the markdown table whose header line starts with `header`."""
    lines = text[text.index(header):].splitlines()
    rows = []
    for line in lines[lines.index(next(line for line in lines if line.startswith('|---'))) + 1:]:
        if not line.startswith('|'):
            break
        rows.append([cell.strip() for cell in line.strip().strip('|').split(' | ')])
    return rows


def columns(sql, table):
    """The column names of `create table <table> (...)`, constraints aside, by commas outside quotes and parentheses."""
    body = re.search(r'create table ' + re.escape(table) + r' \((.*?)\);', COMMENT.sub('', sql), re.S).group(1)
    parts, part, depth, quoted = [], '', 0, False
    for char in body:
        quoted = quoted != (char == "'")
        depth += 0 if quoted else (char == '(') - (char == ')')
        if char == ',' and not depth and not quoted:
            parts.append(part)
            part = ''
        else:
            part += char
    parts.append(part)
    return {words[0] for words in (piece.split() for piece in parts) if words and words[0] not in CONSTRAINTS}


def nested(value, kind):
    """Every {kind: ...} object inside value."""
    if isinstance(value, dict):
        found = [value] if kind in value else []
        return found + [ref for item in value.values() for ref in nested(item, kind)]
    if isinstance(value, list):
        return [ref for item in value for ref in nested(item, kind)]
    return []


def references(rule, kind):
    """The {kind: ...} references of a rule: in the job it sets and in its value, never its own lists."""
    return nested(rule.get('job', {}), kind) + nested(rule.get('value', {}), kind)


def registry_file(key):
    return REGISTRY / key.split('.')[0] / f'{key}.json'


class GateTrainConfig(unittest.TestCase):
    def setUp(self):
        self.config = json.loads(CONFIG.read_text(encoding='utf-8'))
        self.rules = self.config['rules']

    def test_every_rule_of_section_7_has_its_line_and_none_is_added(self):
        section = table_rows(TARGET.read_text(encoding='utf-8'), '| Regra de hoje |')
        self.assertTrue(section)
        self.assertEqual([[rule['today'], rule['infrastructure'], rule['management']] for rule in self.rules], section)

    def test_each_rule_has_one_id(self):
        ids = [rule['id'] for rule in self.rules]
        self.assertEqual(len(ids), len(set(ids)))
        for rule_id in ids:
            self.assertRegex(rule_id, r'^[a-z][a-z0-9-]+$')

    def test_every_mechanism_is_named_and_described(self):
        for rule in self.rules:
            self.assertIn(rule['mechanism'], self.config['mechanisms'], rule['id'])
            if rule['mechanism'] != 'none':
                self.assertTrue(rule.get('job') or rule['mechanism'] == 'log', rule['id'])

    def test_every_job_parameter_is_a_column_of_work_job_and_every_selector_key_one_the_route_reads(self):
        sql = MIGRATION.read_text(encoding='utf-8')
        job_columns = columns(sql, 'work.job')
        self.assertLessEqual({'selector', 'memoize', 'exclusive_key', 'max_attempts', 'retry_on', 'not_before'},
                             job_columns)
        selector_keys = set(re.findall(r"selector\s*(?:\?|->>?)\s*'(\w+)'", sql))
        for rule in self.rules:
            job = rule.get('job', {})
            self.assertLessEqual(set(job), job_columns, rule['id'])
            self.assertLessEqual(set(job.get('selector', {})), selector_keys, rule['id'])

    def test_every_source_named_exists(self):
        for rule in self.rules:
            for path in rule.get('where', []):
                self.assertTrue((ROOT / path).exists(), f"{rule['id']}: {path}")
            for ref in references(rule, 'file'):
                data = json.loads((ROOT / ref['file']).read_text(encoding='utf-8'))
                if 'key' in ref:
                    self.assertIn(ref['key'], data, f"{rule['id']}: {ref}")
            for ref in references(rule, 'dir'):
                self.assertTrue((ROOT / ref['dir']).is_dir(), f"{rule['id']}: {ref}")

    def test_every_registry_key_named_exists(self):
        for rule in self.rules:
            keys = set(rule.get('registry', [])) | {ref['registry'] for ref in references(rule, 'registry')}
            for key in keys:
                self.assertTrue(registry_file(key).is_file(), f"{rule['id']}: {key}")
            self.assertLessEqual({ref['registry'] for ref in references(rule, 'registry')},
                                 set(rule.get('registry', [])), rule['id'])

    def test_the_seven_stages_are_the_gates_own(self):
        rule = next(rule for rule in self.rules if rule['id'] == 'always-stages')
        named = re.findall(r'`([^`]+)`', rule['today'])
        self.assertEqual(named, json.loads(AREAS.read_text(encoding='utf-8'))['always'])
        self.assertEqual(rule['value']['stages'], {'file': 'scripts/lib/gate-areas.json', 'key': 'always'})

    def test_merge_commits_only_and_the_landing_holds_the_branch(self):
        by_id = {rule['id']: rule for rule in self.rules}
        self.assertEqual(by_id['base-merge-before-checks']['value'], {'merge_base_into_branch': True, 'method': 'merge',
                                                                     'rebase': False})
        for rule_id in ('land-with-expected-head', 'batch'):
            self.assertEqual(by_id[rule_id]['mechanism'], 'landing')
            self.assertIn('exclusive_key', by_id[rule_id]['job'])
        self.assertIs(by_id['land-with-expected-head']['value']['expect_head'], True)

    def test_it_is_management_and_stays_out_of_the_infrastructure(self):
        self.assertNotIn('infra', CONFIG.relative_to(ROOT).parts)
        self.assertIn('D-306', self.config['description'])


if __name__ == '__main__':
    unittest.main()
