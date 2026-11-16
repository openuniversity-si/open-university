"""Offline forge behavior for Origin, plus explicit capability gaps.

Origin injects its real CLI client with a transport double, control plane and git
refs. Assertions observe stored comments, pull fields, parent edges and leases,
independently of the declared operation relation. No network.
"""
from http import HTTPStatus
from pathlib import Path
import re
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'lib'))

import config  # noqa: E402
import forge_events  # noqa: E402
import forge_origin  # noqa: E402
import forge_origin_client  # noqa: E402

REPO = 'o/r'
ORIGIN_HOST = 'origin.test'
PR = 1
HEAD, BASE, OTHER = 'a' * 40, 'b' * 40, 'c' * 40
# The three open pulls the fake answers with: the one under test, a draft on the same base, and one for another
# base. Their numbers are counted from PR rather than spelled (LT1).
OPEN_PULLS = [{'number': number, 'draft': draft, 'head': {'ref': head, 'sha': sha},
               'base': {'ref': base_ref, 'sha': BASE}}
              for number, (base_ref, head, sha, draft) in enumerate(
                  [('mod/roadmap-integration', 'feature', HEAD, False),
                   ('mod/roadmap-integration', 'wip', OTHER, True),
                   ('main', 'other', OTHER, False)], start=PR)]


MERGE_OLD = '2026-10-01T12:00:00Z'
MERGE_NEW = '2026-11-01T12:00:00Z'
OPEN_CHANGE, UNMERGED_CHANGE, OLD_CHANGE, NEW_CHANGE, UNTIMED_CHANGE = range(
    PR, PR + len(('open', 'unmerged', 'old', 'new', 'untimed')))
HISTORY = [
    {'number': OPEN_CHANGE, 'state': 'open', 'body': 'open'},
    {'number': UNMERGED_CHANGE, 'state': 'closed', 'body': 'closed', 'merged': False,
     'mergedAt': MERGE_NEW, 'merged_at': None},
    {'number': OLD_CHANGE, 'state': 'closed', 'body': 'old', 'merged': True,
     'mergedAt': MERGE_OLD, 'merged_at': MERGE_OLD},
    {'number': NEW_CHANGE, 'state': 'closed', 'body': 'Capability: CAP-001', 'merged': True,
     'mergedAt': MERGE_NEW, 'merged_at': MERGE_NEW},
    {'number': UNTIMED_CHANGE, 'state': 'closed', 'body': 'missing merge time', 'merged': True},
]


class RefStore:
    """Conditional commit append oracle: stale parents cannot replace the holder."""
    def __init__(self):
        self.records = {}
        self.lose = False

    def read(self, name):
        return self.records.get(name)

    def advance(self, name, record, parent):
        held = self.records.get(name)
        if self.lose or (held[0] if held else None) != parent:
            return False
        self.records[name] = (str(len(self.records)) + repr(record), dict(record))
        return True


class ForgeContract:
    """Supported operations, the same behavioral oracle for every adapter."""

    def test_contract_covers_active_consumer_requirements(self):
        import forge_requirements
        import operation_demands
        name = operation_demands.adapter_name(self.adapter)
        # Behavioral references are independently resolved against real test bodies.
        document = operation_demands.load()
        consumers = ['scripts/lib/train.py', 'scripts/lib/engine_role.py', 'scripts/lib/train_queue.py']
        covered = {operation for operation in document['proofs'][name]
                   if operation_demands._evidence(operation_demands.ROOT,
                       document['proofs'][name][operation], operation)}
        forge_requirements.require_coverage(consumers, covered, {'foreign-ownership'})
        with self.assertRaisesRegex(operation_demands.CompatibilityError, 'approvals'):
            forge_requirements.require_coverage(consumers, covered - {'approvals'}, {'foreign-ownership'})

    def test_closed_changes_preserves_merged_facts_and_inclusive_since(self):
        self.forge.history = HISTORY
        expected = [{'number': OLD_CHANGE, 'body': 'old', 'merged_at': MERGE_OLD},
                    {'number': NEW_CHANGE, 'body': 'Capability: CAP-001', 'merged_at': MERGE_NEW}]
        self.assertEqual(self.adapter.closed_changes(REPO), expected)
        # Offset spelling denotes the same instant, so equality must be inclusive.
        self.assertEqual(self.adapter.closed_changes(REPO, '2026-11-01T09:00:00-03:00'), expected[1:])
        self.assertEqual(self.adapter.closed_changes(REPO, '2026-11-02T00:00:00Z'), [])

    def test_idea_report_keeps_capability_filter_and_consumer_keys(self):
        import idea_to_prod
        self.forge.history = HISTORY
        with mock.patch.object(forge_events, 'adapter_from_config', return_value=self.adapter), \
                mock.patch.object(idea_to_prod, 'REPO', REPO):
            self.assertEqual(idea_to_prod.GitHub().prs(), [
                {'number': NEW_CHANGE, 'body': 'Capability: CAP-001', 'mergedAt': MERGE_NEW}])

    def test_change_names_the_head_the_base_and_the_body(self):
        found = self.adapter.change(REPO, self.forge.pr)
        self.assertEqual((found['head'], found['base_ref'], found['body']), (HEAD, 'mod/roadmap-integration', 'Plan: 1'))

    def test_port_admits_the_compatible_replay_demand(self):
        port = forge_events.ForgeEvents(self.adapter, forge_events.SystemClock(), 'test', 'replay',
                                       consumer='scripts/lib/replay_branch.py')
        self.assertEqual(port.pull(REPO, PR)['head_sha'], HEAD)

    def test_port_checks_the_adjacent_change_evidence(self):
        port = forge_events.ForgeEvents(self.adapter, forge_events.SystemClock(), 'test', 'direct',
                                       consumer='scripts/lib/pr_ready.py')
        self.assertEqual(port.change(REPO, PR)['head'], HEAD)

    def test_comment_append_and_list_preserve_text_and_order(self):
        self.adapter.comment(REPO, PR, 'first')
        self.adapter.comment(REPO, PR, 'second')
        self.assertEqual([item['body'] for item in self.adapter.comments(REPO, PR)], ['first', 'second'])

    def test_upsert_edits_exact_marker_and_keeps_other_comments(self):
        self.adapter.comment(REPO, PR, 'marker extra\nkeep')
        comment_id = self.adapter.upsert_comment(REPO, PR, 'marker', 'marker\nold')
        self.assertEqual(self.adapter.upsert_comment(REPO, PR, 'marker',
                         lambda previous: previous.replace('old', 'new')), comment_id)
        self.assertEqual([item['body'] for item in self.adapter.comments(REPO, PR)],
                         ['marker extra\nkeep', 'marker\nnew'])

    def test_upsert_selects_newest_of_multiple_exact_markers(self):
        self.adapter.comment(REPO, PR, 'marker\nolder')
        self.adapter.comment(REPO, PR, 'marker\nnewer')
        self.adapter.upsert_comment(REPO, PR, 'marker', 'marker\nupdated')
        self.assertEqual([item['body'] for item in self.adapter.comments(REPO, PR)],
                         ['marker\nolder', 'marker\nupdated'])

    def test_upsert_with_stored_id_updates_without_listing(self):
        comment_id = self.adapter.upsert_comment(REPO, PR, 'marker', 'marker\nold')
        self.assertEqual(self.adapter.upsert_comment(REPO, PR, 'marker', 'marker\nnew',
                                                   comment_id=comment_id), comment_id)
        self.assertEqual([item['body'] for item in self.adapter.comments(REPO, PR)], ['marker\nnew'])

    def test_open_pulls_include_drafts_and_filter_the_base(self):
        self.assertEqual(self.adapter.open_pulls(REPO, 'mod/roadmap-integration'), [
            {'number': PR, 'head_ref': 'feature', 'head_sha': HEAD, 'draft': False},
            {'number': PR + 1, 'head_ref': 'wip', 'head_sha': OTHER, 'draft': True}])
        self.assertEqual(len(self.adapter.open_pulls(REPO)), len(OPEN_PULLS))
        self.assertEqual(self.adapter.open_pulls(REPO, 'missing'), [])

    def test_pull_metadata_is_port_shaped(self):
        found = self.adapter.pull(REPO, PR)
        self.assertEqual(found, {'number': PR, 'title': 'A change', 'body': 'Plan: 1',
                                'state': 'open', 'head_ref': 'feature', 'head_sha': HEAD,
                                'base_ref': 'mod/roadmap-integration', 'merge_sha': None, 'created_at': None, 'draft': False})

    def test_lock_lease_renewal_expiry_and_owner_release(self):
        self.assertTrue(self.adapter.lock(REPO, 'train', 'alice', '1', '3'))
        self.assertFalse(self.adapter.lock(REPO, 'train', 'bob', '2', '4'))
        self.adapter.unlock(REPO, 'train', 'bob')
        self.assertFalse(self.adapter.lock(REPO, 'train', 'bob', '2', '4'))
        self.assertTrue(self.adapter.lock(REPO, 'train', 'alice', '2', '5'))
        self.assertFalse(self.adapter.lock(REPO, 'train', 'bob', '3', '6'))
        self.assertTrue(self.adapter.lock(REPO, 'train', 'bob', '5', '7'))
        self.adapter.unlock(REPO, 'train', 'bob')
        self.assertTrue(self.adapter.lock(REPO, 'train', 'alice', '5', '8'))
        # TRAIN-TEMP-FIX R1: a run that died releases with its reason; the lock is free and the record keeps why.
        self.adapter.unlock(REPO, 'train', 'alice', died='ControlError: no events token')
        self.assertEqual(self.refs.read('train')[1],
                         {'owner': 'alice', 'expires': '', 'died': 'ControlError: no events token'})
        self.assertTrue(self.adapter.lock(REPO, 'train', 'bob', '6', '9'))
        self.assertEqual(self.refs.read('train')[1], {'owner': 'bob', 'expires': '9'}, 'a new holder drops the reason')

    def test_lock_reports_a_lost_conditional_advance(self):
        self.refs.lose = True
        self.assertFalse(self.adapter.lock(REPO, 'train', 'alice', '1', '3'))

    def test_calls_are_copied_from_the_clients_request_counter(self):
        before = self.adapter.calls()
        self.adapter.pull(REPO, PR)
        after = self.adapter.calls()
        self.assertEqual(after['sent'] - before['sent'], 1)
        self.assertEqual(after['not_modified'], before['not_modified'])
        after['sent'] = -1
        self.assertGreaterEqual(self.adapter.calls()['sent'], 1)

    def test_change_commits_preserve_parent_edges(self):
        self.assertEqual(self.adapter.change_commits(REPO, PR),
                         [{'sha': HEAD, 'parents': [BASE, OTHER], 'message': 'Head'},
                          {'sha': BASE, 'parents': [], 'message': 'Base'}])

    def test_change_files_preserve_names_across_pages(self):
        self.assertEqual(self.adapter.change_files(REPO, PR), [{'filename': 'a.py'}, {'filename': 'b.py'}])

    def test_commit_files_preserve_names(self):
        self.assertEqual(self.adapter.commit_files(REPO, HEAD), [{'filename': 'a.py'}])

    def test_compare_preserves_merge_base_and_distance(self):
        self.assertEqual(self.adapter.compare(REPO, 'topic/base', HEAD), {'merge_base': BASE, 'behind_by': len((BASE, HEAD))})

    def test_pull_merge_sha_requires_a_completed_merge(self):
        raw = dict(OPEN_PULLS[0], number=PR, merge_commit_sha=OTHER, mergeCommitSha=OTHER)
        target = mock.patch.object(self.adapter.client, 'pull', return_value=raw)
        with target:
            self.assertIsNone(self.adapter.pull(REPO, PR)['merge_sha'])
            raw['merged'] = True
            self.assertEqual(self.adapter.pull(REPO, PR)['merge_sha'], OTHER)

    def test_find_change_selects_latest_matching_head_including_closed(self):
        self.assertEqual(self.adapter.find_change(REPO, 'feature'), PR + len(OPEN_PULLS))
        self.assertIsNone(self.adapter.find_change(REPO, 'missing'))

    def test_open_then_close_change_preserves_requested_fields(self):
        number = self.adapter.open_change(REPO, 'new/topic', 'mod/roadmap-integration', 'New title', 'New body')
        self.assertIsInstance(number, int)
        self.assertEqual(self.adapter.find_change(REPO, 'new/topic'), number)
        self.assertEqual(self.forge.created[-1], {'number': number, 'head': 'new/topic',
                         'base': 'mod/roadmap-integration', 'title': 'New title', 'body': 'New body'})
        self.adapter.close_change(REPO, PR)
        self.assertEqual(self.adapter.pull(REPO, PR)['state'], 'closed')

    def test_identity_names_who_signs(self):
        self.assertTrue(self.adapter.identity())

    def test_append_then_read_keeps_the_order(self):
        channel = forge_events.Channel(REPO, None)
        self.adapter.append(channel, [{'event_id': 'one', 'type': 'pr.ready', 'payload': {}}])
        self.adapter.append(channel, [{'event_id': 'two', 'type': 'pr.ready', 'payload': {}}])
        self.assertEqual([event['event_id'] for event in self.adapter.read(channel)], ['one', 'two'])

    def test_set_status_publishes_the_verdict_on_the_head(self):
        self.adapter.set_status(REPO, HEAD, 'tower/gate', 'success', 'gate passed')
        self.assertEqual(self.forge.statuses[HEAD], [('tower/gate', 'success')])

    def test_merge_takes_the_judged_head_and_names_the_merge_commit(self):
        merged = self.adapter.merge(REPO, self.forge.pr, HEAD)
        self.assertTrue(merged)
        self.assertEqual(self.forge.merged, [(self.forge.pr, HEAD)])

    # The train's queue asks these two beyond the six (D-069 item 7): which changes exist for a base, and
    # who approved one.

    def test_open_changes_are_the_undrafted_changes_of_that_base(self):
        self.assertEqual(self.adapter.open_changes(REPO, 'mod/roadmap-integration'), [self.forge.pr])

    def test_approvals_are_the_identities_whose_latest_review_approves(self):
        self.assertEqual(self.adapter.approvals(REPO, self.forge.pr), ['alice'])

    def test_merge_refuses_a_head_that_is_not_the_judged_one(self):
        with self.assertRaises(RuntimeError):
            self.adapter.merge(REPO, self.forge.pr, OTHER)
        self.assertEqual(self.forge.merged, [])






class OriginForge:
    pr = PR

    def __init__(self, log):
        self.log, self.merged, self.check_runs = log, [], []
        self.comment_records = []
        self.requests = []
        self.created, self.closed = [], False
        self.client = forge_origin_client.OriginClient(run=self.rest)

    def __getattr__(self, name):
        return getattr(self.client, name)

    def rest(self, method, path, body=None):
        self.requests.append(path)
        route = path.partition('?')[0]
        if method == 'GET' and route == f'/repos/{REPO}/pulls/{PR}':
            return dict(OPEN_PULLS[0], number=str(PR), title='A change', body='Plan: 1', state='closed' if self.closed else 'open')
        if method == 'PATCH' and route == f'/repos/{REPO}/pulls/{PR}':
            self.closed = body['state'] == 'closed'
            return {}
        if method == 'POST' and route == f'/repos/{REPO}/pulls':
            number = PR + len(OPEN_PULLS) + len(self.created) + 1
            self.created.append(dict(body, number=number))
            return {'number': str(number)}
        if method == 'GET' and '/compare/' in route:
            assert 'topic%2Fbase...' in route, route
            return {'mergeBaseCommit': {'sha': BASE}, 'behindBy': len((BASE, HEAD))}
        if method == 'GET' and route == f'/repos/{REPO}/commits/{HEAD}/files':
            return {'files': [{'filename': 'a.py'}]}
        if method == 'GET' and route == f'/repos/{REPO}/pulls/{PR}/files':
            if 'pageToken=' in path:
                return {'files': [{'filename': 'b.py'}]}
            return {'files': [{'filename': 'a.py'}], 'nextPageToken': 'second'}
        if method == 'GET' and route == f'/repos/{REPO}/pulls/{PR}/commits':
            if 'pageToken=' in path:
                return {'commits': [{'sha': BASE, 'commit': {'message': 'Base'}}]}
            return {'commits': [{'sha': HEAD, 'parents': [{'sha': BASE}, {'sha': OTHER}], 'commit': {'message': 'Head'}}],
                    'nextPageToken': 'second'}
        if method == 'GET' and route == f'/repos/{REPO}/pulls':
            # Deliberately ignore base like the live route. A second page carries a draft.
            from urllib.parse import parse_qs
            params = parse_qs(path.partition('?')[-1])
            if params.get('state') == ['closed']:
                from datetime import datetime
                items = [dict(item, number=str(item['number'])) for item in self.history
                         if item['state'] == 'closed']
                if params.get('mergedSince'):
                    lower = datetime.fromisoformat(params['mergedSince'][0].replace('Z', '+00:00'))
                    items = [item for item in items if item.get('mergedAt') and
                             datetime.fromisoformat(item['mergedAt'].replace('Z', '+00:00')) >= lower]
                # One item per page exercises opaque cursor forwarding and filter retention.
                offset = int(params.get('pageToken', ['0'])[0])
                result = {'pullRequests': items[offset:offset + 1]}
                if offset + 1 < len(items):
                    result['nextPageToken'] = str(offset + 1)
                return result
            if params.get('state') == ['all']:
                closed = dict(OPEN_PULLS[0], number=str(PR + len(OPEN_PULLS)), state='closed')
                created = [dict(item, number=str(item['number']), head={'ref': item['head']})
                           for item in self.created]
                return {'pullRequests': [dict(OPEN_PULLS[0], number=str(PR)), closed] + created}
            if params.get('pageToken'):
                return {'pullRequests': [dict(item, number=str(item['number'])) for item in OPEN_PULLS[1:]]}
            return {'pullRequests': [dict(OPEN_PULLS[0], number=str(PR))], 'nextPageToken': 'next/page+cursor='}
        if route == f'/repos/{REPO}/pulls/{PR}/comments':
            if method == 'GET':
                return {'comments': [dict(item) for item in self.comment_records]}
            if method == 'POST':
                item = {'id': f'cmt_{len(self.comment_records)}', 'body': body['body']}
                self.comment_records.append(item)
                return dict(item)
        if method == 'PATCH' and route.startswith(f'/repos/{REPO}/pulls/comments/'):
            item = next((item for item in self.comment_records if item['id'] == route.rsplit('/', 1)[1]), None)
            if item is None:
                raise forge_origin_client.OriginClientError('missing comment', status=HTTPStatus.NOT_FOUND)
            item['body'] = body['body']
            return dict(item)
        raise AssertionError(f'unexpected {method} {path}')

    def identity(self):
        return 'origin-bot'

    def change(self, repo, number):
        if (repo, number) != (REPO, self.pr):
            raise RuntimeError('unknown change')
        return {'head': HEAD, 'base': BASE, 'head_ref': 'feature',
                'base_ref': 'mod/roadmap-integration', 'head_repo': REPO,
                'body': 'Plan: 1', 'open': True}

    def url(self):
        return f'https://{ORIGIN_HOST}/{REPO}.git'

    def publish_check_run(self, repo, sha, context, state, description, url=None):
        self.check_runs.append({'repo': repo, 'sha': sha, 'context': context, 'state': state,
                                'description': description, 'url': url})

    def open_changes(self, repo, base):
        if repo != REPO:
            raise RuntimeError('unknown change')
        return [self.pr]

    def reviews(self, repo, number):
        if (repo, number) != (REPO, self.pr):
            raise RuntimeError('unknown change')
        # Origin's own spelling: `verdict` is approve/request_changes/comment, and `comment` decides nothing.
        return [{'verdict': 'approve', 'author': {'user': {'handle': 'alice'}}},
                {'verdict': 'approve', 'author': {'user': {'handle': 'bob'}}},
                {'verdict': 'request_changes', 'author': {'user': {'handle': 'bob'}}},
                {'verdict': 'comment', 'author': {'user': {'handle': 'carol'}}}]

    def merge(self, base, head, sha, message):
        if (base, head, sha) != ('mod/roadmap-integration', 'feature', HEAD):
            raise RuntimeError('wrong merge input')
        self.merged.append((self.pr, sha))
        return 'd' * 40

    @property
    def statuses(self):
        statuses = {}
        for record in self.log.read(forge_origin.OriginAdapter.status_channel(REPO)):
            item = record['payload']
            statuses.setdefault(item['sha'], []).append((item['context'], item['state']))
        return statuses


def declare_git_hosts(case, hosts):
    """Declare origin-client.git_hosts for one test: the Origin adapter refuses a git remote on any other host."""
    real = config.get
    patcher = mock.patch.object(config, 'get', lambda key, *args: list(hosts) if key == 'origin-client.git_hosts'
                                else real(key, *args))
    patcher.start()
    case.addCleanup(patcher.stop)


class OriginContract(ForgeContract, unittest.TestCase):
    def setUp(self):
        log = forge_events.MemoryAdapter()  # D-300: the journal is the git-ref log; the contract needs only its log
        self.forge = OriginForge(log)
        declare_git_hosts(self, [ORIGIN_HOST])
        self.adapter = forge_origin.OriginAdapter(self.forge, REPO, log=log, refs=self.forge)
        self.refs = RefStore()
        self.forge.read = self.refs.read
        self.forge.advance = self.refs.advance

    def test_merged_since_is_sent_to_origin_on_every_cursor_page(self):
        from urllib.parse import parse_qs
        self.forge.history = HISTORY
        self.adapter.closed_changes(REPO, MERGE_OLD)
        queries = [parse_qs(path.partition('?')[-1]) for path in self.forge.requests]
        self.assertGreater(len(queries), 1)
        self.assertTrue(all(query['state'] == ['closed'] and query['mergedSince'] == [MERGE_OLD]
                            for query in queries))

    def test_missing_commit_message_is_a_named_capability_refusal(self):
        import operation_demands
        with mock.patch.object(self.forge.client, '_pages', return_value=[{'sha': HEAD}]):
            with self.assertRaisesRegex(operation_demands.CompatibilityError, 'change_commits, adapter origin'):
                self.adapter.change_commits(REPO, PR)

    def test_comment_timeout_reaches_cli_without_mutating_client_defaults(self):
        client = forge_origin_client.OriginClient(binary='origin')
        self.adapter.client = client
        original = client.conf['timeout_s']
        with mock.patch.object(forge_origin_client, '_run_cli', return_value={'id': 'stored'}) as run:
            self.adapter.upsert_comment(REPO, PR, 'marker', 'marker', comment_id='stored', timeout=original + 1)
        self.assertEqual(run.call_args.args[-1]['timeout_s'], original + 1)
        self.assertEqual(client.conf['timeout_s'], original)

    def test_lock_and_unlock_refuse_another_repository(self):
        with self.assertRaisesRegex(RuntimeError, 'another repository'):
            self.adapter.lock('other/repo', 'train', 'alice', '1', '3')
        with self.assertRaisesRegex(RuntimeError, 'another repository'):
            self.adapter.unlock('other/repo', 'train', 'alice')
        self.assertEqual(self.refs.records, {})

    def test_coverage_is_measured_from_port_dispatches_and_class_members(self):
        # No gap remains: every operation the port dispatches is a member of the origin adapter. The push history
        # behaviour (answers, refusals with their reasons) is in test_origin_history.py, where its proofs point.
        import inspect
        names = set(re.findall(r"_operation\('([^']+)'\)", inspect.getsource(forge_events.ForgeEvents))) | {'change'}
        self.assertEqual(names - set(dir(type(self.adapter))), set())

    def test_calls_counts_a_failed_transport_and_refuses_a_client_without_counters(self):
        before = self.adapter.calls()['sent']
        with mock.patch.object(self.forge.client, '_run', side_effect=OSError('unavailable')):
            with self.assertRaises(forge_origin_client.OriginClientError):
                self.adapter.pull(REPO, PR)
        self.assertEqual(self.adapter.calls()['sent'], before + 1)
        self.adapter.client = object()
        with self.assertRaisesRegex(RuntimeError, 'has no calls operation.*counter'):
            self.adapter.calls()

    def test_upsert_only_recreates_a_missing_comment(self):
        for status in (HTTPStatus.FORBIDDEN, HTTPStatus.TOO_MANY_REQUESTS, HTTPStatus.INTERNAL_SERVER_ERROR, None):
            with self.subTest(status=status):
                error = forge_origin_client.OriginClientError('refused', status=status)
                with mock.patch.object(self.forge.client, 'edit_comment', side_effect=error):
                    with self.assertRaises(forge_origin_client.OriginClientError):
                        self.adapter.upsert_comment(REPO, PR, 'marker', 'marker', comment_id='gone')
                self.assertEqual(self.forge.comment_records, [])
        self.adapter.upsert_comment(REPO, PR, 'marker', 'marker', comment_id='gone')
        self.assertEqual([item['body'] for item in self.forge.comment_records], ['marker'])

    def test_status_retains_details_and_does_not_pollute_events(self):
        self.adapter.set_status(REPO, HEAD, 'gate', 'pending', 'running', 'https://logs.test/1')
        self.adapter.set_status(REPO, HEAD, 'gate', 'success', 'passed')
        records = self.adapter.read(self.adapter.status_channel(REPO))
        self.assertEqual([r['payload']['state'] for r in records], ['pending', 'success'])
        self.assertEqual(records[0]['payload']['url'], 'https://logs.test/1')
        self.assertEqual(records[0]['payload']['description'], 'running')
        self.assertEqual(records[0]['payload']['identity'], 'origin-bot')
        self.assertEqual(self.adapter.read(forge_events.Channel(REPO, None)), [])
        self.assertEqual([(item['context'], item['state']) for item in self.forge.check_runs],
                         [('gate', 'pending'), ('gate', 'success')])

    def test_merge_refuses_another_repository(self):
        with self.assertRaisesRegex(RuntimeError, 'another repository'):
            self.adapter.merge('other/repo', 1, HEAD)
        self.assertEqual(self.forge.merged, [])

    def test_merge_refuses_frozen_production(self):
        change = self.forge.change(REPO, 1)
        change['base_ref'] = 'main'
        change['head_ref'] = 'mod/roadmap-integration'
        with mock.patch.object(self.forge, 'change', return_value=change):
            with self.assertRaisesRegex(RuntimeError, 'frozen'):
                self.adapter.merge(REPO, 1, HEAD)
        self.assertEqual(self.forge.merged, [])

    def test_merge_reports_a_lost_push(self):
        with mock.patch.object(self.forge, 'merge', return_value=None):
            with self.assertRaisesRegex(RuntimeError, 'lost the race'):
                self.adapter.merge(REPO, 1, HEAD)

    def test_identity_refuses_an_empty_signer(self):
        with mock.patch.object(self.forge, 'identity', return_value=''):
            with self.assertRaisesRegex(RuntimeError, 'no identity'):
                self.adapter.identity()



class ClosedChangesRefusal(unittest.TestCase):
    def test_missing_operation_names_operation_and_adapter(self):
        import forge_requirements
        import operation_demands
        import forge_git_ref
        classes = (forge_events.FileAdapter, forge_events.MemoryAdapter,
                   forge_git_ref.GitRefAdapter)
        for cls in classes:
            adapter = cls.__new__(cls)
            name = operation_demands.adapter_name(adapter)
            with self.subTest(adapter=name):
                port = forge_events.ForgeEvents(adapter, forge_events.SystemClock(), 'test', 'refusal')
                with self.assertRaisesRegex(forge_events.ForgeEventsError,
                                            f'operation closed_changes, adapter {name}'):
                    port.closed_changes(REPO)
        adapter = type('UnknownAdapter', (), {})()
        with self.assertRaisesRegex(operation_demands.CompatibilityError,
                                    'adapter UnknownAdapter has no closed_changes operation'):
            forge_requirements.require_surface(adapter, {'closed_changes'}, 'historical read')



if __name__ == '__main__':
    unittest.main()
