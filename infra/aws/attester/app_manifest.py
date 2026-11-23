"""The GitHub App tower-gate-attester from a manifest (D-359 Salto 2; README.md here). Run by the Torre on its box.

    python3 infra/aws/attester/app_manifest.py page  --out DIR [--port PORT]   writes DIR/index.html (the form that posts
                                                                               the manifest to the org's "new App" page)
    python3 infra/aws/attester/app_manifest.py serve --out DIR [--port PORT]   serves DIR on 127.0.0.1:PORT; GitHub's
                                                                               redirect to /callback?code=... runs convert
    python3 infra/aws/attester/app_manifest.py convert CODE [--out DIR]        POST /app-manifests/CODE/conversions and
                                                                               store the secrets (manual fallback)

convert never prints a secret: the App's private key and webhook secret go straight from the response to Secrets Manager
(tower/gate-attester/private-key and tower/gate-attester/webhook-secret) through a mode-600 file under
/workspace/.secrets that is deleted at once; the OAuth client secret is discarded (the attester never uses OAuth). It
writes DIR/app.json (id, slug, owner, html_url: nothing secret) and redeploys the stack with AppId (deploy.sh).
"""
import argparse
import html
import http.server
import json
import os
import secrets
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ORG = 'openuniversity-si'
REPO = 'open-university'
STACK = 'tower-gate-attester'
REGION = os.environ.get('AWS_REGION', 'us-east-1')
SECRETS_DIR = Path(os.environ.get('TOWER_SECRETS_DIR', '/workspace/.secrets'))
KEY_SECRET = 'tower/gate-attester/private-key'
HOOK_SECRET = 'tower/gate-attester/webhook-secret'
PERMISSIONS = {  # least privilege: one write (its own check runs), every other access read-only
    'checks': 'write',
    'statuses': 'read',
    'pull_requests': 'read',
    'issues': 'read',          # the issue_comment event (the Torre's Decision: ... Attest-Head: comment)
    'contents': 'read',        # a merge group commit's parents
    'metadata': 'read',        # the commenter's permission (admin)
    'merge_queues': 'read',    # the merge_group event
}
PORT = 8765  # the local callback server (redirect_url)
EVENTS = ['check_run', 'check_suite', 'status', 'merge_group', 'pull_request', 'issue_comment']


def webhook_url():
    out = subprocess.run(['aws', 'cloudformation', 'describe-stacks', '--region', REGION, '--stack-name', STACK,
                          '--query', "Stacks[0].Outputs[?OutputKey=='WebhookUrl'].OutputValue", '--output', 'text'],
                         check=True, capture_output=True, text=True).stdout.strip()
    if not out.startswith('https://'):
        sys.exit(f'no WebhookUrl output on stack {STACK}')
    return out


def manifest(hook, port):
    return {
        'name': 'tower-gate-attester',
        'description': 'Posts tower/gate-attested after verifying tower/gate, web and the changed files itself (D-359, THREAT-gate).',
        'url': f'https://github.com/{ORG}/{REPO}',
        'hook_attributes': {'url': hook, 'active': True},
        'redirect_url': f'http://127.0.0.1:{port}/callback',
        'public': False,
        'default_permissions': PERMISSIONS,
        'default_events': EVENTS,
    }


def page(out, port, hook=None):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    state = secrets.token_hex(16)
    (out / 'state').write_text(state)
    os.chmod(out / 'state', 0o600)
    data = json.dumps(manifest(hook or webhook_url(), port), indent=1)
    action = f'https://github.com/organizations/{ORG}/settings/apps/new?state={state}'
    (out / 'manifest.json').write_text(data + '\n')
    (out / 'index.html').write_text(f"""<!doctype html>
<meta charset="utf-8"><title>tower-gate-attester: create the App</title>
<h1>tower-gate-attester</h1>
<p>Creates the private GitHub App of the org {ORG} from the manifest below (D-359 Salto 2). Click, then "Create GitHub App"
on GitHub. GitHub sends you back to http://127.0.0.1:{port}/callback, where <code>app_manifest.py serve</code> stores the key
and the webhook secret in AWS Secrets Manager without showing them.</p>
<form action="{html.escape(action)}" method="post">
<input type="hidden" name="manifest" value="{html.escape(data)}">
<button type="submit">Create tower-gate-attester on {ORG}</button>
</form>
<pre>{html.escape(data)}</pre>
""")
    return out / 'index.html'


def put_secret(name, value):
    SECRETS_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = SECRETS_DIR / f'.attester-{secrets.token_hex(6)}.tmp'
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, 'w') as f:
            f.write(value)
        subprocess.run(['aws', 'secretsmanager', 'put-secret-value', '--region', REGION, '--secret-id', name,
                        '--secret-string', f'file://{path}', '--query', 'VersionId', '--output', 'text'],
                       check=True, stdout=subprocess.DEVNULL)
    finally:
        path.unlink(missing_ok=True)


def convert(code, out=None, opener=urllib.request.urlopen, store=put_secret, deploy=True):
    if not code or not all(c.isalnum() or c in '-_' for c in code):
        raise SystemExit('the code is not a manifest code')
    req = urllib.request.Request(f'https://api.github.com/app-manifests/{code}/conversions', data=b'', method='POST',
                                 headers={'Accept': 'application/vnd.github+json', 'User-Agent': 'tower-gate-attester'})
    with opener(req, timeout=20) as resp:
        app = json.loads(resp.read())
    store(KEY_SECRET, app.pop('pem'))
    store(HOOK_SECRET, app.pop('webhook_secret'))
    app.pop('client_secret', None)
    public = {k: app.get(k) for k in ('id', 'slug', 'client_id', 'html_url', 'name')}
    public['owner'] = (app.get('owner') or {}).get('login')
    public['permissions'] = app.get('permissions')
    public['events'] = app.get('events')
    if out:
        Path(out).mkdir(parents=True, exist_ok=True)
        (Path(out) / 'app.json').write_text(json.dumps(public, indent=1) + '\n')
    if deploy:
        subprocess.run([str(HERE / 'deploy.sh'), str(public['id'])], check=True)
    return public


def serve(out, port):
    out = Path(out)
    page(out, port)
    state = (out / 'state').read_text().strip()

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):  # the query carries the one-time code: never log it
            pass

        def reply(self, code, text):
            self.send_response(code)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(text.encode())

        def do_GET(self):
            url = urllib.parse.urlsplit(self.path)
            if url.path in ('/', '/index.html'):
                return self.reply(200, (out / 'index.html').read_text())
            if url.path != '/callback':
                return self.reply(404, 'not found')
            q = urllib.parse.parse_qs(url.query)
            if q.get('state', [''])[0] != state:
                return self.reply(400, 'state mismatch: refused')
            try:
                app = convert(q.get('code', [''])[0], out)
            except Exception as error:  # noqa: BLE001 — the page must say why, without the code
                return self.reply(500, f'conversion failed: {html.escape(type(error).__name__)}')
            install = f"{app['html_url']}/installations/new"
            self.reply(200, f'<p>App {html.escape(str(app["slug"]))} created (id {app["id"]}); secrets stored; stack '
                            f'redeployed. Now <a href="{html.escape(install)}">install it on {ORG}/{REPO} only</a>.</p>')
            print(json.dumps({'app_id': app['id'], 'slug': app['slug'], 'install': install}), flush=True)

    print(f'serving http://127.0.0.1:{port}/ from {out}', flush=True)
    http.server.HTTPServer(('127.0.0.1', port), Handler).serve_forever()


def main(argv=None):
    ap = argparse.ArgumentParser(prog='app_manifest.py')
    sub = ap.add_subparsers(dest='cmd', required=True)
    for name in ('page', 'serve'):
        p = sub.add_parser(name)
        p.add_argument('--out', required=True)
        p.add_argument('--port', type=int, default=PORT)
    c = sub.add_parser('convert')
    c.add_argument('code')
    c.add_argument('--out')
    a = ap.parse_args(argv)
    if a.cmd == 'page':
        print(page(a.out, a.port))
    elif a.cmd == 'serve':
        serve(a.out, a.port)
    else:
        print(json.dumps(convert(a.code, a.out), indent=1))


if __name__ == '__main__':
    main()
