"""IMAGE-PREWARM-C (docs/operations/aws.md 22.9): the image-only swap on landing and the reconciliation off the clock.

On platform.deploy.landed the autodeploy writes deploy.live_image_runner and deploy.live_image_service to the PR head's
bundle S in one statement, only when the merge runs S (the delivery's code: code-only, the base changed none of the bundle's
inputs; the merge's parent is base_before) and both roles have a healthy standby of S (the log, then ECS); else the slow path
as today, with the reason in platform.deploy.image_swap. The ECS tasks carry TOWER_IMAGE_DIGEST (LiveCode from deploy.sh, or
their image), so they stand by under a pointer naming another digest. Off the clock: the reconciled ECS service hands the
role over (its pointer emptied), a build that ended well at the swap's head or later empties the rest, a swap no standby
took within SWAP_LIMIT_S is undone (GATE-LOOKS-GONE, D-316: the prewarm that retired the promoted Spot standbys left).
scripts/medir: image_landing_s and prewarm_task_usd.

Hermetic: fake database, ECS and git repositories made here; OnPostgres runs the real statements (TEST_DATABASE_URL).
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'infra' / 'service'))
sys.path.insert(0, str(ROOT / 'scripts' / 'tests'))
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
from tower_infra import autodeploy, live_image  # noqa: E402
import gate_infra  # noqa: E402
import medir  # noqa: E402

URL = os.environ.get('TEST_DATABASE_URL', '')
BASE, MERGE, PR_HEAD, LATER = 'b' * 40, '9' * 40, '8' * 40, '7' * 40
S, OLD = 'a' * 64, 'f' * 64
KEYS = sorted(live_image.KEYS.values())
CFG = {'promote': True}


def said(sha=None, why='3 file(s) of infra/service/tower_infra/ only'):
    """A bundle job's result as the runner keeps it: the log's tail ends with gate_code's JSON line."""
    line = ({'code_only': True, 'why': why, 'published': True, 'key': f'artifacts/lambda/tower-code/{sha}.zip',
             'sha256': sha, 'bytes': 10, 'uploaded': True} if sha else {'code_only': False, 'why': why})
    return json.dumps({'exit': 0, 'log_uri': 's3://x', 'tail': 'setup: ok\n' + json.dumps(line, sort_keys=True) + '\n'})


def landed(**code):
    return {'merge_sha': MERGE, 'base_before': BASE, 'pr_head': PR_HEAD, 'pr': '7', 'functions': [], 'paths': [],
            'code': {'code_only': True, 'why': '1 file(s)', 'bundle_same': True, **code}}


class Db:
    """The image statements of the autodeploy and of the gate, by their text."""

    def __init__(self):
        self.pointer, self.events, self.job, self.live, self.idents = {}, [], [('succeeded', said(S))], set(), set()
        self.standbys = [('runner', 'healthy', 'arn:r'), ('service', 'healthy', 'arn:s')]

    def scope(self):
        import contextlib
        return contextlib.nullcontext(self)

    def swaps(self, swapped=None):
        return [each for kind, each in self.events if kind == autodeploy.SWAP and swapped in (None, each.get('swapped'))]

    def rows(self, sql, params=None):
        if sql == autodeploy.SWAP_OF:
            return [(1,)] if params['id'] in self.idents else []
        if sql == autodeploy.BUNDLE_JOB:
            assert params['key'] == f'prewarm:code:{PR_HEAD}'
            return self.job
        if sql == autodeploy.STANDBYS:
            return self.standbys if params['digest'] == S else []
        if sql == live_image.READ:
            value = self.pointer.get(params['key'])
            return [] if value is None else [(json.dumps(value), 1)]
        if sql == autodeploy.SWAP_WRITE:
            for key in params['keys'].split(','):
                self.pointer[key] = params['digest']
            payload = {**json.loads(params['payload']), 'swapped': True, 'landed_s': 0.012, 'wrote_at': 100.0}
            self.events.append((autodeploy.SWAP, payload))
            self.idents.add(params['id'])
            return [(json.dumps(payload),)]
        if sql == autodeploy.NEWEST_SWAP:
            found = self.swaps(True)
            return [(json.dumps(found[-1]), 100.0)] if found else []
        if sql == autodeploy.LIVE_SEEN:
            return [(role,) for role in sorted(self.live)]
        if sql == getattr(autodeploy, 'LIVE_BEATING', None):  # PROMOTED-RUNNER-WAITS-ALIVE: the roles that beat live
            assert params == {'digest': S, 'stale_s': 10.0}
            return [(role,) for role in sorted(getattr(self, 'beating', ()))]
        if sql == live_image.EMPTY:
            keys = [key for key in params['keys'].split(',') if self.pointer.get(key) == params['digest']]
            for key in keys:
                self.pointer[key] = ''
            if keys:
                self.events.append(('platform.deploy.image_retired', {**json.loads(params['payload']), 'keys': keys}))
            return [(json.dumps(keys),)] if keys else []
        if sql == autodeploy.ORDER:  # RELOAD-WITHOUT-STANDBY: the order of a landing with no standby pair (its own test module)
            self.events.append((live_image.RELOAD, json.loads(params['payload'])))
            return [(1, None, False, 1)]
        if sql == live_image.ORDER_OF:
            return []
        if sql.startswith('insert'):  # autodeploy.record
            self.events.append((params['type'], json.loads(params['payload'])))
            self.idents.add(params['id'])
            return []
        raise AssertionError(sql)


class Ecs:
    def __init__(self, healthy=True):
        self.healthy, self.calls = healthy, []

    def describe_tasks(self, cluster, tasks):
        self.calls.append((cluster, tasks))
        return {'tasks': [{'taskArn': each, 'lastStatus': 'RUNNING', 'healthStatus': 'HEALTHY' if self.healthy else 'UNHEALTHY'}
                          for each in tasks]}


class World(unittest.TestCase):
    def setUp(self):
        self.db, self.now, self.params = Db(), [1000.0], {}
        self.watcher = autodeploy.AutoDeploy(self.db.scope, self.params.get, lambda _: {}, clock=lambda: self.now[0])
        self.watcher.ecs, self.watcher.cluster = Ecs(), 'tower'
        self.heads = [BASE, MERGE]

    def land(self, event=None, cfg=CFG, heads=None):
        self.watcher.landed[MERGE] = event or landed()
        self.watcher.promote(self.db, heads or self.heads, cfg)


class OnLanding(World):
    def test_both_pointers_are_written_in_one_statement_to_the_pr_heads_bundle(self):
        with self.assertLogs('tower_infra.autodeploy', 'INFO') as logs:
            self.land()
        self.assertEqual(self.db.pointer, {key: S for key in KEYS})
        [swap] = self.db.swaps()
        self.assertEqual((swap['digest'], swap['head'], swap['pr_head'], swap['swapped'], swap['key']),
                         (S, MERGE, PR_HEAD, True, f'artifacts/lambda/tower-code/{S}.zip'))
        self.assertEqual(self.watcher.ecs.calls, [('tower', ['arn:r', 'arn:s'])])  # ECS says healthy now, not only the log
        self.assertIn('both pointers -> aaaaaaaaaaaa', '\n'.join(logs.output))
        self.watcher.promote(self.db, self.heads, CFG)  # the same landing again: nothing
        self.assertEqual(len(self.db.swaps()), 1)

    def test_any_reason_not_to_swap_is_the_slow_path_with_the_reason(self):
        cases = (
            ({'cfg': {'promote': False}}, 'deploy.promote is false'),
            ({'event': landed(bundle_same=False, moved=['infra/service/tower_infra/x.py'])},
             "the base changed the bundle's inputs: infra/service/tower_infra/x.py"),
            ({'heads': [LATER, MERGE]}, "the merge's parent is not base_before"),
            ({'job': []}, 'the PR head has no bundle job'),
            ({'job': [('succeeded', said(why='not code'))]}, 'not code-only: not code'),
            ({'standbys': [('runner', 'healthy', 'arn:r'), ('service', 'started', 'arn:s')]}, 'no healthy service standby'),
            ({'ecs': Ecs(healthy=False)}, 'no healthy runner or service standby'),
        )
        for given, why in cases:
            self.setUp()
            for name in ('job', 'standbys'):
                if name in given:
                    setattr(self.db, name, given[name])
            if 'ecs' in given:
                self.watcher.ecs = given['ecs']
            self.land(given.get('event'), given.get('cfg', CFG), given.get('heads'))
            self.assertEqual(self.db.pointer, {}, why)
            [swap] = self.db.swaps()
            self.assertEqual((swap['swapped'], swap['head']), (False, MERGE))
            self.assertIn(why, swap['why'])

    def test_a_landing_that_is_not_code_only_or_not_the_newest_head_is_todays_path_and_says_nothing(self):
        self.land(landed(code_only=False))
        self.watcher.landed[MERGE] = landed()
        self.watcher.promote(self.db, [MERGE, LATER], CFG)  # another merge landed on top: not swapped
        event = landed()
        del event['code']  # a delivery that does not say (an older port): nothing
        self.watcher.landed[LATER] = event
        self.watcher.promote(self.db, [BASE, LATER], CFG)
        self.assertEqual((self.db.pointer, self.db.events), ({}, []))

    def test_the_swap_runs_before_the_lambda_swap_in_the_look(self):
        source = (ROOT / 'infra/service/tower_infra/autodeploy.py').read_text(encoding='utf-8')
        look = source[source.index('    def decide_in('):]
        self.assertLess(look.index('self.image(db, pushes, cfg)'), look.index('self.swap(db, pushes)'))
        self.assertLess(look.index('self.swap(db, pushes)'), look.index("if not cfg['auto']"))

    def test_promote_is_a_registry_key_defaulting_to_true(self):
        entry = json.loads((ROOT / 'config/registry/deploy/deploy.promote.json').read_text(encoding='utf-8'))
        self.assertEqual((entry['type'], entry['default']), ('boolean', True))
        self.assertIs(autodeploy.DEFAULTS['promote'], True)
        self.assertEqual(live_image.config_data.SPEC['deploy.promote'], (bool, True))


class OffTheClock(World):
    def swapped(self):
        self.land()
        self.db.live = {'runner', 'service'}

    def build(self, status='succeeded', head=MERGE, **more):
        self.params[autodeploy.LAST_BUILD] = json.dumps({'status': status, 'base_head': head, 'ended': 2000,
                                                         'build_id': 'b:1', **more})

    def test_a_build_that_deployed_the_swaps_head_or_later_retires_the_pointers(self):
        self.swapped()
        self.build(head=BASE)  # a build started before the merge: not yet
        self.watcher.settle_image(self.db, self.heads)
        self.build(status='failed')
        self.watcher.settle_image(self.db, self.heads)
        self.build(dirty=['tower-app-runner'])
        self.watcher.settle_image(self.db, self.heads)
        self.assertEqual(self.db.pointer, {key: S for key in KEYS})
        self.build(head=LATER)
        self.watcher.settle_image(self.db, self.heads + [LATER])
        self.assertEqual(self.db.pointer, {key: '' for key in KEYS})
        [retired] = [each for kind, each in self.db.events if kind == 'platform.deploy.image_retired']
        self.assertEqual((retired['digest'], retired['by'], retired['keys']), (S, 'reconciled', KEYS))

    def test_a_swap_no_standby_took_in_the_limit_is_undone(self):
        self.land()
        self.db.live = {'service'}
        self.now[0] = 100.0 + autodeploy.SWAP_LIMIT_S - 1
        self.watcher.settle_image(self.db, self.heads)
        self.assertEqual(self.db.pointer[KEYS[0]], S)
        self.now[0] = 100.0 + autodeploy.SWAP_LIMIT_S + 1
        self.watcher.settle_image(self.db, self.heads)
        self.assertEqual(self.db.pointer, {key: '' for key in KEYS})
        [retired] = [each for kind, each in self.db.events if kind == 'platform.deploy.image_retired']
        self.assertEqual(retired['by'], 'revert')
        self.assertIn('no image_live of the runner standby', retired['why'])

    def test_a_queue_swap_of_the_service_alone_is_kept_once_the_service_took_it(self):
        # QUEUE-SWAP (the merge queue, 15/11): a swap of the service alone (roles [service]) has no runner standby to
        # wait for: once its heir said image_live it stands, and a heir that never did is undone as before
        self.db.pointer[live_image.KEYS['service']] = S
        self.db.events.append((autodeploy.SWAP, {'digest': S, 'head': MERGE, 'swapped': True, 'by': 'queue',
                                                 'roles': ['service'], 'versions': {live_image.KEYS['service']: 1}}))
        self.db.live = {'service'}
        self.now[0] = 100.0 + autodeploy.SWAP_LIMIT_S + 1
        self.watcher.settle_image(self.db, self.heads)
        self.assertEqual(self.db.pointer[live_image.KEYS['service']], S)
        self.assertEqual([each for kind, each in self.db.events if kind == 'platform.deploy.image_retired'], [])
        self.db.live = set()
        self.watcher.settle_image(self.db, self.heads)
        self.assertEqual(self.db.pointer[live_image.KEYS['service']], '')
        [retired] = [each for kind, each in self.db.events if kind == 'platform.deploy.image_retired']
        self.assertEqual((retired['by'], retired['why']), ('revert', f'no image_live of the service standby in {autodeploy.SWAP_LIMIT_S} s'))

    def test_a_role_that_beats_live_but_took_no_work_yet_keeps_the_swap(self):
        # PROMOTED-RUNNER-WAITS-ALIVE: live 11/11 (#537): the runner's four slots were in long checks of the process before
        # the swap, its in-task successor waited for a checkout, and at 60 s the swap was undone for "no image_live of
        # the runner standby": the engine paused 58 s and deployed the slow way
        self.land()
        self.db.live, self.db.beating = {'service'}, {'runner'}
        self.now[0] = 100.0 + autodeploy.SWAP_LIMIT_S + 1
        self.watcher.settle_image(self.db, self.heads)
        self.assertEqual(self.db.pointer, {key: S for key in KEYS})  # it holds the role: not undone
        self.db.beating = set()  # its live beat stopped: dead, the swap goes back as before
        self.watcher.settle_image(self.db, self.heads)
        self.assertEqual(self.db.pointer, {key: '' for key in KEYS})

    def test_a_pointer_handed_over_or_moved_is_left_alone(self):
        self.swapped()
        self.db.pointer[live_image.KEYS['service']] = ''  # the reconciled ECS service handed over
        self.build()
        self.watcher.settle_image(self.db, self.heads)
        self.assertEqual(self.db.pointer, {live_image.KEYS['service']: '', live_image.KEYS['runner']: ''})
        [retired] = [each for kind, each in self.db.events if kind == 'platform.deploy.image_retired']
        self.assertEqual(retired['keys'], [live_image.KEYS['runner']])
        self.db.pointer = {key: OLD for key in KEYS}  # someone pointed elsewhere: not this swap's to retire
        self.watcher.settle_image(self.db, self.heads)
        self.assertEqual(self.db.pointer, {key: OLD for key in KEYS})


class Pointer:
    def __init__(self, value, fail=False):
        self.value, self.fail, self.calls = value, fail, []

    def scope(self):
        import contextlib
        if self.fail:
            raise RuntimeError('db down')
        return contextlib.nullcontext(self)

    def rows(self, sql, params=None):
        if sql == live_image.READ:
            return [(json.dumps(self.value), 3)]
        assert sql == live_image.EMPTY
        self.calls.append(params)
        if self.value == params['digest']:
            self.value = ''
            return [(json.dumps(params['keys'].split(',')),)]
        return []


class Handover(unittest.TestCase):
    def test_the_ecs_task_the_pointer_names_shares_the_role_until_it_hands_it_over(self):
        table = Pointer(S)
        gate = live_image.gate('service', S, table.scope, task='ecs-1')
        self.assertTrue(gate.active() and gate.sharing())
        self.assertFalse(gate.sole())  # the prewarm waits: the promoted standby still runs it
        self.assertTrue(gate.handover())
        [call] = table.calls
        self.assertEqual((call['keys'], call['digest'], call['id']),
                         (live_image.KEYS['service'], S, f'platform.deploy.image_retired:service:{S}:3'))
        self.assertEqual(json.loads(call['payload']), {'role': 'service', 'digest': S, 'task': 'ecs-1', 'by': 'handover'})
        gate.refresh()  # the NOTIFY of that write
        self.assertTrue(gate.active() and gate.sole() and not gate.sharing())

    def test_a_strict_standby_or_another_digest_never_hands_over_and_a_failed_write_is_tried_again(self):
        for gate in (live_image.gate('service', S, Pointer(S).scope, strict=True),
                     live_image.gate('service', OLD, Pointer(S).scope)):
            self.assertFalse(gate.sharing())
            self.assertTrue(gate.handover())
        table = Pointer(S)
        gate = live_image.gate('service', S, table.scope)
        table.fail = True
        with self.assertLogs('tower_infra.live_image', 'ERROR'):
            self.assertFalse(gate.handover())

    def test_an_ecs_task_without_a_pointer_works_and_stands_by_under_another_digest(self):
        # phase A's non-strict gate, now the ECS tasks' (TOWER_IMAGE_DIGEST = LiveCode or the image reference)
        self.assertTrue(live_image.gate('runner', 'img:1', Pointer('').scope).active())
        self.assertFalse(live_image.gate('runner', 'img:1', Pointer(S).scope).active())

    def test_serve_hands_over_after_its_first_live_beat_and_runs_the_prewarm_only_when_sole(self):
        main = (ROOT / 'infra/service/tower_infra/__main__.py').read_text(encoding='utf-8')
        serve = main[main.index('def serve('):main.index('\ndef ', main.index('def serve(') + 1)]
        beat = serve.index('touch_health(engine)\n                last_beat = now')
        self.assertIn('handed = handed or gate.handover()', serve[beat:beat + 200])
        self.assertIn('active=None if gate is None else gate.after_work(gate.sole))', serve)
        loop = serve[serve.index("LOG.info('serve: up')"):]
        self.assertLess(loop.index('if gate is not None and not gate.active():'), loop.index('gate.handover()'))


class LandedCode(unittest.TestCase):
    def setUp(self):
        self.repo = Path(tempfile.mkdtemp())
        self.addCleanup(subprocess.run, ['rm', '-rf', str(self.repo)])
        for path in ('infra/service/tower_infra/a.py', 'infra/service/tower_infra/b.py', 'infra/db/migrations/0001.sql',
                     'infra/service/requirements.txt', 'docs/x.md'):
            self.write(path, 'v0\n')
        self.git('init', '-q', '-b', 'base')
        self.commit('base')

    def git(self, *args):
        return subprocess.run(['git', '-C', str(self.repo), '-c', 'user.name=t', '-c', 'user.email=t@t', *args],
                              check=True, capture_output=True, text=True).stdout.strip()

    def write(self, path, text):
        (self.repo / path).parent.mkdir(parents=True, exist_ok=True)
        (self.repo / path).write_text(text)

    def commit(self, message):
        self.git('add', '.')
        self.git('commit', '-qm', message)
        return self.git('rev-parse', 'HEAD')

    def landing(self, base_change):
        start = self.git('rev-parse', 'HEAD')
        self.git('checkout', '-q', '-b', 'pr')
        self.write('infra/service/tower_infra/a.py', 'v1\n')
        head = self.commit('pr')
        self.git('checkout', '-q', 'base')
        self.write(base_change, 'v2\n')
        base = self.commit('base moved')
        paths = self.git('diff', '--name-only', f'{base}...{head}').split('\n')
        self.assertNotEqual(start, base)
        return gate_infra.landed_code(self.repo, head, base, paths)

    def test_a_base_that_moved_elsewhere_keeps_the_bundle(self):
        code = self.landing('docs/x.md')
        self.assertEqual((code['code_only'], code['bundle_same']), (True, True))
        self.assertNotIn('moved', code)

    def test_a_base_that_moved_the_bundles_inputs_does_not(self):
        for path in ('infra/service/tower_infra/b.py', 'infra/db/migrations/0001.sql', 'infra/service/requirements.txt'):
            self.setUp()
            code = self.landing(path)
            self.assertEqual((code['bundle_same'], code['moved']), (False, [path]))

    def test_the_inputs_are_what_build_code_reads(self):
        import lambda_package
        self.assertEqual(tuple(map(str, lambda_package.CODE_INPUTS)),
                         ('infra/service/tower_infra', 'infra/db/migrations', 'infra/service/requirements.txt'))
        script = (ROOT / 'infra/aws/deploy.sh').read_text(encoding='utf-8')
        self.assertIn('code_inputs="' + ' '.join(map(str, lambda_package.CODE_INPUTS)) + '"', script)


class Templates(unittest.TestCase):
    def test_the_ecs_tasks_carry_the_digest_and_the_live_code_bundle(self):
        stacks = ROOT / 'infra/aws/stacks'
        for name, resource, container in (('30-service.json', 'TaskDefinition', 'service'),
                                          ('30-service.json', 'StandbyTaskDefinition', 'service')):  # GATE-SHUTDOWN: no runner
            template = json.loads((stacks / name).read_text(encoding='utf-8'))
            self.assertEqual(template['Parameters']['LiveCode']['Default'], '')
            self.assertEqual(template['Conditions']['HasLiveCode'],
                             {'Fn::Not': [{'Fn::Equals': [{'Ref': 'LiveCode'}, '']}]})
            [found] = [each for each in template['Resources'][resource]['Properties']['ContainerDefinitions']
                       if each['Name'] == container]
            env = {item['Name']: item['Value'] for item in found['Environment']}
            self.assertEqual(env['TOWER_IMAGE_DIGEST'], {'Fn::If': ['HasLiveCode', {'Ref': 'LiveCode'}, {'Ref': 'Image'}]})
            self.assertEqual(env['TOWER_CODE_KEY'], {'Fn::If': ['HasLiveCode', {
                'Fn::Sub': 'artifacts/lambda/tower-code/${LiveCode}.zip'}, '']})
            self.assertEqual(env['TOWER_CODE_SHA256'], {'Fn::If': ['HasLiveCode', {'Ref': 'LiveCode'}, '']})
            self.assertNotIn('TOWER_STANDBY', env)  # the ECS tasks are never strict

    def test_an_empty_live_code_boots_the_images_own_code(self):
        from tower_infra import code_bundle
        self.assertIsNone(code_bundle.boot('serve', [], environ={'TOWER_CODE_KEY': '', 'TOWER_CODE_SHA256': '',
                                                                 'TOWER_IMAGE_DIGEST': 'registry/tower:1'}))


class Measure(unittest.TestCase):
    def test_landing_to_pointer_and_the_price_of_each_standby(self):
        status = {'image_swap': [{'swapped': True, 'landed_s': 0.031}, {'swapped': False, 'why': 'x'}],
                  'standby': [{'role': 'runner', 'state': 'stopped', 'at': 3600 + 100, 'started_at': 100},
                              {'role': 'service', 'state': 'failed', 'at': 7300, 'started_at': 100},
                              {'role': 'runner', 'state': 'healthy', 'at': 50, 'started_at': 1},
                              {'role': 'service', 'state': 'stopped', 'at': 50}]}
        import config
        found = medir.from_deploy_status(status)
        self.assertEqual(found['image_landing_s'], [0.031])
        self.assertEqual(found['prewarm_task_usd'], [round(config.get('medir.prewarm_runner_usd_h'), 6),
                                                     round(2 * config.get('medir.prewarm_service_usd_h'), 6)])
        self.assertEqual((config.get('medir.prewarm_runner_usd_h'), config.get('medir.prewarm_service_usd_h')),
                         (0.029, 0.0031))
        self.assertNotIn('prewarm_task_usd', medir.from_deploy_status({'standby': []}))


@unittest.skipUnless(URL, 'needs TEST_DATABASE_URL (Postgres; local port 54322)')
class OnPostgres(unittest.TestCase):
    """The real statements: the swap of both rows in one statement with its event, the gates that see it, the handover and
    the retirement by compare-and-swap, and the status that shows them."""

    def setUp(self):
        from runner_world import RunnerWorld
        self.world = type('World', (RunnerWorld,), {'runTest': lambda self: None})()
        self.world.setUp()
        self.addCleanup(self.world.doCleanups)
        self.db = self.world.db

    def test_the_swap_handover_and_retirement_on_the_real_tables(self):
        said = self.world.port('POST', '/v1/deploy/landed', 'torre', {**landed(), 'functions': []})
        self.assertFalse(said['swap']['swapped'])  # IMAGE-SWAP-TIGHTEN: no bundle job here, so the autodeploy decides
        at = float(self.db.rows("select extract(epoch from occurred_at) from log.event where type = 'platform.deploy.landed'")[0][0])
        found = self.db.rows(autodeploy.SWAP_WRITE, {
            'tenant': 'torre', 'digest': S, 'keys': ','.join(KEYS), 'reason': 'test', 'id': f'{autodeploy.SWAP}:{MERGE}',
            'landed_at': at, 'payload': json.dumps({'digest': S, 'head': MERGE})})
        swap = json.loads(found[0][0])
        self.assertEqual((swap['swapped'], swap['versions']), (True, {key: 1 for key in KEYS}))
        self.assertGreaterEqual(swap['landed_s'], 0)
        self.assertIsInstance(swap['wrote_at'], float)
        rows = self.db.rows("select key, value::text, actor from work.config_value where key like 'deploy.live_image_%%' "
                            "order by key")
        self.assertEqual(rows, [(key, json.dumps(S), 'autodeploy') for key in KEYS])
        standby = live_image.gate('runner', S, live_image.kept(self.db), strict=True)
        ecs_service = live_image.gate('service', S, live_image.kept(self.db))
        old = live_image.gate('runner', 'registry/tower:old', live_image.kept(self.db))
        self.assertEqual((standby.active(), ecs_service.sharing(), old.active()), (True, True, False))
        self.assertTrue(ecs_service.handover())
        self.assertEqual(self.db.rows("select value::text, version::text from work.config_value where key = "
                                      "'deploy.live_image_service'"), [('""', '2')])
        again = self.db.rows(live_image.EMPTY, live_image.empty('torre', KEYS, OLD, 'x', {}, 'id-x', 'other digest'))
        self.assertEqual(again, [])  # compare-and-swap: a pointer that names another digest is never emptied
        done = self.db.rows(live_image.EMPTY, live_image.empty('torre', KEYS, S, 'autodeploy', {'by': 'reconciled'},
                                                               'id-y', 'test'))
        self.assertEqual(json.loads(done[0][0]), [live_image.KEYS['runner']])
        standby.refresh()
        self.assertEqual((standby.active(), standby.retired), (False, True))  # its slots end after their runs
        status = self.world.port('GET', '/v1/deploy/status', 'torre')
        self.assertEqual([each['swapped'] for each in status['image_swap']], [True])
        self.assertEqual([each.get('by') for each in status['image_retired']], ['reconciled', 'handover'])
        self.assertEqual(status['image_retired'][0]['keys'], [live_image.KEYS['runner']])
        landing = self.db.rows("select payload::text from log.event where type = 'platform.deploy.landed'")
        self.assertTrue(json.loads(landing[0][0])['code']['bundle_same'])  # the port keeps the delivery's word


if __name__ == '__main__':
    unittest.main()
