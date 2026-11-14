"""The forge executor of the infrastructure (engine-infra-service; INFRA-EXE 2, P4 F2): Origin through its CLI.

The adapter runs against a stub of the origin CLI (a script that answers the way the CLI does and records what it was
asked), alone and through the service's dispatcher on a throwaway database of the toolchain's PostgreSQL (TI1): the
landing with the expected head makes the merge commit; a landing whose head moved is refused, and the job, which names
head_moved as an error that never asks for another attempt, fails without a retry; the dry run of the shadow (P5 F3)
checks the head without merging; an input the forge does not understand is refused; every answer that called Origin
carries the seconds its calls took (forge_merge_s, forge_view_s), which the dispatcher's finish relays to the log as run.usage. No network.
"""
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'tests'))
from infra_db.psql import migrated  # noqa: E402
import test_db  # noqa: E402
from tower_infra import forge, http_port, mechanisms, port  # noqa: E402

URL = os.environ.get('TEST_DATABASE_URL', '')
HEAD = '0123456789abcdef0123456789abcdef01234567'
MOVED = '89abcdef0123456789abcdef0123456789abcdef'
MERGE = 'fedcba9876543210fedcba9876543210fedcba98'
REPO = 'openuniversity-si/open-university'
STUB = '''#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
with open(os.environ['STUB_LOG'], 'a') as log:
    log.write(json.dumps(args + ['key:' + str(bool(os.environ.get('CURSOR_API_KEY'))),
                                 'token:' + str(os.environ.get('CURSOR_AUTH_TOKEN', '')[:3])]) + '\\n')
if args == ['auth', 'token']:
    if os.environ.get('STUB_NO_TOKEN'):
        print('Error: not logged in', file=sys.stderr)
        sys.exit(1)
    print(os.environ.get('STUB_TOKEN', 'tok-of-the-test'))
    sys.exit(0)
if os.environ.get('CURSOR_AUTH_TOKEN') and os.environ.get('STUB_REFUSE_TOKEN'):
    print('Error: HTTP 401 unauthorized', file=sys.stderr)
    sys.exit(1)
if '--squash' in args:
    print('Error: squash merges are not allowed for key crsr_the-key-of-the-test', file=sys.stderr)
    sys.exit(1)
if args[:2] == ['pr', 'merge']:
    if '-F' in args:  # MERGE-READY: the body from its file (a FIFO: open() waits for its writer), before any call
        with open(args[args.index('-F') + 1], encoding='utf-8') as source:
            said = source.read()
        with open(os.environ['STUB_BODY'], 'w', encoding='utf-8') as kept:
            kept.write(said)
    expected = args[args.index('--expect-head') + 1].split('=', 1)[1]
    if expected != os.environ['STUB_HEAD']:
        print('Error: 409 ABORTED: the expected head is not the head of the pull request', file=sys.stderr)
        sys.exit(1)
    print('Merged #' + args[2] + '\\nMerge commit: ' + os.environ['STUB_MERGE'])
elif args[:2] == ['pr', 'view']:
    print(json.dumps({'status': os.environ['STUB_STATUS'], 'latestVersion': {'headSha': os.environ['STUB_HEAD']}}))
else:
    print('Error: not allowed with key crsr_the-key-of-the-test', file=sys.stderr)
    sys.exit(1)
'''


class Stubbed(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.cli = Path(tmp.name) / 'origin'
        self.cli.write_text(STUB)
        self.cli.chmod(self.cli.stat().st_mode | stat.S_IXUSR)
        self.log = Path(tmp.name) / 'calls.jsonl'
        self.environ = {name: value for name, value in os.environ.items()
                        if name not in ('CURSOR_API_KEY', 'CURSOR_AUTH_TOKEN')}
        self.environ.update(STUB_LOG=str(self.log), STUB_HEAD=HEAD, STUB_MERGE=MERGE, STUB_STATUS='open')
        self.forge = forge.OriginForge(cli=str(self.cli), environ=self.environ, credential=lambda: 'key-of-the-test')

    def calls(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def land(self, head=HEAD, **more):
        return self.forge.start({'input_uri': forge.encode({'action': 'land', 'repo': REPO, 'pr': '7', 'head': head,
                                                            'method': 'merge', **more})})


class Adapter(Stubbed):
    def test_the_landing_with_the_expected_head_makes_the_merge_commit(self):
        ended = self.land()
        self.assertEqual((ended['outcome'], ended['result']['merge_sha']), ('succeeded', MERGE))
        self.assertEqual(self.calls(), [['pr', 'merge', '7', '-R', REPO, '--expect-head', f'7={HEAD}', '--merge',
                                         'key:True', 'token:']])  # the key reached the CLI's environment, and nothing else
        self.assertNotIn('key-of-the-test', json.dumps(ended))

    def test_an_answer_that_called_origin_carries_its_seconds_and_one_that_did_not_none(self):
        ticks = iter((float('10'), float('10.25'), float('20'), float('20.5')))
        timed = forge.OriginForge(cli=str(self.cli), environ=self.environ, credential=lambda: 'key-of-the-test',
                                  clock=lambda: next(ticks))
        land = {'action': 'land', 'repo': REPO, 'pr': '7', 'head': HEAD}
        self.assertEqual(timed.start({'input_uri': forge.encode(land)})['usage'], {'forge_merge_s': float('0.25')})
        dry = forge.encode(dict(land, dry_run=True))
        self.assertEqual(timed.start({'input_uri': dry})['usage'], {'forge_view_s': float('0.5')})
        self.assertNotIn('usage', self.forge.start({'input_uri': 'in/a-file'}))

    def test_with_no_key_the_landing_is_refused_without_a_call_and_the_service_runs_on(self):
        keyless = forge.OriginForge(cli=str(self.cli), environ=self.environ, credential=lambda: None)
        ended = keyless.start({'input_uri': forge.encode({'action': 'land', 'repo': REPO, 'pr': '7', 'head': HEAD})})
        self.assertEqual((ended['outcome'], ended['error']), ('failed', 'refused'))
        self.assertEqual(self.calls(), [])

    def test_a_landing_reads_the_credential_once_and_a_warm_up_reads_it_off_the_landing(self):
        reads = []
        counted = forge.OriginForge(cli=str(self.cli), environ=self.environ,
                                    credential=lambda: reads.append(1) or 'key-of-the-test')
        counted.warm()
        self.assertEqual(len(reads), 1)  # the service's warm-up between ticks
        for dry_run in (False, True):
            reads.clear()
            counted.start({'input_uri': forge.encode({'action': 'land', 'repo': REPO, 'pr': '7', 'head': HEAD,
                                                      'method': 'merge', 'dry_run': dry_run})})
            self.assertEqual(len(reads), 1)  # one resolution per landing, not one for the check and one for the call
        forge.OriginForge(cli=str(self.cli), environ=self.environ, credential=lambda: 1 / 0).warm()  # never raises

    def merges(self):
        return [call for call in self.calls() if call[:2] == ['pr', 'merge']]

    def test_a_warm_up_exchanges_the_key_once_and_the_landing_calls_origin_with_the_token_alone(self):
        warm = forge.OriginForge(cli=str(self.cli), environ=self.environ, credential=lambda: 'key-of-the-test')
        warm.warm()
        warm.warm()  # a fresh token is kept: no second exchange
        self.assertEqual([call for call in self.calls() if call[:2] == ['auth', 'token']],
                         [['auth', 'token', 'key:True', 'token:']])
        ended = warm.start({'input_uri': forge.encode({'action': 'land', 'repo': REPO, 'pr': '7', 'head': HEAD})})
        self.assertEqual(ended['outcome'], 'succeeded')
        self.assertEqual(ended['result']['auth'], 'token')  # AWS10: the landing's result says which credential it used
        (merge,) = self.merges()
        self.assertEqual(merge[-2:], ['key:False', 'token:tok'])  # the key is out of the process, the token in
        self.assertEqual(len(self.calls()), 2)  # the exchange and the merge: no exchange on the landing's clock

    def test_a_token_near_its_expiry_is_exchanged_again_and_one_that_cannot_be_got_leaves_the_key(self):
        warm = forge.OriginForge(cli=str(self.cli), environ=self.environ, credential=lambda: 'key-of-the-test')
        warm.warm()
        warm.expires = 0.0  # as if it were about to expire
        warm.warm()
        self.assertEqual(len([call for call in self.calls() if call[:2] == ['auth', 'token']]), 2)
        self.environ['STUB_NO_TOKEN'] = '1'
        failing = forge.OriginForge(cli=str(self.cli), environ=self.environ, credential=lambda: 'key-of-the-test')
        failing.warm()
        failing.warm()  # a failed exchange is not tried again for a while: the ticks do not pay it
        self.assertEqual(len([call for call in self.calls() if call[:2] == ['auth', 'token']]), 3)
        self.assertEqual(failing.land({'input_uri': forge.encode({'action': 'land', 'repo': REPO, 'pr': '7',
                                                                  'head': HEAD})}, [])['outcome'], 'succeeded')
        self.assertEqual(self.merges()[-1][-2:], ['key:True', 'token:'])
        with self.assertLogs('tower_infra.forge', 'WARNING'):  # AWS10: a failed exchange is no longer silent
            forge.OriginForge(cli=str(self.cli), environ=self.environ, credential=lambda: 'key-of-the-test').warm()
        keyed = forge.OriginForge(cli=str(self.cli), environ=self.environ, credential=lambda: 'key-of-the-test')
        self.assertEqual(keyed.start({'input_uri': forge.encode({'action': 'land', 'repo': REPO, 'pr': '7',
                                                                 'head': HEAD})})['result']['auth'], 'key')

    def test_the_expiry_of_the_token_is_read_from_its_claims(self):
        import base64
        claims = base64.urlsafe_b64encode(json.dumps({'exp': 4102444800}).encode()).decode().rstrip('=')
        self.environ['STUB_TOKEN'] = f'header.{claims}.signature'
        warm = forge.OriginForge(cli=str(self.cli), environ=self.environ, credential=lambda: 'key-of-the-test')
        warm.warm()
        self.assertEqual(warm.expires, 4102444800.0)

    def test_a_token_the_cli_refuses_is_dropped_and_the_same_landing_goes_once_more_with_the_key(self):
        warm = forge.OriginForge(cli=str(self.cli), environ=self.environ, credential=lambda: 'key-of-the-test')
        warm.warm()
        self.environ['STUB_REFUSE_TOKEN'] = '1'
        ended = warm.start({'input_uri': forge.encode({'action': 'land', 'repo': REPO, 'pr': '7', 'head': HEAD})})
        self.assertEqual(ended['outcome'], 'succeeded')
        self.assertEqual([call[-2:] for call in self.merges()], [['key:False', 'token:tok'], ['key:True', 'token:']])
        self.assertIsNone(warm.token)
        # a head that moved is no auth failure: refused at once, one call, the token kept
        again = forge.OriginForge(cli=str(self.cli), environ=self.environ, credential=lambda: 'key-of-the-test')
        again.warm()
        del self.environ['STUB_REFUSE_TOKEN']
        before = len(self.merges())
        self.assertEqual(again.start({'input_uri': forge.encode({'action': 'land', 'repo': REPO, 'pr': '7',
                                                                 'head': MOVED})})['error'], 'head_moved')
        self.assertEqual(len(self.merges()) - before, 1)
        self.assertIsNotNone(again.token)

    def test_a_landing_with_the_gates_check_run_posts_it_then_merges_and_without_a_post_merges_nothing(self):
        # CHECK-IN-LANDING (F4 criterion 3): the tower/gate success rides the landing, posted with the Origin app's key right
        # before the merge (the order the forge's ruleset asks for), not by the gate's client and its wait for the service
        order = []
        body = {'headSha': HEAD, 'checkSuite': {'key': 'tower'}, 'checkRun': {'key': 'tower/gate', 'conclusion': 'success'}}

        def post(check):
            order.append(('post', check['headSha'], len(self.calls())))
            return {'outcome': 'created'}
        posting = forge.OriginForge(cli=str(self.cli), environ=self.environ, credential=lambda: 'key-of-the-test',
                                    post_check=post)
        ended = posting.start({'input_uri': forge.encode({'action': 'land', 'repo': REPO, 'pr': '7', 'head': HEAD,
                                                          'method': 'merge', 'check_run': body})})
        self.assertEqual((ended['outcome'], ended['result']['merge_sha'], ended['result']['check_posted']),
                         ('succeeded', MERGE, 'success'))
        self.assertGreaterEqual(ended['result']['check_post_s'], 0)
        self.assertEqual(order, [('post', HEAD, 0)])  # posted before Origin's merge was called
        self.assertEqual(len([call for call in self.calls() if call[:2] == ['pr', 'merge']]), 1)

        def refused(check):
            raise RuntimeError('origin answered 403 for crsr_secret-of-the-test')
        for forge_, check, error in ((posting, dict(body, headSha=MOVED), 'not_understood'),  # only the head that lands
                                     (self.forge, body, 'refused'),  # no app key: nothing merges
                                     (forge.OriginForge(cli=str(self.cli), environ=self.environ, credential=lambda: 'k',
                                                        post_check=refused), body, 'refused'),
                                     (forge.OriginForge(cli=str(self.cli), environ=self.environ, credential=lambda: 'k',
                                                        post_check=lambda check: {'outcome': 'ignored_stale'}), body,
                                      'refused')):
            before = len(self.calls())
            ended = forge_.start({'input_uri': forge.encode({'action': 'land', 'repo': REPO, 'pr': '7', 'head': HEAD,
                                                             'method': 'merge', 'check_run': check})})
            self.assertEqual((ended['outcome'], ended['error']), ('failed', error), ended)
            self.assertEqual(len(self.calls()), before)  # Origin's merge never called
            self.assertNotIn('secret-of-the-test', json.dumps(ended))

    def test_a_landing_whose_head_moved_is_refused(self):
        ended = self.land(head=MOVED)
        self.assertEqual((ended['outcome'], ended['error']), ('failed', 'head_moved'))

    def test_the_dry_run_checks_the_head_and_merges_nothing(self):
        self.assertEqual(self.land(dry_run=True)['result']['would_merge'], True)
        self.assertEqual(self.land(head=MOVED, dry_run=True)['error'], 'head_moved')
        self.environ['STUB_STATUS'] = 'merged'
        self.assertEqual(self.land(dry_run=True)['error'], 'merged')  # never retried: the box merged it first
        self.environ['STUB_STATUS'] = 'closed'
        self.assertEqual(self.land(dry_run=True)['error'], 'refused')
        self.assertFalse([call for call in self.calls() if 'merge' in call])

    def test_an_input_the_forge_does_not_understand_is_refused_without_a_call(self):
        for uri in ('in/a-file', forge.encode({'action': 'push'}), forge.encode({'action': 'land', 'repo': REPO}),
                    'data:application/json,not json'):
            self.assertEqual(self.forge.start({'input_uri': uri})['error'], 'not_understood', uri)
        self.assertEqual(self.calls(), [])

    def test_a_refusal_keeps_no_credential(self):
        ended = self.forge.start({'input_uri': forge.encode({'action': 'land', 'repo': REPO, 'pr': '7', 'head': HEAD,
                                                             'method': 'squash'})})
        self.assertEqual((ended['outcome'], ended['error']), ('failed', 'refused'))  # the stub's refusal names a key
        self.assertNotIn('crsr_the-key', json.dumps(ended))
        self.assertEqual(forge.decode(forge.encode({'action': 'land'})), {'action': 'land'})


class Answer:
    def __init__(self, said):
        self.said = said

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self):
        return json.dumps(self.said).encode()


BODY = 'the title\n\n### Commit plan\n- [x] 1. the title\n'


class MergeReady(Stubbed):
    """MERGE-READY (criterion 2): the train front's merge started ahead, its body a FIFO the landing writes."""

    def setUp(self):
        super().setUp()
        self.body = self.log.parent / 'body.txt'
        self.environ.update(STUB_BODY=str(self.body))
        self.pull, self.asked, self.posted = {'state': 'open', 'head': {'sha': HEAD}, 'body': BODY}, [], []

        def opener(request, timeout=None):
            self.asked.append(request.full_url)
            return Answer(self.pull)
        self.forge = forge.OriginForge(cli=str(self.cli), environ=self.environ, credential=lambda: 'key-of-the-test',
                                       opener=opener, post_check=lambda check: self.posted.append(self.body.exists()) or {})
        self.forge.token, self.forge.expires = 'tok-kept', float('inf')
        self.addCleanup(self.dropped)

    def dropped(self):
        with self.forge.lock:
            self.forge.drop()

    def landed(self, pr='7'):
        return self.forge.start({'input_uri': forge.encode({'action': 'land', 'repo': REPO, 'pr': pr, 'head': HEAD,
                                                            'method': 'merge', 'check_run': {
                                                                'headSha': HEAD, 'checkRun': {'conclusion': 'success'}}})})

    def merges(self):
        return [call for call in self.calls() if call[:2] == ['pr', 'merge']]

    def test_the_merge_started_ahead_waits_for_its_body_and_the_landing_releases_it_after_the_check(self):
        self.assertTrue(self.forge.ready(REPO, '7', HEAD))
        self.assertEqual(self.asked, [f'{forge.ORIGIN_API}/repos/{REPO}/pulls/7'])  # the description, over HTTP
        process = self.forge.kept['process']
        with self.assertRaises(subprocess.TimeoutExpired):
            process.wait(timeout=0.3)  # started, and waiting in its FIFO's open(): nothing merged
        self.assertFalse(self.body.exists())
        self.assertTrue(self.forge.ready(REPO, '7', HEAD))  # asked again: the same one kept
        self.assertIs(self.forge.kept['process'], process)
        ended = self.landed()
        self.assertEqual(ended['outcome'], 'succeeded', ended)
        self.assertEqual((ended['result']['merge_sha'], ended['result']['ready'], self.posted), (MERGE, True, [False]))
        self.assertEqual(self.body.read_text(encoding='utf-8'), BODY)  # the description, the forge's own default
        self.assertEqual(len(self.merges()), 1)  # no second process: the one started ahead merged
        merge = self.merges()[0]
        self.assertIn('-F', merge)
        self.assertEqual((merge[-1], merge[merge.index('--expect-head') + 1]), ('token:tok', f'7={HEAD}'))
        self.assertIn('forge_merge_s', ended['usage'])
        self.assertGreaterEqual(ended['result']['ready_s'], 0.3)
        self.assertIsNone(self.forge.kept)
        self.assertFalse(Path(merge[merge.index('-F') + 1]).parent.exists())

    def test_a_merge_started_ahead_and_stopped_never_merges(self):
        # a FIFO, not stdin: nobody writes it unless the landing does, so no end of file reaches the CLI
        self.assertTrue(self.forge.ready(REPO, '7', HEAD))
        process, fifo = self.forge.kept['process'], self.forge.kept['fifo']
        self.dropped()
        self.assertIsNotNone(process.poll())
        self.assertFalse(self.body.exists())
        self.assertFalse(Path(fifo).parent.exists())

    def test_nothing_is_started_without_the_kept_token_an_open_pull_at_the_head_or_its_description(self):
        for pull in ({'state': 'closed', 'head': {'sha': HEAD}, 'body': BODY},
                     {'state': 'open', 'head': {'sha': MOVED}, 'body': BODY}, {'state': 'open', 'head': {'sha': HEAD}}):
            self.pull = pull
            self.assertFalse(self.forge.ready(REPO, '7', HEAD))
        self.pull = {'state': 'open', 'head': {'sha': HEAD}, 'body': BODY}
        self.forge.expires = 0.0  # no fresh token: the CLI would exchange the key first
        self.assertFalse(self.forge.ready(REPO, '7', HEAD))
        self.assertEqual(self.merges(), [])
        ended = self.landed()  # and the landing merges as before: one process after the check
        self.assertEqual((ended['outcome'], ended['result']['ready']), ('succeeded', False))
        self.assertNotIn('-F', self.merges()[0])

    def test_one_kept_for_another_merge_is_stopped_by_a_landing_that_merges_as_before(self):
        self.assertTrue(self.forge.ready(REPO, '8', HEAD))
        process = self.forge.kept['process']
        ended = self.landed('7')
        self.assertIsNotNone(process.poll())
        self.assertEqual((ended['outcome'], ended['result']['ready'], self.body.exists()), ('succeeded', False, False))
        self.assertEqual([call[2] for call in self.merges() if '-F' not in call], ['7'])  # 8 started, never released

    def test_a_kept_merge_that_ended_is_not_released_and_the_landing_merges_as_before(self):
        self.environ['STUB_REFUSE_TOKEN'] = '1'  # the CLI refused the kept token at once, before its body
        self.assertTrue(self.forge.ready(REPO, '7', HEAD))
        self.forge.kept['process'].wait(timeout=30)
        del self.environ['STUB_REFUSE_TOKEN']
        ended = self.landed()
        self.assertEqual((ended['outcome'], ended['result']['ready']), ('succeeded', False))
        self.assertFalse(self.body.exists())

    def test_a_merge_started_ahead_runs_under_timeout_in_its_own_session_and_is_stopped_with_it(self):
        # MERGE-READY-ORPHAN: a process that ends after it readied the next front leaves no CLI waiting for good
        asked = []

        def spawn(args, **options):
            asked.append((args, options))
            return subprocess.Popen(args, **options)
        self.forge.spawn = spawn
        self.assertTrue(self.forge.ready(REPO, '7', HEAD))
        args, options = asked[0]
        self.assertEqual((args[:5], options['start_new_session']), (['timeout', '-s', 'KILL', str(forge.READY_LIFE_S),
                                                                      str(self.cli)], True))
        self.assertGreater(forge.READY_LIFE_S, forge.READY_MAX_S + 60)  # the oldest one released ends its merge first
        group = self.forge.kept['process'].pid
        self.dropped()
        with self.assertRaises(ProcessLookupError):
            os.killpg(group, 0)  # timeout and the CLI under it, both gone

    def test_an_orphan_ends_by_itself_without_merging(self):
        life = forge.READY_LIFE_S
        forge.READY_LIFE_S = 1
        self.addCleanup(setattr, forge, 'READY_LIFE_S', life)
        self.assertTrue(self.forge.ready(REPO, '7', HEAD))
        process = self.forge.kept['process']
        # killed by its timeout in open(): 137 when `timeout` kills its group, itself too; 124 when the coreutils spares
        # itself (the GitHub runner's): either way the orphan's life ended it
        self.assertIn(process.wait(timeout=30), (124, 137, -9))
        self.assertFalse(self.body.exists())

    def test_the_look_drops_its_kept_merge_when_its_process_ends(self):
        main = (ROOT / 'infra' / 'service' / 'tower_infra' / 'merge_ready.py').read_text(encoding='utf-8')
        self.assertIn('atexit.register(dropped)', main)

    def test_the_look_readies_the_trains_front_and_stops_the_kept_one_when_the_queue_is_empty(self):
        from tower_infra import merge_ready

        class Db:
            front = [('7', HEAD)]

            def rows(self, sql, params=None):
                if sql == merge_ready.TENANT_ID:
                    return [('t-1',)]
                assert sql == merge_ready.FRONT and params == {'tenant': 't-1', 'base': 'mod/roadmap-integration'}
                return self.front
        db, look = Db(), merge_ready.Look(self.forge)
        self.assertEqual(look.step(db), ('7', HEAD))
        process = self.forge.kept['process']
        db.front = []
        self.assertIsNone(look.step(db))
        self.assertIsNotNone(process.poll())
        self.assertIsNone(self.forge.kept)

    def test_the_live_service_starts_the_look_on_tower_train_at_the_threads_own_priority(self):
        main = (ROOT / 'infra' / 'service' / 'tower_infra' / '__main__.py').read_text(encoding='utf-8')
        line = next(each for each in main.splitlines() if 'merge_ready.start(' in each)
        self.assertNotIn('lowly', line)  # its merge's process takes the thread's nice, never lowered back
        self.assertIn('hub.wake(wake.TRAIN)', line)


class ThroughTheDispatcher(Stubbed):
    def setUp(self):
        super().setUp()
        self.name, self.db = migrated(URL)
        self.addCleanup(test_db.destroy, URL, self.name)
        self.call('POST', '/v1/tenants', 'installation', {'name': 'torre', 'token_sha256': port.sha256('torre')})
        self.call('POST', '/v1/executors', 'installation', {'name': 'origin-forge', 'adapter': 'forge'})
        self.call('PUT', '/v1/executors/origin-forge/capacity/origin', 'installation', {'slots': '1'})
        self.call('PUT', '/v1/queues/land', 'torre', {'policy': 'fifo'})

    def call(self, method, path, token, body=None):
        answer = http_port.handle({'rawPath': path, 'requestContext': {'http': {'method': method}},
                                   'headers': {'Authorization': f'Bearer {token}'}, 'body': json.dumps(body or {})},
                                  self.db, port.sha256('installation'))
        return json.loads(answer['body'])

    def landing(self, key, head):
        action = {'action': 'land', 'repo': REPO, 'pr': '7', 'head': head, 'method': 'merge'}
        return self.call('POST', '/v1/jobs', 'torre', {
            'queue': 'land', 'executor': 'origin-forge', 'input_uri': forge.encode(action),
            'input_digest': 'sha256:' + key, 'idempotency_key': key, 'exclusive_key': f'origin:{REPO}:base',
            'max_attempts': '3', 'non_retryable': ['head_moved']})['id']

    def land_once(self):
        run = mechanisms.dispatch(self.db)[0]
        ended = self.forge.start(run)
        return run, mechanisms.finish(self.db, run, ended)

    def test_the_landing_lands_and_records_its_merge_commit(self):
        job = self.landing('lands', HEAD)
        run, state = self.land_once()
        self.assertEqual((run['job'], run['adapter'], state), (job, 'forge', 'succeeded'))
        self.assertEqual(self.call('GET', f'/v1/jobs/{job}', 'torre')['result']['merge_sha'], MERGE)

    def test_the_seconds_of_the_forge_reach_the_log_as_usage(self):
        job = self.landing('measured', HEAD)
        self.land_once()
        usage = self.call('POST', '/v1/log/query', 'torre', {'filters': {'type': 'run.usage'},
                                                             'payload': {'job_id': job}})['events']
        (event,) = usage
        self.assertEqual(event['payload']['meter'], 'forge_merge_s')
        self.assertGreaterEqual(event['payload']['quantity'], 0)

    def test_a_moved_head_fails_the_landing_without_a_retry(self):
        job = self.landing('moved', MOVED)
        _, state = self.land_once()
        self.assertEqual(state, 'failed')
        self.assertEqual(self.call('GET', f'/v1/jobs/{job}', 'torre')['runs'][0]['error_type'], 'head_moved')
        self.assertEqual(mechanisms.dispatch(self.db), [])


if __name__ == '__main__':
    unittest.main()
