"""The session side of AGENT-ENV (D-341): fetch what this agent environment declares and write it for the next shell.

    scripts/cloud/agent-env fetch

The environment is the declaration in config/agent-env/ whose starting credential variable is set. With an empty
agent-env.endpoint (not provisioned yet) it says so in one line and does nothing. Otherwise it GETs
<endpoint>/v1/agent-env with `Authorization: Bearer $<credential>` (urllib: HTTPS_PROXY and the CA bundle the session
already uses), expects {"variables": {NAME: value}, "secrets": {NAME: value}} and refuses the whole bundle, writing
nothing, when a name is denied (agent_env.refused, the validator's own rule) or is not declared by the environment.
A bundle it accepts becomes `export NAME=<shell-quoted value>` lines, appended to $CLAUDE_ENV_FILE when set, else
written to .gate/agent-env.sh, mode 600. It prints names and counts only, never a value, and every failure is one line
and exit 0: setup.sh never fails on it.
"""
from http import HTTPStatus
import json
import os
from pathlib import Path
import re
import shlex
import stat
import sys
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import agent_env
import config

ROOT = Path(__file__).resolve().parents[2]
ROUTE = '/v1/agent-env'
TORRE_ROUTE = '/v1/torre'  # the Torre relay's route under the same endpoint (agent_env_stack.TORRE_ROUTE)
LOCAL_FILE = '.gate/agent-env.sh'
ENV_FILE = 'CLAUDE_ENV_FILE'
FILE_MODE = stat.S_IRUSR | stat.S_IWUSR  # 600: the owner alone reads the secrets
NAME = re.compile(r'^[A-Z][A-Z0-9_]*$')
KINDS = ('variables', 'secrets')
LABEL = 'agent-env'


class Refused(Exception):
    """The bundle is refused as a whole; the message names the reason and never a value."""


def endpoint(root=ROOT):
    return config.get('agent-env.endpoint', root).strip().rstrip('/')


def load_declarations(root=ROOT):
    return [json.loads(path.read_text()) for path in agent_env.declarations(root)]


def credential_variable(declaration):
    return (declaration.get('starting_credential') or {}).get('variable', '')


def select(declarations, environ):
    """The first declaration whose starting credential variable is set, or None."""
    for declaration in declarations:
        if environ.get(credential_variable(declaration)):
            return declaration
    return None


def declared(declaration):
    """{kind: set of names} the declaration lets a bundle carry."""
    return {'variables': set(declaration.get('variables') or {}),
            'secrets': {secret.get('name') for secret in declaration.get('secrets') or []}}


def check_bundle(bundle, declaration, patterns, terms):
    """{kind: {name: value}} of an acceptable bundle; Refused otherwise."""
    if not isinstance(bundle, dict) or set(bundle) - set(KINDS):
        raise Refused('the answer is not {variables, secrets}')
    allowed = declared(declaration)
    accepted, problems = {}, []
    for kind in KINDS:
        entries = bundle.get(kind) or {}
        if not isinstance(entries, dict):
            raise Refused(f'{kind} is not an object')
        for name, value in entries.items():
            if not isinstance(name, str) or not NAME.match(name) or not isinstance(value, str):
                problems.append(f'{kind}: a malformed entry')
                continue
            rule = agent_env.refused(name, patterns, terms)
            if rule:
                problems.append(f'{name} is refused by {rule}')
            elif name not in allowed[kind]:
                problems.append(f'{name} is not declared in {kind} of {declaration.get("id")}')
        accepted[kind] = entries
    if problems:
        raise Refused('; '.join(problems))
    return accepted


def render(accepted):
    return ''.join(f'export {name}={shlex.quote(value)}\n'
                   for kind in KINDS for name, value in sorted(accepted[kind].items()))


def write(text, environ, root=ROOT):
    """Append to $CLAUDE_ENV_FILE when set, else replace .gate/agent-env.sh; mode 600 either way. The target path."""
    target = environ.get(ENV_FILE)
    if target:
        path = Path(target)
        flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
    else:
        path = Path(root) / LOCAL_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    descriptor = os.open(path, flags, FILE_MODE)
    try:
        os.fchmod(descriptor, FILE_MODE)
        os.write(descriptor, text.encode())
    finally:
        os.close(descriptor)
    return path


def request(url, token, timeout):
    """The decoded JSON of a 200 answer; Refused names the failure (host, status or exception type, never the token)."""
    host = urlparse(url).hostname or 'the endpoint'
    try:
        with urlopen(Request(url, headers={'Authorization': f'Bearer {token}', 'Accept': 'application/json'}),
                     timeout=timeout) as response:
            if response.status != HTTPStatus.OK:
                raise Refused(f'{host} answered {response.status}')
            body = response.read()
    except HTTPError as error:
        raise Refused(f'{host} answered {error.code}') from None
    except (OSError, ValueError) as error:
        raise Refused(f'{host} could not be reached ({type(error).__name__})') from None
    try:
        return json.loads(body)
    except ValueError:
        raise Refused(f'{host} did not answer JSON') from None


def fetch(environ=None, root=ROOT, out=print):
    """One line on `out` in every case; always 0."""
    environ = os.environ if environ is None else environ
    base = endpoint(root)
    if not base:
        out(f'{LABEL}: not provisioned (agent-env.endpoint is empty); nothing fetched')
        return 0
    declarations = load_declarations(root)
    declaration = select(declarations, environ)
    if declaration is None:
        names = ', '.join(sorted({credential_variable(item) for item in declarations})) or 'none declared'
        out(f'{LABEL}: no starting credential is set ({names}); nothing fetched')
        return 0
    try:
        bundle = request(base + ROUTE, environ[credential_variable(declaration)],
                         config.get('agent-env.fetch_timeout_s', root))
        accepted = check_bundle(bundle, declaration, agent_env.denied_patterns(root), agent_env.vendor_terms(root))
        path = write(render(accepted), environ, root)
    except Refused as reason:
        out(f'{LABEL}: {declaration["id"]}: bundle refused, nothing written: {reason}')
        return 0
    except OSError as error:
        out(f'{LABEL}: {declaration["id"]}: could not write ({type(error).__name__}); nothing written')
        return 0
    counts = ', '.join(f'{len(accepted[kind])} {kind}' for kind in KINDS)
    names = ' '.join(sorted(name for kind in KINDS for name in accepted[kind])) or '-'
    out(f'{LABEL}: {declaration["id"]}: {counts} written to {path}: {names}')
    return 0


def preflight_lines(environ=None, root=ROOT):
    """(warnings, gaps) for scripts/cloud/preflight: an empty endpoint is a warning only; with an endpoint, a missing
    starting credential is a gap. No network."""
    environ = os.environ if environ is None else environ
    if not endpoint(root):
        return [f'{LABEL}: not provisioned'], []
    if select(load_declarations(root), environ) is None:
        return [], [f'{LABEL}: no starting credential is set']
    return [], []


def main(argv):
    if list(argv) != ['fetch']:
        print('usage: scripts/cloud/agent-env fetch', file=sys.stderr)
        return 2
    try:
        return fetch()
    except Exception as error:  # best effort at session start: one line, never a traceback that could carry a value
        print(f'{LABEL}: failed ({type(error).__name__}); nothing written')
        return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
