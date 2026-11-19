import base64, hashlib, hmac, json, os, time, urllib.error, urllib.request
import boto3

CLOCK = time.time  # epoch seconds of the rate limit; the tests inject theirs
OPEN = urllib.request.urlopen  # the one upstream call; the tests inject theirs
TOKEN = '/tower/agent-env/{}/token-sha256'
LAST = '/tower/torre-relay/last-{}'
CACHE = {}  # the webhook's url and key, read once per container


def answer(ident, status, request_id, forwarded=None):
    print(json.dumps({'env': ident, 'status': status, 'request_id': request_id}))
    body = {} if forwarded is None else {'forwarded': forwarded}
    return {'statusCode': status, 'headers': {'content-type': 'application/json'}, 'body': json.dumps(body)}


def webhook(e):
    if not CACHE:
        sm = boto3.client('secretsmanager')
        for name in ('URL_SECRET', 'KEY_SECRET'):
            CACHE[name] = sm.get_secret_value(SecretId=e[name])['SecretString'].strip()
    return CACHE['URL_SECRET'], CACHE['KEY_SECRET']


def text_of(event, limit):
    """The text of a JSON {text} body of at most `limit` bytes, else None."""
    raw = event.get('body') or ''
    try:
        raw = base64.b64decode(raw) if event.get('isBase64Encoded') else raw.encode()
        if len(raw) > limit:
            return None
        body = json.loads(raw)
    except ValueError:
        return None
    text = body.get('text') if isinstance(body, dict) else None
    return text if isinstance(text, str) and text.strip() else None


def last(ssm, name):
    try:
        return float(ssm.get_parameter(Name=name)['Parameter']['Value'])
    except ssm.exceptions.ParameterNotFound:
        return 0.0


def forward(url, key, ident, text, timeout):
    """The upstream's status, or 0 when it could not be reached; its body is never read."""
    data = json.dumps({'env': ident, 'text': text}).encode()
    headers = {'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'}
    try:
        with OPEN(urllib.request.Request(url, data=data, headers=headers, method='POST'), timeout=timeout) as r:
            return r.status
    except urllib.error.HTTPError as error:
        return error.code
    except (OSError, ValueError):
        return 0


def handler(event, context):
    e = os.environ
    rid = getattr(context, 'aws_request_id', '')
    ident = json.loads(e['ROUTES']).get(event.get('routeKey'), '')
    try:
        ssm = boto3.client('ssm')
        header = (event.get('headers') or {}).get('authorization', '')
        bearer = header[7:] if header[:7].lower() == 'bearer ' else ''
        given = hashlib.sha256(bearer.encode()).hexdigest()
        want = ssm.get_parameter(Name=TOKEN.format(ident))['Parameter']['Value'] if ident and bearer else ''
        if not want or not hmac.compare_digest(given, want.strip().lower()):
            return answer(ident, 401, rid)
        text = text_of(event, int(e['LIMIT']))
        if text is None:
            return answer(ident, 400, rid)
        now = CLOCK()
        if now - last(ssm, LAST.format(ident)) < int(e['WINDOW']):
            return answer(ident, 429, rid)
        url, key = webhook(e)
        status = forward(url, key, ident, text, int(e['TIMEOUT']))
        if status:
            ssm.put_parameter(Name=LAST.format(ident), Value=str(int(now)), Type='String', Overwrite=True)
    except Exception:
        return answer(ident, 500, rid)
    return answer(ident, 200 if 200 <= status < 300 else 502, rid, status)
