"""The webhook consumer (PORT3, PORT7): SQS -> the log, in the VPC, by the same IAM connection the port keeps.

Two kinds of message arrive. PORT7 (the default): API Gateway sent Origin's raw delivery straight to the queue and
answered 202 itself, so nothing has verified it yet: the body is the raw request, the message attributes carry
webhook-id, webhook-timestamp and webhook-signature (the mapping may not carry $context.requestTimeEpoch: the Torre's
probe, variant D, was refused), and this consumer checks the signature against the
forge's keys in the database (the same check the port's accept makes) BEFORE anything is recorded. A delivery that fails
the check is dropped (deleted from the queue, never recorded, the reason logged as one JSON line with "webhook_dropped");
a failure to check (no keys yet, the database unreachable) is retried like any other. The freshness window runs from
the queue's SentTimestamp (set once, when API Gateway's SendMessage is accepted, and kept on every redelivery), not from
now, so a queued delivery is not stale for having waited. PORT3 (AckPath=lambda, the
rollback): the ingress Lambda verified and queued an envelope {headers, body, ingress}; that is recorded as before.

One message is one Origin delivery. record() writes it once by its delivery id
(forge_webhooks.WRITE is idempotent through log.received), so SQS's at-least-once delivery and Origin's retries yield one
registry event. A message that fails is reported in batchItemFailures: SQS keeps it, retries it, and after the queue's
maxReceiveCount moves it to the dead-letter queue; nothing is deleted before it is written.

WEBHOOK-DEAD-ALERT (architecture review, finding 11): nothing reads the dead-letter queue, so a delivery that failed
its last receive went there in silence. The failure of a message's last receive (ApproximateReceiveCount at the queue's
maxReceiveCount) is written once as platform.webhook.dead of the configuration tenant, with the error; a subscription
of that tenant to the platform's topic makes it an alert (aws.md 14.2). Best effort: when the failure is the database
itself the event cannot be written, and the engine's other alarms say so.
"""
import base64
from datetime import datetime, timezone
import json
import os

from . import config_data, forge_webhooks, http_port


TIMING = ('cold', 'gateway_to_handler_ms', 'pre_send_ms', 'origin_sent_to_handler_s', 'ack_path')
HEADERS = ('id', 'timestamp', 'signature')  # the attributes API Gateway copies; the verifier needs exactly these
MAX_RECEIVES = 5  # WEBHOOK-DEAD-ALERT: the queue's maxReceiveCount (40-port.json; a test keeps them equal)
DEAD_EVENT = 'platform.webhook.dead'
DEAD = ("insert into log.event (event_id, tenant_id, type, occurred_at, producer, subject, payload) "
        f"select %(id)s, t.id, '{DEAD_EVENT}', clock_timestamp(), 'tower-webhook-consumer', 'queue/tower-port-webhooks-dlq', "
        "%(payload)s::jsonb from work.tenant t where t.name = %(tenant)s "
        f"and not exists (select 1 from log.event where event_id = %(id)s and type = '{DEAD_EVENT}')")


def ingress_timing(envelope):
    """PORT6: the ingress's timing from the message (None for an old message without it, which records as before)."""
    found = envelope.get('ingress')
    return {name: found.get(name) for name in TIMING} if isinstance(found, dict) else None


RULES = {'tolerance_s': 'service.webhook_tolerance_s', 'drop_stale': 'service.webhook_drop_stale',
         'drop_bad_signature': 'service.webhook_drop_bad_signature'}


def rules(db):
    """The consumer's behaviour rules (DEP9 step 2): freshness window, and whether a stale or an unverifiable delivery is
    dropped (true) or retried (false). Read from work.config_value, ONE query per SQS batch (the batch is the event: a
    Lambda is frozen between invocations and cannot LISTEN tower_config, and a message has already paid the queue's trip,
    so the read adds no ACK latency); an invalid row, a missing row or an unreachable table gives the compiled default."""
    found = {name: default for name, (_, default) in config_data.SPEC.items() if name in RULES.values()}
    try:
        tenant = os.environ.get('TOWER_CONFIG_TENANT', config_data.TENANT)
        for name, text, _version in db.rows(config_data.LOAD, {'tenant': tenant}):
            if name in found:
                try:
                    found[name] = config_data.validate(name, json.loads(text))
                except ValueError:
                    pass  # an invalid stored value never reaches the rule: the default stays
    except Exception:  # noqa: BLE001 - the compiled defaults are the rules
        pass
    return {short: found[name] for short, name in RULES.items()}


class Dropped(Exception):
    """A delivery that is not Origin's (or is stale): never recorded, never retried; the reason is logged."""


def attribute(record, name):
    found = (record.get('messageAttributes') or {}).get(name)
    return found.get('stringValue') if isinstance(found, dict) else None


def direct(record):
    """True for a PORT7 message (API Gateway wrote it), False for a PORT3 envelope (the ingress Lambda did)."""
    return any(attribute(record, name) is not None for name in ('webhook-id', 'webhook-signature'))


def direct_timing(record, headers, sent_ms):
    """PORT7: the registry's timing for a delivery acknowledged by API Gateway. pre_send_ms is None: the gateway's request
    time is not available to the mapping ($context.requestTimeEpoch is refused), and the ACK (request received -> SQS
    accepted) is not observable from the message; it is measured by the API Gateway access log's integrationLatency /
    responseLatency and by the post-deploy ACK smoke (scripts/ack-smoke). There is no Lambda, so no cold start (cold false,
    gateway_to_handler_ms none). origin_sent_to_handler_s is the queue's SentTimestamp minus Origin's webhook-timestamp."""
    stamp = headers.get('webhook-timestamp') or ''
    return {'cold': False, 'gateway_to_handler_ms': None, 'pre_send_ms': None,
            'origin_sent_to_handler_s': round(sent_ms / 1000 - int(stamp), 1) if stamp.isdigit() else None,
            'ack_path': 'sqs'}


def screen(record, db, rule=None):
    """(headers, raw body, timing) of a PORT7 message whose signature is Origin's; Dropped with the reason otherwise."""
    headers = {f'webhook-{name}': attribute(record, f'webhook-{name}') for name in HEADERS}
    headers = {name: value for name, value in headers.items() if value}
    sent = str((record.get('attributes') or {}).get('SentTimestamp') or '')
    if not sent.isdigit():
        raise Dropped('the message carries no SentTimestamp')
    sent_ms = int(sent)
    raw = (record.get('body') or '').encode('utf-8')

    def keys():
        found = db.rows(forge_webhooks.LATEST_KEYS)
        if not found:
            raise RuntimeError('the forge has published no keys yet')  # not a verdict: retried, kept in the queue
        return json.loads(found[0][0]).get('keys') or []

    rule = rule or rules(db)
    refused = forge_webhooks.verified(headers, raw, keys, datetime.fromtimestamp(sent_ms / 1000, timezone.utc),
                                      rule['tolerance_s'])
    if refused:
        stale = refused[0] == 401
        if not (rule['drop_stale'] if stale else rule['drop_bad_signature']):
            raise RuntimeError(f'refused ({refused[0]}) and the rule says retry')  # kept in the queue, then the DLQ
        raise Dropped(('invalid signature: ' if refused[0] == 503 else '') + f'{refused[0]}: {refused[1]}')
    return headers, raw, direct_timing(record, headers, sent_ms)


def drop_line(record, reason):
    return json.dumps({'webhook_dropped': True, 'reason': reason, 'id': attribute(record, 'webhook-id'),
                       'message': record.get('messageId')})


def process(record, db, rule=None):
    """Record one queued delivery; raises when it cannot be recorded (so the message stays in the queue). `record` is the
    SQS record; a bare envelope string is still accepted. Raises Dropped for a delivery that fails the signature check."""
    if isinstance(record, str):
        record = {'body': record}
    if direct(record):
        headers, raw, timing = screen(record, db, rule)
        status, said = forge_webhooks.record(db, headers, raw, timing)
    else:
        envelope = json.loads(record['body'])
        headers = {f'webhook-{name}': value for name, value in envelope['headers'].items() if value is not None}
        status, said = forge_webhooks.record(db, headers, base64.b64decode(envelope['body']), ingress_timing(envelope))
    if status not in (200, 202):
        raise ValueError(f'{status}: {said.get("error")}')
    return status


def dead(record, db, error):
    """WEBHOOK-DEAD-ALERT: a message that failed its last receive is on its way to the dead-letter queue: written once
    as platform.webhook.dead (the configuration tenant's) and logged as one JSON line. Never raises; True when it was the last."""
    try:
        receives = int((record.get('attributes') or {}).get('ApproximateReceiveCount') or 0)
        if receives < MAX_RECEIVES:
            return False
        said = {'message': record.get('messageId'), 'webhook_id': attribute(record, 'webhook-id'), 'receives': receives,
                'error': f'{type(error).__name__}: {error}'[:500]}
        print(json.dumps({'webhook_dead': True, **said}))
        db.rows(DEAD, {'id': f"{DEAD_EVENT}:{record.get('messageId')}", 'payload': json.dumps(said),
                       'tenant': os.environ.get('TOWER_CONFIG_TENANT', config_data.TENANT)})
        return True
    except Exception:  # noqa: BLE001 - the message goes to the dead-letter queue either way
        return False


def consume(event, db):
    """The SQS batch: {batchItemFailures: [{itemIdentifier}]} for the messages that were not recorded."""
    failures = []
    rule = rules(db) if event.get('Records') else None
    for record in event.get('Records') or []:
        try:
            process(record, db, rule)
        except Dropped as why:
            print(drop_line(record, str(why)))  # a verdict, not a failure: deleted from the queue, never recorded
        except Exception as error:  # noqa: BLE001 - kept for the retry and the dead-letter queue
            failures.append({'itemIdentifier': record['messageId']})
            dead(record, db, error)  # WEBHOOK-DEAD-ALERT: its last receive is an event, not a silence
    return {'batchItemFailures': failures}


def handler(event, context):
    lazy = http_port.lazy_database(os.environ.get('TOWER_DB_USER', 'tower_service'), role='consumer')
    answered = consume(event, lazy)
    if answered['batchItemFailures'] and lazy.broken():
        http_port.forget_connection()  # the next invocation opens a fresh one
    return answered
