"""The registry-driven local check (LR1): one refusal per seed check, the budget rules, skip-not-fail. Temp git repos, fake clock."""
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/lib'))

import local_checks  # noqa: E402

DECISIONS = '| Id | Date | Decision |\n|---|---|---|\n| D-025 | 2026-10-22 | Commit check |\n'
Z = '0' * 40


def git(root, *args):
    done = subprocess.run(['git', '-C', str(root), '-c', 'user.name=t', '-c', 'user.email=t@t', *args], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    return done.stdout.strip()


def commit(root, name, text='x\n', message=None):
    path = Path(root) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    git(root, 'add', '-A')
    git(root, 'commit', '-q', '-m', message or f'add {name}')
    return git(root, 'rev-parse', 'HEAD')


class Clock:
    def __init__(self, step):
        self.now, self.step = 0.0, step

    def __call__(self):
        self.now += self.step
        return self.now


def entry(id, handler, budget=1000, stage='local', enabled=True):
    return {'id': id, 'owner': 'test', 'budget_ms': budget, 'handler': handler, 'stage': stage, 'enabled': enabled}


class Repo(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        git(self.root, 'init', '-q', '-b', 'work')
        (self.root / 'docs/domain').mkdir(parents=True)
        (self.root / 'docs/domain/DECISIONS.md').write_text(DECISIONS)
        self.base = commit(self.root, 'README.md')

    def tearDown(self):
        self.tmp.cleanup()

    def ctx(self, **kwargs):
        return local_checks.Context(self.root, **kwargs)


class SeedChecks(Repo):
    def test_one_push_per_commit_refuses_two_commits(self):
        first = commit(self.root, 'a.txt')
        second = commit(self.root, 'b.txt')
        errors = local_checks.one_push_per_commit(self.ctx(refs=[('refs/heads/work', second, 'refs/heads/work', self.base)]))
        self.assertEqual(len(errors), 1)
        self.assertIn('scripts/replay-branch', errors[0])
        self.assertIn(first[:7], errors[0])

    def test_one_push_per_commit_accepts_one_commit_and_ignores_merges(self):
        one = commit(self.root, 'a.txt')
        self.assertEqual(local_checks.one_push_per_commit(self.ctx(refs=[('r', one, 'r', self.base)])), [])
        git(self.root, 'checkout', '-q', '-b', 'side', self.base)
        commit(self.root, 's.txt')
        git(self.root, 'checkout', '-q', 'work')
        git(self.root, 'merge', '-q', '--no-ff', '-m', 'Merge side', 'side')
        merged = git(self.root, 'rev-parse', 'HEAD')
        self.assertEqual(local_checks.one_push_per_commit(self.ctx(refs=[('r', merged, 'r', one)])), [])

    def test_a_new_branch_stacked_on_a_pushed_one_counts_only_its_own_commit(self):
        base_ref = 'refs/remotes/origin/' + local_checks.config.get('train.base_branch')
        git(self.root, 'update-ref', base_ref, self.base)
        commit(self.root, 'a.txt')
        stacked = commit(self.root, 'b.txt')
        zero = '0' * len(stacked)
        new_branch = [('r', stacked, 'r', zero)]
        self.assertEqual(len(local_checks.one_push_per_commit(self.ctx(refs=new_branch))), 1)
        git(self.root, 'update-ref', 'refs/remotes/origin/stack', stacked)
        own = commit(self.root, 'c.txt')
        errors = local_checks.one_push_per_commit(self.ctx(refs=[('r', own, 'r', zero)]))
        self.assertEqual(errors, [])

    def test_without_refs_or_a_base_the_push_checks_skip_and_judge_what_they_can(self):
        """The pre-push edges the push guard's fixture used to reach on every push (GATE-SPEED F2): a push with no refs
        and no upstream skips the commit count, a new branch with nothing to count against skips, and a change with no
        changed file scans nothing."""
        with self.assertRaises(local_checks.Skip):
            local_checks.one_push_per_commit(self.ctx())
        new_branch = commit(self.root, 'a.txt')
        with self.assertRaises(local_checks.Skip):
            local_checks.one_push_per_commit(self.ctx(refs=[('r', new_branch, 'r', '0' * len(new_branch))]))
        (self.root / 'uncommitted.txt').write_text('x\n')
        self.assertIn('uncommitted.txt', self.ctx().changed())  # no refs: the uncommitted files and the base, if any
        git(self.root, 'remote', 'add', 'origin', str(self.root))
        git(self.root, 'update-ref', 'refs/remotes/origin/' + local_checks.config.get('train.base_branch'), self.base)
        self.assertEqual(local_checks.one_push_per_commit(self.ctx()), [])

    def test_a_change_without_files_scans_nothing(self):
        empty = self.ctx(refs=[('r', self.base, 'r', self.base)])
        if local_checks._gitleaks(empty):
            self.assertEqual(local_checks.secret_scan_diff(empty), [])

    def test_no_history_rewrite_refuses_a_push_that_drops_the_remote_commit(self):
        pushed = commit(self.root, 'a.txt')
        git(self.root, 'reset', '-q', '--hard', self.base)
        rewritten = commit(self.root, 'a.txt', 'amended\n')
        errors = local_checks.no_history_rewrite(self.ctx(refs=[('refs/heads/work', rewritten, 'refs/heads/work', pushed)]))
        self.assertEqual(len(errors), 1)
        self.assertIn(f'refs/heads/work would move from {pushed[:7]} to {rewritten[:7]}', errors[0])
        self.assertIn('scripts/replay-branch', errors[0])

    def test_no_history_rewrite_accepts_fast_forwards_merges_new_branches_and_deletions(self):
        one = commit(self.root, 'a.txt')
        git(self.root, 'checkout', '-q', '-b', 'side', self.base)
        commit(self.root, 's.txt')
        git(self.root, 'checkout', '-q', 'work')
        git(self.root, 'merge', '-q', '--no-ff', '-m', 'Merge side', 'side')
        merged = git(self.root, 'rev-parse', 'HEAD')
        for refs in ([('r', one, 'r', self.base)], [('r', merged, 'r', one)], [('r', one, 'r', Z)], [('r', Z, 'r', one)]):
            self.assertEqual(local_checks.no_history_rewrite(self.ctx(refs=refs)), [])
        with self.assertRaises(local_checks.Skip):
            local_checks.no_history_rewrite(self.ctx(refs=[('r', one, 'r', 'f' * 40)]))

    def test_gate_change_needs_a_known_decision(self):
        commit(self.root, 'scripts/gate-dev', '#!/bin/sh\n')
        ctx = self.ctx(body='no decision cited', refs=[('r', git(self.root, 'rev-parse', 'HEAD'), 'r', self.base)])
        errors = local_checks.gate_change_cites_decision(ctx)
        self.assertTrue(errors and errors[0].startswith('gate:'), errors)
        ctx = self.ctx(body='Cites D-025.', refs=ctx.refs)
        self.assertEqual(local_checks.gate_change_cites_decision(ctx), [])
        with self.assertRaises(local_checks.Skip):
            local_checks.gate_change_cites_decision(self.ctx(refs=ctx.refs))

    def test_gate_check_needs_no_body_when_the_gate_is_untouched(self):
        sha = commit(self.root, 'src/a.py')
        self.assertEqual(local_checks.gate_change_cites_decision(self.ctx(refs=[('r', sha, 'r', self.base)])), [])

    def test_secret_scan_refuses_a_secret_without_printing_it(self):
        if not local_checks._gitleaks(self.ctx()):
            self.skipTest('gitleaks is not installed')
        secret = 'AKIA' + 'IOSFODNN7EXAMPLQ'
        sha = commit(self.root, 'conf.env', f'aws_access_key_id = {secret}\naws_secret_access_key = wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY\n')
        errors = local_checks.secret_scan_diff(self.ctx(refs=[('r', sha, 'r', self.base)]))
        self.assertTrue(errors, 'expected a finding')
        self.assertNotIn(secret, ' '.join(errors))

    def test_secret_scan_skips_without_gitleaks(self):
        original = local_checks._gitleaks
        local_checks._gitleaks = lambda ctx: None
        try:
            with self.assertRaises(local_checks.Skip):
                local_checks.secret_scan_diff(self.ctx())
        finally:
            local_checks._gitleaks = original

    def test_no_registered_literals_refuses_a_literal_in_a_changed_file(self):
        import config_check
        real = config_check.engine_files
        config_check.engine_files = lambda root: [('scripts/lib/budgets.py', '.py'), ('scripts/lib/other.py', '.py')]
        try:
            text = 'budgets_pr_changed_lines = 600\nvalue = 3\n'
            commit(self.root, 'scripts/lib/budgets.py', text)
            commit(self.root, 'scripts/lib/other.py', text)
            ctx = self.ctx()
            ctx._changed = ['scripts/lib/budgets.py']
            errors = local_checks.no_registered_literals(ctx)
        finally:
            config_check.engine_files = real
        self.assertEqual(len(errors), 1, errors)
        self.assertIn('budgets.pr_changed_lines', errors[0])

    def test_structure_fast_refuses_a_bad_plan_and_runs_on_a_clean_tree(self):
        errors = local_checks.structure_fast(self.ctx(body='no plan here'))
        self.assertTrue(any(line.startswith('plan:') for line in errors), errors)


TREE_MODULES = {'config_check': ('structure_config_check', 'config_check', True),
                'literal_census': ('structure_literal_census', 'literal_census', True),
                'vendor': ('structure_vendor', 'vendor_check', True),
                'unit_check': ('structure_unit_check', 'unit_check', False)}


class FakeRegime:
    def __init__(self, lifted):
        self.lifted_locks = set(lifted)

    def lifted(self, lock):
        return lock in self.lifted_locks


class RegimeLift(Repo):
    """D-260: the one-push refusal is the commit-plan lock; an active regime lifts it, the regime's absence keeps it."""

    def test_an_active_regime_lifts_one_push_per_commit(self):
        commit(self.root, 'a.txt')
        second = commit(self.root, 'b.txt')
        ctx = self.ctx(refs=[('refs/heads/work', second, 'refs/heads/work', self.base)])
        import commit_check
        with mock.patch.object(commit_check, 'regime', FakeRegime({'commit-plan'})), mock.patch('sys.stderr', io.StringIO()):
            self.assertEqual(local_checks._lift_of('one_push_per_commit', local_checks.one_push_per_commit(ctx)), [])

    def test_an_active_regime_lifts_the_literal_census_lock(self):
        import commit_check
        errors = ['number 9 is written 6 times']
        with mock.patch.object(commit_check, 'regime', FakeRegime({'literals'})), mock.patch('sys.stderr', io.StringIO()):
            self.assertEqual(local_checks._lift_of('literal_census', errors), [])
            self.assertEqual(local_checks._lift_of('no_registered_literals', errors), errors)

    def test_without_the_regime_one_push_per_commit_refuses(self):
        commit(self.root, 'a.txt')
        second = commit(self.root, 'b.txt')
        ctx = self.ctx(refs=[('refs/heads/work', second, 'refs/heads/work', self.base)])
        import commit_check
        with mock.patch.object(commit_check, 'regime', None):
            self.assertEqual(len(local_checks._lift_of('one_push_per_commit', local_checks.one_push_per_commit(ctx))), 1)


class OnlyFlag(Repo):
    """--only NAME runs the one check of that id (lane 1's request, D-236): the commit path can carry one check."""

    def run_main(self, only):
        out = io.StringIO()
        with mock.patch('sys.stdout', out):
            code = local_checks.main(self.root, only=only)
        return code, out.getvalue()

    def test_only_runs_the_named_check_and_no_other(self):
        code, text = self.run_main('no_registered_literals')
        self.assertIn('local-check no_registered_literals:', text)
        self.assertNotIn('local-check secret_scan_diff:', text)
        self.assertEqual(code, 0)

    def test_an_unknown_name_is_refused_with_the_registry_names(self):
        code, text = self.run_main('no_such_check')
        self.assertEqual(code, 1)
        self.assertIn('no check named no_such_check', text)
        self.assertIn('no_registered_literals', text)


class TreeModules(Repo):
    def patched(self, module, result):
        import importlib
        mod = importlib.import_module(module)
        real, calls = mod.check, []
        mod.check = lambda *args: calls.append(args) or result
        self.addCleanup(setattr, mod, 'check', real)
        return calls

    def test_the_five_tree_modules_are_registered_local_and_owned_by_structure(self):
        import config
        checks = {c['id']: c for c in config.get('local-checks.checks')}
        for id, (handler, _, _) in TREE_MODULES.items():
            self.assertEqual((checks[id]['handler'], checks[id]['stage'], checks[id]['owner'], checks[id]['enabled']),
                             (handler, 'local', 'structure', True))
            self.assertIn(handler, local_checks.HANDLERS)

    def test_a_base_relative_module_without_a_base_is_skipped(self):
        for handler, module, base in TREE_MODULES.values():
            if base:
                calls = self.patched(module, (['never'], []))
                outcome = local_checks.run(self.ctx(), entries=[entry(module, handler)], state=self.root / 'state.json')
                self.assertEqual(outcome['results'][0]['status'], 'skipped', module)
                self.assertIn('no base', outcome['results'][0]['reason'])
                self.assertEqual(calls, [])

    def test_module_errors_are_refusals_and_warnings_are_not(self):
        git(self.root, 'branch', 'base')
        git(self.root, 'branch', '--set-upstream-to', 'base')
        for handler, module, base in TREE_MODULES.values():
            calls = self.patched(module, (['err: one'], ['warn: two']))
            self.assertEqual(local_checks.HANDLERS[handler](self.ctx()), ['err: one'], module)
            self.assertEqual(calls, [(self.root, 'base') if base else (self.root,)])


    def test_a_git_variable_of_another_repository_skips_the_module(self):
        git(self.root, 'branch', 'base')
        git(self.root, 'branch', '--set-upstream-to', 'base')
        calls = self.patched('unit_check', ([], []))
        other = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, other)
        own = git(self.root, 'rev-parse', '--absolute-git-dir').strip()
        with mock.patch.dict(os.environ, {'GIT_INDEX_FILE': str(other / 'index')}):
            outcome = local_checks.run(self.ctx(), entries=[entry('unit_check', 'structure_unit_check')],
                                       state=self.root / 'state.json')
        self.assertEqual(outcome['results'][0]['status'], 'skipped')
        self.assertIn('GIT_INDEX_FILE names another repository', outcome['results'][0]['reason'])
        self.assertEqual(calls, [])
        with mock.patch.dict(os.environ, {'GIT_INDEX_FILE': own + '/index', 'GIT_DIR': own}):
            self.assertEqual(local_checks.HANDLERS['structure_unit_check'](self.ctx()), [])
        self.assertEqual(len(calls), 1)

def record(number, text='A rule.'):
    return f'---\nnumber: {number}\ntime: 2026-11-03\npremises: none\nproof: scripts/tests/x.test.sh\n---\n{text}\n'


class DecisionTableCheck(Repo):
    """D-217: a decision record pushed without its row in DECISIONS.md is refused, with the fix in the message."""

    def setUp(self):
        super().setUp()
        git(self.root, 'branch', 'base')
        git(self.root, 'branch', '--set-upstream-to', 'base')

    def table(self):
        return self.root / 'docs/domain/DECISIONS.md'

    def test_the_check_is_registered_local_and_its_handler_is_in_handlers(self):
        import config
        checks = {c['id']: c for c in config.get('local-checks.checks')}
        self.assertEqual((checks['decision_table']['handler'], checks['decision_table']['stage'], checks['decision_table']['enabled']),
                         ('decision_table', 'local', True))
        self.assertIs(local_checks.HANDLERS['decision_table'], local_checks.decision_table_in_step)

    def test_a_record_pushed_without_its_row_is_refused_with_the_fix(self):
        commit(self.root, 'docs/domain/decisions/D-300.md', record('D-300'))
        outcome = local_checks.run(self.ctx(), entries=[entry('decision_table', 'decision_table')], state=self.root / 'state.json')
        self.assertEqual(outcome['results'][0]['status'], 'failed', outcome['results'][0])
        self.assertEqual(len(outcome['errors']), 1)
        self.assertIn('D-300', outcome['errors'][0])
        self.assertIn('scripts/decision-table --write', outcome['errors'][0])

    def test_the_record_with_its_row_passes(self):
        import decision_table
        commit(self.root, 'docs/domain/decisions/D-300.md', record('D-300'))
        self.table().write_text(decision_table.with_missing(self.table().read_text(), decision_table.load(self.root)))
        commit(self.root, 'docs/domain/DECISIONS.md', self.table().read_text())
        self.assertEqual(local_checks.decision_table_in_step(self.ctx()), [])

    def test_a_row_the_base_had_and_the_push_lost_is_refused(self):
        self.table().write_text(DECISIONS.replace('| D-025 |', '| D-026 |'))
        commit(self.root, 'docs/domain/DECISIONS.md', self.table().read_text())
        errors = local_checks.decision_table_in_step(self.ctx())
        self.assertEqual(len(errors), 1)
        self.assertIn('D-25', errors[0])

    def test_a_push_that_touches_no_decision_is_not_judged_even_when_the_table_drifts(self):
        git(self.root, 'checkout', '-q', 'base')
        commit(self.root, 'docs/domain/decisions/D-300.md', record('D-300'))
        git(self.root, 'checkout', '-q', 'work')
        git(self.root, 'merge', '-q', '--no-edit', 'base')
        git(self.root, 'branch', '-f', 'base', 'work')
        commit(self.root, 'a.txt')
        self.assertEqual(local_checks.decision_table_in_step(self.ctx()), [])

    def test_a_record_that_does_not_parse_is_refused(self):
        commit(self.root, 'docs/domain/decisions/D-300.md', 'no front matter\n')
        errors = local_checks.decision_table_in_step(self.ctx())
        self.assertEqual(len(errors), 1)
        self.assertIn('D-300.md', errors[0])


class Runner(Repo):
    def setUp(self):
        super().setUp()
        self.state = self.root / 'state.json'
        local_checks.HANDLERS['t_ok'] = lambda ctx: []
        local_checks.HANDLERS['t_find'] = lambda ctx: ['found: thing']
        local_checks.HANDLERS['t_skip'] = lambda ctx: (_ for _ in ()).throw(local_checks.Skip('no tool'))
        local_checks.HANDLERS['t_boom'] = lambda ctx: 1 / 0

    def tearDown(self):
        for name in ('t_ok', 't_find', 't_skip', 't_boom'):
            local_checks.HANDLERS.pop(name, None)
        super().tearDown()

    def run_checks(self, entries, step=0.001, total=30000):
        return local_checks.run(self.ctx(clock=Clock(step)), entries=entries, total_limit=total, state=self.state)

    def test_over_budget_moves_to_the_gate_and_is_skipped_next_time(self):
        entries = [entry('slow', 't_ok', budget=100), entry('fast', 't_ok', budget=100)]
        first = self.run_checks(entries, step=0.5)  # 500 ms each
        self.assertTrue(all(r.get('over_budget') for r in first['results']))
        lines = []
        local_checks.report(first, lines.append)
        self.assertTrue(any('MOVES TO THE GATE' in line for line in lines), lines)
        self.assertEqual(set(json.loads(self.state.read_text())['moved']), {'slow', 'fast'})
        second = self.run_checks(entries, step=0.0001)
        self.assertEqual([r['status'] for r in second['results']], ['gate', 'gate'])
        self.assertEqual(entries[0]['stage'], 'local')  # the registry entry is never edited

    def test_total_budget_is_reported(self):
        outcome = self.run_checks([entry('a', 't_ok', budget=10 ** 6), entry('b', 't_ok', budget=10 ** 6)], step=1.0, total=1500)
        self.assertTrue(outcome['total_over'])
        lines = []
        local_checks.report(outcome, lines.append)
        self.assertTrue(any('total budget' in line for line in lines), lines)
        self.assertFalse(self.state.exists())

    def test_finding_fails_and_skip_or_error_does_not(self):
        outcome = self.run_checks([entry('f', 't_find')])
        self.assertEqual(outcome['errors'], ['found: thing'])
        outcome = self.run_checks([entry('s', 't_skip'), entry('b', 't_boom'), entry('off', 't_find', enabled=False),
                                   entry('g', 't_find', stage='gate')])
        self.assertEqual(outcome['errors'], [])
        self.assertEqual([r['status'] for r in outcome['results']], ['skipped', 'skipped', 'disabled', 'gate'])
        self.assertIn('ZeroDivisionError', outcome['results'][1]['reason'])

    def test_module_function_handler_and_unknown_handler(self):
        outcome = self.run_checks([entry('m', 'local_checks:parse_refs'), entry('u', 'nope')])
        self.assertEqual(outcome['results'][1]['status'], 'skipped')
        self.assertIn('no handler', outcome['results'][1]['reason'])

    def test_refs_from_pre_push_stdin_lines(self):
        one, two = commit(self.root, 'a.txt'), commit(self.root, 'b.txt')
        stdin = io.StringIO(f'refs/heads/work {two} refs/heads/work {self.base}\n')
        entries = [entry('one', 'one_push_per_commit')]
        outcome = local_checks.run(self.ctx(refs=local_checks.parse_refs(stdin.read())), entries=entries, total_limit=30000, state=self.state)
        self.assertEqual(len(outcome['errors']), 1)
        self.assertIn(one[:7], outcome['results'][0]['errors'][0])

    def test_registry_seed_is_valid(self):
        import config
        checks = config.get('local-checks.checks')
        self.assertEqual({c['handler'] for c in checks} - set(local_checks.HANDLERS), set())
        self.assertEqual(len({c['id'] for c in checks}), len(checks))
        self.assertGreater(config.get('local-checks.total_budget_ms'), 0)


if __name__ == '__main__':
    unittest.main()
