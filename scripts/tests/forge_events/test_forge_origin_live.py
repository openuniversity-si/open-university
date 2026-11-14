"""FORGE-PORT (CANALE8): the Origin client against the live API. Skipped unless asked for.

This is the case that proves the transport, the credential exchange and the real response shapes.
It runs only when OU_ORIGIN_LIVE names the repository to read, so an ordinary test run never
touches the network:

    OU_ORIGIN_LIVE=<owner>/<name> \
    OU_ORIGIN_LIVE_PULL=<number> \
    python3 scripts/tests/forge_events/test_forge_origin_live.py -v

It prints what it saw -- the identity, the fields the adapter consumes with their values, the
comments and the budget -- so the evidence is in the run, not in a claim. It reads; it never
writes. No case merges, comments or opens a change, because a live write is not a test.
"""
import json
import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent / 'scripts' / 'lib'))

import forge_origin_client as client  # noqa: E402

REPO = os.environ.get('OU_ORIGIN_LIVE', '')
PULL = os.environ.get('OU_ORIGIN_LIVE_PULL', '')
MISSING = json.loads((Path(__file__).resolve().parent / 'fixtures' / 'origin.json').read_text())['missing_number']
CONF = client.settings()
STATUS = {item['kind']: int(item['status']) for item in CONF['statuses']}


def seen(label, value):
    print(f'  {label}: {value}')


class LiveCase(unittest.TestCase):
    @unittest.skipUnless(REPO, 'live Origin read: set OU_ORIGIN_LIVE=<owner>/<name> to run it')
    def setUp(self):
        self.client = client.OriginClient()

    def test_the_rate_limit_answers_with_the_principal_budget(self):
        found = self.client.rate_limit()
        core = (found.get('resources') or {}).get('core') or {}
        print('\n[rate_limit]')
        seen('limit', core.get('limit'))
        seen('remaining', core.get('remaining'))
        seen('used', core.get('used'))
        self.assertIsInstance(core.get('limit'), int)
        self.assertGreater(core['limit'], 0)

    def test_the_identity_is_the_user_namespace_or_the_gap_is_named(self):
        print('\n[identity]')
        try:
            identity = self.client.identity()
        except client.OriginIdentityGap as gap:
            seen('gap', gap)
            self.assertIn('no user identity', str(gap))
            return
        seen('identity', identity)
        self.assertTrue(identity)

    def test_a_pull_request_maps_into_the_adapter_shape(self):
        if not PULL:
            self.skipTest('live Origin read of one change: set OU_ORIGIN_LIVE_PULL=<number>')
        raw = self.client.pull(REPO, PULL)
        shaped = self.client.change(REPO, PULL)
        print(f'\n[pull {REPO}#{PULL}]')
        seen('number', raw.get('number'))
        seen('state', raw.get('state'))
        seen('merged', raw.get('merged'))
        seen('webUrl', raw.get('webUrl'))
        seen('head.ref / head.sha', f"{shaped['head_ref']} / {shaped['head']}")
        seen('base.ref / base.sha', f"{shaped['base_ref']} / {shaped['base']}")
        seen('open', shaped['open'])
        seen('body chars', len(shaped['body']))
        self.assertEqual(set(shaped), {'head', 'base', 'head_ref', 'base_ref', 'head_repo', 'body', 'open'})
        self.assertEqual(shaped['head_repo'], REPO)

    def test_the_comment_list_pages_without_error(self):
        if not PULL:
            self.skipTest('live Origin read of comments: set OU_ORIGIN_LIVE_PULL=<number>')
        found = self.client.comments(REPO, PULL)
        print(f'\n[comments {REPO}#{PULL}]')
        seen('comments', len(found))
        seen('fields of the first', sorted(found[0]) if found else '(none)')
        self.assertIsInstance(found, list)

    def test_a_missing_change_is_a_not_found_with_the_api_message(self):
        with self.assertRaises(client.OriginClientError) as caught:
            self.client.change(REPO, MISSING)
        print('\n[missing change]')
        seen('status', caught.exception.status)
        seen('message', str(caught.exception))
        self.assertEqual(caught.exception.status, STATUS['not-found'])


if __name__ == '__main__':
    unittest.main()
