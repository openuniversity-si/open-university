"""The log's subscriptions (engine-infra-service; INFRA-SVC 4, P3 F4).

Through the port on a throwaway database of the toolchain's PostgreSQL (TI1), with the service's deliverer and a
recording sink: a subscriber receives each event of its tenant once, in the order of the log and only of its types, and
never another tenant's; a sink that refuses or fails gets the same events again; an event younger than the settle
window waits; a rewind replays the history from a point, and only the tenant's own subscription rewinds; a paused
subscription receives nothing; the HTTPS and SNS sinks send what they should; a sink the deliverer cannot reach is
refused at subscription. No network.
"""
from http import HTTPStatus
import json
import os
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'tests'))
from infra_db.psql import migrated  # noqa: E402
import test_db  # noqa: E402
from tower_infra import http_port, port, subscriptions  # noqa: E402

URL = os.environ.get('TEST_DATABASE_URL', '')
TOPIC = 'arn:aws-partition:sns:region-of-the-test:the-account:tower-platform-events'
SETTLED = '0 seconds'  # the tests' events are settled at once; the window itself has its own test


class Recorder:
    def __init__(self, answers=None):
        self.batches, self.answers = [], list(answers or [])

    def __call__(self, sink, subscription, events):
        self.batches.append((sink, subscription, [event['event_id'] for event in events]))
        answer = self.answers.pop(0) if self.answers else True
        if isinstance(answer, Exception):
            raise answer
        return answer


class Subscribed(unittest.TestCase):
    def setUp(self):
        self.name, self.db = migrated(URL)
        self.addCleanup(test_db.destroy, URL, self.name)
        for name in ('torre', 'another'):
            self.call('POST', '/v1/tenants', 'installation', {'name': name, 'token_sha256': port.sha256(name)})
        made = self.call('POST', '/v1/subscriptions', 'torre', {'sink': TOPIC, 'types': ['forge.pushed']})
        self.subscription = made['id']

    def call(self, method, path, token, body=None, status=None):
        answer = http_port.handle({'rawPath': path, 'requestContext': {'http': {'method': method}},
                                   'headers': {'Authorization': f'Bearer {token}'}, 'body': json.dumps(body or {})},
                                  self.db, port.sha256('installation'))
        if status is not None:
            self.assertEqual(answer['statusCode'], status, answer['body'])
        return json.loads(answer['body'])

    def event(self, tenant, kind, name, at="clock_timestamp()"):
        self.db.rows("insert into log.event (event_id, tenant_id, type, occurred_at, producer, subject, payload) "
                     f"select %(id)s, id, %(type)s, {at}, 'test', 'test', '{{}}'::jsonb from work.tenant "
                     "where name = %(tenant)s returning event_id", {'id': name, 'type': kind, 'tenant': tenant})

    def deliver(self, send, settle=SETTLED):
        return subscriptions.deliver(self.db, send, settle=settle)


class Delivery(Subscribed):
    def test_a_subscriber_receives_each_event_of_its_tenant_once_in_order_and_only_of_its_types(self):
        for name in ('first', 'second'):
            self.event('torre', 'forge.pushed', name)
        self.event('torre', 'forge.commented', 'not-its-type')
        self.event('another', 'forge.pushed', 'not-its-tenant')
        sent = Recorder()
        self.assertEqual(self.deliver(sent), {self.subscription: len(('first', 'second'))})
        self.assertEqual(self.deliver(sent), {})
        self.assertEqual(sent.batches, [(TOPIC, self.subscription, ['first', 'second'])])

    def test_a_sink_that_refuses_or_fails_gets_the_same_events_again(self):
        self.event('torre', 'forge.pushed', 'kept')
        sent = Recorder([False, RuntimeError('the sink is down'), True])
        with self.assertLogs('tower_infra.subscriptions', level='ERROR'):  # the failure is named, never raised
            for _ in range(len(sent.answers)):
                self.deliver(sent)
        self.assertEqual([ids for _, _, ids in sent.batches], [['kept'], ['kept'], ['kept']])
        self.assertEqual(self.deliver(sent), {})

    def test_an_event_younger_than_the_settle_window_waits(self):
        self.event('torre', 'forge.pushed', 'fresh')
        sent = Recorder()
        self.assertEqual(self.deliver(sent, settle='1 hour'), {})
        self.assertEqual(self.deliver(sent), {self.subscription: 1})

    def test_a_subscription_starts_at_its_creation(self):
        self.event('torre', 'forge.pushed', 'before', at="clock_timestamp() - interval '1 day'")
        self.assertEqual(self.deliver(Recorder()), {})

    def test_a_rewind_replays_the_history_from_a_point_and_only_the_tenants_own(self):
        self.event('torre', 'forge.pushed', 'old', at="clock_timestamp() - interval '1 day'")
        self.event('torre', 'forge.pushed', 'new')
        sent = Recorder()
        self.deliver(sent)
        since = self.db.rows("select (clock_timestamp() - interval '2 days')::text")[0][0]
        self.call('POST', f'/v1/subscriptions/{self.subscription}/rewind', 'another', {'since': since},
                  status=HTTPStatus.NOT_FOUND)
        self.call('POST', f'/v1/subscriptions/{self.subscription}/rewind', 'torre', {'since': since},
                  status=HTTPStatus.OK)
        self.deliver(sent)
        self.assertEqual([ids for _, _, ids in sent.batches], [['new'], ['old', 'new']])
        rewound = self.call('POST', '/v1/log/query', 'torre', {'filters': {'type': 'platform.subscription.rewound'}})
        self.assertEqual([event['payload']['subscription_id'] for event in rewound['events']], [self.subscription])

    def test_a_cancelled_subscription_receives_nothing_and_only_its_tenant_cancels_it_once(self):
        self.event('torre', 'forge.pushed', 'held')
        path = f'/v1/subscriptions/{self.subscription}/cancel'
        self.call('POST', path, 'another', {}, status=HTTPStatus.NOT_FOUND)
        self.call('POST', path, 'torre', {}, status=HTTPStatus.OK)
        self.call('POST', path, 'torre', {}, status=HTTPStatus.OK)
        self.assertEqual(self.deliver(Recorder()), {})
        done = self.call('POST', '/v1/log/query', 'torre', {'filters': {'type': 'platform.subscription.cancelled'}})
        self.assertEqual(len(done['events']), 1)

    def test_a_paused_subscription_receives_nothing(self):
        self.event('torre', 'forge.pushed', 'held')
        self.db.rows("update log.subscription set state = 'paused' returning id")
        self.assertEqual(self.deliver(Recorder()), {})

    def test_a_sink_the_deliverer_cannot_reach_is_refused_at_subscription(self):
        for sink in ('sink-of-the-test', 'ftp' + '://a-sink', None):
            self.call('POST', '/v1/subscriptions', 'torre', {'sink': sink}, status=HTTPStatus.BAD_REQUEST)
        self.assertTrue(subscriptions.understood(TOPIC))


class Answer:
    def __init__(self, status):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class Topic:
    def __init__(self):
        self.published = []

    def publish(self, TopicArn, Message, MessageAttributes):  # noqa: N803 - boto3's names
        self.published.append((TopicArn, json.loads(Message)['event_id'], MessageAttributes['type']['StringValue']))


class Sinks(unittest.TestCase):
    EVENTS = [{'event_id': 'one', 'type': 'forge.pushed'}, {'event_id': 'two', 'type': 'forge.commented'}]

    def test_an_https_sink_receives_one_post_and_accepts_with_a_2xx(self):
        seen = []

        def opener(request, timeout):
            seen.append((request.full_url, request.get_method(), json.loads(request.data), request.headers))
            return Answer(HTTPStatus.ACCEPTED if len(seen) == 1 else HTTPStatus.SERVICE_UNAVAILABLE)
        sink = '://'.join(('https', 'receiver.test/hook'))
        send = subscriptions.Sinks(opener=opener)
        self.assertEqual((send(sink, 'the-subscription', self.EVENTS), send(sink, 'the-subscription', self.EVENTS)),
                         (True, False))
        url, verb, body, headers = seen[0]
        self.assertEqual((url, verb, body['subscription'], [event['event_id'] for event in body['events']]),
                         (sink, 'POST', 'the-subscription', ['one', 'two']))
        self.assertEqual(headers['Tower-subscription'], 'the-subscription')

    def test_an_sns_sink_receives_one_message_per_event_with_its_type(self):
        topic = Topic()
        self.assertTrue(subscriptions.Sinks(sns=topic)(TOPIC, 'the-subscription', self.EVENTS))
        # LATE-SETUP-SAID: a client made when the first event goes to SNS, once, and never for an HTTPS sink
        made = []
        other = Topic()
        lazy = subscriptions.Sinks(sns_of=lambda: made.append(1) or other, opener=lambda *a, **k: self.fail('no HTTPS here'))
        self.assertEqual(made, [])
        lazy('a-sink-of-nobody', 'the-subscription', self.EVENTS)
        self.assertEqual(made, [])
        self.assertTrue(lazy(TOPIC, 'the-subscription', self.EVENTS))
        self.assertTrue(lazy(TOPIC, 'the-subscription', self.EVENTS))
        self.assertEqual(made, [1])
        self.assertEqual(topic.published, [(TOPIC, 'one', 'forge.pushed'), (TOPIC, 'two', 'forge.commented')])

    def test_any_other_sink_accepts_nothing(self):
        with self.assertLogs('tower_infra.subscriptions', level='WARNING'):
            self.assertFalse(subscriptions.Sinks()(TOPIC, 'the-subscription', self.EVENTS))  # no SNS client given
            self.assertFalse(subscriptions.Sinks(sns=Topic())('a-sink-of-nobody', 'the-subscription', self.EVENTS))


if __name__ == '__main__':
    unittest.main()
