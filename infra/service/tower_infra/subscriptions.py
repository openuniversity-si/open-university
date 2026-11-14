"""The log's subscriptions (P3 F4; ARQUITETURA-ALVO §5): the service delivers each active subscription's pending events
to its sink, in the order of the log, and moves the subscription's cursor past what the sink accepted (migration 0005).

A sink is an HTTPS URL, which receives a POST of {"subscription": <id>, "events": [...]} (a 2xx accepts the batch), or
an SNS topic of the installation (an ARN of service sns), which receives one message per event with its type as an attribute.
A batch the sink refuses, or a call that fails, keeps the cursor: the next pass sends the same events again, so a
subscriber receives every event of its tenant, in order, at least once and each with the event_id it dedupes on (once,
for a subscriber that keeps the ids it saw). Events younger than the settle window wait, so an event whose transaction
commits late is never passed over. The database is any object with rows(sql, params); the SNS client and the HTTP
opener are the caller's. Standard library only.
"""
from http import HTTPStatus
import json
import logging
import re

LOG = logging.getLogger('tower_infra.subscriptions')
ACTIVE = "select id::text, sink from log.subscription where state = 'active' order by id"
PENDING = 'select to_jsonb(e)::text from log.pending(%(id)s::uuid, %(limit)s::int, %(settle)s::interval) e'
ADVANCE = 'select log.advance(%(id)s::uuid, %(at)s::timestamptz, %(event)s)'
HTTPS = 'https://'
SNS = re.compile(r'^arn:[a-z-]+:sns:')  # any partition's SNS topic


def understood(sink):
    """Whether the deliverer can send to a sink: an HTTPS URL or an SNS topic."""
    return isinstance(sink, str) and (sink.startswith(HTTPS) or bool(SNS.match(sink)))


def deliver(db, send, limit=100, settle='5 seconds'):
    """One pass over the active subscriptions; answers {subscription: events accepted} for the sinks that took
    them."""
    accepted = {}
    for subscription, sink in db.rows(ACTIVE):
        events = [json.loads(row[0]) for row in db.rows(PENDING, {'id': subscription, 'limit': limit,
                                                                   'settle': settle})]
        if not events:
            continue
        try:
            taken = send(sink, subscription, events)
        except Exception:  # noqa: BLE001 - a sink that fails keeps its cursor; the next pass sends the same events
            LOG.exception('subscriptions: the sink of %s failed', subscription)
            taken = False
        if taken:
            last = events[-1]
            db.rows(ADVANCE, {'id': subscription, 'at': last['occurred_at'], 'event': last['event_id']})
            accepted[subscription] = len(events)
    return accepted


class Sinks:
    """send(sink, subscription, events) for deliver: HTTPS by POST, SNS by publish; any other sink accepts nothing."""

    def __init__(self, sns=None, opener=None, timeout_s=10.0, sns_of=None):
        if opener is None:  # urllib.request costs ~35 ms to import: the port's Lambda never sends, so it never pays
            import urllib.request
            opener = urllib.request.urlopen
        # LATE-SETUP-SAID: sns_of makes the client when the first event goes to SNS: the service made it at its start,
        # a boto3 client (its endpoints resolved, its handlers built) on the swap's clock of a quarter of a vCPU
        self._sns, self.sns_of, self.opener, self.timeout_s = sns, sns_of, opener, timeout_s

    @property
    def sns(self):
        if self._sns is None and self.sns_of is not None:
            self._sns, self.sns_of = self.sns_of(), None
        return self._sns

    def __call__(self, sink, subscription, events):
        if sink.startswith(HTTPS):
            body = json.dumps({'subscription': subscription, 'events': events}).encode('utf-8')
            import urllib.request
            request = urllib.request.Request(sink, data=body, method='POST', headers={
                'Content-Type': 'application/json', 'Tower-Subscription': subscription})
            with self.opener(request, timeout=self.timeout_s) as answer:
                return HTTPStatus.OK <= answer.status < HTTPStatus.MULTIPLE_CHOICES
        if SNS.match(sink) and self.sns is not None:
            for event in events:
                self.sns.publish(TopicArn=sink, Message=json.dumps(event), MessageAttributes={
                    'type': {'DataType': 'String', 'StringValue': event['type']}})
            return True
        LOG.warning('subscriptions: %s has a sink the deliverer cannot send to', subscription)
        return False
