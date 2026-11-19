"""The AWS stack that serves each AGENT-ENV bundle (D-341): infra/aws/stacks/45-agent-env.json, generated from the
declarations in config/agent-env/ and the deny list agent-env.denied_names. Offline: it reads files and writes one file.

    python3 scripts/lib/agent_env_stack.py template [--check]

writes the stack (--check: exit 1 when the committed one differs). It renders the skeleton infra/aws/agent-env/
environment.json once per declaration <id>: a Lambda tower-app-agent-env-<id> outside the VPC, its own role of that name
under the tower-boundary permissions boundary (SSM GetParameter and GetParametersByPath on /tower/agent-env/<id>/ alone,
kms:Decrypt only through SSM, its log group), the log group and a route GET /agent-env/<id>/v1/agent-env on the port's HTTP
API (the export tower-port-api-id), so the client's agent-env.endpoint is <port url>/agent-env/<id>. The function's code is
infra/aws/agent-env/handler.py inline (a ZipFile, as the mail stack's forwarder); the declaration's non-secret variables,
its SSM secret map (last segment -> name) and the deny list are embedded as its environment at deploy time. Values come
only from SSM, never from the tree. A Secrets Manager reference is refused here until the boundary reads tower/agent-env/
(a later PR). Every role of the stack carries an explicit Deny of secretsmanager:* on the Torre's webhook secrets
(WEBHOOK), so no environment's role can read them whatever its allows say. Stdlib only, deterministic (no clock).
"""
import argparse
import json
from pathlib import Path
import sys

import agent_env
import agent_env_client

ROOT = Path(__file__).resolve().parent.parent.parent
STACK = 'infra/aws/stacks/45-agent-env.json'
SKELETON = 'infra/aws/agent-env/environment.json'
HANDLER = 'infra/aws/agent-env/handler.py'
NAME = 'tower-app-agent-env-{id}'
BASE = '/agent-env/{id}'  # the environment's agent-env.endpoint is <port url> + BASE
ROUTE = 'GET ' + BASE + agent_env_client.ROUTE
API_EXPORT = 'tower-port-api-id'
STORE = 'ssm'  # the one store served until the boundary reads Secrets Manager
WEBHOOK = 'arn:${AWS::Partition}:secretsmanager:${AWS::Region}:${AWS::AccountId}:secret:tower/torre-webhook-*'
DENY_SID = 'NeverTheTorreWebhook'


class StackError(Exception):
    """A declaration the stack cannot serve yet; the message names it."""


def skeleton(root=ROOT):
    return json.loads((Path(root) / SKELETON).read_text(encoding='utf-8'))


def logical(ident):
    return ''.join(part.capitalize() for part in ident.split('-'))


def secret_map(declaration):
    """{last segment: name} of the declaration's SSM secrets, each a direct child of its prefix."""
    prefix = agent_env.PREFIXES[STORE].format(id=declaration['id'])
    found = {}
    for secret in declaration.get('secrets') or []:
        if secret['store'] != STORE:
            raise StackError(f'{declaration["id"]}: {secret["name"]} is in {secret["store"]}; this stack serves {STORE} only')
        segment = secret['ref'][len(prefix):]
        if not secret['ref'].startswith(prefix) or not segment or '/' in segment:
            raise StackError(f'{declaration["id"]}: {secret["name"]} is not a direct child of {prefix}')
        found[segment] = secret['name']
    return found


def filled(node, words, code, environment):
    """The skeleton's node with one environment's words, its code and its environment in place."""
    if isinstance(node, dict):
        return {filled(key, words, code, environment): filled(value, words, code, environment) for key, value in node.items()}
    if isinstance(node, list):
        return [filled(value, words, code, environment) for value in node]
    if node == '@CODE@':
        return code
    if node == '@ENVIRONMENT@':
        return environment
    if isinstance(node, str):
        for word, value in words.items():
            node = node.replace(word, value)
    return node


def rendered(declaration, shape, code, denied):
    """(resources, outputs) of one declaration."""
    ident = declaration['id']
    prefix = agent_env.PREFIXES[STORE].format(id=ident)
    words = {'@PREFIX@': prefix, '@PATH@': prefix.rstrip('/'), '@ID@': ident, '@KEY@': logical(ident)}
    environment = {'ENV_ID': ident, 'PREFIX': prefix, 'VARIABLES': json.dumps(declaration.get('variables') or {}, sort_keys=True),
                   'SECRETS': json.dumps(secret_map(declaration), sort_keys=True), 'DENIED': json.dumps(denied)}
    return (filled(shape['Resources'], words, code, environment), filled(shape['Outputs'], words, code, environment))


def deny_webhook(resources, allowed=()):
    """Append the explicit Deny of the Torre's webhook secrets to every role of the stack but the `allowed` ones."""
    deny = {'Sid': DENY_SID, 'Effect': 'Deny', 'Action': 'secretsmanager:*', 'Resource': {'Fn::Sub': WEBHOOK}}
    for name, item in resources.items():
        if item['Type'] == 'AWS::IAM::Role' and name not in allowed:
            for policy in item['Properties']['Policies']:
                policy['PolicyDocument']['Statement'].append(dict(deny))


def template(root=ROOT):
    root = Path(root)
    errors = agent_env.check(root)
    if errors:
        raise StackError('; '.join(errors))
    shape = skeleton(root)
    code = (root / HANDLER).read_text(encoding='utf-8')
    if len(code.encode('utf-8')) >= shape['zipfile_limit']:
        raise StackError(f'{HANDLER} is over the ZipFile limit of {shape["zipfile_limit"]} bytes')
    denied = agent_env.denied_patterns(root)
    resources, outputs = {}, {}
    for path in agent_env.declarations(root):
        found, given = rendered(json.loads(path.read_text(encoding='utf-8')), shape, code, denied)
        resources.update(found)
        outputs.update(given)
    deny_webhook(resources)
    return {'AWSTemplateFormatVersion': '2010-09-09', 'Description': shape['Description'],
            'Resources': resources, 'Outputs': outputs}


def render(root=ROOT):
    return json.dumps(template(root), indent='  ') + '\n'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('command', choices=['template'])
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--root', default=str(ROOT))
    args = parser.parse_args(argv)
    try:
        body = render(args.root)
    except StackError as error:
        print(f'agent-env stack: {error}')
        return 1
    path = Path(args.root) / STACK
    if args.check:
        same = path.exists() and path.read_text(encoding='utf-8') == body
        print(f'agent-env stack: {STACK} {"matches" if same else "differs from"} its generation')
        return 0 if same else 1
    path.write_text(body, encoding='utf-8')
    print(f'agent-env stack: wrote {STACK}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
