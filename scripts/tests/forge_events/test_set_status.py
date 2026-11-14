"""forge_events port (D-065, M2): set status (TX24: one file per feature; fixtures in scripts/tests/test_forge_events.py)."""
from http import HTTPStatus
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from test_forge_events import HEAD, REPO, port  # noqa: E402,F401
import config  # noqa: E402
import forge_events  # noqa: E402
import forge_origin  # noqa: E402
import forge_origin_client  # noqa: E402


class SetStatus(unittest.TestCase):
    """GX-17: the commit status goes through the port; Origin records the trail and publishes a check run."""

    def test_the_port_hands_the_status_to_the_adapter(self):
        adapter = forge_events.MemoryAdapter()
        port(adapter).set_status(REPO, HEAD, 'tower/gate', 'pending', 'running', None)
        self.assertEqual(adapter.statuses, [dict(repo=REPO, sha=HEAD, context='tower/gate', state='pending',
                                                 description='running', url=None)])

    def test_an_adapter_without_the_operation_is_refused_by_name(self):
        with self.assertRaisesRegex(forge_events.ForgeEventsError, 'no set_status operation'):
            port(forge_events.FileAdapter(tempfile.mkdtemp())).set_status(REPO, HEAD, 'tower/gate', 'success', 'ok')

    def adapter(self, client):
        refs = mock.Mock()
        refs.url.return_value = f'https://{config.get("origin-client.git_hosts")[0]}/{REPO}.git'
        return forge_origin.OriginAdapter(client, REPO, log=forge_events.MemoryAdapter(), refs=refs)

    def test_origin_publishes_the_check_and_keeps_the_journal_trail(self):
        client = mock.Mock()
        client.identity.return_value = 'tester'
        adapter = self.adapter(client)
        adapter.set_status(REPO, HEAD, 'tower/gate', 'success', 'ok', REPO)
        client.publish_check_run.assert_called_once_with(REPO, HEAD, 'tower/gate', 'success', 'ok', REPO)
        [event] = adapter.log.read(adapter.status_channel(REPO))
        self.assertEqual(event['payload']['sha'], HEAD)
        self.assertEqual(event['payload']['state'], 'success')

    def test_a_403_surfaces_with_its_code_and_preserves_the_journal(self):
        client = mock.Mock()
        client.identity.return_value = 'tester'
        client.publish_check_run.side_effect = forge_origin_client.OriginClientError('refused', status=HTTPStatus.FORBIDDEN)
        adapter = self.adapter(client)
        with self.assertRaises(forge_origin_client.OriginClientError) as caught:
            adapter.set_status(REPO, HEAD, 'tower/gate', 'success', 'ok')
        self.assertEqual(caught.exception.status, HTTPStatus.FORBIDDEN)
        self.assertEqual(len(adapter.log.read(adapter.status_channel(REPO))), 1)

    def test_the_registry_keys_exist_with_their_defaults(self):
        self.assertIs(config.get('forge-events.status_enabled'), True)
        self.assertEqual(config.get('forge-events.status_context_gate'), 'tower/gate')


if __name__ == '__main__':
    unittest.main()
