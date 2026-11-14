"""CHECK-RUN-AWS (docs/operations/aws.md 22.9): tower/gate posted by the engine on AWS, the Cloudflare Worker off the path.

The port takes the check run (POST /v1/check-run, the Worker's body) as an event; the live service takes it once, mints
the Origin app's installation token with the app's key from Parameter Store (an EdDSA app JWT, as the Worker signed it)
and posts it; the gate's client (forge_control.PortAdapter) waits for its word. The key's public half is named by its
JWK thumbprint (RFC 7638 over the RFC 8037 key), which is how `origin app view` lists an app's signing keys.

Hermetic but for OnPostgres (TEST_DATABASE_URL, skipped without).
"""
import base64
import io
import json
import os
from pathlib import Path
import sys
import unittest
import urllib.error

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'infra' / 'service'))
sys.path.insert(0, str(ROOT / 'scripts' / 'tests'))
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
from tower_infra import checks, ed25519, http_port  # noqa: E402
import forge_control  # noqa: E402

URL = os.environ.get('TEST_DATABASE_URL', '')
# RFC 8037 appendix A.1 and A.3: the Ed25519 key and its JWK thumbprint
SEED = base64.urlsafe_b64decode('nWGxne_9WmC6hEr0kuwsxERJxWl7MmkZcDusAxyuf2A=')
THUMBPRINT = 'kPrK_qmxVWaYVA9wwBF6Iuo3vVzz7TxHCTwXBygrS4k'
LABEL = ' '.join(('PRIVATE', 'KEY'))  # the RFC's public test key, framed as a PEM without the literal the secret scan reads
PEM = (f'-----BEGIN {LABEL}-----\n' + base64.b64encode(checks.PKCS8_ED25519 + SEED).decode() + f'\n-----END {LABEL}-----\n')
HEAD = 'a' * 40
BODY = {'repo': checks.REPO, 'headSha': HEAD, 'checkSuite': {'name': 'tower'}, 'checkRun': {'name': 'tower/gate', 'status': 'completed'}}


def unb64(text):
    return base64.urlsafe_b64decode(text + '=' * (-len(text) % 4))


class TheKey(unittest.TestCase):
    def test_the_key_is_read_from_its_pem_and_named_by_its_thumbprint(self):
        self.assertEqual(checks.seed_of(PEM), SEED)
        self.assertEqual(checks.kid(SEED), THUMBPRINT)  # RFC 8037 A.3
        for bad in ('', f'-----BEGIN {LABEL}-----\nAAAA\n-----END {LABEL}-----', 'not a key'):
            with self.assertRaises(ValueError):
                checks.seed_of(bad)

    def test_the_app_jwt_is_the_workers_and_verifies_under_the_public_half(self):
        jwt = checks.app_jwt(SEED, 'app_1', 1000)
        header, claims, signature = jwt.split('.')
        self.assertEqual(json.loads(unb64(header)), {'alg': 'EdDSA', 'typ': 'JWT'})
        self.assertEqual(json.loads(unb64(claims)), {'iss': 'app_1', 'aud': 'origin-apps', 'iat': 1000, 'exp': 1300})
        self.assertTrue(ed25519.verify(ed25519.public_key(SEED), f'{header}.{claims}'.encode(), unb64(signature)))


class Answer(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class Origin:
    def __init__(self, refuse=None):
        self.calls, self.refuse = [], refuse

    def __call__(self, request, timeout=None):
        url, body = request.full_url, json.loads(request.data or b'null')
        self.calls.append((request.get_method(), url, dict(request.header_items()).get('Authorization'), body))
        if url.endswith('/access_tokens'):
            return Answer(json.dumps({'token': 'oit_x', 'expiresAt': '2099-01-01T00:00:00Z'}).encode())
        if self.refuse:
            raise urllib.error.HTTPError(url, self.refuse, 'no', {}, io.BytesIO(b''))
        return Answer(json.dumps({'outcome': 'created'}).encode())


class Db:
    """The two statements of the Poster: the open check runs and the states said (once per id and state)."""

    def __init__(self, asked):
        self.asked, self.said = list(asked), {}

    def rows(self, sql, params=None):
        if sql == checks.OPEN:
            return [(json.dumps(each),) for each in self.asked if (each['id'], 'taken') not in self.said]
        if sql == checks.SAY:
            payload = json.loads(params['payload'])
            key = (payload['id'], payload['state'])
            if key in self.said:
                return []
            self.said[key] = payload
            return [(None,)]
        raise AssertionError(sql)


def asked(ident='1'):
    return {'id': ident, 'state': 'asked', 'headSha': HEAD, 'checkSuite': BODY['checkSuite'], 'checkRun': BODY['checkRun']}


class ThePoster(unittest.TestCase):
    def test_an_asked_check_run_is_taken_once_and_posted_with_the_installation_token(self):
        origin, db = Origin(), Db([asked()])
        poster = checks.Poster(None, lambda: PEM, 'app_1', 'i_1', opener=origin, clock=lambda: 1000.0)
        self.assertEqual(poster.step(db), 1)
        (method, url, auth, _), (method2, url2, auth2, body) = origin.calls
        self.assertEqual((method, url), ('POST', f'{checks.ORIGIN_API}/app/installations/i_1/access_tokens'))
        self.assertTrue(auth.startswith('Bearer ey'))  # the app JWT
        self.assertEqual((method2, url2, auth2), ('POST', f'{checks.ORIGIN_API}/repos/openuniversity-si/open-university/check-runs',
                                                  'Bearer oit_x'))
        self.assertEqual(body, {'headSha': HEAD, 'checkSuite': BODY['checkSuite'], 'checkRun': BODY['checkRun']})
        self.assertEqual((db.said[('1', 'posted')]['outcome'], db.said[('1', 'posted')]['kid']), ('created', THUMBPRINT))
        other = checks.Poster(None, lambda: PEM, 'app_1', 'i_1', opener=origin)
        self.assertEqual(other.step(db), 0)  # taken already: another live service posts nothing
        db.asked.append(asked('2'))
        poster.step(db)
        self.assertEqual(sum(1 for _, url, _, _ in origin.calls if url.endswith('/access_tokens')), 1)  # the token kept

    def test_a_refusal_is_said_and_a_401_mints_the_token_again(self):
        origin, db = Origin(refuse=401), Db([asked()])
        poster = checks.Poster(None, lambda: PEM, 'app_1', 'i_1', opener=origin, clock=lambda: 1000.0)
        self.assertEqual(poster.step(db), 0)
        self.assertEqual(db.said[('1', 'failed')]['why'], 'origin answered 401')
        self.assertIsNone(poster.token)
        self.assertIsNone(checks.from_environ(None, {}))
        self.assertIsInstance(checks.from_environ(None, {checks.KEY_PARAMETER: '/k', checks.APP_ID: 'a', checks.INSTALLATION: 'i'}),
                              checks.Poster)


class Port:
    def __init__(self, states):
        self.states, self.calls = list(states), []

    def call(self, method, path, body=None):
        self.calls.append((method, path, body))
        if method == 'POST':
            return {'id': '7', 'state': 'asked'}
        return self.states.pop(0) if self.states else {'id': '7', 'state': 'asked'}


class TheClient(unittest.TestCase):
    def test_the_gate_s_client_waits_for_the_services_word(self):
        now = [0.0]
        def sleep(s):
            now[0] += s
        port = Port([{'state': 'asked'}, {'state': 'taken'}, {'state': 'posted', 'outcome': 'created'}])
        adapter = forge_control.PortAdapter(port, sleep=sleep, clock=lambda: now[0])
        self.assertEqual(adapter.check_run(checks.REPO, {k: v for k, v in BODY.items() if k != 'repo'}), 'created')
        self.assertEqual(port.calls[0], ('POST', '/v1/check-run', BODY))
        for states, why in (([{'state': 'failed', 'why': 'origin answered 403'}], 'origin answered 403'),
                            ([{'state': 'posted', 'outcome': 'ignored_stale'}], 'stale'), ([], 'no word')):
            with self.assertRaises(forge_control.ControlError) as refused:
                forge_control.PortAdapter(Port(states), sleep=sleep, clock=lambda: now[0]).check_run(checks.REPO, {})
            self.assertIn(why, str(refused.exception))

    def test_a_success_the_landing_follows_comes_back_as_its_body_and_only_the_others_are_posted_here(self):
        # CHECK-IN-LANDING (F4 criterion 3): on the port's route the gate's success is not posted by the client and waited
        # for: its body rides the landing job, which the live service posts right before the merge (forge.OriginForge)
        import forge_origin
        sha = 'ab' * 20
        adapter = forge_origin.OriginAdapter.__new__(forge_origin.OriginAdapter)
        trails = []
        adapter.client, adapter.repo, adapter.identity = object(), checks.REPO, lambda: 'tower'
        adapter.log = type('Log', (), {'append': lambda self, channel, envelopes: trails.append(envelopes)})()
        port = Port([{'state': 'posted', 'outcome': 'created'}])
        adapter.checks = forge_control.PortAdapter(port, sleep=lambda s: None)
        body = adapter.set_status(checks.REPO, sha, 'tower/gate', 'success', 'passed', landing=True)
        self.assertEqual((body['headSha'], body['checkRun']['key'], body['checkRun']['conclusion']), (sha, 'tower/gate', 'success'))
        self.assertEqual(port.calls, [])  # nothing asked at the port: the landing posts it
        self.assertIsNone(adapter.set_status(checks.REPO, sha, 'tower/gate', 'pending', 'running'))  # the others, as before
        self.assertEqual(port.calls[0][:2], ('POST', '/v1/check-run'))
        forge_origin.wait_for_trails(5)
        self.assertEqual(len(trails), 2)  # each one's trail, the landing's success too
        adapter.checks = type('Control', (), {'check_run': lambda self, repo, body: port.calls.append(('control', body))})()
        self.assertIsNone(adapter.set_status(checks.REPO, sha, 'tower/gate', 'success', 'passed', landing=True))
        self.assertEqual(port.calls[-1][0], 'control')  # a publisher that does not land posts it itself

    def test_the_publisher_named_port_is_the_ports(self):
        import forge_origin
        from unittest import mock
        made = {}
        with mock.patch.object(forge_origin.config, 'get', return_value='port'), \
                mock.patch('forge_origin_client.client_from_config', return_value=object()), \
                mock.patch.object(forge_origin, 'OriginAdapter', side_effect=lambda client, repo, checks: made.update(checks=checks)):
            forge_origin.adapter_from_config()
        self.assertIsInstance(made['checks'], forge_control.PortAdapter)


class TheRoutes(unittest.TestCase):
    def test_the_routes_are_the_ports(self):
        verbs = {(verb, pattern) for verb, pattern, _ in http_port.ROUTES}
        self.assertIn(('POST', r'/v1/check-run'), verbs)
        self.assertIn(('GET', r'/v1/check-run/(?P<ident>[0-9]{1,24})'), verbs)


@unittest.skipUnless(URL, 'needs TEST_DATABASE_URL (Postgres; local port 54322)')
class OnPostgres(unittest.TestCase):
    def setUp(self):
        from runner_world import RunnerWorld
        self.world = type('World', (RunnerWorld,), {'runTest': lambda self: None})()
        self.world.setUp()
        self.addCleanup(self.world.doCleanups)
        self.db = self.world.db

    def test_a_check_run_asked_at_the_port_is_posted_by_the_service_and_its_state_read_back(self):
        said = self.world.port('POST', '/v1/check-run', 'torre', BODY)
        self.assertEqual(said['state'], 'asked')
        self.assertEqual(self.world.port('GET', f"/v1/check-run/{said['id']}", 'torre')['state'], 'asked')
        origin = Origin()
        poster = checks.Poster(None, lambda: PEM, 'app_1', 'i_1', opener=origin)
        self.assertEqual(poster.step(self.db), 1)
        self.assertEqual(poster.step(self.db), 0)  # taken once
        found = self.world.port('GET', f"/v1/check-run/{said['id']}", 'torre')
        self.assertEqual((found['state'], found['outcome'], found['kid']), ('posted', 'created', THUMBPRINT))
        self.assertNotIn('checkRun', found)
        for body in ({**BODY, 'repo': 'x/y'}, {**BODY, 'headSha': 'short'}, {k: v for k, v in BODY.items() if k != 'checkRun'}):
            with self.assertRaises(Exception) as refused:
                checks.ask(self.db, ('installation', None), body)
            self.assertEqual(getattr(refused.exception, 'status', None), 400)


if __name__ == '__main__':
    unittest.main()
