"""The Origin webhook ingress (PORT3): verify the signature, write the raw delivery to a durable queue, answer 202.

Origin gives a webhook 10 s and the owner wants the ping to return in a second, cold start included. The old path
(http_port -> forge_webhooks.accept) opened a database connection from a VPC Lambda before answering. This one touches
no database: a Lambda outside the VPC, standard library only, that
  1. checks the headers and the timestamp (400, 401, no other call),
  2. checks the Ed25519 signature against the forge's keys, which the service publishes to the SSM parameter
     TOWER_FORGE_KEYS_PARAMETER whenever they change (read once and kept in memory; read again, at most every
     REFETCH_S, when no kept key verifies, since the keys rotate weekly) -> 401/503 and NO queue write on failure,
  3. writes the delivery (headers + raw body) to the SQS queue TOWER_INGRESS_QUEUE_URL and answers 202 only after SQS
     has accepted it (a durable write); when SQS fails it answers 503 and Origin retries.
webhook_consumer.handler (in the VPC, SQS event source) records each message in the log through forge_webhooks.record,
once per delivery id (log.received), so the engine, the registry and the subscriptions see every event. A message the
consumer cannot record is retried and, after maxReceiveCount, kept in the dead-letter queue.
"""
import base64
from datetime import datetime, timezone
import json
import os
import time

from . import awsjson, forge_webhooks

TTL_S = 3600.0  # a kept key set is trusted this long
REFETCH_S = 5.0  # and re-read at most this often when none of its keys verifies a signature
ACK_LIMIT_S = float(os.environ.get('TOWER_INGRESS_ACK_LIMIT_S') or 1)  # medir.webhook_ack_limit_s: a failure limit, not a timeout
MAX_BODY = 600_000  # raw bytes: base64 plus the envelope must fit in SQS's 1 MiB message
HEADERS = ('id', 'timestamp', 'event-type', 'event-id', 'app-id', 'installation-id', 'signature')


def answer(status, body):
    return {'statusCode': status, 'headers': {'content-type': 'application/json'}, 'body': json.dumps(body)}


class Ingress:
    def __init__(self, sqs, ssm, queue_url, parameter, clock=time.monotonic, seed=None):
        self.sqs, self.ssm, self.queue_url, self.parameter, self.clock = sqs, ssm, queue_url, parameter, clock
        self.kept, self.read_at = None, None
        if seed:  # PORT5: the keys the stack put in the environment (public keys): no SSM call on the cold path
            self.kept, self.read_at = seed, clock() - REFETCH_S  # a miss may re-read the parameter at once (rotation)

    def fetch(self):
        value = self.ssm.call('GetParameter', {'Name': self.parameter})['Parameter']['Value']
        self.kept, self.read_at = json.loads(value).get('keys') or [], self.clock()
        return self.kept

    def keys(self):
        if self.kept is None or self.clock() - self.read_at > TTL_S:
            return self.fetch()
        return self.kept

    def verify(self, headers, body, now):
        """None when the delivery is Origin's and fresh, else (status, why); one re-read of the keys on a miss."""
        try:
            refused = forge_webhooks.verified(headers, body, self.keys, now)
            if refused and refused[0] == 503 and self.clock() - self.read_at >= REFETCH_S:
                refused = forge_webhooks.verified(headers, body, self.fetch, now)
        except Exception as error:  # noqa: BLE001 - the keys are unreachable: Origin retries a 5xx
            return 503, f'the forge keys could not be read: {str(error)[:200]}'
        return refused

    def handle(self, event, now=None, cold=False, started=None):
        if event.get('requestContext', {}).get('http', {}).get('method') != 'POST' or \
                event.get('rawPath') != forge_webhooks.PATH:
            return answer(404, {'error': 'no route'})
        headers = {key.lower(): value for key, value in (event.get('headers') or {}).items()}
        raw = (base64.b64decode(event.get('body') or '') if event.get('isBase64Encoded')
               else (event.get('body') or '').encode('utf-8'))
        if len(raw) > MAX_BODY:
            return answer(413, {'error': f'the body is over {MAX_BODY} bytes'})
        refused = self.verify(headers, raw, now or datetime.now(timezone.utc))
        if refused:
            return answer(refused[0], {'error': refused[1]})
        message = {'headers': {name: headers.get(f'webhook-{name}') for name in HEADERS if name != 'signature'},
                   'body': base64.b64encode(raw).decode('ascii'),
                   'ingress': stamped(event, headers, started if started is not None else time.time(), cold)}
        try:
            self.sqs.call('SendMessage', {'QueueUrl': self.queue_url, 'MessageBody': json.dumps(message)})
        except Exception as error:  # noqa: BLE001 - not durable, so not accepted: Origin retries the delivery
            return answer(503, {'error': f'the delivery could not be queued: {str(error)[:200]}'})
        return answer(202, {'accepted': headers['webhook-id']})


def stamped(event, headers, started, cold):
    """PORT6: the ingress timing that rides in the queued message (no extra call, a few numbers), so the consumer can put
    it in the registry: the gateway's stamp to this handler's start (the Init of a cold start included), the work until
    just before the SQS send (pre_send_ms = gateway_to_handler_ms + that work; the send itself is not known before it
    happens, so the real ACK is at least this), and Origin's send to the handler."""
    now = time.time()
    gateway = (event.get('requestContext') or {}).get('timeEpoch')
    before = started * 1000 - gateway if gateway else None
    sent = headers.get('webhook-timestamp')
    return {'v': 1, 'cold': bool(cold), 'gateway_to_handler_ms': round(before) if before is not None else None,
            'pre_send_ms': round((now - started) * 1000 + (before or 0), 1),
            'origin_sent_to_handler_s': round(started - int(sent), 1) if (sent or '').isdigit() else None}


_ingress = None


def seeded(environ):
    """The keys of TOWER_FORGE_KEYS (the SSM parameter's value, which the stack copies in at deploy time; the forge's
    PUBLIC verification keys, not a secret), or None when absent or unreadable (the parameter is then read on first use)."""
    try:
        return json.loads(environ.get('TOWER_FORGE_KEYS') or 'null').get('keys') or None
    except (ValueError, AttributeError):
        return None


def build(environ=None):
    environ = os.environ if environ is None else environ
    region = environ.get('AWS_REGION') or environ['AWS_DEFAULT_REGION']
    return Ingress(awsjson.Client('sqs', region, '1.0', 'AmazonSQS'), awsjson.Client('ssm', region, '1.1', 'AmazonSSM'),
                   environ['TOWER_INGRESS_QUEUE_URL'], environ['TOWER_FORGE_KEYS_PARAMETER'], seed=seeded(environ))


def prepare():
    """The init phase's share: the SQS connection opened before the first delivery and, only when the stack gave no
    keys in the environment, the keys read (PORT5: with them the init makes one network call, not two); best effort,
    since a failure here only moves the same work to the first call."""
    global _ingress
    try:
        _ingress = build()
        _ingress.sqs.warm()
        if _ingress.kept is None:
            _ingress.fetch()
    except Exception:  # noqa: BLE001
        pass


_first = True


def timing(event, started, answered, cold, limit_s=None):
    """One log line per delivery for the measurement (docs/operations/aws.md, PORT3): the gateway's own stamp of the
    request (requestContext.timeEpoch, ms) against this handler's start gives what happened before the Lambda (the
    init of a cold start included, since the request waits for it); the signed webhook-timestamp (s) against now gives
    Origin's send to here; ms is this handler's work. ack_ms is the ACK as far as the code can see it, the gateway's
    stamp to this answer (gateway_to_handler_ms + ms; ms alone when the stamp is missing), and over_limit is whether
    it passed the failure limit (PORT4; medir.webhook_ack_limit_s): a flag on the line, nothing is cut. The network
    between Origin and the gateway, and the answer's way back, are outside it."""
    headers = {key.lower(): value for key, value in (event.get('headers') or {}).items()}
    gateway = event.get('requestContext', {}).get('timeEpoch')
    sent = headers.get('webhook-timestamp')
    limit_s = ACK_LIMIT_S if limit_s is None else limit_s
    work = (time.time() - started) * 1000
    before = started * 1000 - gateway if gateway else None
    ack = work + (before or 0)
    return json.dumps({'ingress': answered['statusCode'], 'cold': cold, 'id': headers.get('webhook-id'),
                       'type': headers.get('webhook-event-type'), 'ms': round(work, 1),
                       'gateway_to_handler_ms': round(before) if before is not None else None,
                       'origin_sent_to_handler_s': round(started - int(sent), 1) if (sent or '').isdigit() else None,
                       'ack_ms': round(ack, 1), 'limit_s': limit_s, 'over_limit': ack > limit_s * 1000})


def handler(event, context):
    global _ingress, _first
    cold, _first = _first, False
    started = time.time()
    if _ingress is None:
        _ingress = build()
    answered = _ingress.handle(event, cold=cold, started=started)
    print(timing(event, started, answered, cold))
    return answered


if os.environ.get('TOWER_INGRESS_QUEUE_URL'):
    prepare()
