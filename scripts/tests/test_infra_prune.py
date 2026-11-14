"""LAMBDA-PRUNE (the review's finding 26): the port Lambdas' old versions and the unnamed old packages under artifacts/lambda/
are deleted once a day; the aliased, the newest, the stack's own and every named package stay. Fake Lambda, S3, ECS and log."""
import json
from pathlib import Path
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'infra' / 'service'))
from tower_infra import prune  # noqa: E402

DAY = 86400.0
NOW = 1_800_000_000.0
DIGEST = 'a' * 64
SLOW = f'slow deploy of artifacts/lambda/tower-port-api/{"b" * 64}.zip on artifacts/lambda/deps/{"c" * 64}.zip with 256 MB'


class Lambda:
    def __init__(self, versions, aliases, page=3):
        self.versions, self.aliases, self.page, self.deleted, self.refuse = versions, aliases, page, [], set()

    def list_versions_by_function(self, FunctionName, Marker=None):
        items = [{'Version': '$LATEST'}] + self.versions.get(FunctionName, [])
        start = int(Marker or 0)
        out = {'Versions': items[start:start + self.page]}
        if start + self.page < len(items):
            out['NextMarker'] = str(start + self.page)
        return out

    def list_aliases(self, FunctionName, Marker=None):
        return {'Aliases': self.aliases.get(FunctionName, [])}

    def delete_function(self, FunctionName, Qualifier=None):
        assert Qualifier and Qualifier.isdigit(), 'only a qualified version may be deleted'
        if (FunctionName, Qualifier) in self.refuse:
            raise RuntimeError('ResourceConflictException')
        self.deleted.append((FunctionName, int(Qualifier)))


class S3:
    def __init__(self, objects):
        self.objects, self.deleted, self.fail = objects, [], set()

    def list_objects_v2(self, Bucket, Prefix, ContinuationToken=None):
        assert (Bucket, Prefix) == ('bucket', 'artifacts/lambda/')
        start = int(ContinuationToken or 0)
        out = {'Contents': self.objects[start:start + 2]}
        if start + 2 < len(self.objects):
            out['NextContinuationToken'] = str(start + 2)
        return out

    def delete_objects(self, Bucket, Delete):
        keys = [item['Key'] for item in Delete['Objects']]
        self.deleted.extend(key for key in keys if key not in self.fail)
        return {'Errors': [{'Key': key} for key in keys if key in self.fail]}


class Ecs:
    def __init__(self, env=None, broken=False):
        self.env, self.broken = env or {}, broken

    def describe_services(self, cluster, services):
        assert cluster == 'tower' and services == ['tower-service', 'tower-runner']
        if self.broken:
            raise RuntimeError('AccessDenied')
        return {'services': [{'taskDefinition': 'arn:task-definition/tower-service:41'},
                             {'taskDefinition': 'arn:task-definition/tower-runner:12'}]}

    def describe_task_definition(self, taskDefinition):
        if taskDefinition == 'tower-service-standby':
            raise RuntimeError('ClientException: Unable to describe task definition.')
        return {'taskDefinition': {'containerDefinitions': [
            {'environment': [{'name': name, 'value': value} for name, value in self.env.get(taskDefinition, {}).items()]}]}}


class Log:
    def __init__(self, last=None, code=None):
        self.last, self.code, self.said = last, code, []

    def rows(self, sql, params=None):
        if sql == prune.LAST:
            return [(self.last,)]
        if sql == prune.LIVE_CODE:
            return [(self.code,)] if self.code else []
        if sql == prune.SAY:
            self.said.append(json.loads(params['payload']))
            return []
        raise AssertionError(sql)


def obj(key, days_old, size=100):
    return {'Key': key, 'LastModified': NOW - days_old * DAY, 'Size': size}


def versions(numbers, slow=()):
    return [{'Version': str(n), **({'Description': SLOW} if n in slow else {})} for n in numbers]


class Doomed(unittest.TestCase):
    def test_keeps_the_newest_the_aliased_with_their_weights_and_the_newest_slow_one(self):
        found = prune.doomed(versions(range(1, 21), slow=(3, 5)), [
            {'Name': 'live', 'FunctionVersion': '7', 'RoutingConfig': {'AdditionalVersionWeights': {'2': 0.1}}}], keep=10)
        self.assertEqual(found, [1, 3, 4, 6, 8, 9, 10])  # 11..20 newest, 7 live, 2 weighted, 5 the newest slow one

    def test_nothing_when_there_are_no_more_than_kept(self):
        self.assertEqual(prune.doomed(versions(range(1, 11)), [{'FunctionVersion': '10'}], keep=10), [])

    def test_latest_is_never_a_number(self):
        self.assertEqual(prune.doomed([{'Version': '$LATEST'}], [], keep=0), [])


class Run(unittest.TestCase):
    def rig(self, env=None, code=None, broken=False, objects=None, last=None):
        lam = Lambda({'tower-port-api': versions(range(1, 16), slow=(4,)),
                      'tower-port-webhook-consumer': versions(range(1, 4))},
                     {'tower-port-api': [{'Name': 'live', 'FunctionVersion': '15'}]})
        s3 = S3(objects if objects is not None else [
            obj('artifacts/lambda/tower-port-api/old.zip', 40),
            obj('artifacts/lambda/tower-port-api/new.zip', 3),
            obj(f'artifacts/lambda/tower-port-api/{"b" * 64}.zip', 90),  # named by the kept slow version 4
            obj(f'artifacts/lambda/deps/{"c" * 64}.zip', 90),  # its layer
            obj(f'artifacts/lambda/tower-code/{DIGEST}.zip', 60),  # deploy.live_code
            obj(f'artifacts/lambda/tower-code/{"d" * 64}.zip', 45),  # the service's task definition
            obj('artifacts/lambda/head/0123abc.json', 31, size=7)])
        ecs = Ecs({'arn:task-definition/tower-service:41': {
            'TOWER_CODE_KEY': f'artifacts/lambda/tower-code/{"d" * 64}.zip', 'AWS_REGION': 'us-east-1'}}, broken)
        log = Log(last=last, code=code)
        return prune.Prune(lam, s3, ecs, 'bucket', 'tower', clock=lambda: NOW), lam, s3, log

    def test_deletes_the_old_versions_and_the_unnamed_old_packages_and_says_it(self):
        look, lam, s3, log = self.rig(code=f'{DIGEST}@0123456789abcdef')
        said = look.step(log)
        self.assertEqual(lam.deleted, [('tower-port-api', n) for n in (1, 2, 3, 5)])  # 4 slow, 6..15 newest, 15 live
        self.assertEqual(sorted(s3.deleted), ['artifacts/lambda/head/0123abc.json', 'artifacts/lambda/tower-port-api/old.zip'])
        self.assertEqual(log.said, [said])
        self.assertEqual((said['state'], said['objects'], said['bytes']), ('done', 2, 107))
        self.assertEqual(said['versions'], {'tower-port-api': [1, 2, 3, 5]})  # GATE-SHUTDOWN: the API is the one function
        self.assertEqual(said['kept'], {'tower-port-api': 11})

    def test_a_function_that_is_gone_is_skipped_and_the_pass_goes_on(self):
        look, lam, s3, log = self.rig(code=f'{DIGEST}@0123456789abcdef')

        class NotFound(Exception):
            pass
        NotFound.__name__ = 'ResourceNotFoundException'

        def gone(**kwargs):
            raise NotFound('Function not found: tower-port-api')
        lam.list_versions_by_function = gone
        with mock.patch.object(prune, 'FUNCTIONS', ('tower-port-api',)):
            said = look.step(log)
        self.assertEqual((said['state'], said['versions']), ('done', {}))
        self.assertIn('artifacts/lambda/tower-port-api/old.zip', s3.deleted)  # the packages' part still ran

    def test_without_every_reference_read_no_package_is_deleted_but_the_versions_still_are(self):
        look, lam, s3, log = self.rig(code=f'{DIGEST}@0123456789abcdef', broken=True)
        said = look.step(log)
        self.assertEqual(s3.deleted, [])
        self.assertEqual(said['objects'], 0)
        self.assertIn('AccessDenied', said['packages_skipped'])
        self.assertEqual(len(lam.deleted), 4)

    def test_the_live_code_keeps_its_bundle(self):
        look, lam, s3, log = self.rig(code=None)
        look.step(log)
        self.assertIn(f'artifacts/lambda/tower-code/{DIGEST}.zip', s3.deleted)

    def test_a_version_lambda_refuses_and_an_object_s3_refuses_are_not_counted(self):
        look, lam, s3, log = self.rig(code=f'{DIGEST}@0123456789abcdef')
        lam.refuse.add(('tower-port-api', '2'))
        s3.fail.add('artifacts/lambda/tower-port-api/old.zip')
        said = look.step(log)
        self.assertEqual(said['versions']['tower-port-api'], [1, 3, 5])
        self.assertEqual((said['objects'], said['bytes']), (1, 7))

    def test_once_a_day_after_the_last_pass_the_log_says(self):
        look, lam, s3, log = self.rig(last=NOW - DAY + 60)
        self.assertIsNone(look.step(log))
        self.assertEqual((lam.deleted, log.said), ([], []))
        look.clock = lambda: NOW + 61
        self.assertEqual(look.step(log)['state'], 'done')
        self.assertIsNone(look.step(log))  # the next one a day later

    def test_off_without_the_bucket_or_the_cluster(self):
        self.assertIsNone(prune.start(None, None, None, environ={'TOWER_ARTIFACT_BUCKET': 'b'}))


if __name__ == '__main__':
    unittest.main()
