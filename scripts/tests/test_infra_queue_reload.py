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
from tower_infra import autodeploy, config_data, http_port, queue_deploy  # noqa: E402
import deploy  # noqa: E402
import lambda_package  # noqa: E402

GIT_ENV = {**os.environ, 'GIT_AUTHOR_NAME': 't', 'GIT_AUTHOR_EMAIL': 't@t', 'GIT_COMMITTER_NAME': 't',
           'GIT_COMMITTER_EMAIL': 't@t', 'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_CONFIG_NOSYSTEM': '1'}


class Log:
    """The log.event statements of queue_deploy and http_port.queue_state, by statement."""

    def __init__(self):
        self.events, self.at = [], 100.0

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
            return [(1,)] if self.has(params['id'], queue_deploy.OUTCOME) else []
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
        look.queue = Queue()
        made = []
        look.order = lambda db, head, digest, key, pr_head, **more: made.append((head, digest, key, pr_head, more))
        look.queue_look('db', {'queue_reload': False})
        self.assertEqual(seen, [])
        look.queue_look('db', look.settings())
        seen[0]('s' * 40, 'd' * 64, 'k')
        self.assertEqual(made, [('s' * 40, 'd' * 64, 'k', None, {'roles': ['service'], 'by': 'queue'})])
        self.assertEqual(config_data.SPEC['deploy.queue_reload'], (bool, True))
        self.assertTrue(autodeploy.DEFAULTS['queue_reload'])


class Watch(unittest.TestCase):
    """deploy.py queue: the merge_group job's part."""

    def run_queue(self, sequence):
        rung, clock = [], [0.0]
        heads = iter(sequence)

        def opener(request, timeout=None):
            rung.append(json.loads(request.data))

            class Answer:
                status = 202

                def read(self):
                    return b'{}'

                def __enter__(self):
                    return self

                def __exit__(self, *_):
                    return False
            return Answer()

        def tick(seconds):
            clock[0] += seconds
        env = {'TOWER_DEPLOY_DOORBELL_URL': 'https://door', 'TOWER_DEPLOY_DOORBELL_TOKEN': 'x'}
        code = deploy.queue('c' * 40, 'refs/heads/gh-readonly-queue/main/pr-1-x', env, opener=opener,
                            heads=lambda: next(heads), clock=lambda: clock[0], sleep=tick, limit_s=60)
        return code, [each['event'] for each in rung]

    def test_it_rings_prepare_at_once_and_landed_when_main_is_the_commit(self):
        ref = 'refs/heads/gh-readonly-queue/main/pr-1-x'
        code, rung = self.run_queue([{'refs/heads/main': 'a' * 40, ref: 'c' * 40}, {},
                                     {'refs/heads/main': 'c' * 40}])
        self.assertEqual((code, rung), (0, ['prepare', 'landed']))

    def test_a_group_that_leaves_the_queue_rings_nothing_more(self):
        code, rung = self.run_queue([{'refs/heads/main': 'a' * 40}] * 200)
        self.assertEqual((code, rung), (0, ['prepare']))


if __name__ == '__main__':
    unittest.main()
