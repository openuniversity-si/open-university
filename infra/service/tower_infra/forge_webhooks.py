"""Origin's webhooks into the log (P4 F2b; ARQUITETURA-ALVO §2 and §5: forge.* is the raw ingress of the forge).

Origin delivers each event to the port, POST /v1/forge/origin/webhooks, at least once. Each delivery is signed with
Ed25519 (the Torre's reading of cursor.com/docs/api/origin/reference/webhooks, 04/11):
- webhook-signature carries "v1ed,<base64>", among other values separated by spaces.
- What is signed is the UTF-8 of the lowercase hex of SHA-256("<webhook-id>.<webhook-timestamp>.<raw body>").
- The key is one of Origin's public JWKS (keys_url). The JWKS rotates weekly and the signature names no key, so every
  key is tried.

The port's Lambda has no route to the internet (D-309), so the service fetches the JWKS (refresh) and records it in the
log as platform.forge.keys whenever it changes, and the port verifies against the latest one (accept). accept answers:
- 400: a delivery missing its webhook-id, timestamp or v1ed signature, or carrying no event type.
- 401: a timestamp more than 300 s from the clock (a replay or a skewed sender).
- 503: no key verifies. Origin retries 5xx, and the service may not have the rotated key yet.
- 404: an installation that no forge executor maps to a tenant, in its config's installations.
- 200: a delivery already received (log.received), written once.
- 202: the event written as forge.<type> for the installation's tenant; a ping goes in as the platform's.
After verification the body is the authority, over the routing headers. Standard library only.
"""
import base64
from datetime import datetime, timezone
import hashlib
import json
import re

from . import ed25519

PATH = '/v1/forge/origin/webhooks'
KEYS_URL = 'https://api.cursor.com/v1/origin/keys'
TOLERANCE_S = 300
TAG = 'v1ed,'
TYPE = re.compile(r'[a-z0-9_]+(\.[a-z0-9_]+)*')
LATEST_KEYS = ("select payload::text from log.event where type = 'platform.forge.keys' and tenant_id is null "
               "order by occurred_at desc limit 1")
TENANT = ("select config->'installations'->>%(installation)s from work.executor where adapter = 'forge' "
          "and config->'installations'->>%(installation)s is not null order by name limit 1")
WRITE = ("with seen as (insert into log.received (event_id) values (%(seen)s) on conflict do nothing "
         "returning event_id) "
         "insert into log.event (event_id, tenant_id, type, occurred_at, producer, subject, payload) "
         "select %(event)s, %(tenant)s::uuid, %(type)s, clock_timestamp(), 'forge/origin', %(subject)s, "
         "%(payload)s::jsonb from seen returning event_id")
RECORD_KEYS = ("insert into log.event (event_id, tenant_id, type, occurred_at, producer, subject, payload) "
               "values (%(event)s, null, 'platform.forge.keys', clock_timestamp(), 'forge/origin', 'keys/origin', "
               "%(payload)s::jsonb) returning event_id")


def raw_keys(jwks):
    """The Ed25519 keys of a JWKS, as [kid, x] pairs (x: the public key, base64url)."""
    return sorted([key.get('kid') or '', key['x']] for key in (jwks or {}).get('keys') or []
                  if key.get('kty') == 'OKP' and key.get('crv') == 'Ed25519' and key.get('x'))


def decoded(x):
    return base64.urlsafe_b64decode(x + '=' * (-len(x) % 4))


def signatures(header):
    """The v1ed signatures of a webhook-signature header, decoded; any other value is someone else's."""
    found = []
    for value in (header or '').split():
        if value.startswith(TAG):
            try:
                found.append(base64.b64decode(value[len(TAG):], validate=True))
            except ValueError:
                continue
    return found


def digest(delivery, timestamp, body):
    return hashlib.sha256(f'{delivery}.{timestamp}.'.encode('utf-8') + body).hexdigest()


def verified(headers, body, keys, now, tolerance=TOLERANCE_S):
    """None when the delivery is Origin's and fresh, else (status, why). `tolerance` is the freshness window in seconds
    (the queue consumer reads it from the table, DEP9; the port keeps the compiled one)."""
    delivery, timestamp = headers.get('webhook-id'), headers.get('webhook-timestamp')
    signed = signatures(headers.get('webhook-signature'))
    if not delivery or not timestamp or not signed:
        return 400, 'a webhook needs webhook-id, webhook-timestamp and a v1ed signature'
    try:
        skew = abs(now.timestamp() - int(timestamp))
    except ValueError:
        return 400, 'webhook-timestamp is not a Unix time'
    if skew > tolerance:
        return 401, f'webhook-timestamp is {skew:.0f} s from the clock (more than {tolerance} s)'
    keys = keys() if callable(keys) else keys  # read only once the cheap checks passed: a refusal never needs the database
    message = digest(delivery, timestamp, body).encode('ascii')
    if any(ed25519.verify(decoded(x), message, signature) for _kid, x in keys for signature in signed):
        return None
    return 503, 'no key of the forge verifies the signature (it may have rotated; the service refreshes the keys)'


def accept(db, headers, body, now=None):
    """One delivery of Origin's: (status, answer); headers lowercase, body the raw bytes."""
    def keys():
        found = db.rows(LATEST_KEYS)
        return (json.loads(found[0][0]).get('keys') or []) if found else []

    refused = verified(headers, body, keys, now or datetime.now(timezone.utc))
    if refused:
        return refused[0], {'error': refused[1]}
    return record(db, headers, body)


def record(db, headers, body, ingress=None):
    """A delivery whose signature is verified (here by accept, in the PORT3 path by the ingress before it queued it):
    (status, answer), written once by its delivery id. `ingress` (PORT6): the ingress's timing for this delivery, kept in the
    event's payload as `ingress` so the registry holds every delivery's timing; absent for the old path and old messages."""
    try:
        delivery = json.loads(body)
    except ValueError:
        return 400, {'error': 'the body is not JSON'}
    event = delivery.get('event') or {}
    kind = event.get('type') or headers.get('webhook-event-type') or ''
    if not TYPE.fullmatch(kind):
        return 400, {'error': f'event type {kind!r} is not one'}
    installation = delivery.get('installationId') or headers.get('webhook-installation-id')
    tenant = None
    if kind != 'ping':
        mapped = db.rows(TENANT, {'installation': installation}) if installation else []
        if not mapped or not mapped[0][0]:
            return 404, {'error': f'no forge executor maps installation {installation} to a tenant'}
        tenant = mapped[0][0]
    webhook = {name: headers.get(f'webhook-{name}') for name in ('id', 'timestamp', 'event-type', 'event-id',
                                                                    'app-id', 'installation-id')}
    written = db.rows(WRITE, {
        'seen': f"forge:origin:{webhook['id']}", 'event': f"forge.{kind}:{webhook['id']}", 'tenant': tenant,
        'type': f'forge.{kind}', 'subject': f'installation/{installation}' if installation else 'app/origin',
        'payload': json.dumps({'webhook': webhook, 'delivery': delivery, **({'ingress': ingress} if ingress else {})})})
    return (202, {'accepted': webhook['id']}) if written else (200, {'duplicate': webhook['id']})


def publish(db, put, parameter):
    """The service's other half (PORT3): the latest keys copied to the SSM parameter the webhook ingress reads, so that
    the ingress verifies without a database. `put(name, value)` writes the parameter."""
    found = db.rows(LATEST_KEYS)
    if found:
        put(parameter, found[0][0])
    return bool(found)


def fetched(url, opener=None, timeout_s=10.0):
    import urllib.request  # the service's half only: the port's Lambda never fetches, so it never imports it
    opener = opener or urllib.request.urlopen
    request = urllib.request.Request(url, headers={'Accept': 'application/json', 'User-Agent': 'tower-infra'})
    with opener(request, timeout=timeout_s) as answer:
        return json.loads(answer.read())


def refresh(db, fetch=fetched, url=KEYS_URL):
    """The service's half (it reaches the internet, the port does not): the forge's JWKS recorded when it changed."""
    keys = raw_keys(fetch(url))
    if not keys:
        raise ValueError(f'the forge published no Ed25519 key at {url}')
    sha256 = hashlib.sha256(json.dumps(keys).encode('utf-8')).hexdigest()
    found = db.rows(LATEST_KEYS)
    if found and json.loads(found[0][0]).get('sha256') == sha256:
        return False
    db.rows(RECORD_KEYS, {'event': f'platform.forge.keys:{sha256}',
                          'payload': json.dumps({'keys': keys, 'sha256': sha256, 'url': url})})
    return True
