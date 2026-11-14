"""PR-OBSERVATION (docs/operations/aws.md 22.9): what `pr metadata` reads of a PR, asked at the port and read by the live
service with the forge's key: the pull, its commits and comments (every page), the comparison with its base, and the head
branch's pushes from the log's forge.repository.pushed (the lane read them from its clone's reflog).

Hermetic but for OnPostgres (TEST_DATABASE_URL, skipped without).
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'infra' / 'service'))
sys.path.insert(0, str(ROOT / 'scripts' / 'tests'))
from tower_infra import forge, http_port, observations  # noqa: E402

URL = os.environ.get('TEST_DATABASE_URL', '')
REPO = observations.REPO
HEAD, BASE_SHA = 'a' * 40, 'b' * 40
AT = f'/repos/{REPO}'


def pushed(ref, before, after, at, forced=False, deleted=False, repo=REPO):
    owner, name = repo.split('/')
    return json.dumps({'delivery': {'event': {'payload': {
        'pushedAt': at, 'repository': {'name': name, 'owner': {'slug': owner}},
        'refUpdates': [{'ref': ref, 'before': before, 'after': after, 'forced': forced, 'deleted': deleted}]}}}})


class ThePushes(unittest.TestCase):
    def test_the_head_branchs_pushes_newest_first_once_each_from_the_log(self):
        rows = [(pushed('refs/heads/units/x', 'b1', 'a2', 't2', forced=True),), (pushed('refs/heads/units/x', 'b1', 'a2', 't2'),),
                (pushed('refs/heads/units/y', '0', 'c', 't1'),), (pushed('refs/heads/units/x', '0', 'b1', 't0'),),
                (pushed('refs/heads/units/x', 'a2', '0', 't3', deleted=True),), (pushed('refs/heads/units/x', 'z', 'y', 't', repo='o/r'),)]
        self.assertEqual(observations.pushes_of(rows, REPO, 'units/x'), [
            {'before': 'b1', 'after': 'a2', 'timestamp': 't2', 'forced': True},  # said twice by Origin: once here
            {'before': '0', 'after': 'b1', 'timestamp': 't0', 'forced': False}])


class Forge:
    def __init__(self, pages=2, refuse=None):
        self.asked, self.pages, self.refuse = [], pages, refuse

    def api_get(self, path):
        self.asked.append(path)
        if self.refuse and self.refuse in path:
            raise RuntimeError('origin api failed: 503')
        if path == f'{AT}/pulls/7':
            return {'number': 7, 'body': 'b', 'head': {'ref': 'units/x', 'sha': HEAD}, 'base': {'ref': 'mod/base'}}
        if path.startswith(f'{AT}/compare/'):
            return {'mergeBaseCommit': {'sha': BASE_SHA}, 'behindBy': 0}
        key = 'commits' if '/commits?' in path else 'files' if '/files?' in path else 'comments'
        page = 2 if 'pageToken=p2' in path else 1
        more = {'nextPageToken': 'p2'} if page < self.pages else {}
        return {key: [{'n': f'{key}-{page}'}], **more}


class Db:
    def __init__(self, asked, pushes=()):
        self.asked, self.said, self.pushes = list(asked), {}, list(pushes)

    def rows(self, sql, params=None):
        if sql == observations.OPEN:
            return [(json.dumps(each),) for each in self.asked if (each['id'], 'taken') not in self.said]
        if sql == observations.PUSHED:  # OBSERVE-PUSHES: the database chooses the head branch's pushes
            assert json.loads(params['ref']) == [{'ref': 'refs/heads/units/x'}], params
            return self.pushes
        if sql == observations.SAY:
            payload = json.loads(params['payload'])
            key = (payload['id'], payload['state'])
            if key in self.said:
                return []
            self.said[key] = payload
            return [(None,)]
        raise AssertionError(sql)


def asked(ident='1'):
    return {'id': ident, 'state': 'asked', 'pr': 7, 'head': HEAD}


class TheObserver(unittest.TestCase):
    def test_an_asked_observation_is_read_once_with_every_page_and_said(self):
        origin = Forge()
        db = Db([asked()], pushes=[(pushed('refs/heads/units/x', '0', HEAD, 't0'),)])
        self.assertEqual(observations.Observer(origin).step(db), 1)
        said = db.said[('1', 'observed')]
        seen = said['observation']
        self.assertEqual((said['pr'], said['head']), (7, HEAD))
        self.assertEqual(seen['commits'], [{'n': 'commits-1'}, {'n': 'commits-2'}])
        self.assertEqual(seen['comments'], [{'n': 'comments-1'}, {'n': 'comments-2'}])
        self.assertEqual(seen['files'], [{'n': 'files-1'}, {'n': 'files-2'}])  # OBSERVATION-FILES
        self.assertEqual(seen['compare']['mergeBaseCommit']['sha'], BASE_SHA)
        self.assertEqual(seen['pushes'], [{'before': '0', 'after': HEAD, 'timestamp': 't0', 'forced': False}])
        self.assertIn(f'{AT}/compare/mod%2Fbase...{HEAD}', origin.asked)  # the base's ref quoted: #642's compare was a 404
        self.assertEqual(observations.Observer(Forge()).step(db), 0)  # taken already

    def test_the_four_reads_after_the_pull_go_at_once(self):
        # OBSERVE-PARALLEL: one after the other they held #652's landing 7.5 s at `pr metadata`
        import threading
        started, release, waited = [], threading.Event(), []
        class Slow(Forge):
            def api_get(self, path):
                if '/pulls/7' in path and not path.endswith('/pulls/7'):
                    started.append(path)
                    if len(started) == 4:
                        release.set()
                    waited.append(release.wait(2))  # each read waits for the four to have started: none ends alone
                elif '/compare/' in path:
                    started.append(path)
                    if len(started) == 4:
                        release.set()
                    waited.append(release.wait(2))
                return super().api_get(path)
        db = Db([asked()])
        self.assertEqual(observations.Observer(Slow(pages=1)).step(db), 1)
        self.assertEqual((len(started), waited), (4, [True] * 4))  # one after the other, the first three would time out

    def test_a_read_that_fails_is_said_failed(self):
        db = Db([asked()])
        self.assertEqual(observations.Observer(Forge(refuse='/comments')).step(db), 0)
        self.assertIn('503', db.said[('1', 'failed')]['why'])

    def test_the_same_pr_and_head_asked_twice_is_one_observation(self):
        # OBSERVE-ON-PUSH: the pre-gate pre-asks it on the push; the delivery's own ask gets the same id
        class Idem(Db):
            def __init__(self):
                super().__init__([]); self.events = []
            def rows(self, sql, params=None):
                if sql == observations.FOR_HEAD:
                    return [(e['id'],) for e in self.events if str(e['pr']) == params['pr'] and e['head'] == params['head']][:1]
                if sql == observations.SAY:
                    self.events.append(json.loads(params['payload'])); return [(None,)]
                raise AssertionError(sql)
        db = Idem()
        first = observations.ask(db, ('installation', None), {'pr': 7, 'head': HEAD}, clock=lambda: 111, configured=lambda *a: None)
        again = observations.ask(db, ('installation', None), {'pr': 7, 'head': HEAD}, clock=lambda: 222, configured=lambda *a: None)
        self.assertEqual(first['id'], again['id'])
        self.assertEqual(observations.ask(db, ('installation', None), {'pr': 7, 'head': 'c' * 40}, clock=lambda: 333, configured=lambda *a: None)['id'], '333')

    def test_the_routes_are_the_ports(self):
        verbs = {(verb, pattern) for verb, pattern, _ in http_port.ROUTES}
        self.assertIn(('POST', r'/v1/pr-observation'), verbs)
        self.assertIn(('GET', r'/v1/pr-observation/(?P<ident>[0-9]{1,24})'), verbs)


class TheForgesRead(unittest.TestCase):
    def run_of(self, answers):
        calls = []

        def run(args, **options):
            calls.append((args, options['env']))
            code, out, err = answers.pop(0)
            return subprocess.CompletedProcess(args, code, out, err)
        return calls, run

    def test_a_get_answers_its_json_and_a_refused_kept_token_is_tried_once_with_the_key(self):
        calls, run = self.run_of([(0, '{"number": 7}', '')])
        origin = forge.OriginForge(cli='origin', run=run, environ={}, credential=lambda: 'crsr_key')
        self.assertEqual(origin.api_get(f'{AT}/pulls/7'), {'number': 7})
        self.assertEqual(calls[0][0], ['origin', 'api', f'{AT}/pulls/7', '-X', 'GET'])
        calls, run = self.run_of([(1, '', 'HTTP 401 unauthorized'), (0, '{"ok": true}', '')])
        origin = forge.OriginForge(cli='origin', run=run, environ={}, credential=lambda: 'crsr_key')
        origin.token, origin.expires = 'oit_kept', 1e12
        self.assertEqual(origin.api_get('/x'), {'ok': True})
        self.assertEqual((calls[0][1].get('CURSOR_AUTH_TOKEN'), calls[1][1].get('CURSOR_API_KEY')), ('oit_kept', 'crsr_key'))
        calls, run = self.run_of([(1, '', 'HTTP 404 not found crsr_secret123456')])
        with self.assertRaises(RuntimeError) as refused:
            forge.OriginForge(cli='origin', run=run, environ={}, credential=lambda: 'crsr_key').api_get('/y?pageSize=1')
        self.assertIn('404', str(refused.exception))
        self.assertNotIn('crsr_secret', str(refused.exception))


class TheForgesHttpRead(unittest.TestCase):
    """OBSERVE-HTTP (criterion 3): a fresh observation was 10.3 to 11.0 s, five `origin api` processes on the service's
    quarter of a vCPU; with the kept token the live service's forge reads the API itself."""

    class Opener:
        def __init__(self, answers):
            self.answers, self.asked = list(answers), []

        def __call__(self, request, timeout=None):
            import io
            import urllib.error
            self.asked.append((request.full_url, request.get_header('Authorization'), timeout))
            code, body = self.answers.pop(0)
            if code != 200:
                raise urllib.error.HTTPError(request.full_url, code, 'refused', {}, io.BytesIO(b''))
            return io.BytesIO(json.dumps(body).encode())

    def forge_with(self, answers, cli=()):
        calls, cli = [], list(cli)

        def run(args, **options):
            calls.append(args)
            code, out, err = cli.pop(0)
            return subprocess.CompletedProcess(args, code, out, err)
        opener = self.Opener(answers)
        origin = forge.OriginForge(cli='origin', run=run, environ={}, credential=lambda: 'crsr_key', opener=opener)
        origin.token, origin.expires = 'oit_kept', 1e12
        return origin, opener, calls

    def test_a_kept_token_reads_the_api_over_http_and_no_cli_runs(self):
        origin, opener, calls = self.forge_with([(200, {'number': 7})])
        self.assertEqual(origin.api_get(f'{AT}/pulls/7'), {'number': 7})
        self.assertEqual(opener.asked, [(f'https://api.cursor.com/v1/origin{AT}/pulls/7', 'Bearer oit_kept', 15)])
        self.assertEqual((calls, origin.via), ([], 'http'))

    def test_a_refused_token_is_dropped_and_the_cli_reads_it(self):
        origin, opener, calls = self.forge_with([(401, None)], cli=[(0, '{"number": 7}', '')])
        self.assertEqual(origin.api_get(f'{AT}/pulls/7'), {'number': 7})
        self.assertEqual((calls[0][:3], origin.via, origin.token), (['origin', 'api', f'{AT}/pulls/7'], 'cli', None))

    def test_another_refusal_is_the_reads_failure_as_the_clis(self):
        origin, _opener, calls = self.forge_with([(404, None)])
        with self.assertRaises(RuntimeError) as refused:
            origin.api_get('/x')
        self.assertIn('404', str(refused.exception))
        self.assertEqual(calls, [])

    def test_without_the_opener_or_a_fresh_token_the_cli_reads_as_before(self):
        calls = []

        def run(args, **options):
            calls.append(args)
            return subprocess.CompletedProcess(args, 0, '{"ok": true}', '')
        plain = forge.OriginForge(cli='origin', run=run, environ={}, credential=lambda: 'crsr_key')
        plain.token, plain.expires = 'oit_kept', 1e12
        self.assertEqual((plain.api_get('/x'), plain.via), ({'ok': True}, 'cli'))
        stale, _opener, _calls = self.forge_with([], cli=[(0, '{"ok": true}', '')])
        stale.expires = 0.0
        self.assertEqual((stale.api_get('/y'), stale.via), ({'ok': True}, 'cli'))

    def test_the_observation_says_each_reads_seconds_and_how_it_read(self):
        origin = Forge()
        origin.via = 'http'
        db = Db([asked()], pushes=[(pushed('refs/heads/units/x', '0', HEAD, 't0'),)])
        observations.Observer(origin).step(db)
        parts = db.said[('1', 'observed')]['parts']
        self.assertEqual(sorted(parts), ['comments_s', 'commits_s', 'compare_s', 'files_s', 'pull_s', 'pushes_s', 'via'])
        self.assertEqual(parts['via'], 'http')


@unittest.skipUnless(URL, 'needs TEST_DATABASE_URL (Postgres; local port 54322)')
class OnPostgres(unittest.TestCase):
    def setUp(self):
        from runner_world import RunnerWorld
        self.world = type('World', (RunnerWorld,), {'runTest': lambda self: None})()
        self.world.setUp()
        self.addCleanup(self.world.doCleanups)

    def test_the_database_answers_the_head_branchs_pushes_only(self):
        # OBSERVE-PUSHES: every push of 30 days came back to be filtered in the service (pushes_s 0.23 to 0.82 s)
        for n, (ref, after) in enumerate((('refs/heads/units/x', HEAD), ('refs/heads/units/y', 'c' * 40),
                                          ('refs/heads/units/x-two', 'd' * 40))):
            self.world.db.rows("insert into log.event (event_id, tenant_id, type, occurred_at, producer, subject, payload) "
                               "values (%(id)s, null, 'forge.repository.pushed', now(), 'test', 'forge/push', %(payload)s::jsonb)",
                               {'id': f'push-{n}', 'payload': pushed(ref, '0' * 40, after, f't{n}')})
        rows = self.world.db.rows(observations.PUSHED, {'ref': json.dumps([{'ref': 'refs/heads/units/x'}])})
        self.assertEqual(observations.pushes_of(rows, REPO, 'units/x'),
                         [{'before': '0' * 40, 'after': HEAD, 'timestamp': 't0', 'forced': False}])
        self.assertEqual(len(rows), 1)  # neither units/y nor units/x-two came back

    def test_an_observation_asked_at_the_port_is_read_by_the_service_and_answered_whole(self):
        said = self.world.port('POST', '/v1/pr-observation', 'torre', {'pr': 7, 'head': HEAD})
        self.assertEqual(self.world.port('GET', f"/v1/pr-observation/{said['id']}", 'torre')['state'], 'asked')
        self.assertEqual(observations.Observer(Forge()).step(self.world.db), 1)
        found = self.world.port('GET', f"/v1/pr-observation/{said['id']}", 'torre')
        self.assertEqual((found['state'], found['observation']['pull']['number']), ('observed', 7))
        for body in ({'pr': 7, 'head': 'short'}, {'pr': '7', 'head': HEAD}, {'head': HEAD}):
            with self.assertRaises(Exception) as refused:
                observations.ask(self.world.db, ('installation', None), body)
            self.assertEqual(getattr(refused.exception, 'status', None), 400)


if __name__ == '__main__':
    unittest.main()
