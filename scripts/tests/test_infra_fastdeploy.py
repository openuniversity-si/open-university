"""The fast deploy (DEP8): the alias swap, its smoke and rollback, the freshness guard, the autodeploy wiring, the task role's
IAM against the boundary, and the measures. Hermetic: boto-like fakes, a fake database, no AWS."""
import base64
import hashlib
import io
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'infra' / 'service'))
sys.path.insert(0, str(ROOT / 'scripts' / 'tests'))
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
from tower_infra import autodeploy, fastdeploy  # noqa: E402
import deploy_classify  # noqa: E402
import test_infra_autodeploy as base  # noqa: E402

DIGEST = hashlib.sha256(b'zip').hexdigest()
B64 = base64.b64encode(bytes.fromhex(DIGEST)).decode()


class FakeLambda:
    def __init__(self, live='4', fail=None, executed=None, status=200, error=None, alias_error=None, stale=0,
                 update_pending=0, version_pending=0, update_failed=False, conflicts=0, busy_before=0):
        self.live, self.fail, self.calls, self.executed, self.status, self.error = live, fail or {}, [], executed, status, error
        self.alias_error, self.stale, self.old = alias_error, stale, live  # stale: alias calls that still answer the old version
        self.codes = {'4': 'old'}
        self.updated = False
        self.update_pending, self.version_pending, self.update_failed = update_pending, version_pending, update_failed
        self.conflicts, self.busy_before = conflicts, busy_before

    def get_alias(self, **kw):
        self.calls.append(('get_alias', kw['FunctionName']))
        return {'FunctionVersion': self.live}

    def get_function_configuration(self, **kw):
        if 'Qualifier' in kw and kw['Qualifier'] != '5':
            return {'CodeSha256': self.codes.get(kw['Qualifier'])}
        if not self.updated:  # before the upload: the function is idle (or busy with an earlier update: busy_before)
            if self.busy_before > 0:
                self.busy_before -= 1
                return {'LastUpdateStatus': 'InProgress'}
            return {'LastUpdateStatus': 'Successful', 'CodeSha256': self.codes.get(kw.get('Qualifier'))}
        self.calls.append(('get_function_configuration', kw.get('Qualifier')))
        if self.update_failed:
            return {'LastUpdateStatus': 'Failed', 'LastUpdateStatusReason': 'ENI limit'}
        if 'Qualifier' not in kw:
            if self.update_pending > 0:
                self.update_pending -= 1
                return {'LastUpdateStatus': 'InProgress'}
            return {'LastUpdateStatus': 'Successful'}
        if self.version_pending > 0:
            self.version_pending -= 1
            return {'LastUpdateStatus': 'Successful', 'State': 'Pending'}
        return {'LastUpdateStatus': 'Successful', 'State': 'Active', 'CodeSha256': self.codes.get('5')}

    def update_function_code(self, **kw):
        self.calls.append(('update_function_code', kw['FunctionName'], kw['S3Key'], kw.get('Publish')))
        if self.conflicts > 0:
            self.conflicts -= 1
            raise RuntimeError('ResourceConflictException: update in progress')
        if 'update_function_code' in self.fail:
            raise self.fail['update_function_code']
        self.updated = True

    def publish_version(self, **kw):
        self.calls.append(('publish_version', kw['FunctionName']))
        assert self.updated_ok(), 'published before the update was Successful'
        self.codes['5'] = B64
        return {'Version': '5', 'CodeSha256': self.fail.get('sha', B64)}

    def updated_ok(self):
        return self.update_pending == 0 and not self.update_failed

    def update_alias(self, **kw):
        self.calls.append(('update_alias', kw['FunctionName'], kw['FunctionVersion']))
        self.live = kw['FunctionVersion']

    def invoke(self, **kw):
        self.calls.append(('invoke', kw['FunctionName'], kw['Qualifier']))
        body = json.dumps({'statusCode': self.status}).encode()
        if kw['Qualifier'] == fastdeploy.ALIAS:
            if self.stale > 0:  # eventual consistency: the alias still points at the old version
                self.stale -= 1
                version = self.old
            else:
                version = self.executed or self.live
            failed = self.alias_error
        else:  # a version by its qualifier is exact
            version, failed = kw['Qualifier'], self.error
        return {'Payload': io.BytesIO(body), 'ExecutedVersion': version, **({'FunctionError': 'Unhandled'} if failed else {})}


class FakeS3:
    def __init__(self, objects):
        self.objects = objects

    def get_object(self, Bucket, Key):
        if Key not in self.objects:
            raise KeyError(Key)
        return {'Body': io.BytesIO(json.dumps(self.objects[Key]).encode())}


def manifest(head, base_sha='b0', files=None):
    entry = {'sha256': DIGEST, 'key': f'artifacts/lambda/tower-port-api/{DIGEST}.zip', 'files': files or {'tower_infra/__init__.py': 'x', 'tower_infra/http_port.py': 'y'}}
    return {'head': head, 'base': base_sha, 'functions': {f: {**entry, 'key': entry['key'].replace('tower-port-api', f)} for f in fastdeploy.FUNCTIONS}}


def clock():
    ticks = iter([0.0, 0.0, 0.0, 0.0, 0.0, 0.0125] + [1.0] * 8)  # activate begin/end, smoke_pre begin/end, swap begin/end
    return lambda: next(ticks)


class Swap(unittest.TestCase):
    def deploy(self, lam):
        return fastdeploy.FastDeploy(lam, FakeS3({}), 'bucket', clock=clock(), sleep=lambda s: None,
                                     propagation_s=2).deploy('tower-port-api', manifest('h1'), 'h1')

    def test_update_publish_swap_smoke_in_that_order_and_the_swap_is_timed(self):
        lam = FakeLambda()
        entry = self.deploy(lam)
        self.assertEqual([c[0] for c in lam.calls], ['get_alias', 'update_function_code', 'get_function_configuration',
                                                       'publish_version', 'get_function_configuration', 'invoke', 'update_alias', 'invoke'])
        self.assertEqual([c[2] for c in lam.calls if c[0] == 'invoke'], ['5', 'live'])  # the version first, then the alias
        self.assertIsNone(lam.calls[1][3])  # no Publish: the version is made after the update is Successful
        self.assertIsNotNone(entry['activate_ms'])
        self.assertEqual((entry['ok'], entry['version'], entry['previous'], entry['swap_ms']), (True, '5', '4', 12.5))
        self.assertEqual(lam.live, '5')

    def test_pending_and_in_progress_are_waited_for_then_the_swap_goes_on(self):
        lam = FakeLambda(update_pending=3, version_pending=4, conflicts=2, busy_before=2)
        sleeps = []
        entry = fastdeploy.FastDeploy(lam, FakeS3({}), 'bucket', clock=lambda: 0.0, sleep=sleeps.append,
                                      propagation_s=2).deploy('tower-port-api', manifest('h1'), 'h1')
        self.assertEqual((entry['ok'], entry['version'], lam.live), (True, '5', '5'))
        self.assertGreaterEqual(len(sleeps), 9)
        self.assertEqual([c[0] for c in lam.calls].count('update_function_code'), 3)  # two conflicts, then accepted

    def test_a_version_that_never_becomes_active_is_not_active_in_n_s_and_never_swaps(self):
        now = [0.0]
        lam = FakeLambda(version_pending=10 ** 6)

        def sleep(seconds):
            now[0] += seconds
        entry = fastdeploy.FastDeploy(lam, FakeS3({}), 'bucket', clock=lambda: now[0], sleep=sleep, propagation_s=2,
                                      activate_s=30).deploy('tower-port-api', manifest('h1'), 'h1')
        self.assertEqual((entry['ok'], entry['smoke_pre'], entry['rolled_back'], lam.live), (False, 'not active in 30 s', False, '4'))
        self.assertNotIn('update_alias', [c[0] for c in lam.calls])
        self.assertNotIn('invoke', [c[0] for c in lam.calls])
        self.assertGreaterEqual(entry['activate_ms'], 30000)

    def test_a_conflict_that_never_clears_ends_as_not_active(self):
        now = [0.0]
        lam = FakeLambda(conflicts=10 ** 6)

        def sleep(seconds):
            now[0] += seconds
        entry = fastdeploy.FastDeploy(lam, FakeS3({}), 'bucket', clock=lambda: now[0], sleep=sleep, propagation_s=2,
                                      activate_s=10).deploy('tower-port-api', manifest('h1'), 'h1')
        self.assertEqual((entry['ok'], entry['smoke_pre'], lam.live), (False, 'not active in 10 s', '4'))

    def test_a_failed_update_aborts_with_its_reason(self):
        lam = FakeLambda(update_failed=True)
        entry = self.deploy(lam)
        self.assertFalse(entry['ok'])
        self.assertIn('ENI limit', entry['reason'])
        self.assertNotIn('publish_version', [c[0] for c in lam.calls])
        self.assertEqual(lam.live, '4')

    def test_a_red_pre_smoke_never_swaps_and_needs_no_rollback(self):
        for kind in ({'error': True}, {'status': 503}):
            lam = FakeLambda(**kind)
            entry = self.deploy(lam)
            self.assertFalse(entry['ok'], kind)
            self.assertFalse(entry['rolled_back'], kind)
            self.assertEqual((entry['smoke_pre'], entry['swap_ms']), ('failed', None))
            self.assertNotIn('update_alias', [c[0] for c in lam.calls])
            self.assertEqual(lam.live, '4')
            self.assertIn('smoke', entry['reason'])

    def test_an_alias_that_answers_the_old_version_for_a_while_is_propagation_not_failure(self):
        lam = FakeLambda(stale=3)
        entry = self.deploy(lam)
        self.assertEqual((entry['ok'], entry['rolled_back'], entry['propagated'], lam.live), (True, False, True, '5'))
        self.assertIsNotNone(entry['propagation_ms'])
        self.assertEqual(entry['smoke_pre'], 'ok')
        self.assertIsNotNone(entry['smoke_pre_ms'])
        self.assertEqual(len([c for c in lam.calls if c[0] == 'invoke' and c[2] == 'live']), 4)

    def test_a_propagation_that_does_not_converge_in_the_window_is_recorded_and_kept(self):
        lam = FakeLambda(stale=10 ** 6)
        ticks = iter(range(0, 100))
        entry = fastdeploy.FastDeploy(lam, FakeS3({}), 'bucket', clock=lambda: next(ticks) * 0.5, sleep=lambda s: None,
                                      propagation_s=2).deploy('tower-port-api', manifest('h1'), 'h1')
        self.assertEqual((entry['ok'], entry['propagated'], entry['rolled_back'], lam.live), (True, False, False, '5'))
        self.assertIsNotNone(entry['propagation_ms'])
        self.assertEqual(entry['smoke'], 'ok')

    def test_an_alias_that_answers_an_error_after_the_swap_is_rolled_back(self):
        for kind in ({'alias_error': True}, {'status': 503, 'stale': 0, 'executed': '5'}):
            lam = FakeLambda(**kind)
            if 'status' in kind:  # healthy by version, unhealthy through the alias
                lam.invoke = (lambda real: lambda **kw: real(**kw) if kw['Qualifier'] != 'live' else
                              {'Payload': io.BytesIO(b'{"statusCode": 503}'), 'ExecutedVersion': '5'})(lam.invoke)
                lam.status = 200
            entry = self.deploy(lam)
            self.assertFalse(entry['ok'], kind)
            self.assertTrue(entry['rolled_back'], kind)
            self.assertEqual(lam.live, '4', kind)
            self.assertIn('smoke', entry['reason'])

    def test_a_package_that_is_not_the_artifact_is_not_swapped_to(self):
        lam = FakeLambda(fail={'sha': 'AAAA'})
        entry = self.deploy(lam)
        self.assertFalse(entry['ok'])
        self.assertNotIn('update_alias', [c[0] for c in lam.calls])
        self.assertEqual(lam.live, '4')

    def test_an_error_before_the_swap_changes_nothing_and_is_recorded(self):
        lam = FakeLambda(fail={'update_function_code': RuntimeError('AccessDeniedException')})
        entry = self.deploy(lam)
        self.assertEqual((entry['ok'], entry['rolled_back'], lam.live), (False, False, '4'))
        self.assertIn('AccessDeniedException', entry['reason'])

    def test_the_version_already_live_is_not_swapped_again(self):
        lam = FakeLambda()
        lam.codes['4'] = B64
        entry = self.deploy(lam)
        self.assertEqual((entry['ok'], entry['reason']), (True, 'already live'))
        self.assertEqual([c[0] for c in lam.calls], ['get_alias'])


class Freshness(unittest.TestCase):
    def test_a_push_between_the_base_and_the_merge_that_touched_the_files_makes_it_stale(self):
        found = manifest('h1')
        fresh = fastdeploy.FastDeploy.fresh
        self.assertTrue(fresh('tower-port-api', found, []))
        self.assertTrue(fresh('tower-port-api', found, [['docs/a.md'], ['infra/service/tower_infra/ingress.py']]))
        self.assertFalse(fresh('tower-port-api', found, [['infra/service/tower_infra/http_port.py']]))
        self.assertFalse(fresh('tower-port-api', found, [None]))  # a push that did not list its paths: unknown
        self.assertFalse(fresh('tower-port-api', found, None))  # the base is not among the pushes

    def test_the_manifest_is_found_by_any_commit_of_the_push_and_must_name_that_head(self):
        s3 = FakeS3({'artifacts/lambda/head/pr.json': manifest('pr'), 'artifacts/lambda/head/liar.json': manifest('other')})
        fast = fastdeploy.FastDeploy(FakeLambda(), s3, 'bucket')
        self.assertEqual(fast.manifest(['merge', 'pr'])['head'], 'pr')
        self.assertIsNone(fast.manifest(['merge', 'liar']))
        self.assertIsNone(fast.manifest(['nothing']))


class Tables(unittest.TestCase):
    def test_the_service_table_agrees_with_the_classifier_on_every_module(self):
        for path in sorted((ROOT / 'infra/service/tower_infra').glob('*.py')) + [ROOT / 'infra/ingress/__init__.py']:
            relative = path.relative_to(ROOT).as_posix()
            classified = {t.split('fast:lambda-', 1)[1] for t in deploy_classify.classify([relative])['fast']}
            expected = {'port': 'tower-port-api', 'ingress': 'tower-port-ack-ingress', 'webhooks': 'tower-port-webhook-consumer'}
            wanted = sorted(expected[c] for c in classified) if 'all' not in classified else sorted(fastdeploy.FUNCTIONS)
            self.assertEqual(fastdeploy.functions_of([relative]), wanted, relative)

    def test_a_module_two_packages_hold_swaps_both_and_a_service_only_module_none(self):
        """SLOW-PATH-NO-ROLLOUT-WAIT: the consumer imports http_port, and both packages hold config_data (LANDING-PREWARM-GONE:
        live_image is the service's alone now, the port's landing imports it no more)."""
        for module in ('http_port', 'config_data'):
            self.assertEqual(fastdeploy.functions_of([f'infra/service/tower_infra/{module}.py']),
                             ['tower-port-api', 'tower-port-webhook-consumer'], module)
        self.assertEqual(fastdeploy.functions_of(['infra/service/tower_infra/autodeploy.py', 'docs/a.md']), [])
        self.assertEqual(fastdeploy.functions_of(['infra/service/tower_infra/live_image.py']), [])

    def test_every_function_has_a_smoke_and_a_parameter(self):
        self.assertEqual(sorted(fastdeploy.SMOKE), sorted(fastdeploy.FUNCTIONS))


class Wiring(unittest.TestCase):
    """autodeploy: the push that changed a port Lambda's file is swapped before the debounce, once, with the events."""
    HEAD, MERGE = base.HEAD, 'f' * 40

    def rig(self, paths, lam=None, objects=None, pr_commit='p' * 40):
        lam = lam or FakeLambda()
        fast = fastdeploy.FastDeploy(lam, FakeS3(objects if objects is not None else {f'artifacts/lambda/head/{pr_commit}.json': manifest(pr_commit, self.HEAD)}),
                                     'bucket', clock=clock())
        rig = base.Rig(fast=fast)
        rig.db.artifacts[pr_commit] = {function: DIGEST for function in fastdeploy.FUNCTIONS}  # its gate job said them
        rig.params[autodeploy.LAST_SHA] = self.HEAD
        rig.build('succeeded', self.HEAD, base.T0 - 5000, base.T0 - 4500, build_id='old')
        rig.db.push(base.T0 - 90000, self.HEAD)
        rig.db.push(base.T0 - 3, self.MERGE, headCommit={'modified': paths, 'id': self.MERGE}, commits=[{'id': pr_commit}])
        rig.lam = lam
        return rig

    def test_a_manifest_another_check_wrote_or_one_no_gate_job_vouches_for_is_never_swapped(self):
        # DIGEST-FROM-GATE-JOB (revisão da arquitetura, achado 35): the runner's role writes artifacts/lambda/*, and every check
        # of any PR runs there: a manifest of this head naming another package (its zip passes the digest check, being that
        # package) was put live by the landing. The digests the gate's own artifact job of the head said decide
        rig = self.rig(['infra/service/tower_infra/ingress.py'])
        rig.db.artifacts['p' * 40] = {function: 'e' * 64 for function in fastdeploy.FUNCTIONS}  # the job built other bytes
        rig.look()
        self.assertEqual([c for c in rig.lam.calls if c[0] in ('update_function_code', 'update_alias')], [])
        skipped = rig.db.observed[-1][1]['fast'][-1]
        self.assertEqual((skipped['function'], skipped['ok']), ('tower-port-ack-ingress', None))
        self.assertIn("the gate's own artifact job of this head did not say it built", skipped['skipped'])
        rig = self.rig(['infra/service/tower_infra/ingress.py'])
        del rig.db.artifacts['p' * 40]  # no artifact job of the head at all (or it did not succeed)
        rig.look()
        self.assertEqual([c for c in rig.lam.calls if c[0] == 'update_alias'], [])

    def test_a_merge_that_changed_the_ingress_swaps_its_alias_and_records_the_events(self):
        rig = self.rig(['infra/service/tower_infra/ingress.py'])
        rig.look()
        self.assertEqual([c for c in rig.lam.calls if c[0] == 'update_alias'], [('update_alias', 'tower-port-ack-ingress', '5')])
        kinds = [kind for kind, _ in rig.db.inserted]
        self.assertIn(autodeploy.FAST, kinds)
        fast = next(p for k, p in rig.db.inserted if k == autodeploy.FAST)
        self.assertEqual((fast['function'], fast['version'], fast['sha'], fast['ok']), ('tower-port-ack-ingress', '5', self.MERGE, True))
        self.assertIsNotNone(fast['swap_ms'])
        self.assertEqual(rig.db.observed[-1][1]['fast'][-1]['function'], 'tower-port-ack-ingress')  # GET /v1/deploy/status
        rig.look(1)
        self.assertEqual(len([c for c in rig.lam.calls if c[0] == 'update_alias']), 1)  # a head is tried once

    def test_the_swaps_shown_survive_a_restart_of_the_service(self):
        # FAST-DURABLE: a new process reads the swaps back from the log before its first observation, so the status's
        # `fast` (which the slow path reads to skip the port stack) does not empty when the service restarts
        rig = self.rig(['infra/service/tower_infra/ingress.py'])
        rig.look()
        rig.watcher.fast_log, rig.watcher.fast_seeded = [], False  # what a restarted process starts with
        rig.look(1)
        shown = rig.db.observed[-1][1]['fast']
        self.assertEqual([(each['function'], each['ok']) for each in shown], [('tower-port-ack-ingress', True)])
        self.assertIsInstance(shown[-1]['at'], int)

    def test_the_swap_happens_while_a_slow_build_is_in_flight_and_inside_the_debounce(self):
        rig = self.rig(['infra/service/tower_infra/http_port.py'])
        rig.build('in_progress', self.HEAD, base.T0 - 1800, None, build_id='slow')
        rig.watcher.running_until, rig.watcher.running_since = base.T0 + 600, base.T0 - 1800  # the doorbell said 409
        decision = rig.look()
        self.assertIn('running', decision[1])  # the slow path waits ...
        self.assertEqual([c for c in rig.lam.calls if c[0] == 'update_alias'], [('update_alias', 'tower-port-api', '5')])  # ... the fast one did not
        fast = rig.db.observed[-1][1]['fast'][-1]
        self.assertEqual((fast['function'], fast['from_version'], fast['to_version'], fast['sha'], fast['smoke'], fast['ok']),
                         ('tower-port-api', '4', '5', self.MERGE, 'ok', True))
        self.assertIsNotNone(fast['swap_ms'])

    def test_the_swap_does_not_wait_for_the_debounce_nor_for_auto(self):
        rig = self.rig(['infra/service/tower_infra/http_port.py'])
        rig.params['x'] = None
        rig.watcher.overrides = {'deploy.auto': (0, False)}
        rig.look()
        self.assertEqual(len([c for c in rig.lam.calls if c[0] == 'update_alias']), 1)

    def test_a_push_to_another_ref_does_not_reset_the_debounce_of_the_base(self):
        rig = self.rig(['docs/x.md'])
        rig.db.push(base.T0 - 1, 'e' * 40, ref='refs/heads/train/events')
        rig.db.push(base.T0 - 1, 'd' * 40, ref='refs/heads/units/other')
        rig.now = base.T0 + 25  # the base push is 28s old of 20
        self.assertEqual(rig.watcher.newest_push(rig.db, base.BASE, rig.now), (self.MERGE, base.T0 - 3))
        self.assertNotIn('debounce', str(rig.look()))

    def test_one_swap_at_a_time_per_function_only(self):
        rig = self.rig(['infra/service/tower_infra/http_port.py'])
        rig.db.free = False  # another task holds the lock of the function
        rig.look()
        self.assertEqual([c for c in rig.lam.calls if c[0] == 'update_alias'], [])
        self.assertEqual(rig.db.observed[-1][1]['fast'][-1]['skipped'], 'another task is swapping this function')

    def test_a_swap_another_task_made_is_shown_once_it_is_in_the_log(self):
        """FAST-SEEN-ACROSS-TASKS: at a landing the two service processes (the one the swap retires and the one it
        promotes) both look; one takes a function's lock and swaps it, the other says `another task is swapping this
        function` and went on showing that, from its own memory, for as long as it lived: the swap the other recorded was
        never in its list. Live 12/11 03:59 UTC (#562): the status kept tower-port-api at ok null for the head, the
        slow path found no swap of it to skip the port stack by, and applied the stack (43 s). While a skip of that
        kind is not answered, the look reads the log's swaps again; the other task's swap takes the skip's place."""
        rig = self.rig(['infra/service/tower_infra/http_port.py'])
        seeds, rows = [], rig.db.rows
        rig.db.rows = lambda sql, params=None: (seeds.append(sql) if sql == autodeploy.FAST_SEED else None, rows(sql, params))[1]
        rig.db.free = False  # the other task holds the lock of the function
        rig.look()
        shown = rig.db.observed[-1][1]['fast']
        both = ['tower-port-api', 'tower-port-webhook-consumer']  # the port's module is in both packages
        self.assertEqual(sorted((each['function'], each['ok'], each['skipped']) for each in shown),
                         [(name, None, 'another task is swapping this function') for name in both])
        # the other task ends its swaps and records them, as this one would (autodeploy.FAST, the log's)
        for n, name in enumerate(both):
            rig.db.ledger.append((autodeploy.FAST, base.at(rig.now + 5 + n), {
                'function': name, 'sha': self.MERGE, 'ok': True, 'version': '5', 'previous': '4', 'swap_ms': 41.0,
                'rolled_back': False, 'reason': None}))
        reads = len(seeds)
        rig.look(10)
        shown = rig.db.observed[-1][1]['fast']
        self.assertEqual([(each['function'], each['ok'], each.get('skipped')) for each in shown if each['sha'] == self.MERGE],
                         [(name, True, None) for name in both])  # one line for each function at this head: its swap
        self.assertEqual(len(seeds), reads + 1)
        rig.look(10)
        self.assertEqual(len(seeds), reads + 1)  # answered: no more reads

    def test_a_red_smoke_swaps_back_and_the_status_says_so(self):
        rig = self.rig(['infra/service/tower_infra/ingress.py'], lam=FakeLambda(alias_error=True))  # one package: the fake is one function
        rig.look()
        self.assertEqual(rig.lam.live, '4')
        fast = rig.db.observed[-1][1]['fast'][-1]
        self.assertEqual((fast['ok'], fast['rolled_back']), (False, True))
        self.assertNotEqual(fast['smoke'], 'ok')
        self.assertIsInstance(fast['rollback_ms'], float)  # FAST-ROLLBACK-MS: the pointer written back, timed
        import medir
        self.assertEqual(medir.from_deploy_status({'fast': [fast, {'rolled_back': True}, {'rollback_ms': 5.0}]}),
                         {'fast_rollback_ms': [fast['rollback_ms']]})

    def test_a_rollback_is_an_event_too(self):
        rig = self.rig(['infra/service/tower_infra/ingress.py'], lam=FakeLambda(alias_error=True))
        rig.look()
        self.assertIn(autodeploy.ROLLEDBACK, [kind for kind, _ in rig.db.inserted])

    def test_nothing_changes_without_an_artifact_or_for_files_no_lambda_holds(self):
        for paths, objects in ((['infra/service/tower_infra/ingress.py'], {}), (['infra/service/tower_infra/autodeploy.py'], None),
                               (['docs/x.md'], None)):
            rig = self.rig(paths, objects=objects)
            rig.look()
            self.assertEqual([c for c in rig.lam.calls if c[0] == 'update_alias'], [], paths)

    def test_a_stale_artifact_is_not_swapped(self):
        rig = self.rig(['infra/service/tower_infra/ingress.py'])
        rig.db.pushes.insert(1, (base.at(base.T0 - 50), [{'ref': f'refs/heads/{base.BASE}', 'after': 'c' * 40, 'deleted': False,
                                                         'headCommit': {'modified': ['infra/ingress/__init__.py']}}]))
        rig.db.pushes[0][1][0]['after'] = self.HEAD
        rig.look()
        self.assertEqual([c for c in rig.lam.calls if c[0] == 'update_alias'], [])

    def test_without_the_artifact_bucket_there_is_no_fast_path(self):
        rig = base.Rig()
        self.assertIsNone(rig.watcher.fast)
        self.assertIsNone(autodeploy.from_boto3(rig.scope, {'TOWER_DOORBELL_FUNCTION': None}))


class Iam(unittest.TestCase):
    def test_the_task_role_gets_exactly_the_five_lambda_actions_on_the_three_functions_and_the_artifacts_read(self):
        service = base.load(ROOT / 'infra/aws/stacks/30-service.json')
        statements = next(r for r in service['Resources'].values() if r.get('Properties', {}).get('RoleName') == 'tower-app-service'
                          )['Properties']['Policies']
        fast = next(s for p in statements for s in p['PolicyDocument']['Statement'] if s['Sid'] == 'SwapThePortAliases')
        self.assertEqual(sorted(fast['Action']), ['lambda:GetAlias', 'lambda:GetFunctionConfiguration', 'lambda:InvokeFunction',
                                                  'lambda:PublishVersion', 'lambda:UpdateAlias', 'lambda:UpdateFunctionCode'])
        text = json.dumps(fast['Resource'])
        self.assertIn('function:tower-port-api', text)
        for gone in ('tower-port-ack-ingress', 'tower-port-webhook-consumer'):  # TASKROLE-LEAST: they left the port stack
            self.assertNotIn(gone, text)
        self.assertNotIn('doorbell', text)
        read = next(s for p in statements for s in p['PolicyDocument']['Statement'] if s['Sid'] == 'ReadTheLambdaArtifacts')
        self.assertEqual(read['Action'], 's3:GetObject')
        self.assertIn('artifacts/lambda/*', json.dumps(read['Resource']))

    def test_the_boundary_allows_them_and_denies_the_code_update_only_on_the_doorbell(self):
        boundary = json.dumps(json.loads((ROOT / 'infra/aws/bootstrap.json').read_text()))
        self.assertIn('"lambda:*"', boundary)
        denied = json.loads((ROOT / 'infra/aws/bootstrap.json').read_text())
        text = json.dumps(denied)
        index = text.index('"lambda:UpdateFunctionCode"')
        window = text[index:index + 900]
        self.assertIn('tower-deploy-doorbell', window)
        for function in fastdeploy.FUNCTIONS:
            self.assertNotIn(function, window)


class Measures(unittest.TestCase):
    def test_medir_lists_the_swap_milliseconds_and_the_port_serves_them(self):
        import medir
        found = medir.from_deploy_status({'fast': [{'function': 'tower-port-api', 'swap_ms': 90.5, 'activate_ms': 4100.0, 'propagation_ms': 1200.0, 'ok': True},
                                                   {'function': 'tower-port-api', 'swap_ms': None, 'ok': False}]})
        self.assertEqual(found, {'fast_swap_ms': [90.5], 'fast_activate_ms': [4100.0], 'fast_propagation_ms': [1200.0]})
        self.assertEqual(medir.from_deploy_status({}), {})


if __name__ == '__main__':
    unittest.main()
