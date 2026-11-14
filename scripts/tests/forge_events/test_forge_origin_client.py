"""FORGE-PORT (CANALE8): the real Origin client, with the transport doubled (no network).

The Origin JSON comes from the shapes in the official OpenAPI 3.1 spec's own examples, kept as
data in fixtures/origin.json and read here rather than spelled (LT1). Every case drives
`OriginClient` through its injected `run`, so what is under test is the mapping into the adapter's
port shape, the cursor pagination, the expectedHeadSha guard and the error mapping -- not the
`origin` CLI, which a separately skipped live case exercises against the real API.
"""
import json
from pathlib import Path
import sys
import unittest
import unittest.mock
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))

import config  # noqa: E402
import forge_origin  # noqa: E402
import forge_origin_client as client  # noqa: E402
import literal_census  # noqa: E402

FIXTURE = json.loads((Path(__file__).resolve().parent / 'fixtures' / 'origin.json').read_text())
REPO, OTHER = FIXTURE['repo'], FIXTURE['other_repo']
NUMBER = FIXTURE['number']
HEAD, BASE, MERGE, MOVED = FIXTURE['head'], FIXTURE['base'], FIXTURE['merge'], FIXTURE['moved_head']
PULL, NAMESPACES = FIXTURE['pull'], FIXTURE['namespaces']
OPEN_PULLS, REVIEWS = FIXTURE['open_pulls'], FIXTURE['reviews_latest_wins']
PULLS_PATH, REVIEWS_PATH = f'/repos/{REPO}/pulls', f'/repos/{REPO}/pulls/{NUMBER}/reviews'
CONF = client.settings(ROOT)
STATUS = {item['kind']: int(item['status']) for item in CONF['statuses']}
ORIGIN_HOST = urlsplit(FIXTURE['refs_url']).hostname
REMOTES = FIXTURE['git_remotes']
PULL_PATH = f'/repos/{REPO}/pulls/{NUMBER}'


class FakeTransport:
    """Answers like the API: one handler per (METHOD, path-without-query), a list to walk for pages."""

    def __init__(self):
        self.calls, self.routes = [], {}

    def body(self):
        """The body of the one call made, which is what the wire test asserts on."""
        return self.calls[0][-1]

    def route(self, method, path, answer):
        self.routes[(method, path)] = answer

    def __call__(self, method, path, body=None):
        self.calls.append((method, path, body))
        base, _, query = path.partition('?')
        answer = self.routes.get((method, base))
        if answer is None:
            raise client.OriginClientError(
                f'origin: exit {STATUS["not-found"]} (not-found); Origin API request failed',
                status=STATUS['not-found'])
        if callable(answer):
            return answer(dict(item.split('=', 1) for item in query.split('&') if item))
        return answer


class ShapeCase(unittest.TestCase):
    def test_the_change_is_the_adapter_port_shape(self):
        self.assertEqual(client.shape_change(PULL, REPO), {
            'head': HEAD, 'base': BASE, 'head_ref': PULL['head']['ref'],
            'base_ref': PULL['base']['ref'], 'head_repo': REPO,
            'body': PULL['body'], 'open': True})

    def test_head_repo_is_the_read_repository_because_origin_has_no_forks(self):
        # PullRequestRef carries only ref and sha, and CreatePullRequestRequest takes branch names
        # that must resolve in the repo: a change never comes from another repository.
        self.assertEqual(client.shape_change(PULL, REPO)['head_repo'], REPO)
        self.assertNotEqual(REPO, OTHER)

    def test_a_merged_change_is_closed(self):
        merged = dict(PULL, state='closed', merged=True, mergeCommitSha=MERGE)
        self.assertFalse(client.shape_change(merged, REPO)['open'])

    def test_a_closed_change_is_not_open(self):
        self.assertFalse(client.shape_change(dict(PULL, state='closed'), REPO)['open'])

    def test_a_draft_is_open(self):
        self.assertTrue(client.shape_change(dict(PULL, draft=True), REPO)['open'])

    def test_a_missing_body_is_empty_not_null(self):
        without = {name: value for name, value in PULL.items() if name != 'body'}
        self.assertEqual(client.shape_change(without, REPO)['body'], '')

    def test_the_port_shape_is_exactly_the_seven_fields_the_adapter_reads(self):
        self.assertEqual(set(client.shape_change(PULL, REPO)),
                         {'head', 'base', 'head_ref', 'base_ref', 'head_repo', 'body', 'open'})


class ChangeCase(unittest.TestCase):
    def setUp(self):
        self.transport = FakeTransport()
        self.transport.route('GET', PULL_PATH, PULL)
        self.client = client.OriginClient(run=self.transport)

    def test_change_reads_the_pull_request_path(self):
        self.assertEqual(self.client.change(REPO, NUMBER)['head'], HEAD)
        self.assertEqual(self.transport.calls, [('GET', PULL_PATH, None)])

    def test_a_number_is_taken_as_the_path_segment_the_spec_types_as_a_string(self):
        self.client.change(REPO, int(NUMBER))
        self.assertEqual(self.transport.calls[0][1], PULL_PATH)

    def test_a_repository_without_an_owner_is_refused_before_any_call(self):
        for bad in ('the-tower', '/the-tower', 'o/r/s', 'o/../r'):
            with self.subTest(repo=bad):
                with self.assertRaises(client.OriginClientError):
                    self.client.change(bad, NUMBER)
        self.assertEqual(self.transport.calls, [])


class OpenChangesCase(unittest.TestCase):
    """The train's queue read: numbers of the open, non-draft changes that target one base."""

    def setUp(self):
        self.transport = FakeTransport()
        self.client = client.OriginClient(run=self.transport)

    def test_a_draft_is_never_a_queue_entry(self):
        self.transport.route('GET', PULLS_PATH, OPEN_PULLS)
        numbers = self.client.open_changes(REPO, PULL['base']['ref'])
        self.assertEqual(numbers, [int(PULL['number'])])
        self.assertNotIn(int(FIXTURE['pull_draft']['number']), numbers)

    def test_only_the_changes_that_target_the_named_base_are_returned(self):
        self.transport.route('GET', PULLS_PATH, OPEN_PULLS)
        self.assertEqual(self.client.open_changes(REPO, 'main'), [int(FIXTURE['pull_other_base']['number'])])

    def test_the_api_is_asked_for_the_open_ones_because_that_filter_holds(self):
        # Measured: `state` filters on the live route, `base` does not, so `base` is applied here.
        self.transport.route('GET', PULLS_PATH, FIXTURE['open_pulls_other_base'])
        self.client.open_changes(REPO, PULL['base']['ref'])
        self.assertIn('state=open', self.transport.calls[0][1])
        self.assertNotIn('base=', self.transport.calls[0][1])

    def test_a_number_comes_back_as_an_int_not_the_string_the_api_types(self):
        self.assertIsInstance(PULL['number'], str)
        self.transport.route('GET', PULLS_PATH, OPEN_PULLS)
        self.assertEqual([type(number) for number in self.client.open_changes(REPO, PULL['base']['ref'])], [int])

    def test_a_base_that_matches_nothing_is_an_empty_queue_not_a_refusal(self):
        self.transport.route('GET', PULLS_PATH, OPEN_PULLS)
        self.assertEqual(self.client.open_changes(REPO, 'no-such-branch'), [])

    def test_the_read_follows_every_page_before_it_filters(self):
        self.transport.route('GET', PULLS_PATH, FakeTransport_page(FIXTURE['open_pulls_other_base'], OPEN_PULLS))
        self.assertEqual(self.client.open_changes(REPO, PULL['base']['ref']), [int(PULL['number'])])
        self.assertEqual(len(self.transport.calls), FIXTURE['pages'])


def FakeTransport_page(first, second):
    """A list route whose first page still paginates, so a filter applied per page would miss the second."""
    first = dict(first, nextPageToken='p2')
    return lambda query: second if 'pageToken' in query else first


class ReviewsCase(unittest.TestCase):
    def setUp(self):
        self.transport = FakeTransport()
        self.client = client.OriginClient(run=self.transport)

    def test_the_reviews_come_back_raw_and_paged(self):
        self.transport.route('GET', REVIEWS_PATH, REVIEWS)
        found = self.client.reviews(REPO, NUMBER)
        self.assertEqual(found, REVIEWS['reviews'])
        self.assertEqual(self.transport.calls[0][0], 'GET')

    def test_a_review_page_that_never_ends_raises_rather_than_reading_short(self):
        self.transport.route('GET', REVIEWS_PATH, lambda query: dict(REVIEWS, nextPageToken='more'))
        with self.assertRaisesRegex(client.OriginClientError, 'truncated'):
            self.client.reviews(REPO, NUMBER)


class IdentityCase(unittest.TestCase):
    def setUp(self):
        self.transport = FakeTransport()
        self.client = client.OriginClient(run=self.transport)

    def test_the_user_namespace_is_the_identity(self):
        self.transport.route('GET', '/namespaces', NAMESPACES)
        self.assertEqual(self.client.identity(), 'openuniversity-si')

    def test_a_team_namespace_is_never_the_identity(self):
        self.transport.route('GET', '/namespaces', FIXTURE['teams_only'])
        with self.assertRaises(client.OriginIdentityGap):
            self.client.identity()

    def test_the_gap_is_named_not_invented(self):
        self.transport.route('GET', '/namespaces', FIXTURE['none'])
        with self.assertRaisesRegex(client.OriginIdentityGap, 'no user identity'):
            self.client.identity()

    def test_two_user_namespaces_are_ambiguous_and_refused(self):
        self.transport.route('GET', '/namespaces', FIXTURE['two_users'])
        with self.assertRaises(client.OriginIdentityGap):
            self.client.identity()

    def test_identity_is_a_non_empty_string_the_adapter_accepts(self):
        self.transport.route('GET', '/namespaces', NAMESPACES)
        self.assertTrue(self.client.identity().strip())


class PaginationCase(unittest.TestCase):
    def setUp(self):
        self.transport = FakeTransport()
        self.client = client.OriginClient(run=self.transport, conf=dict(CONF, page_size=FIXTURE['page']['size'], max_pages=FIXTURE['page']['max']))

    def test_the_cursor_walks_every_page_in_order(self):
        self.transport.route('GET', f'{PULL_PATH}/comments', self.pages(FIXTURE['comment_pages']))
        self.assertEqual([item['id'] for item in self.client.comments(REPO, NUMBER)],
                         ['one', 'two', 'three', 'four', 'five'])
        self.assertEqual(len(self.transport.calls), len(FIXTURE['comment_pages']))
        self.assertTrue(self.transport.calls[0][1].endswith('pageSize=2'))
        self.assertIn('pageToken=p2', self.transport.calls[1][1])

    @staticmethod
    def pages(batches):
        return lambda query: batches[0] if 'pageToken' not in query else \
            batches[int(query['pageToken'][1:]) - 1]

    def test_a_truncated_list_raises_instead_of_coming_back_short(self):
        self.transport.route('GET', f'{PULL_PATH}/comments', lambda query: FIXTURE['always_more'])
        with self.assertRaisesRegex(client.OriginClientError, 'truncated'):
            self.client.comments(REPO, NUMBER)
        self.assertEqual(len(self.transport.calls), FIXTURE['page']['max'])

    def test_the_last_page_is_the_one_whose_token_is_empty(self):
        self.transport.route('GET', f'{PULL_PATH}/comments', FIXTURE['one_comment'])
        self.assertEqual(self.client.comments(REPO, NUMBER), FIXTURE['one_comment']['comments'])
        self.assertEqual(len(self.transport.calls), 1)


class CommentCase(unittest.TestCase):
    def setUp(self):
        self.transport = FakeTransport()
        self.client = client.OriginClient(run=self.transport)

    def test_a_comment_is_a_general_discussion_post(self):
        self.transport.route('POST', f'{PULL_PATH}/comments', FIXTURE['comment'])
        found = self.client.append_comment(REPO, NUMBER, 'hello')
        self.assertEqual(found['id'], FIXTURE['comment']['id'])
        method, path, body = self.transport.calls[0]
        self.assertEqual((method, path), ('POST', f'{PULL_PATH}/comments'))
        self.assertEqual(body, {'body': 'hello'})  # no anchor: a general-discussion thread

    def test_an_empty_comment_is_refused_before_any_call(self):
        for bad in ('', '   ', None):
            with self.subTest(body=bad):
                with self.assertRaises(client.OriginClientError):
                    self.client.append_comment(REPO, NUMBER, bad)
        self.assertEqual(self.transport.calls, [])


class MergeCase(unittest.TestCase):
    def setUp(self):
        self.transport = FakeTransport()
        self.client = client.OriginClient(run=self.transport)
        self.transport.route('POST', f'{PULL_PATH}/merge',
                             dict(FIXTURE['merged'], pullRequest=dict(PULL, state='closed', merged=True)))
        self.method = sorted(CONF['merge_methods'])[0]

    def test_the_judged_head_is_the_expected_head_sha_guard(self):
        found = self.client.merge(REPO, NUMBER, HEAD, method=self.method)
        self.assertEqual(found['mergeCommitSha'], MERGE)
        self.assertEqual(self.transport.body(),
                         {'expectedHeadSha': HEAD, 'mergeMethod': self.method})

    def test_the_method_is_omitted_when_not_named(self):
        self.client.merge(REPO, NUMBER, HEAD)
        self.assertEqual(self.transport.body(), {'expectedHeadSha': HEAD})

    def test_an_abbreviated_sha_is_refused_before_any_call(self):
        with self.assertRaises(client.OriginClientError):
            self.client.merge(REPO, NUMBER, HEAD[:FIXTURE['abbreviated_sha_chars']])
        self.assertEqual(self.transport.calls, [])

    def test_an_unknown_merge_method_is_refused_before_any_call(self):
        with self.assertRaises(client.OriginClientError):
            self.client.merge(REPO, NUMBER, HEAD, method='rebase')
        self.assertEqual(self.transport.calls, [])

    def test_a_moved_head_is_a_conflict_with_the_api_status(self):
        def refused(method, path, body=None):
            raise client.OriginClientError(
                'origin: exit 409 (conflict); Origin API request failed: expected head ...',
                status=STATUS['conflict'])
        self.client._run = refused
        with self.assertRaises(client.OriginClientError) as caught:
            self.client.merge(REPO, NUMBER, HEAD)
        self.assertEqual(caught.exception.status, STATUS['conflict'])


class ErrorMappingCase(unittest.TestCase):
    """The CLI's error contract, doubled: an error envelope on stderr, `Error: ... HTTP <code>` last."""

    def run_cli_error(self, status, envelope):
        done = client.subprocess.CompletedProcess
        with unittest.mock.patch.object(client.subprocess, 'run') as run:
            run.return_value = done(args=[], returncode=1, stdout='',
                                    stderr=f'{envelope}\nError: origin api: HTTP {status} X\n')
            with self.assertRaises(client.OriginClientError) as caught:
                client._run_cli('GET', '/rate_limit', None, 'origin', CONF)
        return caught.exception

    def test_each_status_maps_to_its_registered_kind(self):
        for kind, status in STATUS.items():
            with self.subTest(kind=kind):
                error = self.run_cli_error(status, '{"code":5,"message":"no"}')
                self.assertEqual(error.status, status)
                self.assertIn(kind, str(error))

    def test_an_unregistered_status_is_plain_http(self):
        self.assertIn('(http)', str(self.run_cli_error(FIXTURE['unregistered_status'], FIXTURE['unregistered_body'])))

    def test_the_api_message_is_kept_because_it_is_the_actionable_sentence(self):
        error = self.run_cli_error(STATUS['not-found'], '{"code":5,"message":"Origin pull request not found"}')
        self.assertIn('Origin pull request not found', str(error))

    def test_the_envelope_is_not_pasted_whole_into_the_error(self):
        envelope = '{"code":5,"message":"no","details":[{"requestId":"abc"}]}'
        self.assertNotIn('requestId', str(self.run_cli_error(STATUS['not-found'], envelope)))

    def test_a_credential_shaped_string_is_redacted(self):
        error = self.run_cli_error(STATUS['auth'], '{"code":16,"message":"bad token crsr_abc123DEF"}')
        self.assertNotIn('crsr_abc123DEF', str(error))
        self.assertIn('<redacted>', str(error))

    def test_a_transport_that_cannot_read_a_body_withholds_it(self):
        with unittest.mock.patch.object(client.subprocess, 'run') as run:
            run.return_value = client.subprocess.CompletedProcess(
                args=[], returncode=1, stdout='', stderr='Traceback: something crsr_secret_here')
            with self.assertRaises(client.OriginClientError) as caught:
                client._run_cli('GET', '/rate_limit', None, 'origin', CONF)
        self.assertNotIn('crsr_secret_here', str(caught.exception))

    def test_a_missing_cli_names_the_variable_not_the_key(self):
        with unittest.mock.patch.object(client.subprocess, 'run', side_effect=FileNotFoundError):
            with self.assertRaisesRegex(client.OriginClientError, CONF['cli_env']):
                client._run_cli('GET', '/rate_limit', None, 'origin', CONF)

    def test_a_timeout_is_an_error_not_a_hang(self):
        with unittest.mock.patch.object(client.subprocess, 'run',
                                        side_effect=client.subprocess.TimeoutExpired('origin', 1)):
            with self.assertRaisesRegex(client.OriginClientError, 'timeout'):
                client._run_cli('GET', '/rate_limit', None, 'origin', CONF)

    def test_a_body_travels_on_stdin_never_in_argv(self):
        with unittest.mock.patch.object(client.subprocess, 'run') as run:
            run.return_value = client.subprocess.CompletedProcess(
                args=[], returncode=0, stdout='{"id":"cmt_1"}', stderr='')
            client._run_cli('POST', f'{PULL_PATH}/comments', {'body': 'a'}, 'origin', CONF)
        argv, kwargs = run.call_args[0][0], run.call_args[1]
        self.assertEqual(kwargs['input'], '{"body": "a"}')
        self.assertIn('--input', argv)
        self.assertNotIn('a', argv)
        for item in argv:
            self.assertNotIn('crsr_', item)


class SettingsCase(unittest.TestCase):
    """Every tunable is a registry entry of owner origin-client (D-068), and the module spells none (LT1)."""

    MODULE = ROOT / 'scripts' / 'lib' / 'forge_origin_client.py'

    def test_every_setting_the_module_reads_is_a_registered_key_of_its_owner(self):
        registry = json.loads((ROOT / 'config' / 'registry' / 'origin-client.json').read_text())
        for key in client.SETTINGS:
            with self.subTest(key=key):
                self.assertIn(f'origin-client.{key}', registry['properties'])
                self.assertIn('scripts/lib/forge_origin_client.py',
                              registry['properties'][f'origin-client.{key}']['x-readers'])

    def test_the_module_has_no_unregistered_literal(self):
        # The repository's own rule (LT1), not a hand-rolled approximation: prose stays prose.
        found = literal_census.python_literals(self.MODULE.read_text(), literal_census.Census(ROOT))
        self.assertEqual(found, [])

    def test_the_status_map_is_the_one_the_spec_documents(self):
        self.assertEqual({item['kind']: int(item['status']) for item in CONF['statuses']}, STATUS)
        self.assertEqual(len(STATUS), len(CONF['statuses']))


def declare_git_hosts(case, hosts):
    """Declare origin-client.git_hosts for one test: the adapter refuses a git remote on any other host."""
    real = config.get
    patcher = unittest.mock.patch.object(
        config, 'get', lambda key, *args: list(hosts) if key == 'origin-client.git_hosts' else real(key, *args))
    patcher.start()
    case.addCleanup(patcher.stop)


class AdapterCase(unittest.TestCase):
    """The client inside the real adapter, with git and the control plane out of the way."""

    def setUp(self):
        self.transport = FakeTransport()
        self.transport.route('GET', PULL_PATH, PULL)
        self.transport.route('GET', '/namespaces', NAMESPACES)
        self.client = client.OriginClient(run=self.transport)
        self.refs = unittest.mock.Mock()
        self.refs.url.return_value = FIXTURE['refs_url']
        self.refs.merge.return_value = MERGE
        self.log = unittest.mock.Mock()
        declare_git_hosts(self, [ORIGIN_HOST])

    def make(self):
        return forge_origin.OriginAdapter(self.client, REPO, log=self.log, refs=self.refs)

    def test_the_adapter_reads_the_change_and_the_identity_through_the_client(self):
        adapter = self.make()
        self.assertEqual(adapter.change(REPO, NUMBER)['head'], HEAD)
        self.assertEqual(adapter.identity(), 'openuniversity-si')

    def test_the_adapter_merges_the_judged_head_and_names_the_merge_commit(self):
        self.assertEqual(self.make().merge(REPO, NUMBER, HEAD), MERGE)
        self.refs.merge.assert_called_once()

    def test_the_adapter_refuses_a_head_that_moved(self):
        with self.assertRaises(forge_origin.OriginAdapterError):
            self.make().merge(REPO, NUMBER, MOVED)
        self.refs.merge.assert_not_called()

    def test_approvals_are_each_reviewers_latest_verdict(self):
        # bob approved and then asked for changes; carol only commented. Only alice still approves.
        self.transport.route('GET', REVIEWS_PATH, REVIEWS)
        self.assertEqual(self.make().approvals(REPO, NUMBER), ['alice'])

    def test_a_later_request_for_changes_clears_the_approval(self):
        self.transport.route('GET', REVIEWS_PATH, REVIEWS)
        self.assertNotIn('bob', self.make().approvals(REPO, NUMBER))

    def test_a_comment_never_decides_a_reviewers_standing(self):
        self.assertEqual(REVIEWS['reviews'][-1]['verdict'], 'comment')
        self.transport.route('GET', REVIEWS_PATH, REVIEWS)
        self.assertNotIn('carol', self.make().approvals(REPO, NUMBER))

    def test_a_dismissed_review_does_not_count(self):
        self.transport.route('GET', REVIEWS_PATH, FIXTURE['reviews_with_a_dismissal'])
        self.assertEqual(self.make().approvals(REPO, NUMBER), ['bob'])

    def test_the_identity_is_the_handle_and_falls_back_to_the_id(self):
        # A handle is published only for a visible profile; an app has none, so its id names it.
        self.transport.route('GET', REVIEWS_PATH, FIXTURE['reviews_handle_hidden'])
        user, app = (item['author'] for item in FIXTURE['reviews_handle_hidden']['reviews'])
        self.assertEqual(self.make().approvals(REPO, NUMBER), sorted([user['user']['id'], app['app']['id']]))

    def test_no_reviews_is_no_approvals(self):
        self.transport.route('GET', REVIEWS_PATH, FIXTURE['reviews_empty'])
        self.assertEqual(self.make().approvals(REPO, NUMBER), [])

    def test_approvals_refuse_another_repository(self):
        with self.assertRaisesRegex(forge_origin.OriginAdapterError, 'another repository'):
            self.make().approvals('other/repo', NUMBER)

    def test_open_changes_refuse_another_repository(self):
        with self.assertRaisesRegex(forge_origin.OriginAdapterError, 'another repository'):
            self.make().open_changes('other/repo', PULL['base']['ref'])

    def test_the_adapter_reads_the_open_changes_through_the_client(self):
        self.transport.route('GET', PULLS_PATH, OPEN_PULLS)
        self.assertEqual(self.make().open_changes(REPO, PULL['base']['ref']), [int(PULL['number'])])

    def test_the_adapter_refuses_a_merged_change(self):
        self.transport.route('GET', PULL_PATH, dict(PULL, state='closed', merged=True))
        with self.assertRaises(forge_origin.OriginAdapterError):
            self.make().merge(REPO, NUMBER, HEAD)
        self.refs.merge.assert_not_called()


class ReadinessCase(unittest.TestCase):
    """ORIGIN-FINISH R3: the preflight's Origin lines: each gap is named, never a value, and the API is asked only
    once every local precondition holds (then through the cached probe, like every credential)."""

    def setUp(self):
        self.refs = unittest.mock.Mock()
        self.refs.url.return_value = FIXTURE['refs_url']
        self.names = [config.get('origin-client.auth_token_env', ROOT), config.get('origin-client.credential_env', ROOT)]
        self.probes = []

    def cached(self, answer):
        def probe(key, names, extras, run):
            self.probes.append((key, tuple(names)))
            return answer and run()
        return probe

    def gaps(self, env, hosts=(ORIGIN_HOST,), answer=True, identity=True):
        real = config.get
        values = {'origin-client.git_hosts': list(hosts), 'forge-events.repo': REPO, 'origin-client.cli_dirs': []}
        patcher = unittest.mock.patch.object(config, 'get', lambda key, *args: values[key] if key in values
                                             else real(key, *args))
        patcher.start()
        self.addCleanup(patcher.stop)
        found = unittest.mock.Mock()
        found.identity.side_effect = (lambda: NAMESPACES and 'slug') if identity else client.OriginClientError('401')
        with unittest.mock.patch.dict('os.environ', env, clear=True), \
                unittest.mock.patch('shutil.which', return_value=None):
            return forge_origin.credential_gaps(self.cached(answer), refs=self.refs, client=found)

    def ready(self):
        return {CONF['cli_env']: str(ROOT), self.names[-1]: 'value-never-printed'}

    def test_everything_present_and_the_api_answering_is_ready(self):
        self.assertEqual(self.gaps(self.ready(), hosts=(ORIGIN_HOST,)), [])
        self.assertEqual(self.probes, [('origin', tuple(self.names))])

    def test_every_local_gap_is_named_and_the_api_is_not_asked(self):
        found = self.gaps({}, hosts=())
        expected = (CONF['cli_env'], ' or '.join(self.names), 'origin-client.git_hosts')
        self.assertEqual([item for item, line in zip(expected, found) if item in line], list(expected))
        self.assertEqual(len(found), len(expected))
        self.assertEqual(self.probes, [])

    def test_a_remote_on_another_forge_is_a_gap(self):
        self.refs.url.return_value = REMOTES['other_forge']['url']
        found = self.gaps(self.ready())
        self.assertEqual([line for line in found if REMOTES['other_forge']['host'] in line], found)
        self.assertTrue(found)

    def test_the_same_repository_on_github_is_no_gap(self):
        # GITHUB-SOURCE (14/11/2026): GitHub is the source of truth and Origin its mirror
        self.refs.url.return_value = REMOTES['foreign']['url']
        self.assertEqual(self.gaps(self.ready()), [])

    def test_an_api_that_refuses_the_credential_is_unreachable_and_no_value_is_printed(self):
        found = self.gaps(self.ready(), identity=False)
        self.assertEqual(found, ['Origin API is not reachable'])
        self.assertNotIn('value-never-printed', '\n'.join(found))


class GitHostCase(unittest.TestCase):
    """ORIGIN-FINISH: merges and locks travel by git, so the adapter refuses, at construction and before any API call,
    a git remote on a host origin-client.git_hosts does not declare (a checkout cloned from another forge)."""

    def setUp(self):
        self.transport = FakeTransport()
        self.refs = unittest.mock.Mock()
        self.refs.url.return_value = FIXTURE['refs_url']

    def make(self, hosts):
        declare_git_hosts(self, hosts)
        return forge_origin.OriginAdapter(client.OriginClient(run=self.transport), REPO, log=unittest.mock.Mock(),
                                          refs=self.refs)

    def assert_refused(self, hosts, reason):
        with self.assertRaisesRegex(forge_origin.OriginAdapterError, reason):
            self.make(hosts)
        self.assertEqual(self.transport.calls, [])
        self.refs.merge.assert_not_called()

    def test_the_registry_declares_the_origin_git_host(self):
        self.assertEqual(config.get('origin-client.git_hosts', ROOT), ['origin.cursor.com'])

    def test_no_declared_host_refuses(self):
        self.assert_refused([], 'no Origin git host declared')

    def test_a_remote_on_another_forge_refuses(self):
        foreign = REMOTES['foreign']
        self.refs.url.return_value = foreign['url']
        self.assert_refused([ORIGIN_HOST], f"{foreign['host']}: git remote is not an Origin git host")

    def test_a_local_path_refuses(self):
        for name in ('local', 'file'):
            with self.subTest(name=name):
                self.refs.url.return_value = REMOTES[name]['url']
                self.assert_refused([ORIGIN_HOST], 'a local path: git remote is not an Origin git host')

    def test_a_declared_host_is_accepted(self):
        self.assertIs(self.make([ORIGIN_HOST]).refs, self.refs)

    def test_the_ssh_forms_are_parsed(self):
        for name in ('scp', 'ssh'):
            with self.subTest(name=name):
                self.refs.url.return_value = REMOTES[name]['url']
                self.assertIs(self.make([ORIGIN_HOST]).refs, self.refs)

    def test_the_host_is_read_without_credentials_or_port(self):
        for name, remote in REMOTES.items():
            with self.subTest(name=name):
                self.assertEqual(forge_origin.git_host(remote['url']), remote['host'])

    def test_the_repository_suffix_is_still_checked(self):
        self.refs.url.return_value = REMOTES['other_repo']['url']
        self.assert_refused([ORIGIN_HOST], 'another repository')

class CliLocationCase(unittest.TestCase):
    """F81: a lane no longer exports PATH; the CLI in one of origin-client.cli_dirs is found."""

    def setUp(self):
        import os
        import tempfile
        self.os = os
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name) / 'bin'
        self.dir.mkdir()
        self.cli = self.dir / CONF['cli']
        self.cli.write_text('#!/bin/sh\n')
        self.cli.chmod(0o755)
        self.conf = dict(CONF, cli_dirs=[str(self.dir)])
        self.env = unittest.mock.patch.dict(os.environ, {'PATH': str(Path(self.tmp.name) / 'empty')})
        self.env.start()
        self.addCleanup(self.env.stop)
        os.environ.pop(CONF['cli_env'], None)

    def test_a_cli_off_path_is_found_in_the_listed_directories(self):
        self.assertEqual(client.cli_binary(self.conf), str(self.cli))
        self.assertIsNone(client.cli_binary(dict(self.conf, cli_dirs=[])))

    def test_the_pinned_path_wins(self):
        self.os.environ[CONF['cli_env']] = '/pinned'
        self.assertEqual(client.cli_binary(self.conf), '/pinned')


if __name__ == '__main__':
    unittest.main()
