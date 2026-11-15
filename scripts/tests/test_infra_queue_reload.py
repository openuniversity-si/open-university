"""QUEUE-RELOAD (the Torre, 15/11/2026; Daniel's target of 09/11): a code-only merge is live about a second after it lands.

1. The merge_group job (scripts/lib/deploy.py queue) rings `prepare` at once, watches main and rings `landed` the moment
   main is the queue's commit; a group that leaves the queue rings nothing more.
2. The doorbell's word reaches the port as a direct invocation and becomes one platform.deploy.queue event that wakes the
   look (http_port.queue_state); anything else is ignored.
3. prepare: the service fetches the repository, checks that the sha is the head of main or of a merge-queue branch,
   classifies last-sha..sha with last-sha's classifier and, code-only, puts the bundle its bundler builds from the sha's
   files (the deploy build's own digest); never a change of the classifier or the bundler, never a slow change.
4. landed: main must be the sha and its parent last-sha; then the order of the service alone, by: queue. A process that
   starts after it (the reloaded one) follows the order and records nothing twice.
Hermetic: a bare repository on disk as the remote, the log as a list.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'infra' / 'service'))
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
from tower_infra import autodeploy, config_data, http_port, live_image, queue_deploy  # noqa: E402
import deploy  # noqa: E402
import lambda_package  # noqa: E402

GIT_ENV = {**os.environ, 'GIT_AUTHOR_NAME': 't', 'GIT_AUTHOR_EMAIL': 't@t', 'GIT_COMMITTER_NAME': 't',
           'GIT_COMMITTER_EMAIL': 't@t', 'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_CONFIG_NOSYSTEM': '1'}


class Log:
    """The log.event statements of queue_deploy and http_port.queue_state, by statement."""

    def __init__(self):
        self.events, self.at = [], 100.0
        self.beating = set()  # QUEUE-SWAP: the digests whose service heir beats fresh
        self.pointer = ('', 0)  # deploy.live_image_service and its version

    def has(self, ident, kind):
        return any(each['id'] == ident and each['type'] == kind for each in self.events)

    def add(self, ident, kind, payload):
        if self.has(ident, kind):
            return False
        self.at += 1
        self.events.append({'id': ident, 'type': kind, 'payload': payload, 'at': self.at})
        return True

    def of(self, kind):
        return [each['payload'] for each in self.events if each['type'] == kind]

    def rows(self, sql, params):
        if sql == queue_deploy.QUEUED:
            return [(each['payload']['event'], each['payload']['sha'], each['at']) for each in self.events
                    if each['type'] == queue_deploy.QUEUE]
        if sql == queue_deploy.PREPARED_OF:
            return [(json.dumps(each['payload']),) for each in self.events
                    if each['type'] == queue_deploy.PREPARED and each['id'] == params['id']]
        if sql == queue_deploy.OUTCOME_OF:
            return [(json.dumps(each['payload']),) for each in self.events
                    if each['type'] == queue_deploy.OUTCOME and each['id'] == params['id']]
        if sql == queue_deploy.WANT:
            return [(live_image.SUCCESSOR,)] if self.add(params['id'], live_image.SUCCESSOR, json.loads(params['payload'])) else []
        if sql == queue_deploy.WANTED:
            newest = {}
            for each in self.events:
                if each['type'] == live_image.SUCCESSOR and each['payload'].get('branch') == 'queue':
                    newest[each['payload']['digest']] = each['payload']['state']
            return [(digest,) for digest, state in newest.items() if state == 'wanted']
        if sql == queue_deploy.SWAP:
            if params['digest'] not in self.beating:
                return []
            self.pointer = (params['digest'], self.pointer[1] + 1)
            self.add(params['id'], 'platform.deploy.image_swap', {**json.loads(params['payload']), 'swapped': True,
                                                                   'by': 'queue', 'roles': ['service']})
            return [(self.pointer[1], 1000.5)]
        if sql == queue_deploy.SWAP_OF:
            return [(1,)] if any(each['type'] == 'platform.deploy.image_swap' and each['payload'].get('head') == params['head']
                                 and each['payload'].get('digest') == params['digest'] for each in self.events) else []
        if sql == queue_deploy.SAY:
            self.add(params['id'], params['type'], json.loads(params['payload']))
            return []
        if sql == http_port.QUEUE_SAID:
            return [(queue_deploy.QUEUE,)] if self.add(params['id'], queue_deploy.QUEUE, json.loads(params['payload'])) else []
        raise AssertionError(f'unexpected statement: {sql[:80]}')


class Remote:
    """A repository with the engine's control scripts and a small tower_infra, pushed to a bare remote."""

    def __init__(self, base):
        self.base = Path(base)
        self.bare, self.work = self.base / 'remote.git', self.base / 'author'
        self.git_at(self.base, 'init', '-q', '--bare', str(self.bare))
        self.git_at(self.base, 'init', '-q', '-b', 'main', str(self.work))
        shutil.copytree(ROOT / 'scripts' / 'lib', self.work / 'scripts' / 'lib', ignore=shutil.ignore_patterns('__pycache__'))
        self.write('infra/service/tower_infra/__init__.py', '')
        self.write('infra/service/tower_infra/autodeploy.py', 'LOOK = 1\n')
        self.write('infra/db/migrations/0001_first.sql', 'select 1;\n')
        self.write('infra/service/requirements.txt', 'dbos\n')
        self.write('docs/readme.md', 'a\n')
        self.main = self.commit('base')
        self.git('push', '-q', str(self.bare), 'main')

    def git_at(self, where, *args):
        return subprocess.run(['git', '-C', str(where), *args], check=True, capture_output=True, text=True,
                              env=GIT_ENV).stdout.strip()

    def git(self, *args):
        return self.git_at(self.work, *args)

    def write(self, path, text):
        (self.work / path).parent.mkdir(parents=True, exist_ok=True)
        (self.work / path).write_text(text, encoding='utf-8')

    def commit(self, message):
        self.git('add', '-A')
        self.git('commit', '-q', '-m', message)
        return self.git('rev-parse', 'HEAD')

    def queued(self, changes, number=1):
        """A merge-queue commit on main with these changes ({path: text}), on its gh-readonly-queue branch; main stays."""
        self.git('checkout', '-q', '-B', f'q{number}', 'main')
        for path, text in changes.items():
            self.write(path, text)
        sha = self.commit(f'merge {number}')
        self.git('push', '-q', str(self.bare), f'HEAD:refs/heads/gh-readonly-queue/main/pr-{number}-{self.main}')
        self.git('checkout', '-q', 'main')
        return sha

    def land(self, sha, number=1):
        """The queue moves main to the commit and deletes its branch."""
        self.git('push', '-q', str(self.bare), f'{sha}:refs/heads/main',
                 f':refs/heads/gh-readonly-queue/main/pr-{number}-{self.main}')

    def digest_of(self, sha):
        tree = self.base / f'tree-{sha[:8]}'
        tree.mkdir()
        data = subprocess.run(['git', '-C', str(self.work), 'archive', '--format=tar', sha, '--', *queue_deploy.CODE_INPUTS],
                              check=True, capture_output=True).stdout
        subprocess.run(['tar', '-x', '-C', str(tree)], input=data, check=True)
        return lambda_package.build_code(tree)[1]


class Prepared(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.remote = Remote(self.directory.name)
        self.ssm = {queue_deploy.LAST_SHA: self.remote.main}
        self.stored, self.orders, self.log = {}, [], Log()
        self.queue = self.reload_of()

    def tearDown(self):
        self.directory.cleanup()

    def reload_of(self):
        return queue_deploy.QueueReload(self.ssm.get, self.stored.__setitem__, work=Path(self.directory.name, 'service'),
                                        remote=str(self.remote.bare))

    def order(self, sha, digest, key):
        self.orders.append((sha, digest, key))
        return (len(self.orders) == 1, sha, False)  # the first makes it; then it is busy with this head

    def word(self, event, sha):
        return http_port.handle({'source': 'tower.doorbell', 'detail-type': 'Merge Queue',
                                 'detail': {'event': event, 'sha': sha}}, self.log, '')

    def test_a_code_only_merge_is_prepared_with_the_deploy_builds_own_bundle(self):
        sha = self.remote.queued({'infra/service/tower_infra/autodeploy.py': 'LOOK = 2\n'})
        found = self.queue.prepare(self.log, sha)
        digest = self.remote.digest_of(sha)
        self.assertEqual((found['code_only'], found['sha256'], found['parent'], found['base']),
                         (True, digest, self.remote.main, self.remote.main))
        self.assertEqual(found['key'], f'artifacts/lambda/tower-code/{digest}.zip')
        self.assertEqual(hashlib.sha256(self.stored[found['key']]).hexdigest(), digest)
        self.assertEqual(self.log.of(queue_deploy.PREPARED), [found])
        self.stored.clear()
        self.assertEqual(self.queue.prepare(self.log, sha), found)  # once per (sha, base): recorded, not rebuilt
        self.assertEqual(self.stored, {})

    def test_what_is_not_code_only_or_not_queued_is_left_to_the_deploy_build(self):
        cases = {
            'a migration': {'infra/db/migrations/0002_next.sql': 'select 2;\n'},
            'the image': {'infra/service/requirements.txt': 'dbos\nboto3\n'},
            'a stack': {'infra/aws/stacks/30-service.json': '{}\n'},
            'the bundler': {'infra/service/tower_infra/autodeploy.py': 'LOOK = 3\n', 'scripts/lib/lambda_package.py': '#\n'},
            'docs alone': {'docs/readme.md': 'b\n'},
        }
        whys = {}
        for number, (name, changes) in enumerate(cases.items(), start=1):
            sha = self.remote.queued(changes, number)
            found = self.queue.prepare(self.log, sha)
            self.assertFalse(found['code_only'], name)
            whys[name] = found['why']
        self.assertIn('the image itself changes', whys['a migration'])
        self.assertIn('the classifier or the bundler changes', whys['the bundler'])
        self.assertIn('no service/runner image target', whys['docs alone'])
        self.assertEqual(self.stored, {})
        stray = self.remote.git('commit-tree', '-p', self.remote.main, '-m', 'stray',
                                self.remote.git('rev-parse', f'{self.remote.main}^{{tree}}'))
        self.assertIn('is the head of neither main nor a merge-queue branch', self.queue.prepare(self.log, stray)['why'])

    def test_a_landing_is_ordered_only_once_main_is_it_and_its_parent_is_deployed(self):
        sha = self.remote.queued({'infra/service/tower_infra/autodeploy.py': 'LOOK = 2\n'})
        self.assertEqual(self.word('prepare', sha), {'event_id': f'platform.deploy.queue:prepare:{sha}'})
        self.queue.look(self.log, self.order)
        self.assertEqual(len(self.log.of(queue_deploy.PREPARED)), 1)
        early = queue_deploy.QueueReload(self.ssm.get, self.stored.__setitem__, work=Path(self.directory.name, 'other'),
                                         remote=str(self.remote.bare)).landed(self.log, sha, self.order)
        self.assertEqual(early['state'], 'skipped')
        self.assertIn(f'not {sha[:12]}', early['why'])  # a claim before main moved orders nothing
        self.log.events = [each for each in self.log.events if each['type'] != queue_deploy.OUTCOME]
        self.remote.land(sha)
        self.word('landed', sha)
        self.queue.look(self.log, self.order)
        digest = self.remote.digest_of(sha)
        self.assertEqual(self.orders, [(sha, digest, f'artifacts/lambda/tower-code/{digest}.zip')])
        [said] = self.log.of(queue_deploy.OUTCOME)
        self.assertEqual((said['state'], said['digest']), ('ordered', digest))
        self.queue.look(self.log, self.order)  # handled: nothing again
        self.assertEqual(len(self.orders), 1)
        # the reloaded process: it finds the outcome, follows the order (busy with this head) and records nothing more
        self.reload_of().look(self.log, self.order)
        self.assertEqual(len(self.orders), 2)
        self.assertEqual(len(self.log.of(queue_deploy.OUTCOME)), 1)
        self.assertEqual(len(self.log.of(queue_deploy.PREPARED)), 1)

    def test_a_prepared_bundle_is_wanted_and_a_landing_whose_heir_beats_swaps_the_pointer_alone(self):
        """QUEUE-SWAP: the prepare wants a heir of the bundle in each ECS task; at the landing a heir that beats gets the
        service's pointer (no order: the deploy is the pointer's move), the swap says the head's reload for deploy.sh,
        and the merge queue's other heirs are withdrawn."""
        stale = self.remote.queued({'infra/service/tower_infra/autodeploy.py': 'LOOK = 9\n'}, 2)
        self.queue.prepare(self.log, stale)  # a group that will not land
        sha = self.remote.queued({'infra/service/tower_infra/autodeploy.py': 'LOOK = 2\n'})
        found = self.queue.prepare(self.log, sha)
        wants = {each['digest']: each for each in self.log.of(live_image.SUCCESSOR)}
        self.assertEqual((wants[found['sha256']]['state'], wants[found['sha256']]['branch'], wants[found['sha256']]['key']),
                         ('wanted', 'queue', found['key']))
        self.log.beating.add(found['sha256'])
        self.remote.land(sha)
        said = self.queue.landed(self.log, sha, self.order)
        self.assertEqual((said['state'], said['digest'], said['version']), ('swapped', found['sha256'], 1))
        self.assertEqual(self.orders, [])
        self.assertEqual(self.log.pointer, (found['sha256'], 1))
        [reload] = [each['payload'] for each in self.log.events if each['type'] == live_image.RELOAD]
        self.assertEqual((reload['state'], reload['head'], reload['role'], reload['by']), ('swapped', sha, 'service', 'queue'))
        self.assertTrue(self.queue.swapping(self.log, sha, found['sha256']))
        states = [(each['digest'] == found['sha256'], each['state']) for each in self.log.of(live_image.SUCCESSOR)]
        self.assertEqual(states[-1], (False, 'withdrawn'))  # the group that did not land lets its heir go
        self.assertNotIn((True, 'withdrawn'), states)  # the heir that took the role keeps its want
        self.reload_of().look(self.log, self.order)  # a process that starts after it follows no order: the heir has it
        self.assertEqual(self.orders, [])

    def test_a_landing_with_no_heir_ready_orders_the_reload_and_withdraws_the_heir(self):
        sha = self.remote.queued({'infra/service/tower_infra/autodeploy.py': 'LOOK = 2\n'})
        found = self.queue.prepare(self.log, sha)
        self.remote.land(sha)
        said = self.queue.landed(self.log, sha, self.order)  # its heir never beat (booting, or no successors)
        self.assertEqual(said['state'], 'ordered')
        self.assertEqual(self.orders, [(sha, found['sha256'], found['key'])])
        self.assertEqual(self.log.pointer, ('', 0))
        self.assertEqual(self.log.of(live_image.SUCCESSOR)[-1]['state'], 'withdrawn')

    def test_a_landing_whose_parent_is_not_the_deployed_head_waits_for_the_deploy_build(self):
        first = self.remote.queued({'infra/service/tower_infra/autodeploy.py': 'LOOK = 2\n'})
        self.remote.land(first)
        self.remote.git('checkout', '-q', '-B', 'main', first)
        self.remote.main = first
        second = self.remote.queued({'infra/service/tower_infra/autodeploy.py': 'LOOK = 3\n'}, 2)
        self.remote.land(second, 2)
        said = self.queue.landed(self.log, second, self.order)  # last-sha is still the base: first's build has not ended
        self.assertEqual(said['state'], 'skipped')
        self.assertIn('the deployed is', said['why'])
        self.assertEqual(self.orders, [])

    def test_the_port_records_a_word_once_and_ignores_anything_else(self):
        sha = 'b' * 40
        self.assertEqual(self.word('landed', sha), {'event_id': f'platform.deploy.queue:landed:{sha}'})
        self.word('landed', sha)
        self.assertEqual(self.log.of(queue_deploy.QUEUE), [{'event': 'landed', 'sha': sha}])
        for event, sha in (('deploy', 'b' * 40), ('landed', 'main'), ('', '')):
            self.assertEqual(self.word(event, sha), {'ignored': True})
        self.assertIn('pg_notify(\'tower_deploy\'', http_port.QUEUE_SAID)  # it wakes the look

    def test_the_look_orders_the_service_alone_by_queue_and_the_key_turns_it_off(self):
        look = autodeploy.AutoDeploy(None, lambda name: None, None)
        seen = []

        class Queue:
            def look(self, db, order):
                seen.append(order)

            def adopted(self, db):
                return None
        look.queue = Queue()
        made = []
        look.order = lambda db, head, digest, key, pr_head, **more: made.append((head, digest, key, pr_head, more))
        look.queue_look('db', {'queue_reload': False})
        self.assertEqual(seen, [])
        look.queue_look('db', look.settings())
        seen[0]('s' * 40, 'd' * 64, 'k')
        self.assertEqual(made, [('s' * 40, 'd' * 64, 'k', None, {'roles': ['service'], 'by': 'queue'})])
        self.assertEqual(config_data.SPEC['deploy.queue_reload'], (bool, True))

    def test_the_build_orders_nothing_while_the_queue_swap_of_its_head_is_in_charge(self):
        """QUEUE-SWAP: the build's ask of the head the queue swapped is not ordered (it would reload the process the heir
        takes over from); the build waits for deploy.live_code, which the look writes once the heir took the role over."""
        look = autodeploy.AutoDeploy(None, lambda name: None, None)
        sha, digest = 's' * 40, 'd' * 64

        class Queue:
            def swapping(self, db, head, bundle):
                return (head, bundle) == (sha, digest)

            def look(self, db, order):
                pass

            def adopted(self, db):
                return sha
        look.queue = Queue()
        made, written = [], []
        look.order = lambda *args, **more: made.append(args) or (True, None, False)
        look.live_code = lambda db, head: written.append(head)
        look.seen_build = {'build_id': 'b', 'base_head': sha, 'status': 'in_progress', 'step': 'reload',
                           'reload': {'key': f'artifacts/lambda/tower-code/{digest}.zip', 'sha256': digest, 'head': sha}}

        class DB:
            def rows(self, sql, params=None):
                return []
        look.build_reload(DB())
        self.assertEqual(made, [])
        look.queue_look(DB(), look.settings())
        self.assertEqual(written, [sha])

    def test_a_queue_swap_fires_no_canary_and_is_proven_by_its_heir(self):
        look = autodeploy.AutoDeploy(None, lambda name: None, None)

        class DB:
            def rows(self, sql, params=None):
                raise AssertionError('a queue swap reads no canary')
        self.assertIsNone(look.swap_canary(DB(), {'digest': 'd' * 64, 'by': 'queue', 'versions': {}}, 100.0))
        self.assertIn("payload->>'by' = 'queue'", live_image.RELOAD_OF)
        self.assertEqual(live_image.PROVE_QUEUE_S, live_image.PROVE_S)
        self.assertTrue(autodeploy.DEFAULTS['queue_reload'])


@unittest.skipUnless(os.environ.get('TEST_DATABASE_URL'), 'TEST_DATABASE_URL is not set')
class OnPostgres(unittest.TestCase):
    """QUEUE-SWAP's statements on the engine's own schema: the swap only while the heir beats, its proof by the heir's
    first work and PROVE_QUEUE_S, the takeover that names the head, and deploy.live_code written for it."""

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(ROOT / 'scripts' / 'tests'))
        from infra_db.psql import migrated
        cls.url = os.environ['TEST_DATABASE_URL']
        cls.name, cls.db = migrated(cls.url)
        cls.db.run("insert into work.tenant (name) values ('torre');")

    @classmethod
    def tearDownClass(cls):
        import test_db
        test_db.destroy(cls.url, cls.name)

    def test_the_swap_its_proof_and_the_takeover_end_in_the_live_code_of_the_merge(self):
        digest, head = 'e' * 64, 'f' * 40
        swap = {'digest': digest, 'tenant': 'torre', 'fresh_s': 3.0, 'reason': 'test',
                'id': f'platform.deploy.image_swap:{digest}:queue:{head}',
                'payload': json.dumps({'digest': digest, 'key': f'artifacts/lambda/tower-code/{digest}.zip', 'head': head})}
        self.assertEqual(self.db.rows(queue_deploy.SWAP, swap), [])  # no heir beats: no swap
        self.db.run(f"insert into work.standby_beat (role, digest, task) values ('service', '{digest}', 't:{digest[:12]}');")
        [(version, wrote_at)] = self.db.rows(queue_deploy.SWAP, swap)
        self.assertEqual(self.db.rows("select value #>> '{}' from work.config_value where key = 'deploy.live_image_service'"),
                         [(digest,)])
        self.assertEqual(self.db.rows(queue_deploy.SWAP_OF, {'head': head, 'digest': digest}), [('1',)])
        live = f'platform.deploy.image_live:service:{digest}:{version}'
        reload_of = {'role': 'service', 'digest': digest, 'tenant': 'torre', 'live': live}
        self.assertEqual(self.db.rows(live_image.RELOAD_OF, reload_of)[0][4], 'proving')  # no first work yet
        self.db.run("insert into log.event (event_id, tenant_id, type, occurred_at, producer, subject, payload) "
                    f"values ('{live}', null, 'platform.deploy.image_live', clock_timestamp(), 't', 'deploy/image/service', '{{}}');")
        self.assertEqual(self.db.rows(live_image.RELOAD_OF, reload_of)[0][4], 'proving')  # working, not PROVE_QUEUE_S yet
        self.db.run(f"update log.event set occurred_at = occurred_at - interval '{live_image.PROVE_QUEUE_S + 1:g} seconds' "
                    f"where event_id = '{live}';")
        self.assertEqual(self.db.rows(live_image.RELOAD_OF, reload_of)[0][4], 'succeeded')  # proven by the heir alone
        self.assertEqual(self.db.rows(queue_deploy.ADOPTED, {}), [])  # not taken over yet
        self.db.run("insert into log.event (event_id, tenant_id, type, occurred_at, producer, subject, payload) "
                    f"values ('r', null, '{live_image.RELOAD}', clock_timestamp(), 't', 'deploy/image/service', "
                    f"'{{\"role\": \"service\", \"digest\": \"{digest}\", \"state\": \"reloaded\"}}');")
        self.assertEqual(self.db.rows(queue_deploy.ADOPTED, {}), [(head,)])
        self.assertEqual(self.db.rows(autodeploy.LIVE_CODE_WRITE, {'tenant': 'torre', 'head': head}), [(f'{digest}@{head}',)])
        want = {'id': 'w1', 'payload': json.dumps({'digest': digest, 'branch': 'queue', 'state': 'wanted'})}
        self.db.rows(queue_deploy.WANT, want)
        self.assertEqual(self.db.rows(queue_deploy.WANTED, {}), [(digest,)])
        self.db.rows(queue_deploy.WANT, {'id': 'w2', 'payload': json.dumps({'digest': digest, 'branch': 'queue',
                                                                            'state': 'withdrawn'})})
        self.assertEqual(self.db.rows(queue_deploy.WANTED, {}), [])


class Watch(unittest.TestCase):
    """deploy.py queue: the merge_group job's part."""

    def run_queue(self, sequence, status=202, warm_s=deploy.WARM_S):
        rung, clock = [], [0.0]
        heads = iter(sequence)

        class Bell:
            closed = False

            def send(self, word):
                rung.append(word['event'])
                return status

            def close(self):
                Bell.closed = True

        def tick(seconds):
            clock[0] += seconds
        code = deploy.queue('c' * 40, 'refs/heads/gh-readonly-queue/main/pr-1-x', {}, bell=Bell(),
                            heads=lambda: next(heads), clock=lambda: clock[0], sleep=tick, limit_s=60, warm_s=warm_s)
        self.assertTrue(Bell.closed)
        return code, rung

    def test_it_rings_prepare_at_once_and_landed_when_main_is_the_commit(self):
        ref = 'refs/heads/gh-readonly-queue/main/pr-1-x'
        code, rung = self.run_queue([{'refs/heads/main': 'a' * 40, ref: 'c' * 40}, {},
                                     {'refs/heads/main': 'c' * 40}])
        self.assertEqual((code, rung), (0, ['prepare', 'landed']))

    def test_it_rings_prepare_again_while_it_waits_so_the_landing_finds_everything_warm(self):
        # QUEUE-BELL: every warm_s a prepare again (the port records it once and wakes nobody for the repeats)
        ref = 'refs/heads/gh-readonly-queue/main/pr-1-x'
        waiting = [{'refs/heads/main': 'a' * 40, ref: 'c' * 40}] * 41  # 41 looks 0.25 s apart: 10 s of waiting
        code, rung = self.run_queue(waiting + [{'refs/heads/main': 'c' * 40}], warm_s=5.0)
        self.assertEqual((code, rung), (0, ['prepare', 'prepare', 'prepare', 'landed']))
        self.assertEqual(self.run_queue([{'refs/heads/main': 'c' * 40}], status=None)[0], 2)  # no answer: undecided
        self.assertEqual(self.run_queue([{'refs/heads/main': 'c' * 40}], status=401)[0], 1)

    def test_the_bell_keeps_one_connection_and_opens_it_again_once_when_the_server_closed_it(self):
        import http.client
        made, sent = [], []

        class Connection:
            def __init__(self, host, timeout=None):
                made.append((host, timeout))
                self.fail = len(made) == 1 and len(sent) > 0

            def request(self, method, path, body=None, headers=None):
                if getattr(self, 'drop', False):
                    raise http.client.RemoteDisconnected('closed')
                sent.append((method, path, json.loads(body)['event'], headers['Authorization'] == 'Bearer t'))

            def getresponse(self):
                class Answer:
                    status = 202

                    def read(self):
                        return b''
                return Answer()

            def close(self):
                pass
        bell = deploy.Bell({'TOWER_DEPLOY_DOORBELL_URL': 'https://door.example/', 'TOWER_DEPLOY_DOORBELL_TOKEN': 't'},
                           connect=Connection)
        self.assertEqual(bell.send({'event': 'prepare', 'sha': 's'}), 202)
        self.assertEqual(bell.send({'event': 'prepare', 'sha': 's'}), 202)
        self.assertEqual(len(made), 1)  # one connection for both words
        bell.connection.drop = True  # the server closed the idle connection
        self.assertEqual(bell.send({'event': 'landed', 'sha': 's'}), 202)
        self.assertEqual(len(made), 2)  # opened again once, the word sent again on it
        self.assertEqual(sent, [('POST', '/', 'prepare', True), ('POST', '/', 'prepare', True), ('POST', '/', 'landed', True)])
        self.assertEqual(made[0], ('door.example', 10.0))

    def test_the_watch_reads_the_repository_through_the_forges_adapter(self):
        import source_remote

        class Out:
            returncode, stdout = 0, f"{'a' * 40}\trefs/heads/main\n{'c' * 40}\trefs/heads/gh-readonly-queue/main/pr-1-x\n"
        asked = []
        found = source_remote.heads('https://h/o/r.git', ['refs/heads/main'], run=lambda cmd, **_: asked.append(cmd) or Out())
        self.assertEqual(found, {'refs/heads/main': 'a' * 40, 'refs/heads/gh-readonly-queue/main/pr-1-x': 'c' * 40})
        self.assertEqual(asked, [['git', 'ls-remote', 'https://h/o/r.git', 'refs/heads/main']])
        self.assertEqual(source_remote.heads('u', [], run=lambda cmd, **_: type('E', (), {'returncode': 2})()), {})
        self.assertEqual(source_remote.repo_url({'GITHUB_REPOSITORY': 'o/r'}), 'https://github.com/o/r.git')
        self.assertEqual(source_remote.repo_url({'GITHUB_SERVER_URL': 'https://ghe', 'GITHUB_REPOSITORY': 'o/r'}),
                         'https://ghe/o/r.git')

    def test_a_group_that_leaves_the_queue_rings_nothing_more(self):
        code, rung = self.run_queue([{'refs/heads/main': 'a' * 40}] * 200)
        self.assertEqual((code, set(rung)), (0, {'prepare'}))  # the warm prepares, never a landing


if __name__ == '__main__':
    unittest.main()
