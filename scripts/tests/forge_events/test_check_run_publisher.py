"""F37 (D-299): who posts the gate's Origin check run. forge-events.check_run_publisher = control hands Origin's
check-run body to the control plane (POST /v1/check-run, the events token), which alone holds the app key; client keeps
the Origin client's own post. The control plane is a fake behind the adapter's opener; no network."""
import io
import json
from pathlib import Path
import sys
import unittest
from unittest import mock
import urllib.error

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'lib'))

import config  # noqa: E402
import forge_control  # noqa: E402
import forge_events  # noqa: E402
import forge_origin  # noqa: E402

real_get = config.get
REPO = config.get('forge-events.repo')
SHA = 'a' * 40
TOKEN = 'events-token'
CONTEXT = config.get('forge-events.status_context_gate')


class Plane:
    """POST /v1/check-run as the Worker answers it: `status` and its body; every request kept."""

    def __init__(self, status=200, answer=None):
        self.status, self.answer, self.requests = status, answer or {'outcome': 'created'}, []

    def __call__(self, request, timeout=None):
        self.requests.append((request.full_url, request.get_header('Authorization'), json.loads(request.data)))
        data = json.dumps(self.answer).encode()
        if self.status != 200:
            raise urllib.error.HTTPError(request.full_url, self.status, 'no', {}, io.BytesIO(data))
        return io.BytesIO(data)


class Forge:
    """The Origin client and git refs: its remote is the repository's; it records its own check-run posts."""
    HOST = 'origin.test'

    def __init__(self):
        self.posted, self.journal = [], []

    def url(self):
        return f'https://{self.HOST}/{REPO}.git'

    def identity(self):
        return 'tower-bot'

    def append(self, channel, envelopes):
        self.journal.extend(envelopes)

    def publish_check_run(self, *args):
        self.posted.append(args)


class Publisher(unittest.TestCase):
    def setUp(self):
        real = config.get
        self.values = {'origin-client.git_hosts': [Forge.HOST]}
        self.enterContext(mock.patch.object(config, 'get', lambda name, *a: self.values.get(name, real(name, *a))))
        self.forge = Forge()

    def adapter(self, plane, publisher):
        self.values['forge-events.check_run_publisher'] = publisher
        control = forge_control.ControlAdapter(url='https://control.test', token=TOKEN, opener=plane)
        with mock.patch('forge_origin_client.client_from_config', return_value=self.forge), \
                mock.patch.object(forge_origin, 'GitRefs', return_value=self.forge), \
                mock.patch.object(forge_origin, 'ControlAdapter', return_value=control), \
                mock.patch.object(forge_origin, 'GitRefAdapter', return_value=self.forge):  # D-300: the journal is on Origin
            return forge_origin.adapter_from_config()

    def test_control_posts_origins_body_on_the_judged_head_with_the_events_token(self):
        plane = Plane()
        self.adapter(plane, 'control').set_status(REPO, SHA, CONTEXT, 'success', 'passed · tier 1')
        (url, auth, body), = plane.requests
        self.assertEqual(url, 'https://control.test/v1/check-run')
        self.assertEqual(auth, f'Bearer {TOKEN}')
        self.assertEqual((body['repo'], body['headSha']), (REPO, SHA))
        self.assertEqual((body['checkRun']['key'], body['checkRun']['status'], body['checkRun']['conclusion']),
                         (CONTEXT, 'completed', 'success'))
        self.assertEqual(body['checkSuite']['key'], config.get('forge-events.origin_check_suite_key'))
        self.assertEqual(self.forge.posted, [])  # the client never posts it
        forge_origin.wait_for_trails()  # STATUS-TRAIL-ASIDE: the trail is written beside what follows
        self.assertEqual([item['type'] for item in self.forge.journal], ['forge.status'])  # the trail stays

    def test_the_check_run_is_posted_first_and_the_trail_written_beside_what_follows(self):
        # STATUS-TRAIL-ASIDE: the journal's append and the identity were 12.4 of a publish's 13.5 s, before the verdict
        import threading
        release, order = threading.Event(), []
        plane = Plane()
        self.forge.append = lambda channel, envelopes: (release.wait(5), order.append('trail'), self.forge.journal.extend(envelopes))
        adapter = self.adapter(plane, 'control')
        adapter.set_status(REPO, SHA, CONTEXT, 'success', 'passed')
        order.append('returned')
        self.assertEqual(len(plane.requests), 1)  # the verdict is posted when set_status returns
        self.assertEqual(self.forge.journal, [])  # the trail is still being written
        release.set()
        forge_origin.wait_for_trails()
        self.assertEqual(order, ['returned', 'trail'])
        self.assertEqual([item['type'] for item in self.forge.journal], ['forge.status'])

    def test_a_trail_asked_while_held_is_written_once_the_hold_ends(self):
        # TRAIL-AFTER-LANDING: the trail's push beside the forge's merge made it 7 s (#630, #631; 1.4 to 5.0 s before)
        plane = Plane()
        adapter = self.adapter(plane, 'control')
        with forge_events.trails_held():
            adapter.set_status(REPO, SHA, CONTEXT, 'success', 'passed')
            forge_origin.wait_for_trails()
            self.assertEqual(len(plane.requests), 1)  # the verdict is posted at once
            self.assertEqual(self.forge.journal, [])  # its trail is kept
        forge_origin.wait_for_trails()
        self.assertEqual([item['type'] for item in self.forge.journal], ['forge.status'])
        self.assertIsNone(forge_events.HELD)

    def test_pending_is_in_progress_without_a_conclusion(self):
        plane = Plane()
        self.adapter(plane, 'control').set_status(REPO, SHA, CONTEXT, 'pending', 'running')
        run = plane.requests[0][2]['checkRun']
        self.assertEqual(run['status'], 'in_progress')
        self.assertNotIn('conclusion', run)

    def test_port_is_the_registry_default_since_check_run_aws(self):
        # CHECK-RUN-AWS: the engine's port by default, the Cloudflare Worker off the path of every merge (Daniel, 09/11)
        self.assertEqual(real_get('forge-events.check_run_publisher'), 'port')

    def test_client_keeps_its_own_post(self):
        plane = Plane()
        self.values['forge-events.check_run_publisher'] = 'client'
        with mock.patch('forge_origin_client.client_from_config', return_value=self.forge), \
                mock.patch.object(forge_origin, 'GitRefs', return_value=self.forge), \
                mock.patch.object(forge_origin, 'GitRefAdapter', return_value=self.forge), \
                mock.patch.object(forge_origin, 'ControlAdapter', side_effect=AssertionError('the Worker is not used')):
            forge_origin.adapter_from_config().set_status(REPO, SHA, CONTEXT, 'failure', 'failed')
        self.assertEqual(self.forge.posted, [(REPO, SHA, CONTEXT, 'failure', 'failed', None)])
        forge_origin.wait_for_trails()  # STATUS-TRAIL-ASIDE: the trail is written beside what follows
        self.assertEqual([item['type'] for item in self.forge.journal], ['forge.status'])  # D-300: the trail on Origin
        self.assertEqual(plane.requests, [])

    def test_an_unconfigured_plane_raises_its_503_and_reason(self):
        plane = Plane(503, {'error': 'the check run is not configured (ORIGIN_APP_PRIVATE_KEY)'})
        with self.assertRaisesRegex(forge_control.ControlError, r'^503: .*ORIGIN_APP_PRIVATE_KEY'):
            self.adapter(plane, 'control').set_status(REPO, SHA, CONTEXT, 'success', 'passed')

    def test_a_stale_outcome_is_an_error(self):
        with self.assertRaisesRegex(forge_control.ControlError, 'stale'):
            self.adapter(Plane(answer={'outcome': 'ignored_stale'}), 'control').set_status(REPO, SHA, CONTEXT, 'success', '')

    def test_a_refused_token_names_its_variable(self):
        with self.assertRaisesRegex(forge_control.ControlError, config.get('forge-events.control_token_env')):
            self.adapter(Plane(401, {'error': 'events token required'}), 'control').set_status(REPO, SHA, CONTEXT, 'success', '')


if __name__ == '__main__':
    unittest.main()
