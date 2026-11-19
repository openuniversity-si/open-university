import fnmatch, hashlib, hmac, json, os, time
import boto3

TTL = 60  # seconds a container keeps its SSM reads (D-341: 60 s or less)
TOKEN = 'token-sha256'
CLOCK = time.monotonic
CACHE = {}


def env():
    e = os.environ
    return e['ENV_ID'], e['PREFIX'], json.loads(e['VARIABLES']), json.loads(e['SECRETS']), json.loads(e['DENIED'])


def cached(key, read):
    hit = CACHE.get(key)
    if hit and CLOCK() - hit[0] < TTL:
        return hit[1]
    value = read()
    CACHE[key] = (CLOCK(), value)
    return value


def read_token(ssm, prefix):
    return ssm.get_parameter(Name=prefix + TOKEN)['Parameter']['Value']


def read_path(ssm, prefix):
    found, kw = {}, {'Path': prefix, 'WithDecryption': True}
    while True:
        page = ssm.get_parameters_by_path(**kw)
        for item in page['Parameters']:
            found[item['Name'][len(prefix):]] = item['Value']
        if not page.get('NextToken'):
            return found
        kw['NextToken'] = page['NextToken']


def answer(ident, status, names, body=None):
    print(json.dumps({'env': ident, 'status': status, 'names': sorted(names)}))
    out = {'statusCode': status, 'headers': {'content-type': 'application/json'}}
    out['body'] = json.dumps(body if body is not None else {})
    return out


def bundle(variables, secrets, denied, found):
    """{variables, secrets} of an acceptable bundle and [], or None and the names that refuse it."""
    given = {secrets.get(segment, segment): value for segment, value in found.items() if segment != TOKEN}
    names = list(variables) + list(given)
    bad = [n for n in names if any(fnmatch.fnmatchcase(n, p) for p in denied)]
    bad += [segment for segment in found if segment != TOKEN and segment not in secrets]
    return (None, bad) if bad else ({'variables': variables, 'secrets': given}, [])


def handler(event, context):
    ident, prefix, variables, secrets, denied = env()
    try:
        ssm = boto3.client('ssm')
        want = cached('token', lambda: read_token(ssm, prefix))
        header = (event.get('headers') or {}).get('authorization', '')
        bearer = header[7:] if header[:7].lower() == 'bearer ' else ''
        given = hashlib.sha256(bearer.encode()).hexdigest()
        if not bearer or not hmac.compare_digest(given, want.strip().lower()):
            return answer(ident, 401, [])
        body, bad = bundle(variables, secrets, denied, cached('path', lambda: read_path(ssm, prefix)))
    except Exception:
        return answer(ident, 500, [])
    if body is None:
        return answer(ident, 500, bad)
    return answer(ident, 200, list(body['variables']) + list(body['secrets']), body)
