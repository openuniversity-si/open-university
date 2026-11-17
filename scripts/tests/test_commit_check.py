"""scripts/commit-check (D-025): one fixture per refusal and one clean PR. No network."""
import contextlib
import copy
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/lib'))
import commit_check  # noqa: E402
import forge_events  # noqa: E402
sys.path.insert(0, str(Path(__file__).resolve().parent))  # the tests' own helpers
import forge_doubles  # noqa: E402
import hermetic  # noqa: E402
PLAN = '## Commit plan\n- [x] 1. One.\n- [x] 2. Two.\n- [ ] 3. Three.\n'
DECISIONS = '| Id | Date | Decision |\n|---|---|---|\n| D-025 | 2026-10-22 | Commit check |\n'


def commit(sha, subject, files, parents=1):
    return {'sha': sha * 40, 'message': subject + '\n\nBody.', 'parents': ['p' * 40] * parents, 'files': files}


CLEAN = {
    'body': PLAN + 'Implements D-025.\n',
    'commits': [commit('a', 'Add the rule', ['src/a.py', 'tests/a.py']), commit('b', 'Use the rule', ['src/b.py']),
                commit('c', 'Merge origin/main', ['src/a.py'], parents=2), commit('d', 'Fix tests of the merge', ['src/a.py'])],
    'pushes': [{'before': '0' * 40, 'after': 'a' * 40}, {'before': 'a' * 40, 'after': 'b' * 40},
               {'before': 'b' * 40, 'after': 'c' * 40}, {'before': 'c' * 40, 'after': 'd' * 40}],
}


class CommitCheck(unittest.TestCase):
    def run_check(self, pr):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'docs/domain').mkdir(parents=True)
            (root / 'docs/domain/DECISIONS.md').write_text(DECISIONS)
            (root / 'pr.json').write_text(json.dumps(pr))
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = commit_check.main(['--fixture', str(root / 'pr.json'), '--root', str(root)])
        return code, out.getvalue()

    @contextlib.contextmanager
    def switch(self, value):
        """The P-G3 switch through the store (GA-PG8); the registry default is off since GX-27."""
        with commit_check.config.use_adapter(forge_events.MemoryAdapter()):
            if commit_check.config.get('merge.tier1_requires_base_merge') != value:  # set_value refuses a no-op
                commit_check.config.set_value('merge.tier1_requires_base_merge', value, actor='gx27-fixture',
                                              reason='switch in a fixture', now=hermetic.clock().now())
            yield

    def refused(self, pr, rule):
        code, out = self.run_check(pr)
        self.assertEqual(code, 1, out)
        self.assertEqual([line.split(':')[0] for line in out.splitlines() if line.startswith('FAIL')], ['FAIL ' + rule], out)

    def test_clean_pr_passes(self):
        code, out = self.run_check(CLEAN)
        self.assertEqual(code, 0, out)
        self.assertIn('4 commit(s); 0 refusal(s)', out)

    def test_refuses_a_body_without_a_commit_plan(self):
        self.refused({**CLEAN, 'body': 'No plan.'}, 'plan')
        self.refused({**CLEAN, 'body': '## Commit plan\n'}, 'plan')

    def test_a_plan_of_more_than_eight_items_passes(self):
        """D-307: no maximum while budgets.pr_commits_max is 0, its default; a PR is split by its content."""
        code, out = self.run_check({**CLEAN, 'body': PLAN + ''.join(f'- [ ] {n}. More.\n' for n in range(4, 10))})
        self.assertEqual(code, 0, out)
        self.assertIn('0 refusal(s)', out)

    def test_refuses_fixup_commits(self):
        for subject in ('fixup! Add the rule', 'squash! Add the rule'):
            self.refused({**CLEAN, 'commits': CLEAN['commits'][:1] + [commit('b', subject, ['src/b.py'])], 'pushes': []}, 'fixup')
        follow = [commit('a', 'Add the rule', ['src/a.py', 'tests/a.py']), commit('b', 'Fix ids in the rule test', ['tests/a.py'])]
        self.refused({**CLEAN, 'commits': follow, 'pushes': []}, 'fixup')

    def test_refuses_several_commits_in_one_push(self):
        self.refused({**CLEAN, 'pushes': [{'before': '0' * 40, 'after': 'b' * 40, 'timestamp': '2026-10-22T17:45:28Z'}]}, 'push')

    def test_a_merge_of_the_moved_head_carries_one_commit_and_no_more(self):
        """VAZÃO F30: deliver pushed m (a merge of the base into a), the lane had made b on a; its merge n of m carries b
        in one push. Two commits made under the moved head are still a batch."""
        full = {name: commit(name, '', [])['sha'] for name in 'abcmnpq0'}

        def made(name, parents):
            return {**commit(name, f'Commit {name}', ['src/a.py']), 'parents': [full[p] for p in parents]}
        commits = [made('a', 'p'), made('m', 'aq'), made('b', 'a'), made('n', 'bm')]
        pushes = [{'before': full[before], 'after': full[after]} for before, after in ('0a', 'am', 'mn')]
        for listed in (commits, [commits[0], commits[2], commits[1], commits[3]]):  # b made before m: date order
            code, out = self.run_check({**CLEAN, 'commits': listed, 'pushes': pushes})
            self.assertEqual(code, 0, out)
        batch = [made('a', 'p'), made('m', 'aq'), made('b', 'a'), made('c', 'b'), made('n', 'cm')]
        self.refused({**CLEAN, 'commits': batch, 'pushes': pushes}, 'push')
        other = [made('a', 'p'), made('m', 'aq'), made('b', 'a'), made('n', 'mb')]  # b merged into m: not a carried commit
        self.refused({**CLEAN, 'commits': other, 'pushes': pushes}, 'push')

    def test_the_push_refusal_names_the_replay_remedy(self):
        code, out = self.run_check({**CLEAN, 'number': 505, 'pushes': [{'before': '0' * 40, 'after': 'b' * 40}]})
        self.assertEqual(code, 1, out)
        self.assertIn('push each commit as it is done (D-022); fix: scripts/replay-branch 505', out)

    def test_refuses_force_push_activity_on_the_head_ref(self):
        forced = [{'before': 'e' * 40, 'after': 'd' * 40, 'timestamp': '2026-10-27T03:12:09Z'}]
        self.refused({**CLEAN, 'number': 585, 'branch': 'mod/x', 'force_pushes': forced}, 'force-push')
        code, out = self.run_check({**CLEAN, 'number': 585, 'branch': 'mod/x', 'force_pushes': forced})
        self.assertIn('mod/x was force-pushed at 2026-10-27T03:12:09Z (eeeeeee -> ddddddd)', out)
        self.assertIn('fix: scripts/replay-branch 585 replays the PR on a new branch', out)

    def test_no_force_push_activity_passes(self):
        code, out = self.run_check({**CLEAN, 'number': 585, 'branch': 'mod/x', 'force_pushes': []})
        self.assertEqual(code, 0, out)

    def test_refuses_a_head_behind_its_base_without_a_merge_of_the_base(self):
        base = {'ref': 'mod/roadmap-integration', 'behind_by': 3, 'merge_base': 'f' * 40}
        rebased = [commit('a', 'Add the rule', ['src/a.py']), commit('b', 'Use the rule', ['src/b.py'])]
        pr = {**CLEAN, 'branch': 'mod/x', 'base': base, 'commits': rebased, 'pushes': CLEAN['pushes'][:2]}
        with self.switch(True):
            self.refused(pr, 'rebase')
            code, out = self.run_check(pr)
            self.assertIn('mod/x is 3 commit(s) behind mod/roadmap-integration and no commit of the PR merges it '
                          '(3 behind, limit 0; merge base fffffff)', out)
            self.assertIn('`git merge origin/mod/roadmap-integration` (a merge commit), never a rebase', out)
            other = {**commit('c', 'Merge another branch', ['src/a.py'], parents=2), 'parents': ['b' * 40, '9' * 40]}
            self.refused({**pr, 'commits': rebased + [other], 'pushes': CLEAN['pushes'][:3]}, 'rebase')

    def test_the_p_g3_switch_off_allows_a_head_behind_up_to_the_registry_limit(self):
        """GX-22: merge.tier1_requires_base_merge off removes the rebase refusal up to merge.max_behind_base; beyond it the
        refusal names the registry limit. FP1 is untouched: a force push is refused either way."""
        limit = commit_check.config.get('merge.max_behind_base')
        rebased = [commit('a', 'Add the rule', ['src/a.py']), commit('b', 'Use the rule', ['src/b.py'])]
        within = {**CLEAN, 'branch': 'mod/x', 'commits': rebased, 'pushes': CLEAN['pushes'][:len(rebased)],
                  'base': {'ref': 'mod/roadmap-integration', 'behind_by': limit, 'merge_base': CLEAN['commits'][-1]['sha'][::-1]}}
        beyond = {**within, 'base': {**within['base'], 'behind_by': limit + 1}}
        forced = {**within, 'force_pushes': [{'before': rebased[0]['sha'], 'after': rebased[-1]['sha']}]}
        self.assertFalse(commit_check.config.get('merge.tier1_requires_base_merge'), 'GX-27: the registry default is off')
        code, out = self.run_check(within)
        self.assertEqual(code, 0, out)
        with self.switch(True):  # the old rule back: one key
            self.refused(within, 'rebase')
        with self.switch(False):
            code, out = self.run_check(within)
            self.assertEqual(code, 0, out)
            code, out = self.run_check(beyond)
            self.assertIn(f'({limit + 1} behind, limit {limit}; merge base', out)
            self.refused(forced, 'force-push')

    def test_a_head_that_merged_its_base_is_up_to_date_or_is_merged_passes(self):
        merge = {**commit('c', 'Merge origin/mod/roadmap-integration', ['src/a.py'], parents=2), 'parents': ['b' * 40, 'f' * 40]}
        commits = CLEAN['commits'][:2] + [merge, CLEAN['commits'][3]]
        behind = {'ref': 'mod/roadmap-integration', 'behind_by': 2, 'merge_base': 'f' * 40}
        for pr in ({**CLEAN, 'base': behind, 'commits': commits},
                   {**CLEAN, 'base': {**behind, 'behind_by': 0, 'merge_base': 'p' * 40}},
                   {**CLEAN, 'base': {'ref': 'mod/roadmap-integration'}},
                   {**CLEAN, 'base': {**behind, 'behind_by': 1, 'merge_base': 'd' * 40}}):
            code, out = self.run_check(pr)
            self.assertEqual(code, 0, out)

    def test_refuses_a_comment_that_waits_on_the_owner_without_a_later_decision(self):
        for comments in (['T1 stalled.\n\nBLOCKED: the push check refuses this PR.'],
                         ['Gate red.', 'This is a decision for the owner: replay or wait?'],
                         ['Decision: replay.', '- **Waiting for your decision** on the base merge.']):
            self.refused({**CLEAN, 'number': 505, 'comments': comments}, 'decision-wait')
        code, out = self.run_check({**CLEAN, 'number': 505, 'comments': comments})
        self.assertIn('DECIDE, THEN REPORT (Daniel 2026-10-26 21:29): pick the safest reversible option', out)

    def test_a_later_decision_line_clears_the_owner_wait(self):
        for comments in (['BLOCKED: refused push.', 'Decision: replayed with scripts/replay-branch 505.'],
                         ['Waiting for your decision on X.\nDecision: took the reversible option X.'],
                         ['The check matches `BLOCKED:` and `decision for the owner` only outside code:\n'
                          '> BLOCKED: quoted\n```\nBLOCKED: fenced\n```\nNot BLOCKED: mid-line marker.'],
                         ['<!-- forge-events v1 -->\nforge_events: BLOCKED: inside the event log']):
            code, out = self.run_check({**CLEAN, 'comments': comments})
            self.assertEqual(code, 0, f'{comments}: {out}')

    def test_only_comments_up_to_the_gated_push_are_judged(self):
        def at(body, clock):
            return {'body': body, 'created_at': f'2026-10-27T{clock}Z'}
        pushes = [{**push, 'timestamp': f'2026-10-27T15:{index:02d}:30Z'} for index, push in enumerate(CLEAN['pushes'])]
        second, last = CLEAN['commits'][1]['sha'], CLEAN['commits'][-1]['sha']
        gated = {**CLEAN, 'pushes': pushes, 'gated': {'sha': second}}  # pushed 15:01:30; the gate runs on it
        late_wait = [at('Gate running.', '15:01:00'), at('BLOCKED: waiting for the owner.', '15:02:00')]
        self.assertEqual(self.run_check({**gated, 'comments': late_wait})[0], 0, 'a wait after the gated push')
        self.refused({**gated, 'comments': late_wait, 'gated': {'sha': last}}, 'decision-wait')
        late_decision = [at('BLOCKED: waiting for the owner.', '15:00:00'), at('Decision: replay.', '15:05:00')]
        self.refused({**gated, 'comments': late_decision}, 'decision-wait')
        self.refused({**gated, 'comments': late_decision, 'gated': {'pushed_at': '2026-10-27T15:04:59Z'}}, 'decision-wait')
        self.assertEqual(self.run_check({**gated, 'comments': late_decision,
                                         'gated': {'pushed_at': '2026-10-27T15:05:00Z'}})[0], 0)  # at the push counts
        unknown = {**gated, 'gated': {'sha': 'e' * len(second)}}  # no push of the gated sha is known: all are judged
        self.assertEqual(self.run_check({**unknown, 'comments': late_decision})[0], 0)
        self.refused({**unknown, 'comments': late_wait}, 'decision-wait')

    def test_refuses_a_gate_change_without_an_approved_decision(self):
        gate = {**CLEAN, 'files': ['scripts/lib/gate-build.py', 'src/a.py']}
        self.refused({**gate, 'body': PLAN}, 'gate')
        self.refused({**gate, 'body': PLAN + 'Implements D-999.\n'}, 'gate')
        self.assertEqual(self.run_check(gate)[0], 0)

    def test_local_mode_is_a_source_of_its_own(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err), self.assertRaises(SystemExit) as raised:
            commit_check.main(['--local', '--pr', '1'])
        self.assertEqual(raised.exception.code, 2)  # argparse: --local and --pr are mutually exclusive
        self.assertIn('not allowed with argument', err.getvalue())
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            commit_check.main([])


STEPS = list('abcdefghijkl')  # a twelve-commit PR
CALLS = ('pull', 'change_commits', 'compare', 'pushes', 'force_pushes', 'comments')  # the six forge operations


class GatedFetch(unittest.TestCase):
    """GX-14: fetch judges the gated sha, reads file names from the local checkout and costs the six CALLS."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)
        cls.git('init', '-q', '-b', 'base')
        cls.git('config', 'user.email', 't@example.com')
        cls.git('config', 'user.name', 'T')
        cls.base = cls.commit('Base', 'README')
        cls.shas = [cls.commit(f'Step {step}', f'src/step{step}.py') for step in STEPS]
        cls.late = cls.commit(f'Fix tests of step {STEPS[-1]}', f'src/step{STEPS[-1]}.py')  # pushed during the gate

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    @classmethod
    def git(cls, *args):
        return subprocess.run(['git', '-C', str(cls.root), *args], check=True, capture_output=True, text=True).stdout.strip()

    @classmethod
    def commit(cls, subject, name):
        path = cls.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(path.read_text() + subject if path.exists() else subject)
        cls.git('add', name)
        cls.git('commit', '-q', '-m', subject)
        return cls.git('rev-parse', 'HEAD')

    def fake(self, operation, *args):
        """The forge's answer to one port operation on PR 1, in the port's shapes (D-293: the operations, never a
        vendor's REST paths)."""
        self.calls.append((operation, args))
        everything = self.shas + [self.late]
        if operation == 'pull':
            return {'number': 1, 'body': PLAN + 'Implements D-025.\n', 'head_ref': 'mod/x', 'head_sha': self.late,
                    'base_ref': 'base', 'created_at': None, 'draft': False}
        if operation == 'change_commits':
            return [{'sha': sha, 'message': self.git('log', '-1', '--format=%B', sha),
                     'parents': [self.git('rev-parse', sha + '^')]} for sha in everything]
        if operation == 'compare':
            return {'behind_by': 0, 'merge_base': self.base}
        if operation == 'pushes':
            return [{'before': before, 'after': after, 'timestamp': f'2026-10-27T15:{index:02d}:00Z'}
                    for index, (before, after) in enumerate(zip([self.base] + everything, everything))]
        if operation == 'force_pushes':
            return []
        if operation == 'comments':  # after the gated push (15:11), before the late one (15:12)
            return [{'body': 'BLOCKED: waiting for the owner.', 'created_at': '2026-10-27T15:11:30Z',
                     'author_association': None}]
        raise AssertionError(f'unexpected forge operation {operation}')

    def operations(self):
        return [operation for operation, _ in self.calls]

    def fetch(self, sha, root=None, head=None, transport=None):
        self.calls = []
        answer = transport or self.fake
        names = ('pull', 'change_commits', 'compare', 'pushes', 'force_pushes', 'comments', 'commit_files',
                 'change_files')
        adapter = forge_doubles.origin(**{name: (lambda name: lambda repo, *args: answer(name, *args))(name)
                                          for name in names})
        with mock.patch.object(forge_events, 'adapter_from_config', return_value=adapter):
            return commit_check.fetch(1, sha, root or self.root, head=head)

    def test_a_twelve_commit_pr_costs_six_calls_and_no_call_per_commit(self):
        pr = self.fetch(self.shas[-1])
        self.assertLessEqual(len(self.calls), len(CALLS), self.calls)
        self.assertEqual(set(self.operations()), set(CALLS))
        self.assertFalse({'commit_files', 'change_files'} & set(self.operations()), self.calls)
        self.assertEqual([commit['sha'] for commit in pr['commits']], self.shas)
        self.assertEqual(pr['commits'][0]['files'], [f'src/step{STEPS[0]}.py'])
        self.assertEqual(pr['files'], [f'src/step{step}.py' for step in STEPS])
        self.assertEqual(next(args for operation, args in self.calls if operation == 'compare'), ('base', self.shas[-1]))

    def test_origins_newest_first_page_still_gives_every_commit_up_to_the_gated_one_oldest_first(self):
        # PLAN-COMMIT-ORDER: Origin lists a PR's commits newest first; the cut at the gated sha's index kept that commit
        # alone (#690: the live service's merge of the base as the head, its own commit out of the plan's count)
        def newest_first(operation, *args):
            answer = self.fake(operation, *args)
            return list(reversed(answer)) if operation == 'change_commits' else answer
        pr = self.fetch(self.shas[-1], transport=newest_first)
        self.assertEqual([commit['sha'] for commit in pr['commits']], self.shas)
        self.assertEqual(pr['commits'][0]['files'], [f'src/step{STEPS[0]}.py'])

    def test_a_merge_head_reaches_its_own_commits_and_not_the_bases(self):
        page = [{'sha': 'm', 'message': 'Merge base into units/x', 'parents': ['b', 'x']},  # Origin: newest first
                {'sha': 'b', 'message': 'unit work\n\nPlan: 1', 'parents': ['o']},
                {'sha': 'z', 'message': 'pushed after the gated head', 'parents': ['m']}]
        self.assertEqual([each['sha'] for each in commit_check.gated_commits(page, 'm')], ['b', 'm'])
        self.assertEqual([each['sha'] for each in commit_check.gated_commits(list(reversed(page)), 'm')], ['b', 'm'])

    def test_fetch_preserves_metadata_and_fixture_shape(self):
        created = '2026-10-27T14:00:00Z'

        def rest(operation, *args):
            result = self.fake(operation, *args)
            if operation == 'pull':
                result.update(created_at=created, draft=True)
            return result

        pr = self.fetch(self.shas[-1], transport=rest)
        self.assertEqual(pr['created_at'], created)
        self.assertTrue(pr['draft'])
        self.assertEqual(set(pr), {'number', 'body', 'branch', 'commits', 'created_at', 'draft',
                                  'files', 'comments', 'gated', 'pushes', 'force_pushes', 'base'})

    def test_fetch_refuses_missing_force_history_before_reading(self):
        import forge_origin
        import operation_demands
        adapter = object.__new__(forge_origin.OriginAdapter)
        document = copy.deepcopy(operation_demands.load())
        document['proofs']['origin'].pop('force_pushes')
        with mock.patch.object(forge_events, 'adapter_from_config', return_value=adapter), \
                mock.patch.object(operation_demands, 'load', return_value=document):
            with self.assertRaisesRegex(forge_events.ForgeEventsError, 'operation force_pushes, adapter origin'):
                commit_check.fetch(1, root=self.root)

    def test_fetch_refuses_missing_force_method_before_reading(self):
        import forge_origin

        class NoForceHistory(forge_origin.OriginAdapter):
            def __getattribute__(self, name):
                if name == 'force_pushes':
                    raise AttributeError(name)
                return super().__getattribute__(name)

            def __getattr__(self, name):
                raise AssertionError(f'{name} read before the refusal')

        adapter = object.__new__(NoForceHistory)
        with mock.patch.object(forge_events, 'adapter_from_config', return_value=adapter):
            with self.assertRaisesRegex(forge_events.ForgeEventsError, 'force_pushes'):
                commit_check.fetch(1, root=self.root)

    def test_a_push_during_the_gate_does_not_change_its_verdict(self):
        known = {'D-025'}
        self.assertEqual(commit_check.check(self.fetch(self.shas[-1]), known), [])
        live = commit_check.check(self.fetch(None), known)  # the live head: a fix-up commit and a later owner wait
        self.assertEqual(sorted(line.split(':')[0] for line in live), ['decision-wait', 'fixup'], live)

    def test_a_checkout_head_is_the_gated_sha_only_when_it_is_a_pr_commit(self):
        for head, gated in ((self.shas[-1], self.shas[-1]), (self.base, self.late), (None, self.late)):
            self.assertEqual(self.fetch(None, head=head)['gated']['sha'], gated, head)

    def test_a_gated_sha_off_the_page_is_read_from_the_checkout(self):
        self.git('checkout', '-q', '-b', 'side', self.base)
        side = self.commit('Side step', 'src/side.py')
        pr = self.fetch(side)
        self.assertEqual(pr['commits'], [{'sha': side, 'message': 'Side step', 'parents': [self.base],
                                          'files': ['src/side.py']}])

    def test_without_a_checkout_files_come_from_the_forge(self):
        files = {sha: [f'src/step{step}.py'] for step, sha in zip(STEPS, self.shas)}

        def rest(operation, *args):
            if operation == 'commit_files':
                self.calls.append((operation, args))
                return [{'filename': name} for name in files[args[0]]]
            if operation == 'change_files':
                self.calls.append((operation, args))
                return [{'filename': name} for names in files.values() for name in names]
            return self.fake(operation, *args)
        pr = self.fetch(self.shas[-1], root=Path('/nonexistent-checkout'), transport=rest)
        self.assertEqual(pr['commits'][0]['files'], files[self.shas[0]])
        self.assertEqual(len(pr['files']), len(STEPS))
        self.assertEqual(len(self.calls), len(CALLS) + len(STEPS) + 1)  # one call per commit, one for the change
        self.assertEqual(self.operations().count('commit_files'), len(STEPS))

class PlanCompletenessAtGate(unittest.TestCase):
    """GX-21: the `pr metadata` stage refuses an unticked plan item and an undecidable lane on the head itself; since
    D-322 through commit-check (delivery), not the structure check."""

    BODY = '## Plan\n- [ ] 1. first\n- [ ] 2. second\n- [ ] 3. third\n'

    def test_the_615_shape_item_three_unticked_is_red_naming_it(self):
        commits = [{'message': 'a\n\nPlan: 1', 'files': ['a.py']}, {'message': 'b\n\nPlan: 2', 'files': ['b.py']}]
        errors = commit_check.plan_completeness_errors(self.BODY, commits)
        self.assertEqual(len(errors), 1)
        self.assertIn('item(s) 3 not ticked', errors[0])
        self.assertIn('edit the PR body', errors[0])
        self.assertIn('REAL commit', errors[0])
        self.assertIn('never an empty one', errors[0])

    def test_an_empty_commit_with_the_trailer_does_not_clear_it(self):
        commits = [{'message': 'a\n\nPlan: 1, 2', 'files': ['a.py']}, {'message': 'x\n\nPlan: 3', 'files': []}]
        self.assertIn('item(s) 3 not ticked', commit_check.plan_completeness_errors(self.BODY, commits)[0])

    def test_a_real_commit_for_every_item_is_green(self):
        commits = [{'message': 'a\n\nPlan: 1, 2, 3', 'files': ['a.py']}]
        self.assertEqual(commit_check.plan_completeness_errors(self.BODY, commits), [])

    def test_a_body_without_items_is_left_to_the_plan_count_check(self):
        self.assertEqual(commit_check.plan_completeness_errors('no plan', []), [])

    def test_d083_a_draft_head_is_judged_on_what_its_commits_delivered(self):
        """A serial PR is green on every commit while its plan is still a plan; the rest is a warning naming them."""
        commits = [{'message': 'a\n\nPlan: 1', 'files': ['a.py']}]
        errors, warnings = commit_check.plan_verdict(self.BODY, commits, draft=True)
        self.assertEqual(errors, [])
        self.assertEqual(len(warnings), 1)
        self.assertIn('item(s) 2, 3 not ticked', warnings[0])
        self.assertIn('D-083', warnings[0])

    def test_d083_a_ready_pr_is_refused_as_gx21_says(self):
        commits = [{'message': 'a\n\nPlan: 1', 'files': ['a.py']}]
        errors, warnings = commit_check.plan_verdict(self.BODY, commits, draft=False)
        self.assertEqual(errors, commit_check.plan_completeness_errors(self.BODY, commits))
        self.assertEqual(warnings, [])
        self.assertEqual(commit_check.plan_verdict(self.BODY, [{'message': 'a\n\nPlan: 1, 2, 3', 'files': ['a.py']}],
                                                draft=True), ([], []))

    LANE_MANIFESTS = {'engine': {'id': 'engine', 'owner': 'lane-a', 'paths': ['scripts/engine/**', 'scripts/census/**'],
                                 'shared': ['scripts/census/**']},
                      'admin': {'id': 'admin', 'owner': 'lane-b', 'paths': ['apps/admin/**', 'apps/tsconfig.json'],
                                'shared': ['apps/tsconfig.json']}}

    def lane_fixture(self, tmp):
        for unit, manifest in self.LANE_MANIFESTS.items():
            path = Path(tmp, 'units', unit, 'unit.json')
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps(manifest))
        subprocess.run(['git', '-C', tmp, 'init', '-q'], check=True)
        subprocess.run(['git', '-C', tmp, 'add', '-A'], check=True)
        subprocess.run(['git', '-C', tmp, '-c', 'user.email=t@example.com', '-c', 'user.name=T', 'commit', '-q', '-m', 'base'],
                       check=True)
        import train_git
        import train_ownership
        return train_ownership.UnitOwnership(train_git.GitWorkspace(Path(tmp)))

    def lane_errors(self, changed):
        with tempfile.TemporaryDirectory() as tmp:
            self.lane_fixture(tmp)
            return commit_check.lane_errors(Path(tmp), 'HEAD', changed)

    def test_a_change_across_lanes_is_refused_with_the_units_listed(self):
        errors = self.lane_errors(['scripts/engine/a.py', 'apps/admin/r.ts'])
        self.assertEqual(len(errors), 1)
        self.assertIn('lane undecidable', errors[0])
        self.assertIn('admin (lane-b), engine (lane-a)', errors[0])

    def test_one_lane_or_no_unit_is_decidable(self):
        self.assertEqual(self.lane_errors(['scripts/engine/a.py', 'scripts/engine/b.py']), [])
        self.assertEqual(self.lane_errors(['docs/free.md']), [])

    def test_lane_own_a_shared_path_alone_leaves_the_lane_decidable(self):
        self.assertEqual(self.lane_errors(['apps/admin/r.ts', 'scripts/census/admin.json']), [])
        self.assertEqual(self.lane_errors(['scripts/engine/a.py', 'apps/tsconfig.json']), [])

    def test_lane_own_a_shared_path_with_a_real_second_lane_is_still_refused(self):
        errors = self.lane_errors(['scripts/engine/a.py', 'apps/admin/r.ts', 'scripts/census/admin.json'])
        self.assertEqual(len(errors), 1)
        self.assertIn('admin (lane-b), engine (lane-a)', errors[0])

    def test_lane_own_a_change_of_only_shared_paths_has_no_lane(self):
        changed = ['scripts/census/admin.json', 'apps/tsconfig.json']
        self.assertEqual(self.lane_errors(changed), [])
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(self.lane_fixture(tmp).lane_of('HEAD', changed))

    def test_lane_own_a_shared_path_names_its_owner_and_never_refuses(self):
        """Sharing removes the ambiguity and the wait, never the owner (SHARED-NEEDS-NO-OWNER): owner_of() and units()
        still name lane-a's unit for its shared path, and refusals() never asks lane-a to approve it."""
        changed = ['apps/admin/r.ts', 'scripts/census/admin.json']
        with tempfile.TemporaryDirectory() as tmp:
            ownership = self.lane_fixture(tmp)
            self.assertEqual(ownership.lane_of('HEAD', changed), 'lane-b')
            self.assertEqual(ownership.owner_of('HEAD', 'scripts/census/admin.json'), ('engine', 'lane-a'))
            self.assertEqual(sorted(ownership.units('HEAD', changed)), ['admin', 'engine'])
            self.assertEqual(ownership.refusals('HEAD', changed, 'lane-b', lambda: self.fail('nobody is asked')), [])
            self.assertEqual(ownership.refusals('HEAD', ['scripts/engine/a.py', 'scripts/census/a.json'], 'lane-a', list), [])
            self.assertEqual(ownership.refusals('HEAD', ['scripts/engine/a.py', 'scripts/census/a.json'], 'lane-b', list),
                             [{'unit': 'engine', 'owner': 'lane-a', 'files': ['scripts/engine/a.py']}])

    def test_lane_own_lane_of_and_lane_errors_agree(self):
        """A change lane_of names a lane for is never refused, and a refused change has no lane (train_ownership)."""
        cases = {('scripts/engine/a.py',): 'lane-a', ('docs/free.md',): None,
                 ('apps/admin/r.ts', 'scripts/census/admin.json'): 'lane-b', ('scripts/census/admin.json',): None,
                 ('scripts/engine/a.py', 'apps/tsconfig.json'): 'lane-a',
                 ('scripts/engine/a.py', 'apps/admin/r.ts'): None,
                 ('scripts/engine/a.py', 'apps/admin/r.ts', 'apps/tsconfig.json'): None}
        refused = {('scripts/engine/a.py', 'apps/admin/r.ts'), ('scripts/engine/a.py', 'apps/admin/r.ts', 'apps/tsconfig.json')}
        with tempfile.TemporaryDirectory() as tmp:
            ownership = self.lane_fixture(tmp)
            for changed, lane in cases.items():
                self.assertEqual(ownership.lane_of('HEAD', list(changed)), lane, changed)
                self.assertEqual(bool(commit_check.lane_errors(Path(tmp), 'HEAD', list(changed))), changed in refused, changed)

    def test_d322_pr_errors_judge_the_discipline_the_plan_and_the_lanes_of_the_read_pr(self):
        """What the structure check judged of a read PR before D-322 is commit-check's pr_errors, its locks unchanged."""
        pr = {'body': self.BODY, 'draft': False, 'files': ['a.py'],
              'commits': [dict(commit('a', 'a', ['a.py']), message='a\n\nPlan: 1')]}
        with mock.patch.object(commit_check, 'regime', None), tempfile.TemporaryDirectory() as tmp:
            errors, warnings = commit_check.pr_errors(pr, Path(tmp))
            self.assertIn('item(s) 2, 3 not ticked', ' '.join(errors))
            self.assertEqual(warnings, [])
            errors, warnings = commit_check.pr_errors(dict(pr, draft=True), Path(tmp))
            self.assertNotIn('not ticked', ' '.join(errors))
            self.assertIn('D-083', ' '.join(warnings))
        lifting = type('Regime', (), {'lifted': staticmethod(lambda lock: lock == 'structure')})()
        with mock.patch.object(commit_check, 'regime', lifting), contextlib.redirect_stderr(io.StringIO()):
            self.assertNotIn('not ticked', ' '.join(commit_check.pr_errors(pr, Path(tmp))[0]))

    def test_d322_the_pr_body_file_is_refused_without_a_plan_and_judged_against_its_base(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(['git', '-C', tmp, 'init', '-q', '-b', 'main'], check=True)
            git = ['git', '-C', tmp, '-c', 'user.email=t@example.com', '-c', 'user.name=T', 'commit', '-q', '--allow-empty']
            subprocess.run([*git, '-m', 'base'], check=True)
            subprocess.run(['git', '-C', tmp, 'branch', 'base'], check=True)
            (root / 'a.py').write_text('a\n')
            subprocess.run(['git', '-C', tmp, 'add', 'a.py'], check=True)
            subprocess.run([*git, '-m', 'a\n\nPlan: 1'], check=True)
            body = root / 'body.md'
            body.write_text('Summary.\n')
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(commit_check.main(['--pr-body', str(body), '--root', tmp]), 1)
            self.assertIn('FAIL plan: the PR body needs a D-022 commit plan checklist', out.getvalue())
            body.write_text(self.BODY)
            with mock.patch.object(commit_check, 'regime', None):
                self.assertEqual(commit_check.body_errors(self.BODY, root), ([], []))  # no base: the plan alone
                errors, _ = commit_check.body_errors(self.BODY, root, 'base')
            self.assertEqual(len(errors), 1)
            self.assertIn('item(s) 2, 3 not ticked', errors[0])


if __name__ == '__main__':
    unittest.main(verbosity=1)


class FakeRegime:
    """The exception regime's interface (D-260) with the locks it lifts chosen by the test."""

    def __init__(self, lifted):
        self.lifted_locks = set(lifted)

    def lifted(self, lock):
        return lock in self.lifted_locks


class RegimeLock(unittest.TestCase):
    """D-260: a lifted lock warns and refuses nothing; without the regime module the locks act as they do today."""

    PR = {'body': '', 'commits': [], 'number': 1}

    def test_without_the_regime_a_missing_plan_is_refused(self):
        with mock.patch.object(commit_check, 'regime', None):
            self.assertTrue(commit_check.check(self.PR, {}))

    def test_an_active_regime_lifts_the_commit_plan_lock(self):
        with mock.patch.object(commit_check, 'regime', FakeRegime({'commit-plan'})), contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(commit_check.check(self.PR, {}), [])
        self.assertIn('lock commit-plan lifted by the exception regime', err.getvalue())

    def test_an_active_regime_keeps_the_other_locks(self):
        with mock.patch.object(commit_check, 'regime', FakeRegime({'literals'})):
            self.assertTrue(commit_check.check(self.PR, {}))
