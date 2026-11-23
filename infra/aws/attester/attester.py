"""tower-gate-attester (THREAT-gate, C7, D-359 Salto 2): the AWS verifier that posts the check `tower/gate-attested`.

The GitHub App tower-gate-attester sends its webhooks to this Lambda's Function URL. The front half (`handler` on an
HTTP event) verifies X-Hub-Signature-256 with the webhook secret, keeps only the events that can change the verdict
(the required checks completing, a merge group, a PR head moving, a Torre `Decision:` comment, a re-run of our own
check) and hands a small job to the back half by an asynchronous self-invocation, answering 202 at once. The back half
(`handler` on a job, the function tower-gate-attester-worker) runs one at a time (reserved concurrency 1: no two
verdicts race; Lambda keeps and retries the queued jobs), mints an installation token from
the App's private key and reads every fact itself through the GitHub API, never trusting a verdict sent to it (D-359 (B)):

  pull request head SHA  the newest run (by id) of each required check, reported by GitHub Actions (integration 15368),
                         is completed and success on that exact SHA; the changed files (the PR's own file list, fail
                         closed past 3000) touch no .github/workflows/, .github/actions/ or .github/rulesets/ file, unless
                         an administrator of the repository commented `Decision: ...` with the line
                         `Attest-Head: <that exact SHA>` (the Torre's install path, D-359 (D), D-087); a fork PR touching
                         anything under .github/ is always refused.
  merge group SHA        (gh-readonly-queue/main/pr-N-<prefix>) the required checks are green on the group's commit, the
                         commit is GitHub's merge of exactly two parents (the prefix, then a PR head), and that PR head
                         already carries a green tower/gate-attested of this App (D-359 (C)).

Anything not yet complete is `in_progress`; any red, missing-by-design or unverifiable fact is `failure` (fail closed,
metas 100%). main-health / full-suite are NOT inputs: the Andon never freezes the queue through this check (E).
Stdlib + boto3 (present in the Lambda runtime); the RS256 signature of the App JWT is computed here, without a layer.

Local preview (no App needed; GH_TOKEN of a reader, prints the verdict, writes nothing):
    python3 infra/aws/attester/attester.py evaluate --repo openuniversity-si/open-university --sha <sha40>
"""
import base64
import hashlib
import hmac
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

API = 'https://api.github.com'
CONTEXT = 'tower/gate-attested'
ACTIONS_APP_ID = 15368
REQUIRED = ('tower/gate', 'web', 'gate pinned to the base')
PROTECTED = ('.github/workflows/', '.github/actions/', '.github/rulesets/')
MAX_FILES = 3000
SHA40 = re.compile(r'^[0-9a-f]{40}$')
QUEUE_REF = re.compile(r'^(?:refs/heads/)?gh-readonly-queue/(?P<base>.+)/pr-(?P<number>\d+)-(?P<prefix>[0-9a-f]{40})$')
ATTEST_HEAD = re.compile(r'^\s*Attest-Head:\s*(?P<sha>[0-9a-f]{40})\s*$', re.MULTILINE)
POLICY = 'attester-policy v1 (D-359 B/C/D/E)'

CLOCK = time.time
OPEN = urllib.request.urlopen  # the tests inject theirs
CACHE = {}


# ---------------------------------------------------------------- configuration

def config():
    e = os.environ
    return {
        'repo': e.get('REPO', 'openuniversity-si/open-university'),
        'base': e.get('BASE_BRANCH', 'main'),
        'app_id': int(e['APP_ID']) if e.get('APP_ID', '').isdigit() else None,
        'actions_app_id': int(e.get('ACTIONS_APP_ID', ACTIONS_APP_ID)),
        'required': tuple(json.loads(e['REQUIRED_CHECKS'])) if e.get('REQUIRED_CHECKS') else REQUIRED,
        'key_secret': e.get('KEY_SECRET', 'tower/gate-attester/private-key'),
        'hook_secret': e.get('HOOK_SECRET', 'tower/gate-attester/webhook-secret'),
    }


def secret(name, ttl=300):
    hit = CACHE.get(('secret', name))
    if hit and hit[1] > CLOCK():
        return hit[0]
    import boto3  # the Lambda runtime's; imported late so the tests and the CLI need none
    value = boto3.client('secretsmanager').get_secret_value(SecretId=name)['SecretString']
    CACHE[('secret', name)] = (value, CLOCK() + ttl)
    return value


# ---------------------------------------------------------------- RS256 (PKCS#1 v1.5) without a crypto library

def _der(data, i):
    tag = data[i]
    length = data[i + 1]
    i += 2
    if length & 0x80:
        n = length & 0x7F
        length = int.from_bytes(data[i:i + n], 'big')
        i += n
    return tag, data[i:i + length], i + length


def _ints(seq):
    out, i = [], 0
    while i < len(seq):
        tag, value, i = _der(seq, i)
        if tag == 0x02:
            out.append(int.from_bytes(value, 'big'))
        else:
            out.append(value)
    return out


def rsa_key(pem):
    """(n, e, d, p, q, dp, dq, qinv) from a PKCS#1 or PKCS#8 PEM."""
    lines = [line.strip() for line in pem.strip().splitlines()]
    body = base64.b64decode(''.join(line for line in lines if line and not line.startswith('-----')))
    _, seq, _ = _der(body, 0)
    items = _ints(seq)
    if 'BEGIN PRIVATE KEY' in pem:  # PKCS#8: version, algorithm, OCTET STRING(PKCS#1)
        _, inner, _ = _der(items[2], 0)
        items = _ints(inner)
    if len(items) < 9 or items[0] != 0:
        raise ValueError('not an RSA private key')
    return tuple(items[1:9])


DIGEST_INFO = bytes.fromhex('3031300d060960864801650304020105000420')


def rs256(key, message):
    n, e, d, p, q, dp, dq, qinv = key
    size = (n.bit_length() + 7) // 8
    t = DIGEST_INFO + hashlib.sha256(message).digest()
    em = b'\x00\x01' + b'\xff' * (size - len(t) - 3) + b'\x00' + t
    m = int.from_bytes(em, 'big')
    m1, m2 = pow(m, dp, p), pow(m, dq, q)
    s = m2 + ((qinv * (m1 - m2)) % p) * q
    if pow(s, e, n) != m:  # never publish a faulty signature
        raise ValueError('RSA self-check failed')
    return s.to_bytes(size, 'big')


def _b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode()


def app_jwt(app_id, pem, now=None):
    now = int(CLOCK() if now is None else now)
    head = _b64(json.dumps({'alg': 'RS256', 'typ': 'JWT'}, separators=(',', ':')).encode())
    body = _b64(json.dumps({'iat': now - 60, 'exp': now + 540, 'iss': str(app_id)}, separators=(',', ':')).encode())
    signing = f'{head}.{body}'.encode()
    return f'{head}.{body}.{_b64(rs256(rsa_key(pem), signing))}'


# ---------------------------------------------------------------- GitHub client

class GitHub:
    def __init__(self, token, opener=None):
        self.token = token
        self.open = opener or OPEN

    def call(self, method, path, body=None):
        url = path if path.startswith('http') else API + path
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method, headers={
            'Authorization': f'Bearer {self.token}',
            'Accept': 'application/vnd.github+json',
            'X-GitHub-Api-Version': '2022-11-28',
            'User-Agent': 'tower-gate-attester',
            **({'Content-Type': 'application/json'} if data else {}),
        })
        with self.open(req, timeout=10) as resp:
            raw = resp.read()
        return json.loads(raw) if raw else None

    def pages(self, path, key=None, limit=30):
        out = []
        sep = '&' if '?' in path else '?'
        for page in range(1, limit + 1):
            got = self.call('GET', f'{path}{sep}per_page=100&page={page}')
            items = got.get(key, []) if key else got
            out += items
            if len(items) < 100:
                break
        return out


def installation_token(cfg, opener=None):
    hit = CACHE.get('token')
    if hit and hit[1] > CLOCK():
        return hit[0]
    if cfg['app_id'] is None:
        raise RuntimeError('APP_ID is not set (create the App, then update the stack parameter AppId)')
    jwt = GitHub(app_jwt(cfg['app_id'], secret(cfg['key_secret'])), opener)
    inst = jwt.call('GET', f"/repos/{cfg['repo']}/installation")
    tok = jwt.call('POST', f"/app/installations/{inst['id']}/access_tokens", {})
    CACHE['token'] = (tok['token'], CLOCK() + 45 * 60)
    return tok['token']


# ---------------------------------------------------------------- the verdict (pure)

def newest(runs, name, app_id):
    mine = [r for r in runs if r.get('name') == name and (r.get('app') or {}).get('id') == app_id]
    return max(mine, key=lambda r: int(r.get('id') or 0)) if mine else None


def judge_checks(runs, sha, required, actions_app_id):
    pending, red, green = [], [], []
    for name in required:
        run = newest(runs, name, actions_app_id)
        if run is None:
            pending.append(f'{name}: no run of GitHub Actions ({actions_app_id}) yet')
        elif run.get('head_sha') not in (None, sha):
            red.append(f'{name}: run {run.get("id")} judged {run.get("head_sha")}, not {sha}')
        elif run.get('status') != 'completed':
            pending.append(f'{name}: run {run.get("id")} {run.get("status")}')
        elif run.get('conclusion') != 'success':
            red.append(f'{name}: run {run.get("id")} concluded {run.get("conclusion")}')
        else:
            green.append(f'{name}: run {run.get("id")} success')
    return pending, red, green


def judge_files(files, truncated, fork, decision_ok):
    red = []
    if truncated:
        red.append(f'changed files could not be read completely (more than {MAX_FILES}); fail closed')
    for path in sorted(set(files)):
        if fork and (path == '.github' or path.startswith('.github/')):
            red.append(f'fork PR changes {path}: refused (THREAT-gate)')
        elif path.startswith(PROTECTED) and not decision_ok:
            red.append(f'{path} changed: needs an administrator comment "Decision: ..." with "Attest-Head: <head sha>" (D-359 (D), D-087)')
    return red


def decision_for(comments, sha, is_admin):
    """The first comment that starts with Decision:, names this exact head and comes from an administrator."""
    for c in comments:
        body = (c.get('body') or '').lstrip()
        if not body.startswith('Decision:'):
            continue
        if sha not in [m.group('sha') for m in ATTEST_HEAD.finditer(body)]:
            continue
        login = (c.get('user') or {}).get('login') or ''
        if login and is_admin(login):
            return {'comment': c.get('id'), 'by': login}
    return None


def verdict(pending, red, green, notes=()):
    if red:
        return 'completed', 'failure', f'{len(red)} fact(s) refused', red + list(pending), green, notes
    if pending:
        return 'in_progress', None, f'waiting on {len(pending)} required check(s)', list(pending), green, notes
    return 'completed', 'success', 'every required fact verified on this exact SHA', [], green, notes


# ---------------------------------------------------------------- gathering the facts (reads only)

def facts_pr(gh, cfg, pr, sha):
    repo = cfg['repo']
    runs = gh.pages(f'/repos/{repo}/commits/{sha}/check-runs?filter=all', key='check_runs', limit=10)
    pending, red, green = judge_checks(runs, sha, cfg['required'], cfg['actions_app_id'])
    notes = [f'PR #{pr["number"]} head {sha}']
    if pr.get('base', {}).get('ref') != cfg['base']:
        red.append(f'PR base is {pr.get("base", {}).get("ref")!r}, not {cfg["base"]!r}')
    head_repo = ((pr.get('head') or {}).get('repo') or {}).get('full_name') or ''
    fork = head_repo.casefold() != repo.casefold()
    listed = gh.pages(f'/repos/{repo}/pulls/{pr["number"]}/files', limit=MAX_FILES // 100)
    files = [f['filename'] for f in listed] + [f['previous_filename'] for f in listed if f.get('previous_filename')]
    truncated = int(pr.get('changed_files') or 0) > len(listed) or len(listed) >= MAX_FILES
    decision = None
    if not fork and any(p.startswith(PROTECTED) for p in files):
        comments = gh.pages(f'/repos/{repo}/issues/{pr["number"]}/comments', limit=10)

        def is_admin(login):
            got = gh.call('GET', f'/repos/{repo}/collaborators/{login}/permission')
            return (got or {}).get('permission') == 'admin'
        decision = decision_for(comments, sha, is_admin)
        if decision:
            notes.append(f'workflow/ruleset change accepted by Decision comment {decision["comment"]} of {decision["by"]}')
    red += judge_files(files, truncated, fork, decision is not None)
    if fork:
        notes.append(f'fork head repository {head_repo}')
    return runs, verdict(pending, red, green, notes)


def facts_queue(gh, cfg, sha, match, app_id):
    repo = cfg['repo']
    runs = gh.pages(f'/repos/{repo}/commits/{sha}/check-runs?filter=all', key='check_runs', limit=10)
    pending, red, green = judge_checks(runs, sha, cfg['required'], cfg['actions_app_id'])
    notes = [f'merge group of PR #{match["number"]} on {match["prefix"]}']
    if match['base'] != cfg['base']:
        red.append(f'merge group targets {match["base"]!r}, not {cfg["base"]!r}')
    parents = [p['sha'] for p in (gh.call('GET', f'/repos/{repo}/commits/{sha}') or {}).get('parents', [])]
    if len(parents) != 2 or parents[0] != match['prefix']:
        red.append(f'merge group commit parents {parents} are not [prefix {match["prefix"]}, PR head]')
    else:
        head = parents[1]
        theirs = gh.pages(f'/repos/{repo}/commits/{head}/check-runs?filter=all&check_name={urllib.request.quote(CONTEXT)}',
                          key='check_runs', limit=2)
        mine = newest(theirs, CONTEXT, app_id)
        if mine is None or mine.get('status') != 'completed' or mine.get('conclusion') != 'success':
            red.append(f'PR head {head} has no green {CONTEXT} of this App')
        else:
            green.append(f'PR head {head}: {CONTEXT} run {mine["id"]} success')
    return runs, verdict(pending, red, green, notes)


def find_pr(gh, cfg, job):
    repo = cfg['repo']
    if job.get('pr'):
        pr = gh.call('GET', f'/repos/{repo}/pulls/{int(job["pr"])}')
        return pr if pr and (pr.get('state') == 'open' or job.get('any_state')) else None
    for pr in gh.call('GET', f'/repos/{repo}/commits/{job["sha"]}/pulls') or []:
        if pr.get('state') == 'open' and (pr.get('head') or {}).get('sha') == job['sha'] \
                and (pr.get('base') or {}).get('ref') == cfg['base']:
            return gh.call('GET', f'/repos/{repo}/pulls/{pr["number"]}')
    return None


def evaluate(gh, cfg, job, app_id):
    """(sha, runs, verdict) or None when the job names nothing the attester judges."""
    match = QUEUE_REF.match(job.get('branch') or '')
    if match and SHA40.match(job.get('sha') or ''):
        runs, v = facts_queue(gh, cfg, job['sha'], match.groupdict(), app_id)
        return job['sha'], runs, v
    pr = find_pr(gh, cfg, job)
    if not pr:
        return None
    sha = pr['head']['sha']
    if job.get('sha') and job['sha'] != sha:
        return None  # a stale job: the newer head has its own events
    runs, v = facts_pr(gh, cfg, pr, sha)
    return sha, runs, v


def render(sha, v):
    status, conclusion, title, findings, green, notes = v
    lines = [f'**{CONTEXT}** for `{sha}` — {POLICY}', '']
    lines += [f'- {n}' for n in notes]
    if findings:
        lines += ['', '**Refused / waiting:**'] + [f'- {f}' for f in findings]
    if green:
        lines += ['', '**Verified:**'] + [f'- {g}' for g in green]
    return {'title': title[:250], 'summary': '\n'.join(lines)[:60000]}


def write(gh, cfg, sha, runs, v, app_id):
    status, conclusion = v[0], v[1]
    output = render(sha, v)
    last = newest(runs, CONTEXT, app_id)
    if last and last.get('status') == status and last.get('conclusion') == conclusion \
            and (last.get('output') or {}).get('title') == output['title']:
        return {'wrote': False, 'status': status, 'conclusion': conclusion}
    body = {'name': CONTEXT, 'head_sha': sha, 'status': status, 'output': output,
            'external_id': hashlib.sha256(output['summary'].encode()).hexdigest()[:20]}
    if status == 'completed':
        body['conclusion'] = conclusion
        body['completed_at'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(CLOCK()))
    got = gh.call('POST', f'/repos/{cfg["repo"]}/check-runs', body)
    return {'wrote': True, 'id': (got or {}).get('id'), 'status': status, 'conclusion': conclusion}


# ---------------------------------------------------------------- the front half: which webhooks make a job

def job_for(event_name, payload, cfg):
    if ((payload.get('repository') or {}).get('full_name') or '').casefold() != cfg['repo'].casefold():
        return None
    action = payload.get('action')
    required = set(cfg['required'])
    if event_name == 'check_run':
        run = payload.get('check_run') or {}
        app = (run.get('app') or {}).get('id')
        if action == 'completed' and run.get('name') in required and app == cfg['actions_app_id']:
            pass
        elif action == 'rerequested' and run.get('name') == CONTEXT and app == cfg['app_id']:
            pass
        else:
            return None
        suite = run.get('check_suite') or {}
        prs = [p.get('number') for p in run.get('pull_requests') or []]
        return {'sha': run.get('head_sha'), 'branch': suite.get('head_branch') or '',
                **({'pr': prs[0]} if len(prs) == 1 and not QUEUE_REF.match(suite.get('head_branch') or '') else {})}
    if event_name == 'check_suite':
        suite = payload.get('check_suite') or {}
        app = (suite.get('app') or {}).get('id')
        if (action == 'completed' and app == cfg['actions_app_id']) or (action == 'rerequested' and app == cfg['app_id']):
            return {'sha': suite.get('head_sha'), 'branch': suite.get('head_branch') or ''}
        return None
    if event_name == 'status':
        if payload.get('context') in required:
            return {'sha': payload.get('sha'), 'branch': ''}
        return None
    if event_name == 'merge_group' and action == 'checks_requested':
        group = payload.get('merge_group') or {}
        return {'sha': group.get('head_sha'), 'branch': group.get('head_ref') or ''}
    if event_name == 'pull_request' and action in ('opened', 'synchronize', 'reopened', 'edited'):
        pr = payload.get('pull_request') or {}
        return {'sha': (pr.get('head') or {}).get('sha'), 'pr': pr.get('number'), 'branch': ''}
    if event_name == 'issue_comment' and action in ('created', 'edited'):
        issue = payload.get('issue') or {}
        body = ((payload.get('comment') or {}).get('body') or '').lstrip()
        if 'pull_request' in issue and body.startswith('Decision:') and ATTEST_HEAD.search(body):
            return {'pr': issue.get('number'), 'branch': ''}
    return None


def signed(secret_value, body, header):
    if not header or not header.startswith('sha256='):
        return False
    want = 'sha256=' + hmac.new(secret_value.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(want, header)


def _reply(code, body):
    return {'statusCode': code, 'headers': {'Content-Type': 'application/json'}, 'body': json.dumps(body)}


def front(event, context, cfg, invoke=None):
    headers = {k.lower(): v for k, v in (event.get('headers') or {}).items()}
    raw = event.get('body') or ''
    body = base64.b64decode(raw) if event.get('isBase64Encoded') else raw.encode()
    if len(body) > 5_000_000:
        return _reply(413, {'error': 'too large'})
    if not signed(secret(cfg['hook_secret']), body, headers.get('x-hub-signature-256')):
        return _reply(401, {'error': 'bad signature'})
    name = headers.get('x-github-event', '')
    if name == 'ping':
        return _reply(200, {'pong': True})
    job = job_for(name, json.loads(body or b'{}'), cfg)
    if not job:
        return _reply(202, {'ignored': name})
    job['delivery'] = headers.get('x-github-delivery', '')
    job['event'] = name
    if invoke is None:
        import boto3
        invoke = lambda payload: boto3.client('lambda').invoke(  # noqa: E731
            FunctionName=os.environ.get('WORKER', 'tower-gate-attester-worker'), InvocationType='Event',
            Payload=json.dumps(payload).encode())
    invoke({'job': job})
    return _reply(202, {'queued': job})


def back(job, cfg, gh=None):
    if cfg['app_id'] is None:
        raise RuntimeError('APP_ID is not set')
    gh = gh or GitHub(installation_token(cfg))
    got = evaluate(gh, cfg, job, cfg['app_id'])
    if got is None:
        out = {'job': job, 'skipped': True}
    else:
        sha, runs, v = got
        out = {'job': job, 'sha': sha, **write(gh, cfg, sha, runs, v, cfg['app_id'])}
    print(json.dumps(out))
    return out


def handler(event, context=None):
    cfg = config()
    if 'job' in event:
        return back(event['job'], cfg)
    return front(event, context, cfg)


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(prog='attester.py', description='preview the verdict for a SHA or a PR; writes nothing')
    sub = ap.add_subparsers(dest='cmd', required=True)
    ev = sub.add_parser('evaluate')
    ev.add_argument('--repo', default='openuniversity-si/open-university')
    ev.add_argument('--sha')
    ev.add_argument('--pr', type=int)
    ev.add_argument('--branch', default='', help='gh-readonly-queue/main/pr-N-<prefix> for a merge group SHA')
    ev.add_argument('--app-id', type=int, default=0, help='the App id, to find its green run on a merge group PR head')
    ev.add_argument('--any-state', action='store_true', help='also judge a closed or merged PR (--pr), for rehearsals')
    a = ap.parse_args(argv)
    os.environ['REPO'] = a.repo
    cfg = config()
    token = os.environ.get('GH_TOKEN') or os.environ.get('GITHUB_TOKEN')
    if not token:
        sys.exit('set GH_TOKEN (a read-only reader is enough)')
    got = evaluate(GitHub(token), cfg, {'sha': a.sha, 'pr': a.pr, 'branch': a.branch, 'any_state': a.any_state}, a.app_id)
    if got is None:
        print('nothing to judge (no open PR to the base with that head)')
        return 2
    sha, _, v = got
    print(json.dumps({'sha': sha, 'status': v[0], 'conclusion': v[1], **render(sha, v)}, indent=1))
    return 0 if v[1] == 'success' else 1


if __name__ == '__main__':
    sys.exit(main())
