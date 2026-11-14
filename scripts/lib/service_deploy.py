"""The control-plane deploy (D-291 (6), TRAIN-DEFINITIVE F16, R5): the Worker of services/control-plane uploaded through
the Cloudflare REST API, with no npx and no wrangler, inside the job budget.

One call: PUT <service.deploy_api_url>/accounts/<account_id>/workers/scripts/<name> (wrangler.toml's account and name),
multipart/form-data with a `metadata` part and one part per module of src/*.js. The metadata carries main_module (the
basename of wrangler.toml `main`), the compatibility date (and flags), the Durable Object bindings, every [vars] entry,
BUDGET_S (service.job_budget_s, the one job budget; wrangler.toml must not set it), DEPLOYED_TREE (the git tree of the checkout's services/control-plane, which GET /status answers as deployed_tree), and
keep_bindings secret_text and secret_key so the Worker's secrets survive. No migration is sent (v1 is applied) and the
cron trigger is not re-sent (the upload leaves it as it is). The token is the variable service.deploy_token_env names
(CLOUDFLARE_API_TOKEN, an entry of service.token_holders); it is sent as a bearer header and never printed.

Library: tree(root), drift(root, deployed_tree), metadata(root, deployed_tree), request(root, token, deployed_tree),
deploy(root, environ, opener, timeout). `python3 scripts/lib/service_deploy.py [--dry-run]` deploys this checkout's
control plane (exit 1 when it did not), or prints the metadata it would send (no token needed).
"""
import argparse
from http import HTTPStatus
import json
import os
from pathlib import Path
import subprocess
import sys
import tomllib
import urllib.error
import urllib.request
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config  # noqa: E402
import service_credentials  # noqa: E402
import service_budget  # noqa: E402

ROOT = Path(__file__).resolve().parents[1].parent
TREE_VAR = 'DEPLOYED_TREE'
BUDGET_VAR = 'BUDGET_S'  # the lease of a claimed job: service.job_budget_s, never a [vars] entry
MODULE_TYPE = 'application/javascript+module'
KEEP = ['secret_text', 'secret_key']  # the Worker's secrets (RUNNER_TOKEN, EVENTS_TOKEN, ...) survive an upload
CRLF = b'\r\n'


def setting(name):
    """A registry value of this engine (ROOT), whatever checkout the deploy reads its files from."""
    return config.get(name, ROOT)


def tree(root=ROOT):
    """The git tree of the checkout's services/control-plane at HEAD (what the Worker records as DEPLOYED_TREE)."""
    return subprocess.run(['git', '-C', str(root), 'rev-parse', f'HEAD:{setting("service.deploy_path")}'],
                          check=True, capture_output=True, text=True).stdout.strip()


def drift(root, deployed_tree):
    """True when the checkout's control plane is not the deployed one (an unknown deployed tree is drift)."""
    return tree(root) != deployed_tree


def wrangler(root=ROOT):
    """wrangler.toml of the control plane, parsed."""
    return tomllib.loads((Path(root) / setting('service.deploy_path') / 'wrangler.toml').read_text())


def modules(root=ROOT):
    """(basename, bytes) of every module the Worker is made of: src/*.js, sorted."""
    source = Path(root) / setting('service.deploy_path') / 'src'
    return [(path.name, path.read_bytes()) for path in sorted(source.glob('*.js'))]


def metadata(root=ROOT, deployed_tree=None):
    """The upload's metadata part (a dict): what wrangler would send for this wrangler.toml, minus migrations and
    triggers, plus DEPLOYED_TREE and keep_bindings."""
    toml = wrangler(root)
    bindings = [{'type': 'durable_object_namespace', 'name': item['name'], 'class_name': item['class_name']}
                for item in toml.get('durable_objects', {}).get('bindings', [])]
    if BUDGET_VAR in toml.get('vars', {}):
        raise ValueError(f'wrangler.toml [vars] sets {BUDGET_VAR}: the budget is service.job_budget_s only')
    for name, value in toml.get('vars', {}).items():
        bindings.append({'type': 'plain_text', 'name': name, 'text': value} if isinstance(value, str)
                        else {'type': 'json', 'name': name, 'json': value})
    bindings.append({'type': 'plain_text', 'name': BUDGET_VAR, 'text': f'{service_budget.budget_s():g}'})
    bindings.append({'type': 'plain_text', 'name': TREE_VAR, 'text': deployed_tree or tree(root)})
    document = {'main_module': Path(toml['main']).name, 'compatibility_date': toml['compatibility_date'],
                'bindings': bindings, 'keep_bindings': list(KEEP)}
    if toml.get('compatibility_flags'):
        document['compatibility_flags'] = list(toml['compatibility_flags'])
    if toml.get('observability', {}).get('enabled'):
        document['observability'] = {'enabled': True}
    return document


def url(root=ROOT):
    toml = wrangler(root)
    base = setting('service.deploy_api_url').rstrip('/')
    return f'{base}/accounts/{toml["account_id"]}/workers/scripts/{toml["name"]}'


def _part(name, content_type, data, filename=None):
    disposition = f'form-data; name="{name}"' + (f'; filename="{filename}"' if filename else '')
    return CRLF.join([f'Content-Disposition: {disposition}'.encode(), f'Content-Type: {content_type}'.encode(), b'',
                      data])


def request(root=ROOT, token='', deployed_tree=None):
    """The upload: PUT of the Worker script as multipart/form-data, bearer `token`."""
    boundary = f'tower-{uuid.uuid4().hex}'.encode()
    parts = [_part('metadata', 'application/json', json.dumps(metadata(root, deployed_tree)).encode())]
    parts += [_part(name, MODULE_TYPE, data, filename=name) for name, data in modules(root)]
    body = b''.join(b'--' + boundary + CRLF + part + CRLF for part in parts) + b'--' + boundary + b'--' + CRLF
    return urllib.request.Request(url(root), data=body, method='PUT', headers={
        'authorization': f'Bearer {token}', 'content-type': f'multipart/form-data; boundary={boundary.decode()}',
        'user-agent': setting('service.user_agent')})


def _success(status):
    try:
        return HTTPStatus(status).is_success
    except ValueError:
        return False


def _first_error(raw):
    try:
        answer = json.loads(raw)
    except (TypeError, ValueError):
        return ''
    errors = answer.get('errors') if isinstance(answer, dict) else None
    if errors and isinstance(errors[0], dict):
        return f'{errors[0].get("code", "")} {errors[0].get("message", "")}'.strip()
    return ''


def deploy(root=ROOT, environ=None, opener=None, timeout=None):
    """(ok, sentence): uploads the checkout's control plane. Refuses without the token (naming the inventory); a 2xx
    with success true is ok; anything else names the HTTP status and the API's first error. Never the token."""
    environ = os.environ if environ is None else environ
    variable = setting('service.deploy_token_env')
    token = environ.get(variable)
    if not token:
        item = service_credentials.entry(variable)
        reason = service_credentials.absent_sentence(item) if item else f'{variable} is not set'
        return False, f'the control-plane deploy needs {variable}: {reason}'
    opener = opener or urllib.request.urlopen
    timeout = setting('service.deploy_timeout_s') if timeout is None else timeout

    def said(ok, sentence):
        return ok, sentence.replace(token, '<token>')

    try:
        current = tree(root)
        name = wrangler(root)['name']
        upload = request(root, token, current)
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError, tomllib.TOMLDecodeError) as error:
        return said(False, f'the control-plane deploy could not be built: {error}')
    try:
        with opener(upload, timeout=timeout) as response:
            status, raw = response.status, response.read()
    except urllib.error.HTTPError as error:
        status, raw = error.code, error.read()
        if status in (HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN):
            return said(False, service_credentials.refused_sentence(variable, status, by='the Cloudflare API'))
    except OSError as error:  # URLError, a timeout: nothing answered
        return said(False, f'the control-plane deploy of {name} got no answer: {error}')
    try:
        answer = json.loads(raw)
    except (TypeError, ValueError):
        answer = None
    if isinstance(answer, dict) and answer.get('success') is True and _success(status):
        shown = setting('service.deploy_tree_chars')
        return said(True, f'deployed {setting("service.deploy_path")} tree {current[:shown]} to {name}')
    error = _first_error(raw) or 'no error message'
    return said(False, f'the control-plane deploy of {name} failed: the Cloudflare API answered {status}: {error}')


def main(argv=None, environ=None):
    parser = argparse.ArgumentParser(description='Deploy the control plane (services/control-plane) through the '
                                                 'Cloudflare API.')
    parser.add_argument('--dry-run', action='store_true', help='print the metadata the upload would send, no token')
    parser.add_argument('--root', default=str(ROOT), help='the checkout (default: this one)')
    args = parser.parse_args(argv)
    if args.dry_run:
        print(json.dumps(metadata(args.root), indent=1, sort_keys=True))
        return 0
    environ = os.environ if environ is None else environ
    if not environ.get(setting('service.deploy_token_env')):
        ok, sentence = deploy(args.root, environ)
        print(sentence, file=sys.stderr)
        return 1
    if environ.get(setting('service.deploy_token_env')):
        service_budget.phase('deploy-check')
        try:
            check = urllib.request.Request(setting('service.control_url').rstrip('/') + '/status',
                                           headers={'user-agent': setting('service.user_agent')})
            with urllib.request.urlopen(check, timeout=setting('service.control_timeout_s')) as response:
                deployed = json.loads(response.read()).get('deployed_tree')
            if not drift(args.root, deployed):
                print('control-plane deploy passed: the merged tree is already deployed')
                return 0
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            print(f'control-plane deploy failed: cannot read the deployed tree ({type(error).__name__})', file=sys.stderr)
            return 1
    service_budget.phase('deploy-upload')
    ok, sentence = deploy(args.root, environ)
    service_budget.phase('deploy-answer')
    print(sentence, file=sys.stdout if ok else sys.stderr)
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
