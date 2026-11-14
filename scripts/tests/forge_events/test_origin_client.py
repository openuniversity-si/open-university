"""The one registry key selects the forge adapter (D-283). No network.

The landed Origin client (the origin CLI) owns change, identity and the check-run post.
This file proves the port: the flow runs through the adapter forge-events.adapter selects (D-293: origin).
"""
from pathlib import Path
import sys
import unittest

_lib = Path(__file__).resolve()
while _lib.name != 'scripts':
    _lib = _lib.parent
sys.path.insert(0, str(_lib / 'lib'))

import config  # noqa: E402
import forge_events  # noqa: E402
import forge_origin  # noqa: E402
import forge_origin_client  # noqa: E402
import test_forge_contract as contract  # noqa: E402


def exercise(adapter, forge):
    """The six operations. The body names no vendor: the registry key picked the adapter."""
    repo = contract.REPO
    found = adapter.change(repo, forge.pr)
    if found['head'] != contract.HEAD or not adapter.identity():
        raise AssertionError('change or identity')
    channel = forge_events.Channel(repo, None)
    adapter.append(channel, [{'event_id': 'one', 'type': 'pr.ready', 'payload': {}}])
    adapter.append(channel, [{'event_id': 'two', 'type': 'pr.ready', 'payload': {}}])
    if [event['event_id'] for event in adapter.read(channel)] != ['one', 'two']:
        raise AssertionError('append/read order')
    adapter.set_status(repo, contract.HEAD, 'tower/gate', 'success', 'gate passed')
    if forge.statuses[contract.HEAD] != [('tower/gate', 'success')]:
        raise AssertionError('status')
    if not adapter.merge(repo, forge.pr, contract.HEAD):
        raise AssertionError('merge')
    try:
        adapter.merge(repo, forge.pr, contract.OTHER)
    except RuntimeError:
        refused = True
    else:
        refused = False
    if not refused or forge.merged != [(forge.pr, contract.HEAD)]:
        raise AssertionError('a moved head was merged')


class _OriginSide:
    """Client, git refs and the journal the port sees when the key is origin. No network."""

    pr = 1

    def __init__(self, log):
        self.log, self.merged, self.check_runs = log, [], []

    def identity(self):
        return 'origin-bot'

    def change(self, repo, number):
        if (repo, number) != (contract.REPO, self.pr):
            raise RuntimeError('unknown change')
        return {'head': contract.HEAD, 'base': contract.BASE, 'head_ref': 'feature',
                'base_ref': 'mod/roadmap-integration', 'head_repo': repo, 'body': 'Plan: 1', 'open': True}

    def url(self):
        return contract.OriginForge(self.log).url()

    def merge(self, base, head, sha, message):
        if (base, head, sha) != ('mod/roadmap-integration', 'feature', contract.HEAD):
            raise RuntimeError('wrong merge input')
        self.merged.append((self.pr, sha))
        return 'd' * len(contract.HEAD)

    def publish_check_run(self, repo, sha, context, state, description, url=None):
        self.check_runs.append((sha, context, state))

    @property
    def statuses(self):
        return contract.OriginForge(self.log).statuses


def _configured(name):
    real = config.get
    chosen = {'forge-events.adapter': name, 'forge-events.log_adapter': name, 'forge-events.file_kinds': [],
              'forge-events.repo': contract.REPO, 'forge-events.board_issue': 0,
              'origin-client.git_hosts': [contract.ORIGIN_HOST], 'forge-events.check_run_publisher': 'client'}  # this flow is the client's own post; the default is control (D-313)

    def get(key, *args):
        return chosen[key] if key in chosen else real(key, *args)
    return get


class CheckRun(unittest.TestCase):
    def test_publish_check_run_posts_the_mapped_verdict_through_the_landed_transport(self):
        seen = []

        def run(method, path, body=None):
            seen.append((method, path, body))
            return {'outcome': 'created'}

        client = forge_origin_client.OriginClient(run=run)
        outcome = client.publish_check_run('other/repo', contract.HEAD, 'tower/gate', 'success', 'gate passed')
        mapped = next(item for item in config.get('forge-events.origin_status_map') if item['state'] == 'success')
        method, path, body = seen[0]
        self.assertEqual(outcome, 'created')
        self.assertEqual(method, 'POST')
        self.assertTrue(path.endswith('/check-runs'))
        self.assertEqual(body['headSha'], contract.HEAD)
        self.assertEqual(body['checkRun']['status'], mapped['status'])
        self.assertEqual(body['checkRun']['conclusion'], mapped['conclusion'])
        self.assertEqual(body['checkSuite']['key'], config.get('forge-events.origin_check_suite_key'))


class OneKey(unittest.TestCase):
    def test_the_flow_follows_forge_events_adapter(self):
        import inspect
        self.assertNotIn('github', inspect.getsource(exercise))
        self.assertNotIn('origin', inspect.getsource(exercise))
        log = forge_events.MemoryAdapter()
        side = _OriginSide(log)
        with (unittest.mock.patch('forge_origin.GitRefAdapter', return_value=log),
              unittest.mock.patch('forge_origin.GitRefs', return_value=side),
              unittest.mock.patch('forge_origin_client.client_from_config', return_value=side),
              unittest.mock.patch.object(config, 'get', _configured('origin'))):
            chosen = forge_events.adapter_from_config()
            self.assertEqual(config.get('forge-events.adapter'), 'origin')
            exercise(chosen, side)
        self.assertIsInstance(chosen, forge_origin.OriginAdapter)
        self.assertEqual(side.check_runs, [(contract.HEAD, 'tower/gate', 'success')])


if __name__ == '__main__':
    unittest.main()
