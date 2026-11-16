"""The forge's webhooks into the log (engine-infra-service; INFRA-EXE 2b, P4 F2b).

Ed25519 in the standard library: RFC 8032's own vectors sign and verify, a tampered message, an out-of-range S and a
short key are refused, and a delivery Origin's way signed by an independent implementation (Node's crypto, fixed here)
verifies. Through the port on a throwaway database of the toolchain's PostgreSQL (TI1), with no token: a delivery
signed Origin's way is written once as the installation's forge.<type> event, and again is a duplicate; a stale
timestamp, a signature no key verifies and a missing header are refused with nothing written; an installation no forge
executor maps is 404 and a ping is the platform's; the service records the forge's keys only when they change, and a
delivery signed with a rotated key verifies once they are recorded; the installation configures its own executor and a
tenant cannot. No network.
"""
import base64
from datetime import datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'tests'))
from infra_db.psql import migrated  # noqa: E402
import test_db  # noqa: E402
from tower_infra import ed25519, forge_webhooks, http_port, port  # noqa: E402

URL = os.environ.get('TEST_DATABASE_URL', '')
# RFC 8032 §7.1, tests 1 to 3: secret key, public key, message, signature
RFC = [('9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60',
        'd75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a', '',
        'e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe'
        '24655141438e7a100b'),
       ('4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb',
        '3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c', '72',
        '92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302a'
        'eeb00d291612bb0c00'),
       ('c5aa8df43f9f837bedb7442f31dcb7b166d38535076f094b85ce3a2e0b4458f7',
        'fc51cd8e6218a1a38da47ed00230f0580816ed13ba3303ac5deb911548908025', 'af82',
        '6291d657deec24024827e69c3abe01a30ce548a284743a445e3680d7db5ac3ac18ff9b538d16f290ae67f760984dc6594a7c15e9716ed2'
        '8dc027beceea1ec40a')]
# A delivery signed Origin's way by Node's own Ed25519 (crypto.sign over the hex digest), 04/11
NODE = {'x': 'mKBb7tVILKkrYwDzt8jU6JI63p5DvqzyYUSqTTOae60', 'id': 'whd_of_the_test', 'ts': '1762290000',
        'body': ('eyJkZWxpdmVyeUlkIjoid2hkX29mX3RoZV90ZXN0IiwiYXBwSWQiOiJhcHBfeCIsImluc3RhbGxhdGlvbklkIjoiaV94IiwiZXZl'
                 'bnQiOnsiaWQiOiJldnRfMSIsInR5cGUiOiJwdWxsX3JlcXVlc3QuY3JlYXRlZCIsImV2ZW50VGltZSI6IjIwMjYtMTEtMDRUMjM6'
                 'MDA6MDBaIiwicGF5bG9hZCI6eyJudW1iZXIiOjd9fX0='),
        'signature': 'BHz/bJtA32nQb22FgIowb0yqK8vy4MJ+Ys1f/Xr3IGeUbAUs15D9JAYafMGJUiornQoDZvddp47DLhYwzdQoCA=='}
SECRET, ROTATED = hashlib.sha256(b'the forge of the test').digest(), hashlib.sha256(b'its next key').digest()
NOW = datetime.fromisoformat('2026-11-04T23:00:10+00:00')


def x_of(secret):
    return base64.urlsafe_b64encode(ed25519.public_key(secret)).decode().rstrip('=')


def jwks(*secrets):
    return {'keys': [{'kty': 'OKP', 'crv': 'Ed25519', 'alg': 'EdDSA', 'kid': f'key-{n}', 'x': x_of(secret)}
                     for n, secret in enumerate(secrets)]}


def delivery(kind='pull_request.created', installation='i_of_the_test', secret=SECRET, webhook='whd_1', when=NOW):
    body = json.dumps({'deliveryId': webhook, 'appId': 'app_of_the_test', 'installationId': installation,
                       'event': {'id': 'evt_1', 'type': kind, 'eventTime': '2026-11-04T23:00:00Z',
                                 'payload': {'number': int('7')}}}).encode()
    if installation is None:
        body = json.dumps({'deliveryId': webhook, 'appId': 'app_of_the_test',
                           'event': {'id': 'evt_ping', 'type': 'ping', 'eventTime': '2026-11-04T23:00:00Z',
                                     'payload': {}}}).encode()
    stamp = str(int(when.timestamp()))
    signed = ed25519.sign(secret, forge_webhooks.digest(webhook, stamp, body).encode())
    headers = {'webhook-id': webhook, 'webhook-timestamp': stamp, 'webhook-event-type': kind,
               'webhook-signature': 'v1a,somebody-else ' + 'v1ed,' + base64.b64encode(signed).decode()}
    return headers, body


class Ed25519(unittest.TestCase):
    def test_the_rfcs_vectors_sign_and_verify(self):
        for secret, public, message, signature in RFC:
            self.assertEqual(ed25519.public_key(bytes.fromhex(secret)).hex(), public)
            self.assertEqual(ed25519.sign(bytes.fromhex(secret), bytes.fromhex(message)).hex(), signature)
            self.assertTrue(ed25519.verify(bytes.fromhex(public), bytes.fromhex(message), bytes.fromhex(signature)))

    def test_a_tampered_message_an_out_of_range_s_and_a_bad_length_are_refused(self):
        _secret, public, message, signature = (bytes.fromhex(value) for value in RFC[1])
        self.assertFalse(ed25519.verify(public, message + b'!', signature))
        half = int('32')  # R, then S, little-endian
        too_big = signature[:half] + (int.from_bytes(signature[half:], 'little') + ed25519.L).to_bytes(half, 'little')
        self.assertFalse(ed25519.verify(public, message, too_big))
        self.assertFalse(ed25519.verify(public[1:], message, signature))
        self.assertFalse(ed25519.verify(public, message, signature[1:]))

    def test_a_delivery_signed_by_an_independent_implementation_verifies(self):
        body, signed = base64.b64decode(NODE['body']), base64.b64decode(NODE['signature'])
        message = forge_webhooks.digest(NODE['id'], NODE['ts'], body).encode()
        self.assertTrue(ed25519.verify(forge_webhooks.decoded(NODE['x']), message, signed))
        self.assertFalse(ed25519.verify(forge_webhooks.decoded(NODE['x']), message.upper(), signed))


class Webhooks(unittest.TestCase):
    def setUp(self):
        self.name, self.db = migrated(URL)
        self.addCleanup(test_db.destroy, URL, self.name)
        self.tenant = self.ok('POST', '/v1/tenants', 'installation', {'name': 'torre',
                                                                      'token_sha256': port.sha256('torre')})['id']
        self.ok('POST', '/v1/executors', 'installation', {'name': 'origin-forge', 'adapter': 'forge'})
        self.ok('PUT', '/v1/executors/origin-forge/config', 'installation',
                {'config': {'installations': {'i_of_the_test': self.tenant}}})
        self.assertTrue(forge_webhooks.refresh(self.db, fetch=lambda url: jwks(SECRET)))

    def call(self, method, path, token, body=None, headers=None, raw=None, now=NOW):
        event = {'rawPath': path, 'requestContext': {'http': {'method': method}},
                 'headers': {**({'Authorization': f'Bearer {token}'} if token else {}), **(headers or {})},
                 'body': raw.decode() if raw is not None else json.dumps(body or {})}
        answer = http_port.handle(event, self.db, port.sha256('installation'), now=now)
        return answer['statusCode'], json.loads(answer['body'])

    def ok(self, method, path, token, body=None):
        status, said = self.call(method, path, token, body)
        self.assertLess(status, int('300'), said)
        return said

    def deliver(self, headers, body, now=NOW):
        return self.call('POST', forge_webhooks.PATH, None, headers=headers, raw=body, now=now)

    def forge_events(self):
        return self.db.rows("select type, tenant_id::text, payload->'delivery'->'event'->>'id' from log.event "
                            "where type like 'forge.%' order by occurred_at")

    def test_a_signed_delivery_is_written_once_as_the_installations_forge_event(self):
        headers, body = delivery()
        self.assertEqual(self.deliver(headers, body), (int('202'), {'accepted': 'whd_1'}))
        self.assertEqual(self.deliver(headers, body), (int('200'), {'duplicate': 'whd_1'}))
        self.assertEqual(self.forge_events(), [('forge.pull_request.created', self.tenant, 'evt_1')])

    def test_a_stale_timestamp_a_signature_no_key_verifies_and_a_missing_header_are_refused(self):
        headers, body = delivery(when=NOW - timedelta(seconds=forge_webhooks.TOLERANCE_S + 1))
        self.assertEqual(self.deliver(headers, body)[0], int('401'))
        headers, body = delivery(secret=ROTATED)
        self.assertEqual(self.deliver(headers, body)[0], int('503'))  # Origin retries; the keys may lag a rotation
        headers, body = delivery()
        self.assertEqual(self.deliver(headers, body + b' ')[0], int('503'))  # the body is what is signed
        self.assertEqual(self.deliver({key: value for key, value in headers.items() if key != 'webhook-signature'},
                                      body)[0], int('400'))
        self.assertEqual(self.forge_events(), [])

    def test_an_installation_no_executor_maps_is_404_and_a_ping_is_the_platforms(self):
        headers, body = delivery(installation='i_unknown')
        self.assertEqual(self.deliver(headers, body)[0], int('404'))
        headers, body = delivery(kind='ping', installation=None, webhook='whd_ping')
        self.assertEqual(self.deliver(headers, body)[0], int('202'))
        self.assertEqual(self.forge_events(), [('forge.ping', None, 'evt_ping')])

    def test_the_keys_are_recorded_when_they_change_and_a_rotated_key_verifies_once_recorded(self):
        self.assertFalse(forge_webhooks.refresh(self.db, fetch=lambda url: jwks(SECRET)))
        headers, body = delivery(secret=ROTATED, webhook='whd_rotated')
        self.assertEqual(self.deliver(headers, body)[0], int('503'))
        self.assertTrue(forge_webhooks.refresh(self.db, fetch=lambda url: jwks(SECRET, ROTATED)))
        self.assertEqual(self.deliver(headers, body)[0], int('202'))
        with self.assertRaises(ValueError):
            forge_webhooks.refresh(self.db, fetch=lambda url: {'keys': [{'kty': 'RSA', 'n': 'x'}]})

    def test_the_installation_configures_its_executor_and_a_tenant_cannot(self):
        status, _ = self.call('PUT', '/v1/executors/origin-forge/config', 'torre', {'config': {'installations': {}}})
        self.assertEqual(status, int('404'))
        status, _ = self.call('PUT', '/v1/executors/origin-forge/config', 'installation', {'config': 'not an object'})
        self.assertEqual(status, int('400'))
        configured = self.db.rows("select count(*) from log.event where type = 'executor.configured'")[0][0]
        self.assertEqual(int(configured), 1)


if __name__ == '__main__':
    unittest.main()
