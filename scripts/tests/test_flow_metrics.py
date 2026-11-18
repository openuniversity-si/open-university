"""Integrated commits and their guards (FLUXO-AMPLO, D-137). Hermetic: a throwaway git repository, no network."""
from datetime import datetime
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import json
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import box_meter  # noqa: E402
import flow_metrics  # noqa: E402

SINCE = '1970-01-01'


class Repo:
    def __init__(self, path):
        self.path = Path(path)
        self.env = dict(os.environ, GIT_AUTHOR_NAME='t', GIT_AUTHOR_EMAIL='t@t', GIT_COMMITTER_NAME='t',
                        GIT_COMMITTER_EMAIL='t@t')
        self.git('init', '-q', '-b', 'main')
        self.write('seed/a.txt', 'seed\n')
        self.commit('seed')

    def git(self, *args):
        return subprocess.run(['git', '-C', str(self.path), *args], check=True, capture_output=True, text=True,
                              env=self.env).stdout.strip()

    def write(self, name, text):
        target = self.path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)

    def change(self, files, subject, body='', when=None):
        """Write `files` ({path: text}) and commit them (at the ISO time `when`, if given); returns the sha."""
        for name, text in files.items():
            self.write(name, text)
        return self.commit(subject, body, when)

    def commit(self, subject, body='', when=None):
        self.git('add', '-A')
        env = dict(self.env, GIT_AUTHOR_DATE=when, GIT_COMMITTER_DATE=when) if when else self.env
        subprocess.run(['git', '-C', str(self.path), 'commit', '-q', '-m', f'{subject}\n\n{body}'], check=True,
                       capture_output=True, env=env)
        return self.git('rev-parse', 'HEAD')

    def envelope(self, name, steps, merged_at=None, subject=None):
        """Branch `name` with one commit per (files, subject, body) of `steps`, merged with a merge commit (whose
        subject is `subject`, else GitHub's form for PR #1)."""
        self.git('checkout', '-q', '-b', name)
        shas = [self.change(*step) for step in steps]
        self.git('checkout', '-q', 'main')
        env = dict(self.env, GIT_COMMITTER_DATE=merged_at) if merged_at else self.env
        subprocess.run(['git', '-C', str(self.path), 'merge', '-q', '--no-ff', '-m', subject or f'Merge pull request #1 from owner/{name}', name], check=True,
                       capture_output=True, env=env)
        return shas


class FlowMetricsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Repo(self.tmp.name)
        # the guard rules are judged with the regime off; the live registry's regime is CountGuardsLock's case (D-260)
        flow_metrics._LIFTED.clear()
        self.addCleanup(flow_metrics._LIFTED.clear)
        patch = mock.patch.object(flow_metrics, 'regime', None)
        patch.start()
        self.addCleanup(patch.stop)

    def report(self):
        return flow_metrics.report(flow_metrics.measure(self.repo.path, 'main', SINCE))

    def test_merge_envelopes_are_not_counted_and_plain_commits_count(self):
        steps = [({'site/web/a.txt': 'a\n'}, 'add a', 'Plan: 1'), ({'scripts/lib/b.txt': 'b\n'}, 'add b', 'Plan: 4')]
        self.repo.envelope('one', steps)
        total = self.report()['total']
        self.assertEqual(total['raw'], len(steps))
        self.assertEqual(total['counted'], total['raw'])
        self.assertEqual(total['split'], 0)

    def test_whitespace_only_commit_is_empty_and_not_counted(self):
        self.repo.change({'site/web/a.txt': 'a b\n'}, 'base file')
        self.repo.envelope('ws', [({'site/web/a.txt': 'a  b\n'}, 'spacing', '')])
        total = self.report()['total']
        self.assertEqual(total['empty'], 1)
        self.assertEqual(total['counted'], total['raw'] - 1)

    def test_revert_and_fixup_subjects_are_rework(self):
        self.repo.envelope('rw', [({'site/web/a.txt': 'x\n'}, 'Revert "x"', ''), ({'site/web/b.txt': 'y\n'}, 'fixup! x', '')])
        total = self.report()['total']
        self.assertEqual(total['fixup'], total['raw'])
        self.assertEqual(total['counted'], 0)

    def test_same_files_same_plan_in_a_row_count_once(self):
        self.repo.envelope('sp', [({'site/web/a.txt': 'one\n'}, 'part one', 'Plan: 7'),
                                  ({'site/web/a.txt': 'two\n'}, 'part two', 'Plan: 7')])
        total = self.report()['total']
        self.assertEqual(total['split'], 1)
        self.assertEqual(total['counted'], total['raw'] - 1)

    def test_other_plan_item_on_the_same_file_is_not_a_split(self):
        self.repo.envelope('np', [({'site/web/a.txt': 'one\n'}, 'first', 'Plan: 7'),
                                  ({'site/web/a.txt': 'two\n'}, 'second', 'Plan: 8')])
        self.assertEqual(self.report()['total']['split'], 0)

    def test_two_code_areas_are_tangled_but_docs_and_tests_accompany(self):
        self.repo.envelope('tg', [
            ({'site/web/a.txt': 'a\n', 'scripts/lib/b.txt': 'b\n'}, 'both', ''),
            ({'site/web/c.txt': 'c\n', 'docs/c.md': 'c\n', 'scripts/tests/test_c.py': 'c\n'}, 'code, docs, test', '')])
        total = self.report()['total']
        self.assertEqual(total['tangled'], 1)
        self.assertEqual(total['counted'], total['raw'])

    def test_guard_ratios_are_shares_of_the_raw_count(self):
        self.repo.envelope('gr', [({'site/web/a.txt': 'x\n'}, 'Revert "x"', 'Plan: 1')])
        guards = self.report()['guards']
        self.assertEqual(guards['fixup'], 1)
        self.assertEqual(guards['plan_linked'], 1)
        self.assertEqual(guards['empty'], 0)

    def test_cycles_are_medians_of_wait_and_authoring_per_commit(self):
        first, last, merged = ('2026-10-30T10:00:00+00:00', '2026-10-30T10:30:00+00:00', '2026-10-30T10:50:00+00:00')
        self.repo.envelope('cy', [({'site/a.txt': 'a\n'}, 'one', '', first), ({'site/b.txt': 'b\n'}, 'two', '', last)], merged)
        cycles = flow_metrics.cycles(flow_metrics.merged_envelopes(self.repo.path, 'main', SINCE, 'UTC'))
        (day, cycle), = cycles.items()
        stamp = datetime.fromisoformat
        self.assertEqual(day, stamp(merged).date().isoformat())
        self.assertEqual(cycle['prs'], 1)
        self.assertEqual(cycle['lanes'], 1)
        self.assertEqual(cycle['wait_s'], (stamp(merged) - stamp(last)).total_seconds())
        self.assertEqual(cycle['authoring_s'], (stamp(last) - stamp(first)).total_seconds() / len(('one', 'two')))

    def test_lanes_are_the_distinct_head_branches_of_a_day(self):
        self.repo.envelope('one', [({'site/a.txt': 'a\n'}, 'a', '')])
        self.repo.envelope('two', [({'site/b.txt': 'b\n'}, 'b', '')])
        merged = flow_metrics.merged_envelopes(self.repo.path, 'main', SINCE, 'UTC')
        self.assertEqual({lane for _, _, lane, _ in merged}, {'one', 'two'})

    def test_a_line_removed_by_the_next_commit_is_a_rewrite_within_one_but_not_within_none(self):
        shas = self.repo.envelope('rw1', [({'site/a.txt': 'keep\nfirst version\n'}, 'a', ''),
                                          ({'site/a.txt': 'keep\nsecond version\n'}, 'b', '')])
        merged = flow_metrics.merged_envelopes(self.repo.path, 'main', SINCE, 'UTC')
        self.assertEqual(len(merged), 1)
        result = flow_metrics.durability(self.repo.path, 'main', SINCE, 1, 'UTC')
        self.assertEqual((result['rewritten'], result['share']), (1, 1 / len(shas)))
        self.assertEqual(flow_metrics.durability(self.repo.path, 'main', SINCE, 0, 'UTC')['rewritten'], 0)

    def test_blank_lines_and_untouched_lines_are_not_rewrites(self):
        self.repo.envelope('rw2', [({'site/a.txt': 'one\n\n'}, 'a', ''), ({'site/b.txt': 'two\n\n'}, 'b', '')])
        self.assertEqual(flow_metrics.durability(self.repo.path, 'main', SINCE, 1, 'UTC')['rewritten'], 0)

    def test_a_script_and_its_library_are_one_area(self):
        self.assertEqual(flow_metrics.area('scripts/flow-metrics'), flow_metrics.area('scripts/lib/flow_metrics.py'))
        self.assertNotEqual(flow_metrics.area('scripts/x'), flow_metrics.area('site/x'))
        self.assertEqual(flow_metrics.area('apps/one/x.ts'), 'apps/one')

    def test_admit_judges_a_range_before_it_is_integrated(self):
        self.repo.git('checkout', '-q', '-b', 'work')
        self.repo.change({'site/a.txt': 'one\n'}, 'part one', 'Plan: 7')
        self.repo.change({'site/a.txt': 'two\n'}, 'part two', 'Plan: 7')
        self.repo.change({'site/b.txt': 'b\n'}, 'other file', 'Plan: 7')
        rows = flow_metrics.admit(self.repo.path, 'main..work', 'UTC')
        self.assertEqual([labels for _, _, labels in rows], [['rework'], ['split'], []])
        self.assertEqual([subject for _, subject, _ in flow_metrics.refused(rows)], ['part two'])

    def test_rolling_counts_only_merges_inside_the_window_and_keeps_the_rule(self):
        stamp = datetime.fromisoformat
        self.repo.envelope('old', [({'site/a.txt': 'a\n'}, 'old work', '', '2026-10-01T10:00:00+00:00')],
                           '2026-10-01T10:30:00+00:00')
        self.repo.envelope('new', [({'site/b.txt': 'b\n'}, 'new work', '', '2026-10-02T10:00:00+00:00'),
                                   ({'site/c.txt': 'c\n'}, 'Revert "new work"', '', '2026-10-02T10:10:00+00:00')],
                           '2026-10-02T10:30:00+00:00')
        merged = flow_metrics.merged_envelopes(self.repo.path, 'main', SINCE, 'UTC')
        now = stamp('2026-10-02T12:00:00+00:00').timestamp()
        day = datetime.fromisoformat('2026-10-02T00:00:00+00:00') - datetime.fromisoformat('2026-10-01T00:00:00+00:00')
        result = flow_metrics.rolling(merged, now, day.total_seconds())
        self.assertEqual(result, {'raw': len(('b', 'c')), 'counted': 1})
        both = flow_metrics.rolling(merged, now, day.total_seconds() + day.total_seconds())
        self.assertEqual(both['raw'], len(('a', 'b', 'c')))

    def test_pr_rate_counts_the_last_merges_up_to_now_and_names_the_ladder_step(self):
        merged = [(None, at, 'lane', []) for at in (0, 100, 200, 300)]
        quiet = flow_metrics.pr_rate(merged, 350, 2)
        self.assertEqual((quiet['prs'], quiet['window_s']), (2, 150))
        self.assertAlmostEqual(quiet['rate'], 2 / 150)
        self.assertEqual(quiet['step'], 1)
        self.assertAlmostEqual(quiet['next'], 10 * 1000 / 86400)
        stalled = flow_metrics.pr_rate(merged, 300 + 86400, 4)
        self.assertEqual(stalled['step'], 0)
        self.assertAlmostEqual(stalled['next'], 1000 / 86400)
        self.assertEqual(flow_metrics.pr_rate([], 400, 3), {'prs': 0, 'window_s': 0, 'rate': 0.0, 'step': 0, 'next': 1000 / 86400})
        self.assertEqual(flow_metrics.pr_rate(merged, 150, 9)['prs'], 2)

    def test_closed_hours_count_merges_per_minute_and_leave_the_running_hour_out(self):
        stamp = lambda text: datetime.fromisoformat(text).timestamp()  # noqa: E731
        merged = [(None, stamp(at), 'lane', []) for at in
                  ('2026-10-02T09:10:00+00:00', '2026-10-02T10:05:00+00:00', '2026-10-02T10:59:59+00:00',
                   '2026-10-02T11:30:00+00:00')]
        rows = flow_metrics.closed_hours(merged, stamp('2026-10-02T11:45:00+00:00'), 3, 'UTC')
        self.assertEqual([(row['hour'], row['prs']) for row in rows],
                         [('2026-10-02 10:00', 2), ('2026-10-02 09:00', 1), ('2026-10-02 08:00', 0)])
        self.assertAlmostEqual(rows[0]['per_minute'], 2 / 60)

    def test_a_pr_whose_line_a_later_pr_removes_is_reworked_but_not_by_itself_or_past_the_window(self):
        changes = [{'sha': 'a', 'added': {('f', 'x')}, 'removed': []},
                   {'sha': 'b', 'added': {('f', 'y')}, 'removed': [('f', 'x')]},
                   {'sha': 'c', 'added': {('g', 'z')}, 'removed': []},
                   {'sha': 'd', 'added': set(), 'removed': [('g', 'z')]},
                   {'sha': 'e', 'added': set(), 'removed': [('f', 'y')]}]
        owner = {'a': 0, 'b': 1, 'c': 2, 'd': 2, 'e': 9}
        self.assertEqual(flow_metrics.reworked_prs(changes, owner, 1), [0])
        self.assertEqual(flow_metrics.reworked_prs(changes, owner, 8), [0, 1])

    def test_incidents_counts_open_records_and_those_without_a_root_cause(self):
        folder = Path(self.repo.path) / 'docs' / 'operations' / 'incidents'
        folder.mkdir(parents=True)
        (folder / 'I-1.md').write_text('---\nstatus: open\n---\n## Case\n(to be decided)\n')
        (folder / 'I-2.md').write_text('---\nstatus: open\n---\n## Case\nknown\n')
        (folder / 'I-3.md').write_text('---\nstatus: closed\n---\n## Case\n(to be decided)\n')
        self.assertEqual(flow_metrics.incidents(self.repo.path), {'open': 2, 'undecided': 1})

    def test_hourly_buckets_counted_commits_by_the_hour_they_landed_newest_first(self):
        stamp = datetime.fromisoformat
        self.repo.envelope('h0', [({'site/a.txt': 'a\n'}, 'a', '', '2026-10-02T11:10:00+00:00'),
                                  ({'site/b.txt': 'b\n'}, 'Revert "a"', '', '2026-10-02T11:20:00+00:00')], '2026-10-02T11:40:00+00:00')
        self.repo.envelope('h2', [({'site/c.txt': 'c\n'}, 'c', '', '2026-10-02T09:10:00+00:00')], '2026-10-02T09:30:00+00:00')
        merged = flow_metrics.merged_envelopes(self.repo.path, 'main', SINCE, 'UTC')
        now = stamp('2026-10-02T12:00:00+00:00').timestamp()
        hours = len(('now', 'ago', 'before', 'earlier'))
        self.assertEqual(flow_metrics.hourly(merged, now, hours), [1, 0, 1, 0])

    def test_a_commit_that_only_changes_docs_is_labelled_and_still_counts(self):
        self.repo.envelope('dc', [({'docs/a.md': 'a\n'}, 'prose', ''), ({'site/b.txt': 'b\n', 'docs/b.md': 'b\n'}, 'code and prose', '')])
        data = self.report()
        self.assertEqual(data['total']['docsonly'], 1)
        self.assertEqual(data['total']['counted'], data['total']['raw'])
        self.assertEqual(data['guards']['docsonly'], 1 / data['total']['raw'])

    def test_a_commit_a_later_commit_of_the_same_pull_request_rewrites_is_rework(self):
        self.repo.envelope('rw', [({'site/a.txt': 'keep\nfirst version\n'}, 'a', ''), ({'site/b.txt': 'other\n'}, 'b', ''),
                                  ({'site/a.txt': 'keep\nsecond version\n'}, 'c', '')])
        result = flow_metrics.rework(self.repo.path, 'main', SINCE, 'UTC')
        self.assertEqual(result['rewritten'], 1)
        self.assertEqual(result['share'], 1 / len(('a', 'b', 'c')))

    def test_a_rewrite_in_another_pull_request_is_not_rework_of_this_one(self):
        self.repo.envelope('p1', [({'site/a.txt': 'one version\n'}, 'a', '')])
        self.repo.envelope('p2', [({'site/a.txt': 'two versions\n'}, 'b', '')])
        self.assertEqual(flow_metrics.rework(self.repo.path, 'main', SINCE, 'UTC')['rewritten'], 0)

    def test_admit_shows_rework_inside_the_range_without_refusing_it(self):
        self.repo.git('checkout', '-q', '-b', 'work')
        self.repo.change({'site/a.txt': 'keep\nfirst version\n'}, 'a', 'Plan: 1')
        self.repo.change({'site/b.txt': 'other\n'}, 'b', 'Plan: 2')
        self.repo.change({'site/a.txt': 'keep\nsecond version\n'}, 'c', 'Plan: 3')
        rows = flow_metrics.admit(self.repo.path, 'main..work', 'UTC')
        self.assertEqual([labels for _, _, labels in rows], [['rework'], [], []])
        self.assertEqual(flow_metrics.refused(rows), [])

    def test_merged_envelopes_reads_the_commits_of_every_pull_request_with_one_git_log(self):
        for name in ('one', 'two', 'three'):
            self.repo.envelope(name, [({f'site/{name}.txt': 'x\n'}, name, '')])
        calls = []
        real = flow_metrics.commit_facts
        flow_metrics.commit_facts = lambda root, shas, zone: (calls.append(list(shas)) or real(root, shas, zone))
        try:
            merged = flow_metrics.merged_envelopes(self.repo.path, 'main', SINCE, 'UTC')
        finally:
            flow_metrics.commit_facts = real
        self.assertEqual(len(calls), 1)
        self.assertEqual([len(facts) for _, _, _, facts in merged], [1, 1, 1])

    def test_the_lane_is_read_from_the_head_branch_name_and_the_hours_are_counted_per_lane(self):
        self.assertEqual(flow_metrics.family('claude/fluxo-amplo-v8-lane2-gate10s'), 'lane2')
        self.assertEqual(flow_metrics.family('claude/fluxo-amplo-v8-docsonly'), 'lane1')
        self.repo.envelope('claude-x-lane2-y', [({'site/a.txt': 'a\n'}, 'a', '', '2026-10-02T11:10:00+00:00')], '2026-10-02T11:40:00+00:00')
        self.repo.envelope('other', [({'site/b.txt': 'b\n'}, 'b', '', '2026-10-02T11:50:00+00:00'),
                                     ({'site/c.txt': 'c\n'}, 'c', '', '2026-10-02T11:55:00+00:00')], '2026-10-02T11:58:00+00:00')
        merged = flow_metrics.merged_envelopes(self.repo.path, 'main', SINCE, 'UTC')
        now = datetime.fromisoformat('2026-10-02T12:00:00+00:00').timestamp()
        self.assertEqual(flow_metrics.hourly_by_lane(merged, now, len(('now', 'before'))), {'lane1': [len(('b', 'c')), 0], 'lane2': [1, 0]})

    def test_since_is_the_start_of_that_day_whatever_the_hour_now(self):
        self.repo.envelope('sd', [({'site/a.txt': 'a\n'}, 'early', '', '2026-10-24T00:30:00+00:00')], '2026-10-24T00:40:00+00:00')
        data = flow_metrics.report(flow_metrics.measure(self.repo.path, 'main', '2026-10-24 00:00', 'UTC'))
        self.assertEqual(data['total']['raw'], 1)


def commit(sha, files, plan, gate_fix=False):
    return {'sha': sha, 'subject': 'change', 'plan': plan, 'files': files, 'gate_fix': gate_fix}


class GateFix(unittest.TestCase):
    def test_a_gate_fix_on_the_same_item_and_file_is_not_split(self):
        verdicts = flow_metrics.classify([commit('a', ['scripts/x.py'], 'item'),
                                          commit('b', ['scripts/x.py'], 'item', gate_fix=True)])
        self.assertNotIn('split', verdicts['b'])

    def test_the_same_item_and_file_without_the_trailer_is_split(self):
        verdicts = flow_metrics.classify([commit('a', ['scripts/x.py'], 'item'),
                                          commit('b', ['scripts/x.py'], 'item')])
        self.assertIn('split', verdicts['b'])

    def test_the_trailer_is_read_from_the_commit_body(self):
        self.assertTrue(flow_metrics.GATE_FIX.search('Plan: item\nGate-fix: literal census'))
        self.assertFalse(flow_metrics.GATE_FIX.search('Plan: item\nthe gate-fix was discussed'))


def verdict(kind, pr, sha, base, carried=None):
    return {'type': kind, 'version': 4, 'payload': {'pr': pr, 'sha': sha, 'base_sha': base, 'carried_from': carried}}


def merged(pr, merge_sha, batch_id=None):
    return {'type': 'pr.merged', 'version': 1, 'payload': {'pr': pr, 'merge_sha': merge_sha, 'batch_id': batch_id}}


def ejected(pr, batch_id, cause='culprit'):
    return {'type': 'pr.ejected', 'version': 1, 'payload': {'pr': pr, 'batch_id': batch_id, 'cause': cause}}


class FakePort:
    """The forge event port's read, from per-PR fixtures; records each channel read."""

    def __init__(self, channels, error=None):
        self.channels, self.error, self.reads = channels, error, []

    def read(self, repo, pr=None, strict=False, kinds=None):
        self.reads.append((repo, pr, tuple(kinds or ())))
        if self.error:
            raise self.error
        return [event for event in self.channels.get(pr, []) if not kinds or event['type'] in kinds]


class GateRuns(unittest.TestCase):
    """VAZÃO F24: the red-gate share p and gate runs per merged PR n_r, from the gate verdicts on each PR's channel."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Repo(self.tmp.name)

    def test_p_is_red_runs_over_all_runs_and_n_r_is_runs_per_pr_with_a_verdict(self):
        events = {1: [verdict('gate.failed', 1, 'a1', 'b0'), verdict('gate.passed', 1, 'a2', 'b0'), merged(1, 'm1')],
                  2: [verdict('gate.passed', 2, 'c1', 'b0'), verdict('gate.passed', 2, 'c2', 'b1', {'event_id': 'x'})],
                  3: [],
                  4: [verdict('gate.failed', 4, 'd1', 'b0'), merged(4, 'elsewhere')]}
        row = flow_metrics.gate_runs(events, [(1, 'm1'), (2, 'm2'), (3, 'm3'), (4, 'm4')])
        self.assertEqual((row['runs'], row['red']), (4, 1))
        self.assertAlmostEqual(row['p'], 1 / 4)
        self.assertAlmostEqual(row['n_r'], 4 / 2)
        self.assertEqual(row['measured'], [1, 2])
        self.assertEqual(row['unrecorded'], [3])
        self.assertEqual(row['foreign'], [4])
        self.assertEqual((row['rejudged'], row['carried']), (1, 1))

    def test_a_rerun_after_a_red_or_on_the_same_base_is_not_a_base_move(self):
        events = {1: [verdict('gate.failed', 1, 'a1', 'b0'), verdict('gate.passed', 1, 'a2', 'b1'),
                      verdict('gate.passed', 1, 'a2', 'b1'), verdict('gate.passed', 1, 'a3', '')]}
        self.assertEqual(flow_metrics.gate_runs(events, [(1, 'm1')])['rejudged'], 0)

    def test_an_empty_window_measures_nothing(self):
        row = flow_metrics.gate_runs({}, [])
        self.assertEqual((row['runs'], row['p'], row['n_r']), (0, 0.0, 0.0))

    def test_the_window_is_the_last_merged_prs_in_either_subject_form(self):
        self.repo.envelope('old', [({'site/a.txt': 'a\n'}, 'a', '')], subject='Merge pull request #1093 from owner/old')
        self.repo.envelope('mid', [({'site/b.txt': 'b\n'}, 'b', '')], subject='mid work (#7)')
        self.repo.envelope('new', [({'site/c.txt': 'c\n'}, 'c', '')], subject='new work (#8)')
        heads = self.repo.git('log', '--first-parent', '--merges', '--format=%H').split()
        self.assertEqual(flow_metrics.merged_prs(self.repo.path, 'main', SINCE, 2, 'UTC'), [(8, heads[0]), (7, heads[1])])
        self.assertEqual([pr for pr, _ in flow_metrics.merged_prs(self.repo.path, 'main', SINCE, 9, 'UTC')], [8, 7, 1093])

    def test_the_port_is_read_once_per_window_pr_and_only_for_gate_verdicts_and_merges(self):
        self.repo.envelope('one', [({'site/a.txt': 'a\n'}, 'a', '')], subject='one (#5)')
        self.repo.envelope('two', [({'site/b.txt': 'b\n'}, 'b', '')], subject='two (#6)')
        port = FakePort({6: [verdict('gate.failed', 6, 's', 'b'), verdict('gate.passed', 6, 's2', 'b'),
                             {'type': 'pr.pushed', 'version': 1, 'payload': {'pr': 6}},
                             dict(verdict('gate.failed', 6, 's3', 'b'), version=99)],
                         5: [verdict('gate.passed', 5, 't', 'b')]})
        row = flow_metrics.measured_gate_runs(self.repo.path, 'main', SINCE, 1, 'UTC', port=port, repo='r')
        self.assertEqual([pr for _repo, pr, _kinds in port.reads], [6])
        self.assertEqual(set(port.reads[0][2]), {'gate.passed', 'gate.failed', 'pr.merged', 'pr.ejected'})
        self.assertEqual((row['runs'], row['red'], row['n_r']), (2, 1, 2.0))

    def test_an_unreadable_port_is_reported_and_the_render_names_the_window(self):
        self.repo.envelope('one', [({'site/a.txt': 'a\n'}, 'a', '')], subject='one (#5)')
        port = FakePort({}, error=RuntimeError('no credential'))
        row = flow_metrics.measured_gate_runs(self.repo.path, 'main', SINCE, 3, 'UTC', port=port, repo='r')
        self.assertEqual(row['prs'], [5])
        self.assertIn('no credential', flow_metrics.render_gate_runs(row)[0])
        lines = flow_metrics.render_gate_runs(flow_metrics.gate_runs({5: [verdict('gate.failed', 5, 'a', 'b')]}, [(5, 'm')]))
        self.assertEqual(len(lines), 3)
        self.assertIn('last 1 merged PRs (merged #5 to #5): 1 of 1 (p 1.000)', lines[0])
        self.assertIn('1.00 (n_r', lines[1])


class BatchRuns(unittest.TestCase):
    """F36: a PR judged in a tier-2 batch on the box costs 1/k of a run, and the culprit's share is red."""

    def test_each_member_of_a_batch_is_one_kth_of_a_run(self):
        events = {1: [merged(1, 'm1', 'b-one')], 2: [merged(2, 'm2', 'b-one')], 3: [merged(3, 'm3', 'b-one')],
                  4: [merged(4, 'm4', 'b-one')]}
        row = flow_metrics.gate_runs(events, [(4, 'm4'), (3, 'm3'), (2, 'm2'), (1, 'm1')])
        self.assertAlmostEqual(row['runs'], 1.0)
        self.assertAlmostEqual(row['n_r'], 1 / 4, msg='four PRs for one tier-2 run')
        self.assertEqual((row['red'], row['measured'], row['batched'], row['unrecorded']), (0, [4, 3, 2, 1], [4, 3, 2, 1], []))

    def test_the_culprit_share_is_red_and_its_later_gate_counts_whole(self):
        events = {1: [merged(1, 'm1', 'b-red')],
                  2: [ejected(2, 'b-red'), verdict('gate.passed', 2, 'a2', 'b1'), merged(2, 'm2', 'b-next')],
                  3: [merged(3, 'm3', 'b-next')]}
        row = flow_metrics.gate_runs(events, [(3, 'm3'), (2, 'm2'), (1, 'm1')], sizes={'b-red': 2})
        self.assertAlmostEqual(row['runs'], 1 / 2 + 1 / 2 + 1 + 1 / 2 + 1 / 2)
        self.assertAlmostEqual(row['red'], 1 / 2)
        self.assertAlmostEqual(row['p'], (1 / 2) / 3)

    def test_a_verdict_or_shard_id_is_not_a_batch(self):
        events = {1: [verdict('gate.passed', 1, 'a', 'b'), merged(1, 'm1', 'v-strict')]}
        row = flow_metrics.gate_runs(events, [(1, 'm1')])
        self.assertEqual((row['runs'], row['batched']), (1, []))

    def test_the_render_names_the_batched_prs(self):
        lines = flow_metrics.render_gate_runs(flow_metrics.gate_runs({1: [merged(1, 'm1', 'b-x')], 2: [merged(2, 'm2', 'b-x')]},
                                                                     [(2, 'm2'), (1, 'm1')]))
        self.assertIn('0 of 1 (p 0.000)', lines[0])
        self.assertIn('2 judged in a batch at 1/k run each', lines[1])


class LockBatches(unittest.TestCase):
    """F36: batches in the box's lock log: runs per resolved PR, green batches, held time against a single delivery."""

    def rows(self):
        single = [{'pr': n, 'waited_s': 0.0, 'held_s': 100.0, 'at': n} for n in (1, 2)]
        green = {'pr': 3, 'waited_s': 5.0, 'held_s': 110.0, 'at': 3,
                 'batch': {'id': 'b-g', 'prs': [3, 4, 5], 'runs': 1, 'merged': [3, 4, 5]}}
        red = {'pr': 6, 'waited_s': 0.0, 'held_s': 300.0, 'at': 4,
               'batch': {'id': 'b-r', 'prs': [6, 7, 8, 9], 'runs': 3, 'merged': [6], 'ejected': [7]}}
        return single + [green, red]

    def test_runs_per_resolved_pr_and_green_batches(self):
        row = flow_metrics.batch_log(self.rows())
        self.assertEqual((row['batches'], row['green'], row['runs'], row['resolved']), (2, 1, 4, 5))
        self.assertAlmostEqual(row['runs_per_resolved'], 4 / 5)
        self.assertEqual((row['held_per_batch_s'], row['held_per_single_s']), (205.0, 100.0))
        self.assertEqual(row['sizes'], {'b-g': 3, 'b-r': 4})
        self.assertIn('1 green, 4 tier-2 runs for 5 resolved PRs (0.80 per PR', flow_metrics.render_batches(row))

    def test_only_the_last_batches_count(self):
        row = flow_metrics.batch_log(self.rows(), last=1)
        self.assertEqual((row['batches'], row['runs'], row['resolved']), (1, 3, 2))

    def test_a_log_without_batches_renders_nothing(self):
        self.assertIsNone(flow_metrics.render_batches(flow_metrics.batch_log(self.rows()[:2])))

    def test_the_constraint_carries_the_batches_of_the_whole_log(self):
        path = Path(tempfile.mkdtemp()) / 'lock.jsonl'
        path.write_text('not json\n' + ''.join(json.dumps(row) + '\n' for row in self.rows()) + '{"pr": 9}\n')
        self.assertEqual(flow_metrics.lock_rows(str(path)), self.rows(), 'a broken line is skipped')
        found = flow_metrics.constraint([], 10.0, 1, str(path), path)
        self.assertEqual((found['deliveries'], found['batches']['batches']), (4, 2))
        self.assertIn('batches on the box (last 2)', flow_metrics.render({'days': {}, 'total': {}, 'guards': {},
                                                                          'constraint': found}))


class Constraint(unittest.TestCase):
    """F38: the constraint is a measure: the box's busy share from its lock log against BOX_BOUND."""

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.queue = self.dir / 'fila.md'
        self.queue.write_text('# Fila\n\n## Unidades\n\n| # | x |\n|---|---|\n| F1 | a |\n| F2 | b |\n\n## Deixadas de fora\n')
        self.merged = [(None, 3600.0 * 10 - 600 * i, 'lane', {}) for i in range(6)]

    def log(self, *held):
        path = self.dir / 'lock.jsonl'
        path.write_text(''.join(json.dumps({'pr': i, 'waited_s': 0.0, 'held_s': h, 'at': 36000 - 60 * i}) + '\n'
                                for i, h in enumerate(held)))
        return str(path)

    def test_a_box_busy_less_than_the_bound_points_upstream(self):
        found = flow_metrics.constraint(self.merged, 36000.0, 1, self.log(100, 100, 100), self.queue)
        self.assertAlmostEqual(found['busy'], 300 / 3600)
        self.assertEqual(found['merged'], 6)
        self.assertEqual(found['queue_rows'], 2)
        self.assertTrue(found['constraint'].startswith('supply'))  # 2 rows for 3 gating lanes

    def test_ready_units_and_an_idle_box_point_at_the_lanes_authoring(self):
        found = flow_metrics.constraint(self.merged, 36000.0, 1, self.log(100), self.queue, lanes=1)
        self.assertTrue(found['constraint'].startswith('lane authoring'))

    def test_a_box_busy_past_the_bound_is_the_constraint(self):
        found = flow_metrics.constraint(self.merged, 36000.0, 1, self.log(*[300] * 9), self.queue)
        self.assertGreaterEqual(found['busy'], flow_metrics.BOX_BOUND)
        self.assertTrue(found['constraint'].startswith('box'))

    def test_suites_count_toward_the_busy_box_apart_from_deliveries(self):
        path = Path(self.log(100, 100))
        suites = [{'pr': None, 'kind': 'suite', 'waited_s': w, 'held_s': 300.0, 'at': 35000 + w} for w in (0.0, 40.0)]
        path.write_text(path.read_text() + ''.join(json.dumps(row) + '\n' for row in suites))
        found = flow_metrics.constraint(self.merged, 36000.0, 1, str(path), self.queue)
        self.assertAlmostEqual(found['busy'], 800 / 3600)
        self.assertEqual((found['deliveries'], found['held_per_delivery_s']), (2, 100.0))
        self.assertEqual((found['suites'], found['held_per_suite_s']), (2, 300.0))
        self.assertEqual((found['waits'], found['wait_max_s']), (1, 40.0))
        self.assertIsNone(found['batches']['held_per_batch_s'])
        self.assertEqual(found['batches']['held_per_single_s'], 100.0, 'a suite is not a single delivery')
        line = flow_metrics.render({'days': {}, 'total': {}, 'guards': {}, 'constraint': found})
        self.assertIn('box busy 22% (2 deliveries, 100 s held per delivery; 2 suites, 300 s held per suite; 1 waited',
                      line)

    def test_suite_slots_are_their_own_kind_outside_the_box(self):
        path = Path(self.log(100))
        slots = [{'pr': None, 'kind': 'suite_slot', 'waited_s': w, 'held_s': 200.0, 'at': 35000 + w} for w in (0.0, 30.0)]
        path.write_text(path.read_text() + ''.join(json.dumps(row) + '\n' for row in slots))
        found = flow_metrics.constraint(self.merged, 36000.0, 1, str(path), self.queue)
        self.assertAlmostEqual(found['busy'], 100 / 3600, msg='a slot hold is not the box busy')
        self.assertEqual((found['deliveries'], found['suites'], found['waits']), (1, 0, 0))
        self.assertEqual((found['slots'], found['held_per_slot_s'], found['slot_waits'], found['slot_wait_max_s']),
                         (2, 200.0, 1, 30.0))
        self.assertEqual(found['batches']['held_per_single_s'], 100.0, 'a slot is not a single delivery')
        line = flow_metrics.render({'days': {}, 'total': {}, 'guards': {}, 'constraint': found})
        self.assertIn('--changed suites off the box: 2 slot holds, 200 s held per suite, 1 waited, longest 30 s', line)

    def test_a_log_without_slots_prints_no_slot_line(self):
        found = flow_metrics.constraint(self.merged, 36000.0, 1, self.log(100), self.queue)
        self.assertEqual((found['slots'], found['held_per_slot_s']), (0, None))
        self.assertNotIn('off the box', flow_metrics.render({'days': {}, 'total': {}, 'guards': {}, 'constraint': found}))

    def test_a_log_without_suites_says_so(self):
        found = flow_metrics.constraint(self.merged, 36000.0, 1, self.log(100), self.queue)
        self.assertEqual((found['suites'], found['held_per_suite_s']), (0, None))
        self.assertIn('0 suites, no suite logged', flow_metrics.render({'days': {}, 'total': {}, 'guards': {},
                                                                        'constraint': found}))

    def test_the_cpu_of_deliveries_reads_against_the_box_ceiling_and_the_idle_share(self):
        """F71: CPU-s per delivery from the rows with cpu_s; idle = 1 - cpu / (held x vcpus); old rows and suites stay out."""
        path = Path(self.log(100))  # an old row without cpu_s
        rows = [{'pr': 10, 'waited_s': 0.0, 'held_s': 100.0, 'at': 35500, 'cpu_s': 120.0, 'vcpus': 4},
                {'pr': 11, 'waited_s': 0.0, 'held_s': 50.0, 'at': 35600, 'cpu_s': 60.0, 'vcpus': 4},
                {'pr': None, 'kind': 'suite', 'waited_s': 0.0, 'held_s': 75.0, 'at': 35700, 'cpu_s': 300.0, 'vcpus': 4}]
        path.write_text(path.read_text() + ''.join(json.dumps(row) + '\n' for row in rows))
        found = flow_metrics.constraint(self.merged, 36000.0, 1, str(path), self.queue)
        cpu = found['cpu']
        self.assertEqual((cpu['deliveries'], cpu['cpu_per_delivery_s'], cpu['vcpus'], cpu['ceiling_cpu_s_h']),
                         (2, 90.0, 4, 14400))
        self.assertAlmostEqual(cpu['ceiling_per_h'], 160.0)
        self.assertAlmostEqual(cpu['idle'], 1 - 180 / 600)
        line = flow_metrics.render({'days': {}, 'total': {}, 'guards': {}, 'constraint': found})
        self.assertIn('box CPU: 90 CPU-s per delivery (2 with cpu_s) against 4 vCPU (14400 CPU-s/h, ceiling 160 '
                      'deliveries/h); hold idle 70%', line)

    def test_a_log_without_cpu_prints_no_cpu_line(self):
        found = flow_metrics.constraint(self.merged, 36000.0, 1, self.log(100), self.queue)
        self.assertIsNone(found['cpu'])
        self.assertNotIn('box CPU', flow_metrics.render({'days': {}, 'total': {}, 'guards': {}, 'constraint': found}))

    def test_a_missing_log_is_zero_busy_not_a_crash(self):
        found = flow_metrics.constraint(self.merged, 36000.0, 1, str(self.dir / 'none.jsonl'), self.queue)
        self.assertEqual((found['busy'], found['deliveries']), (0.0, 0))


class FakeRegime:
    def __init__(self, lifted):
        self.lifted_locks = set(lifted)

    def lifted(self, lock):
        return lock in self.lifted_locks


class CountGuardsLock(unittest.TestCase):
    """D-260: an active regime lifts the split and fixup guards (they still label); an empty commit stays uncounted."""

    def setUp(self):
        flow_metrics._LIFTED.clear()

    def tearDown(self):
        flow_metrics._LIFTED.clear()

    def envelope(self):
        first = {'sha': 'a', 'files': ['scripts/lib/x.py'], 'subject': 'first', 'plan': None}
        split = {'sha': 'b', 'files': ['scripts/lib/x.py'], 'subject': 'second', 'plan': None}
        fixup = {'sha': 'c', 'files': ['scripts/lib/y.py'], 'subject': flow_metrics.UNDO[0] + 'first', 'plan': None}
        empty = {'sha': 'd', 'files': [], 'subject': 'nothing', 'plan': None}
        return [first, split, fixup, empty]

    def test_without_the_regime_split_and_fixup_are_uncounted(self):
        with mock.patch.object(flow_metrics, 'regime', None):  # uncounted asks the regime too: both run without it
            verdicts = flow_metrics.classify(self.envelope())
            self.assertTrue(flow_metrics.uncounted(verdicts['b']))
            self.assertTrue(flow_metrics.uncounted(verdicts['c']))

    def test_an_active_regime_counts_split_and_fixup_but_not_empty(self):
        with mock.patch.object(flow_metrics, 'regime', FakeRegime({'count-guards'})):
            verdicts = flow_metrics.classify(self.envelope())
            self.assertIn('split', verdicts['b'])
            self.assertFalse(flow_metrics.uncounted(verdicts['b']))
            self.assertFalse(flow_metrics.uncounted(verdicts['c']))
            self.assertTrue(flow_metrics.uncounted(verdicts['d']))


def ledger_lane(pr, weighted, end, merged='m', wall_s=600, tool_calls=40):
    return {'role': 'lane', 'pr': pr, 'merged': merged, 'end': end, 'wall_s': wall_s, 'tool_calls': tool_calls,
            'tokens': {'weighted': weighted}}


class Quota(unittest.TestCase):
    """F59: the cost of a merged PR read from the quota ledger, per lane and with the coordinator's share."""

    ROWS = [ledger_lane(150, 100, '2026-11-03T20:00Z'), ledger_lane(151, 300, '2026-11-03T20:10Z'),
            ledger_lane(151, 100, '2026-11-03T20:20Z', wall_s=60, tool_calls=4),  # a second lane on the same PR adds up
            ledger_lane(152, 900, '2026-11-03T20:30Z', merged=None),  # not merged: no cost per merged PR yet
            ledger_lane(153, 500, '2026-11-03T20:40Z'),
            {'role': 'subagent', 'tokens': {'weighted': 10_000}},
            {'role': 'coordinator', 'prs': [151, 153, 99], 'weighted_per_pr': 100}]

    def test_the_window_is_the_last_merged_prs_and_their_lanes_add_up(self):
        row = flow_metrics.quota(self.ROWS, 2)
        self.assertEqual(row['prs'], [153, 151])
        self.assertEqual((row['weighted_median'], row['weighted_mean'], row['wall_median_s'], row['tool_calls_median']),
                         (450, 450, 630, 42))

    def test_the_coordinator_share_counts_its_prs_inside_the_window(self):
        row = flow_metrics.quota(self.ROWS, 3)
        self.assertEqual((row['coordinator'], round(row['coordinator_share'], 3)), (200, round(200 / 1200, 3)))
        self.assertIn('last 3 merged lanes (#150 to #153): weighted tokens median 400', flow_metrics.render_quota(row))

    def test_an_empty_or_missing_ledger_is_not_measured(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / 'lanes.jsonl'
            self.assertEqual(flow_metrics.read_ledger(ledger), [])
            ledger.write_text(json.dumps(self.ROWS[0]) + '\nbroken\n')
            self.assertEqual(len(flow_metrics.read_ledger(ledger)), 1)
        rendered = flow_metrics.render({'days': {}, 'total': {}, 'guards': {}, 'quota': flow_metrics.quota([], 5)})
        self.assertIn('quota per merged PR: not measured', rendered)



class BatchReading(unittest.TestCase):
    """F64 (D-297): the batch reads ready when the box is busy >= 0.70 and p <= 0.25, with the projected ceiling."""

    TABLE = [{'red_max': 0.10, 'size': 8}, {'red_max': 0.15, 'size': 4}, {'red_max': 0.25, 'size': 2}]

    def found(self, busy, held=90.0, batches=None):
        return {'busy': busy, 'held_per_delivery_s': held, 'batches': batches or {}}

    def gate(self, p, runs=10):
        return {'prs': list(range(50)), 'runs': runs, 'p': p}

    def test_a_busy_box_and_a_low_p_are_ready_with_k_and_the_ceiling(self):
        reading = flow_metrics.batch_reading(self.found(0.75), self.gate(0.12), self.TABLE, 8)
        self.assertTrue(reading['ready'])
        self.assertEqual(reading['k'], 4)
        self.assertAlmostEqual(reading['ceiling_per_h'], 40 * 4 / flow_metrics.BATCH_HOLD)
        line = flow_metrics.render_batch_reading(reading)
        self.assertTrue(line.startswith('batch: ready (box busy 75% >= 70%, p 0.120 <= 0.25 over 50 PRs)'), line)
        self.assertIn('projected ceiling 40/h x 4/1.3 ~ 123/h with k 4', line)

    def test_the_bounds_are_inclusive(self):
        self.assertTrue(flow_metrics.batch_reading(self.found(0.70), self.gate(0.25), self.TABLE, 8)['ready'])

    def test_an_idle_box_is_not_ready(self):
        reading = flow_metrics.batch_reading(self.found(0.48), self.gate(0.0), self.TABLE, 8)
        self.assertEqual((reading['ready'], reading['why']), (False, 'box busy 48% < 70%'))
        self.assertIn('batch: not ready (box busy 48% < 70%', flow_metrics.render_batch_reading(reading))

    def test_a_high_or_unread_p_is_not_ready(self):
        high = flow_metrics.batch_reading(self.found(0.9), self.gate(0.3), self.TABLE, 8)
        self.assertEqual((high['ready'], high['why'], high['k']), (False, 'p 0.300 > 0.25', 1))
        unread = flow_metrics.batch_reading(self.found(0.9), {'prs': [], 'error': 'OSError: offline'}, self.TABLE, 8)
        self.assertFalse(unread['ready'])
        self.assertIn('p unread (OSError: offline)', flow_metrics.render_batch_reading(unread))

    def test_a_measured_batch_hold_replaces_the_default_ratio(self):
        batches = {'held_per_batch_s': 180.0, 'held_per_single_s': 90.0}
        reading = flow_metrics.batch_reading(self.found(0.8, batches=batches), self.gate(0.05), self.TABLE, 8)
        self.assertEqual((reading['k'], reading['ratio']), (8, 2.0))
        self.assertAlmostEqual(reading['ceiling_per_h'], 40 * 8 / 2.0)

    def test_lazy_does_not_read_p_while_the_box_is_idle(self):
        with mock.patch.object(box_meter, 'measured_gate_runs', side_effect=AssertionError('read p')):
            reading = flow_metrics.measured_batch_reading(self.found(0.2), lazy=True)
        self.assertFalse(reading['ready'])


class WindowCache(unittest.TestCase):
    """F91: the window's gate runs are read once per 60 s, and one fetch of the log serves the whole window."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'sub' / 'cache.json'
        self.calls = 0

    def compute(self, value=None):
        self.calls += 1
        return value or {'prs': [1], 'p': 0.5}

    def test_reuses_the_result_inside_the_window(self):
        first = flow_metrics.cached(self.path, 'k', self.compute, ttl=60, now=1000)
        second = flow_metrics.cached(self.path, 'k', self.compute, ttl=60, now=1059)
        self.assertEqual((first, second, self.calls), ({'prs': [1], 'p': 0.5}, {'prs': [1], 'p': 0.5}, 1))

    def test_reads_again_after_the_window(self):
        flow_metrics.cached(self.path, 'k', self.compute, ttl=60, now=1000)
        flow_metrics.cached(self.path, 'k', self.compute, ttl=60, now=1060)
        self.assertEqual(self.calls, 2)

    def test_another_window_is_another_key(self):
        flow_metrics.cached(self.path, 'a', self.compute, ttl=60, now=1000)
        flow_metrics.cached(self.path, 'b', self.compute, ttl=60, now=1001)
        self.assertEqual(self.calls, 2)

    def test_an_unreadable_forge_is_never_kept(self):
        for _ in range(2):
            flow_metrics.cached(self.path, 'k', lambda: self.compute({'prs': [1], 'error': 'OSError: down'}), now=1000)
        self.assertEqual((self.calls, self.path.exists()), (2, False))

    def test_a_broken_cache_file_costs_only_the_reuse(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text('not json')
        self.assertEqual(flow_metrics.cached(self.path, 'k', self.compute, now=1000), {'prs': [1], 'p': 0.5})

    def test_measured_gate_runs_on_the_real_forge_is_cached_but_an_injected_port_is_not(self):
        port = FakePort({})
        with mock.patch.dict(os.environ, {'FLOW_METRICS_CACHE': str(self.path)}), \
                mock.patch.object(box_meter, 'merged_prs', return_value=[(1, 'm1')]), \
                mock.patch.object(box_meter, 'read_gate_runs', wraps=flow_metrics.read_gate_runs) as read:
            for _ in range(2):
                flow_metrics.measured_gate_runs(ROOT, 'main', SINCE, 1, 'UTC', port=port, repo='r')
            self.assertEqual((read.call_count, self.path.exists()), (2, False))
            read.side_effect = lambda merges, *_: {'prs': [pr for pr, _ in merges], 'p': 0.0}
            for _ in range(2):
                flow_metrics.measured_gate_runs(ROOT, 'main', SINCE, 1, 'UTC', repo='r')
            self.assertEqual((read.call_count, self.path.exists()), (3, True))

    def test_pinned_tip_fetches_the_log_once_and_restores_the_read(self):
        class Refs:
            fetches = 0

            def read(self, name):
                Refs.fetches += 1
                return ('sha', name)
        refs = Refs()
        port = mock.Mock(adapter=mock.Mock(refs=refs, main=None, spec=['refs', 'main']))
        original = refs.read
        with flow_metrics.pinned_tip(port):
            for _ in range(5):
                refs.read('log')
        self.assertEqual(Refs.fetches, 1)
        refs.read('log')
        self.assertEqual((Refs.fetches, refs.read == original), (2, True))


if __name__ == '__main__':
    unittest.main()
