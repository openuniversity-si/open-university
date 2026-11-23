"""tower-gate-attester (THREAT-gate, C7, D-359 Salto 2): the AWS verifier of tower/gate-attested. Hermetic: no network.

Verifies: REQ-github-truth
"""
import base64
import itertools
import hashlib
import hmac
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
import urllib.parse
from http import HTTPStatus
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
HERE = ROOT / 'infra' / 'aws' / 'attester'
sys.path.insert(0, str(HERE))
import app_manifest  # noqa: E402
import attester  # noqa: E402

SHA = 'b' * 40
PREFIX = 'a' * 40
OTHER = 'c' * 40
APP = attester.ACTIONS_APP_ID * 2
ACTIONS = attester.ACTIONS_APP_ID
IDS = itertools.count(attester.MAX_FILES)
NOW = attester.MAX_FILES ** 2
HOOK_URL = urllib.parse.urlunsplit(('https', 'hook.test', '/', '', ''))
APP_URL = urllib.parse.urlunsplit(('https', 'apps.test', '/s', '', ''))


def rid():
    return next(IDS)
REPO = 'openuniversity-si/open-university'


def cfg(**over):
    base = {'repo': REPO, 'base': 'main', 'app_id': APP, 'actions_app_id': ACTIONS, 'required': attester.REQUIRED,
            'key_secret': 'k', 'hook_secret': 'h'}
    base.update(over)
    return base


def run(name, conclusion='success', status='completed', app=ACTIONS, sha=SHA):
    return {'id': rid(), 'name': name, 'status': status, 'conclusion': conclusion if status == 'completed' else None,
            'head_sha': sha, 'app': {'id': app}}


def green(sha=SHA):
    return [run(n, sha=sha) for n in attester.REQUIRED]


class FakeGitHub:
    def __init__(self, routes):
        self.routes = routes
        self.posts = []

    def call(self, method, path, body=None):
        if method == 'POST':
            self.posts.append((path, body))
            return {'id': 1}
        for prefix, value in self.routes.items():
            if path.startswith(prefix):
                return value
        raise AssertionError(f'unexpected GET {path}')

    def pages(self, path, key=None, limit=None):
        got = self.call('GET', path)
        return got.get(key, []) if key else got


def pr(files=1, head_repo=REPO, base='main', number=7, sha=SHA):
    return {'number': number, 'state': 'open', 'changed_files': files, 'base': {'ref': base},
            'head': {'sha': sha, 'repo': {'full_name': head_repo}}}


def routes_pr(files, runs, comments=(), perm='admin', head_repo=REPO):
    return {
        f'/repos/{REPO}/pulls/7/files': [{'filename': f} for f in files],
        f'/repos/{REPO}/pulls/7': pr(len(files), head_repo=head_repo),
        f'/repos/{REPO}/commits/{SHA}/check-runs': {'check_runs': runs},
        f'/repos/{REPO}/issues/7/comments': list(comments),
        f'/repos/{REPO}/collaborators/': {'permission': perm},
    }


class Rs256Tests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('openssl'), 'openssl absent')
    def test_signature_equals_openssl_for_pkcs1_and_pkcs8(self):
        with tempfile.TemporaryDirectory() as tmp:
            key = Path(tmp) / 'k.pem'
            subprocess.run(['openssl', 'genrsa', '-traditional', '-out', str(key), '2048'], check=True,
                           capture_output=True)
            p8 = Path(tmp) / 'k8.pem'
            subprocess.run(['openssl', 'pkcs8', '-topk8', '-nocrypt', '-in', str(key), '-out', str(p8)], check=True)
            msg = Path(tmp) / 'm'
            msg.write_bytes(b'header.payload')
            want = subprocess.run(['openssl', 'dgst', '-sha256', '-sign', str(key), str(msg)], check=True,
                                  capture_output=True).stdout
            for pem in (key, p8):
                self.assertEqual(attester.rs256(attester.rsa_key(pem.read_text()), b'header.payload'), want)
            token = attester.app_jwt(APP, key.read_text(), now=NOW)
            head, body, _ = token.split('.')
            claims = json.loads(base64.urlsafe_b64decode(body + '=='))
            self.assertEqual(json.loads(base64.urlsafe_b64decode(head + '==')), {'alg': 'RS256', 'typ': 'JWT'})
            self.assertEqual(claims['iss'], str(APP))
            self.assertLess(claims['iat'], NOW)
            self.assertLess(NOW, claims['exp'])


class FrontTests(unittest.TestCase):
    def test_signature(self):
        body = b'{"a":1}'
        good = 'sha256=' + hmac.new(b's', body, hashlib.sha256).hexdigest()
        self.assertTrue(attester.signed('s', body, good))
        self.assertFalse(attester.signed('s', body + b' ', good))
        self.assertFalse(attester.signed('s', body, None))
        self.assertFalse(attester.signed('s', body, good.replace('sha256=', 'sha1=')))

    def event(self, name, payload, secret='s', sign=True):
        body = json.dumps(payload).encode()
        sig = 'sha256=' + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest() if sign else 'sha256=0'
        return {'headers': {'X-GitHub-Event': name, 'X-Hub-Signature-256': sig, 'X-GitHub-Delivery': 'd1'},
                'body': base64.b64encode(body).decode(), 'isBase64Encoded': True}

    def test_front_refuses_unsigned_and_queues_a_required_completion(self):
        attester.CACHE[('secret', 'h')] = ('s', float('inf'))
        queued = []
        payload = {'action': 'completed', 'repository': {'full_name': REPO},
                   'check_run': {'name': 'tower/gate', 'app': {'id': ACTIONS}, 'head_sha': SHA,
                                 'check_suite': {'head_branch': 'feature'}, 'pull_requests': [{'number': 7}]}}
        self.assertEqual(attester.front(self.event('check_run', payload, sign=False), None, cfg(), queued.append)['statusCode'], HTTPStatus.UNAUTHORIZED)
        self.assertEqual(queued, [])
        got = attester.front(self.event('check_run', payload), None, cfg(), queued.append)
        self.assertEqual(got['statusCode'], HTTPStatus.ACCEPTED)
        self.assertEqual(queued[0]['job']['sha'], SHA)
        self.assertEqual(queued[0]['job']['pr'], 7)
        self.assertEqual(attester.front(self.event('ping', {}), None, cfg(), queued.append)['statusCode'], HTTPStatus.OK)

    def test_job_filter(self):
        c = cfg()
        base = {'repository': {'full_name': REPO}}
        spoof = {**base, 'action': 'completed', 'check_run': {'name': 'tower/gate', 'app': {'id': APP + 1}, 'head_sha': SHA}}
        self.assertIsNone(attester.job_for('check_run', spoof, c))
        other = {**base, 'action': 'completed', 'check_run': {'name': 'lint', 'app': {'id': ACTIONS}, 'head_sha': SHA}}
        self.assertIsNone(attester.job_for('check_run', other, c))
        ours = {**base, 'action': 'rerequested', 'check_run': {'name': attester.CONTEXT, 'app': {'id': APP}, 'head_sha': SHA}}
        self.assertEqual(attester.job_for('check_run', ours, c)['sha'], SHA)
        foreign = {'repository': {'full_name': 'x/y'}, 'action': 'checks_requested', 'merge_group': {'head_sha': SHA}}
        self.assertIsNone(attester.job_for('merge_group', foreign, c))
        ref = f'refs/heads/gh-readonly-queue/main/pr-7-{PREFIX}'
        group = {**base, 'action': 'checks_requested', 'merge_group': {'head_sha': SHA, 'head_ref': ref}}
        self.assertEqual(attester.job_for('merge_group', group, c), {'sha': SHA, 'branch': ref})
        talk = {**base, 'action': 'created', 'issue': {'number': 7, 'pull_request': {}}, 'comment': {'body': 'hello'}}
        self.assertIsNone(attester.job_for('issue_comment', talk, c))
        talk['comment']['body'] = f'Decision: install\nAttest-Head: {SHA}\n'
        self.assertEqual(attester.job_for('issue_comment', talk, c), {'pr': 7, 'branch': ''})
        self.assertEqual(attester.job_for('status', {**base, 'context': 'web', 'sha': SHA}, c)['sha'], SHA)


class VerdictTests(unittest.TestCase):
    def test_checks_newest_by_id_from_actions_only(self):
        runs = [run('tower/gate', 'failure')] + green() + [run('web', 'failure', app=APP + 1)]
        pending, red, ok = attester.judge_checks(runs, SHA, attester.REQUIRED, ACTIONS)
        self.assertEqual((pending, red, len(ok)), ([], [], 3))
        rerun = runs + [run('tower/gate', status='in_progress')]
        self.assertEqual(len(attester.judge_checks(rerun, SHA, attester.REQUIRED, ACTIONS)[0]), 1)
        red_run = runs + [run('web', 'cancelled')]
        self.assertEqual(len(attester.judge_checks(red_run, SHA, attester.REQUIRED, ACTIONS)[1]), 1)
        self.assertEqual(len(attester.judge_checks([], SHA, attester.REQUIRED, ACTIONS)[0]), 3)
        moved = green()[1:] + [run('tower/gate', sha=OTHER)]
        self.assertIn('judged', attester.judge_checks(moved, SHA, attester.REQUIRED, ACTIONS)[1][0])

    def test_files(self):
        self.assertEqual(attester.judge_files(['docs/a.md'], False, False, False), [])
        self.assertEqual(len(attester.judge_files(['.github/workflows/x.yml'], False, False, False)), 1)
        self.assertEqual(attester.judge_files(['.github/workflows/x.yml'], False, False, True), [])
        self.assertEqual(len(attester.judge_files(['.github/rulesets/main.json'], False, False, False)), 1)
        self.assertEqual(len(attester.judge_files(['.github/CODEOWNERS'], False, True, True)), 1)
        self.assertEqual(len(attester.judge_files(['docs/a.md'], True, False, False)), 1)

    def test_decision_needs_admin_exact_head_and_prefix(self):
        admin = {'dsbello'}.__contains__
        good = {'id': 1, 'user': {'login': 'dsbello'}, 'body': f'Decision: ok\nAttest-Head: {SHA}'}
        self.assertEqual(attester.decision_for([good], SHA, admin), {'comment': 1, 'by': 'dsbello'})
        self.assertIsNone(attester.decision_for([good], OTHER, admin))
        self.assertIsNone(attester.decision_for([{**good, 'user': {'login': 'mallory'}}], SHA, admin))
        self.assertIsNone(attester.decision_for([{**good, 'body': f'ok\nAttest-Head: {SHA}'}], SHA, admin))

    def test_pr_end_to_end_and_write_once(self):
        gh = FakeGitHub(routes_pr(['docs/a.md'], green()))
        sha, runs, v = attester.evaluate(gh, cfg(), {'sha': SHA, 'pr': 7}, APP)
        self.assertEqual((v[0], v[1]), ('completed', 'success'))
        out = attester.write(gh, cfg(), sha, runs, v, APP)
        self.assertTrue(out['wrote'])
        path, body = gh.posts[0]
        self.assertEqual((path, body['name'], body['head_sha'], body['conclusion']),
                         (f'/repos/{REPO}/check-runs', attester.CONTEXT, SHA, 'success'))
        mine = {'id': rid(), 'name': attester.CONTEXT, 'status': 'completed', 'conclusion': 'success',
                'app': {'id': APP}, 'head_sha': SHA, 'output': {'title': body['output']['title']}}
        self.assertFalse(attester.write(gh, cfg(), sha, runs + [mine], v, APP)['wrote'])

    def test_workflow_pr_needs_the_torre_decision(self):
        files = ['.github/workflows/x.yml', 'services/runner/github/x.yml']
        gh = FakeGitHub(routes_pr(files, green()))
        self.assertEqual(attester.evaluate(gh, cfg(), {'pr': 7}, APP)[2][1], 'failure')
        comment = {'id': 5, 'user': {'login': 'dsbello'}, 'body': f'Decision: install x\nAttest-Head: {SHA}\n'}
        gh = FakeGitHub(routes_pr(files, green(), [comment]))
        self.assertEqual(attester.evaluate(gh, cfg(), {'pr': 7}, APP)[2][1], 'success')
        gh = FakeGitHub(routes_pr(files, green(), [comment], perm='write'))
        self.assertEqual(attester.evaluate(gh, cfg(), {'pr': 7}, APP)[2][1], 'failure')

    def test_fork_touching_github_is_refused_even_with_decision(self):
        comment = {'id': 5, 'user': {'login': 'dsbello'}, 'body': f'Decision: x\nAttest-Head: {SHA}'}
        gh = FakeGitHub(routes_pr(['.github/workflows/tower-gate.yml'], green(), [comment], head_repo='evil/fork'))
        self.assertEqual(attester.evaluate(gh, cfg(), {'pr': 7}, APP)[2][1], 'failure')

    def test_pending_then_stale_job_skipped(self):
        gh = FakeGitHub(routes_pr(['docs/a.md'], green()[:1]))
        self.assertEqual(attester.evaluate(gh, cfg(), {'pr': 7}, APP)[2][0], 'in_progress')
        self.assertIsNone(attester.evaluate(gh, cfg(), {'pr': 7, 'sha': OTHER}, APP))

    def test_merge_group(self):
        branch = f'gh-readonly-queue/main/pr-7-{PREFIX}'
        attested = {'id': rid(), 'name': attester.CONTEXT, 'status': 'completed', 'conclusion': 'success',
                    'app': {'id': APP}, 'head_sha': OTHER}
        routes = {
            f'/repos/{REPO}/commits/{SHA}/check-runs': {'check_runs': green()},
            f'/repos/{REPO}/commits/{OTHER}/check-runs': {'check_runs': [attested]},
            f'/repos/{REPO}/commits/{SHA}': {'parents': [{'sha': PREFIX}, {'sha': OTHER}]},
        }
        self.assertEqual(attester.evaluate(FakeGitHub(routes), cfg(), {'sha': SHA, 'branch': branch}, APP)[2][1], 'success')
        routes[f'/repos/{REPO}/commits/{OTHER}/check-runs'] = {'check_runs': [{**attested, 'app': {'id': APP + 1}}]}
        self.assertEqual(attester.evaluate(FakeGitHub(routes), cfg(), {'sha': SHA, 'branch': branch}, APP)[2][1], 'failure')
        routes[f'/repos/{REPO}/commits/{SHA}'] = {'parents': [{'sha': OTHER}, {'sha': PREFIX}]}
        self.assertEqual(attester.evaluate(FakeGitHub(routes), cfg(), {'sha': SHA, 'branch': branch}, APP)[2][1], 'failure')


class StackTests(unittest.TestCase):
    def setUp(self):
        self.stack = json.loads((HERE / 'stack.json').read_text())
        self.res = self.stack['Resources']

    def test_one_role_least_privilege(self):
        roles = [r for r in self.res.values() if r['Type'] == 'AWS::IAM::Role']
        self.assertEqual(len(roles), 1)
        stmts = roles[0]['Properties']['Policies'][0]['PolicyDocument']['Statement']
        actions = sorted(a for s in stmts for a in ([s['Action']] if isinstance(s['Action'], str) else s['Action']))
        self.assertEqual(actions, ['lambda:InvokeFunction', 'logs:CreateLogStream', 'logs:PutLogEvents',
                                   'secretsmanager:GetSecretValue'])
        secret = next(s for s in stmts if s['Action'] == 'secretsmanager:GetSecretValue')
        self.assertEqual(secret['Resource'], [{'Ref': 'KeySecret'}, {'Ref': 'HookSecret'}])
        self.assertTrue(all('*' not in json.dumps(s['Resource']) for s in stmts))

    def test_secrets_url_and_serial_worker(self):
        names = sorted(r['Properties']['Name'] for r in self.res.values() if r['Type'] == 'AWS::SecretsManager::Secret')
        self.assertEqual(names, [app_manifest.KEY_SECRET, app_manifest.HOOK_SECRET])
        self.assertTrue(all(r.get('DeletionPolicy') == 'Retain' for r in self.res.values()
                            if r['Type'] == 'AWS::SecretsManager::Secret'))
        self.assertEqual(self.res['WorkerFunction']['Properties']['ReservedConcurrentExecutions'], 1)
        self.assertNotIn('ReservedConcurrentExecutions', self.res['FrontFunction']['Properties'])
        self.assertEqual(self.res['FrontUrl']['Properties']['AuthType'], 'NONE')

    def test_manifest_least_privilege(self):
        m = app_manifest.manifest(HOOK_URL, app_manifest.PORT)
        writes = sorted(k for k, v in m['default_permissions'].items() if v != 'read')
        self.assertEqual(writes, ['checks'])
        self.assertFalse(m['public'])
        self.assertEqual(set(m['default_events']),
                         {'check_run', 'check_suite', 'status', 'merge_group', 'pull_request', 'issue_comment'})

    def test_convert_stores_secrets_without_returning_them(self):
        stored = {}

        class Resp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return json.dumps({'id': APP, 'slug': 's', 'html_url': APP_URL, 'name': 'n',
                                   'client_id': 'c', 'client_secret': 'X', 'pem': 'P', 'webhook_secret': 'W',
                                   'owner': {'login': 'o'}}).encode()
        got = app_manifest.convert('abc123', None, opener=lambda *a, **k: Resp(),
                                   store=lambda n, v: stored.__setitem__(n, v), deploy=False)
        self.assertEqual(stored, {app_manifest.KEY_SECRET: 'P', app_manifest.HOOK_SECRET: 'W'})
        self.assertNotIn('X', json.dumps(got))
        self.assertNotIn('P', json.dumps(got).replace('"permissions"', ''))
        with self.assertRaises(SystemExit):
            app_manifest.convert('../x', None, deploy=False)


if __name__ == '__main__':
    unittest.main(verbosity=1)
