"""Mechanical enforcement of the SEMENTE §6 intention lock (audit C4, D-317, proposed D-358).

Verifies: STD-intention-lock-errors
"""
import contextlib
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import intention_lock
import model

SAMPLE_SEMENTE = (
    '# Semente\n\n'
    '## 1. O que é\n\nIntro.\n\n'
    '## 3. Intenção (v1) — travada\n\nLocked intent v1.\n\n'
    '## 4. Como se mede hoje\n\nMutable measurement.\n\n'
    '## 6. Restrições — travada\n\nLocked constraints v1.\n\n'
    '## 7. Onde o sistema lê\n\nMutable pointers.\n'
)

VALID_INT = {
    'id': 'INT-limits',
    'statement': 'Locked constraints.',
    'state': 'active',
    'owner': 'Daniel',
    'source': 'docs/SEMENTE.md#6',
}

VALID_TRAILER = 'Intention-Change: approved by Daniel 2026-11-22 15:00 BRT (GitHub PR #358)'


def _git(root, *args):
    subprocess.run(['git', '-C', str(root), *args], check=True, capture_output=True, text=True)


def _write(root, rel, content):
    target = Path(root) / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content if isinstance(content, str) else json.dumps(content) + '\n', encoding='utf-8')


def _init_repo(root):
    _git(root, 'init', '-b', 'main')
    _git(root, 'config', 'user.name', 'Test User')
    _git(root, 'config', 'user.email', 'test@example.invalid')
    _write(root, 'docs/SEMENTE.md', SAMPLE_SEMENTE)
    _write(root, 'config/intent/INT-limits.json', VALID_INT)
    _git(root, 'add', '.')
    _git(root, 'commit', '-m', 'base')
    _git(root, 'branch', 'base-ref')


class ParseAndSections(unittest.TestCase):
    def test_extract_sections_isolates_locked_sections_from_unlocked_ones(self):
        sections = intention_lock.extract_sections(SAMPLE_SEMENTE)
        self.assertIn('Locked intent v1.', sections['3'])
        self.assertIn('Locked constraints v1.', sections['6'])
        self.assertIn('Mutable measurement.', sections['4'])
        self.assertNotIn('Mutable measurement.', sections['3'])

    def test_parse_approval_accepts_valid_owner_line_and_rejects_forged_or_placeholder_lines(self):
        parsed = intention_lock.parse_approval(f'Summary\n\n{VALID_TRAILER}\n')
        self.assertEqual(parsed['day'], '2026-11-22')
        self.assertEqual(parsed['clock'], '15:00')
        self.assertEqual(parsed['where'], 'GitHub PR #358')
        for bad in (
            '',
            'Intention-Change: approved by session 2026-11-22 15:00 BRT (chat)',
            'Intention-Change: approved by Daniel <AAAA-MM-DD> 15:00 BRT (PR)',
            'Intention-Change: approved by Daniel 2026-11-22 15:00 BRT (<onde aprovou>)',
            'Intention-Change: approved by Daniel 2026-02-30 15:00 BRT (PR #1)',
            'Intention-Change: approved by Daniel 2026-11-22 99:00 BRT (PR #1)',
            'Intention-Change: approved by Daniel 2026-11-22 15:00 UTC (PR #1)',
            'Intention-Change: approved by Daniel 2026-11-22 15:00 BRT ()',
        ):
            self.assertIsNone(intention_lock.parse_approval(bad), bad)


class GitLockEnforcement(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix='intention-lock-'))
        self.addCleanup(shutil.rmtree, self.root)
        _init_repo(self.root)

    def _commit(self, message):
        _git(self.root, 'add', '-A')
        _git(self.root, 'commit', '-m', message)

    def test_unlocked_semente_sections_change_without_intention_change_passes(self):
        updated = SAMPLE_SEMENTE.replace('Mutable measurement.', 'Updated measurement.').replace(
            'Mutable pointers.', 'Updated pointers.'
        )
        _write(self.root, 'docs/SEMENTE.md', updated)
        self._commit('docs: update non-locked sections')
        self.assertEqual(intention_lock.locked_changes(self.root, 'base-ref'), [])
        self.assertEqual(intention_lock.intention_lock_errors(self.root, 'base-ref', body='no trailer', title='docs: x'), [])

    def test_locked_semente_section_3_and_6_changes_refused_without_approval_and_accepted_with_it(self):
        updated = SAMPLE_SEMENTE.replace('Locked intent v1.', 'Locked intent v2.').replace(
            'Locked constraints v1.', 'Locked constraints v2.'
        )
        _write(self.root, 'docs/SEMENTE.md', updated)
        self._commit('intencao: propose locked update')
        self.assertEqual(
            intention_lock.locked_changes(self.root, 'base-ref'),
            ['docs/SEMENTE.md#3', 'docs/SEMENTE.md#6'],
        )
        refused = intention_lock.intention_lock_errors(self.root, 'base-ref', body='proposal only', title='intencao: update')
        self.assertEqual(len(refused), 1)
        self.assertIn('docs/SEMENTE.md#3', refused[0])
        self.assertIn('docs/SEMENTE.md#6', refused[0])
        self.assertEqual(
            intention_lock.intention_lock_errors(self.root, 'base-ref', body=VALID_TRAILER, title='intencao: update'),
            [],
        )

    def test_int_file_edit_add_or_delete_refused_without_approval_and_enforces_title(self):
        _write(self.root, 'config/intent/INT-limits.json', {**VALID_INT, 'statement': 'Changed.'})
        _write(self.root, 'config/intent/INT-extra.json', {**VALID_INT, 'id': 'INT-extra'})
        self._commit('intent: edit INT files')
        self.assertEqual(
            intention_lock.locked_changes(self.root, 'base-ref'),
            ['config/intent/INT-extra.json', 'config/intent/INT-limits.json'],
        )
        wrong_title = intention_lock.intention_lock_errors(
            self.root, 'base-ref', body=VALID_TRAILER, title='feat: sneak intent change'
        )
        self.assertEqual(len(wrong_title), 1)
        self.assertIn('intencao:', wrong_title[0])
        self.assertEqual(
            intention_lock.intention_lock_errors(self.root, 'base-ref', body=VALID_TRAILER, title='intencao: align limits'),
            [],
        )

    def test_approval_in_commit_message_satisfies_lock_and_clears_pending_warning(self):
        _write(self.root, 'config/intent/INT-limits.json', {**VALID_INT, 'statement': 'Approved change.'})
        self._commit(f'intencao: approved limits\n\n{VALID_TRAILER}')
        self.assertEqual(intention_lock.intention_lock_errors(self.root, 'base-ref', title='intencao: approved'), [])
        self.assertEqual(intention_lock.pending_lock_warnings(self.root, base='base-ref'), [])

    def test_pending_lock_warning_fires_without_commit_trailer_and_unreadable_base_fails_closed(self):
        _write(self.root, 'config/intent/INT-limits.json', {**VALID_INT, 'statement': 'Draft proposal.'})
        self._commit('intencao: draft proposal')
        warnings = intention_lock.pending_lock_warnings(self.root, base='base-ref')
        self.assertEqual(len(warnings), 1)
        self.assertIn('config/intent/INT-limits.json', warnings[0])
        bad_base = intention_lock.intention_lock_errors(self.root, 'no-such-ref')
        self.assertEqual(len(bad_base), 1)
        self.assertIn('cannot resolve merge-base', bad_base[0])

    def test_cli_exits_nonzero_on_refusal_and_zero_when_authorized(self):
        _write(self.root, 'config/intent/INT-limits.json', {**VALID_INT, 'statement': 'Changed via cli test.'})
        self._commit('intencao: cli test')
        body_path = self.root / 'body.md'
        body_path.write_text('no approval yet\n', encoding='utf-8')
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = intention_lock.main(['--root', str(self.root), '--base', 'base-ref', '--pr-body', str(body_path)])
        self.assertEqual(code, 1)
        self.assertIn('FAIL intention-lock:', buf.getvalue())
        body_path.write_text(f'{VALID_TRAILER}\n', encoding='utf-8')
        buf_ok = io.StringIO()
        with contextlib.redirect_stdout(buf_ok):
            code_ok = intention_lock.main([
                '--root', str(self.root), '--base', 'base-ref', '--pr-body', str(body_path), '--title', 'intencao: ok'
            ])
        self.assertEqual(code_ok, 0)


class IntentObjectsAndModelCheck(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix='intent-objects-'))
        self.addCleanup(shutil.rmtree, self.root)
        _write(self.root, 'docs/SEMENTE.md', SAMPLE_SEMENTE)

    def test_check_intent_objects_requires_daniel_owner_and_existing_semente_section(self):
        good = {'INT-limits': {'id': 'INT-limits', 'type': 'INT', 'state': 'active', 'body': VALID_INT}}
        self.assertEqual(intention_lock.check_intent_objects(good, self.root), [])
        bad_owner = {'INT-limits': {'id': 'INT-limits', 'type': 'INT', 'state': 'active',
                                    'body': {**VALID_INT, 'owner': 'session'}}}
        self.assertTrue(any('owner must be Daniel' in line for line in intention_lock.check_intent_objects(bad_owner, self.root)))
        bad_section = {'INT-limits': {'id': 'INT-limits', 'type': 'INT', 'state': 'active',
                                      'body': {**VALID_INT, 'source': 'docs/SEMENTE.md#9'}}}
        self.assertTrue(any('does not exist' in line for line in intention_lock.check_intent_objects(bad_section, self.root)))

    def test_model_check_enforces_lock_when_base_is_given(self):
        _write(self.root, 'contracts/model/validation.v1.json',
               (ROOT / 'contracts/model/validation.v1.json').read_text(encoding='utf-8'))
        _write(self.root, 'config/model/conformance.json',
               (ROOT / 'config/model/conformance.json').read_text(encoding='utf-8'))
        _init_repo(self.root)
        _write(self.root, 'config/intent/INT-limits.json', {**VALID_INT, 'statement': 'Changed in model check.'})
        _git(self.root, 'add', '-A')
        _git(self.root, 'commit', '-m', 'intent: change')
        meta = model.metamodel(ROOT)
        found = {'INT-limits': {'id': 'INT-limits', 'type': 'INT', 'state': 'active', 'source': 'config/intent/INT-limits.json',
                                'fingerprint': 'abc', 'links': [], 'body': {**VALID_INT, 'statement': 'Changed in model check.'}}}
        errors, _ = model.check(meta, found, self.root, base='base-ref', pr_body='none', pr_title='intencao: x')
        self.assertTrue(any('intention-lock:' in line for line in errors))
        errors_ok, _ = model.check(meta, found, self.root, base='base-ref', pr_body=VALID_TRAILER, pr_title='intencao: x')
        self.assertFalse(any('intention-lock:' in line for line in errors_ok))


class RepositorySection3Alignment(unittest.TestCase):
    def test_semente_section_3_proposes_verified_useful_deliveries_and_aligns_intent_files(self):
        sections = intention_lock.extract_sections((ROOT / 'docs/SEMENTE.md').read_text(encoding='utf-8'))
        sec3 = sections['3']
        self.assertIn('entregas úteis verificadas por segundo', sec3)
        self.assertNotIn('Isso é bom senso, não regra mecânica.', sec3)
        for label in ('1.000', '10.000', '100.000', '100 %'):
            self.assertIn(label, sec3)
        for ident in ('INT-intention-v1', 'INT-ladder-1', 'INT-ladder-2', 'INT-ladder-3', 'NEED-throughput'):
            body = json.loads((ROOT / f'config/intent/{ident}.json').read_text(encoding='utf-8'))
            self.assertIn('verified useful deliveries', body['statement'].lower(), ident)
            self.assertIn('100%', body['statement'], ident)


class RepositorySection6QuotaAlignment(unittest.TestCase):
    def test_semente_section_6_reconciles_anthropic_quota_and_governance_lock(self):
        sections = intention_lock.extract_sections((ROOT / 'docs/SEMENTE.md').read_text(encoding='utf-8'))
        sec6 = sections['6']
        self.assertIn('Intention-Change: approved by Daniel', sec6)
        self.assertIn('supply.anthropic_monthly_usd', sec6)
        self.assertIn('REQ-anthropic-budget', sec6)
        self.assertIn('TAIL-*', sec6)
        self.assertNotIn('O orçamento é a cota de **uma** conta Claude Max', sec6)
        for rel in ('config/intent/INT-limits.json', 'config/intent/NEED-cost.json', 'config/problem/NC-cost.json'):
            body = json.loads((ROOT / rel).read_text(encoding='utf-8'))
            self.assertIn('supply.anthropic_monthly_usd', body['statement'], rel)
            self.assertNotIn('one Claude Max quota', body['statement'], rel)
        sup = json.loads((ROOT / 'config/supply/suppliers/SUP-anthropic.json').read_text(encoding='utf-8'))
        val = json.loads((ROOT / 'config/validation/VAL-anthropic-budget.json').read_text(encoding='utf-8'))
        self.assertEqual(sup['budget'], 'REQ-anthropic-budget')
        self.assertEqual(val['threshold_key'], 'supply.anthropic_monthly_usd')

    def test_decisions_d358_and_d362_are_accepted_and_d362_supersedes_d342(self):
        table_text = (ROOT / 'docs/domain/DECISIONS.md').read_text(encoding='utf-8')
        for number, expected_proof, expected_supersedes in (
            ('D-358', 'scripts/tests/intention-lock.test.sh', None),
            ('D-362', 'scripts/tests/supply.test.sh', 'D-342'),
        ):
            text = (ROOT / f'docs/domain/decisions/{number}.md').read_text(encoding='utf-8')
            head = model.FRONT.match(text)
            self.assertIsNotNone(head, number)
            fields = {line.split(':', 1)[0].strip(): line.split(':', 1)[1].strip()
                      for line in head.group(1).splitlines() if ':' in line}
            self.assertEqual(fields.get('number'), number)
            self.assertNotIn('status', fields, number)
            self.assertEqual(fields.get('authority'), 'owner', number)
            self.assertEqual(fields.get('supersedes'), expected_supersedes, number)
            self.assertEqual(fields.get('proof'), expected_proof, number)
            self.assertIn('Torre por delegação do Daniel 22/11/2026', text, number)
            row = next((line for line in table_text.splitlines() if line.startswith(f'| {number} |')), '')
            self.assertTrue(row.endswith('| recorded |'), f'{number}: {row}')
        decisions = {item['id']: item for item in model.read_decisions(ROOT) if item['type'] == 'D'}
        self.assertEqual(decisions['D-358']['state'], 'accepted')
        self.assertEqual(decisions['D-362']['state'], 'accepted')
        self.assertEqual(decisions['D-342']['state'], 'superseded')


if __name__ == '__main__':
    unittest.main()
