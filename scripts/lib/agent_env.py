"""Agent execution environments (AGENT-ENV, D-341): the validator of the declarations in config/agent-env/.

Each declaration, config/agent-env/<id>.json, says what one agent environment receives at session start: its provider,
its non-secret variables, its secrets by name and reference only, its network hosts and its one starting credential.
check(root) returns the errors of every declaration:
  schema    it validates against contracts/agent-env/environment.v1.json, and its id equals its file name;
  prefix    each secret's ref lies under its environment's own prefix for its store (PREFIXES);
  denied    no variable, secret or starting credential is named by a pattern of agent-env.denied_names (fnmatch) or
            matches a retired vendor term (structure.retired_vendor_terms, D-318), the names AGENTS.md "Cloud setup"
            says the engine never sends to a cloud agent.
The delivery and the client ask the same `refused(name)`, so the three refuse one list. Nothing here reads a secret.

    python3 scripts/lib/agent_env.py [--root DIR]

prints each error and a summary line, and exits 1 when there is one.
"""
import argparse
from fnmatch import fnmatchcase
import json
from pathlib import Path
import re
import sys

import config
import json_schema

DECLARATIONS = 'config/agent-env'
SCHEMA = 'contracts/agent-env/environment.v1.json'
PREFIXES = {'ssm': '/tower/agent-env/{id}/', 'secretsmanager': 'tower/agent-env/{id}/'}  # D-341: store -> secret prefix


def denied_patterns(root=None):
    """The registry's deny list, agent-env.denied_names."""
    return config.get('agent-env.denied_names', root)


def vendor_terms(root=None):
    """The retired vendor terms (D-318), refused as names too, so the deny list never names a retired vendor."""
    return config.get('structure.retired_vendor_terms', root)


def refused(name, patterns, terms):
    """The rule that refuses `name`, or None when it may be sent to a cloud agent."""
    for pattern in patterns:
        if fnmatchcase(name, pattern):
            return f'agent-env.denied_names {pattern}'
    for term in terms:
        if re.search(term, name, re.IGNORECASE):
            return 'a retired vendor term (structure.retired_vendor_terms)'
    return None


def names(declaration):
    """[(where, name)] of every name a declaration would put in a session."""
    found = [(f'variables.{name}', name) for name in declaration.get('variables') or {}]
    found += [(f'secrets[{index}].name', secret.get('name', '')) for index, secret in enumerate(declaration.get('secrets') or [])]
    credential = (declaration.get('starting_credential') or {}).get('variable')
    if credential:
        found.append(('starting_credential.variable', credential))
    return found


def validate(declaration, stem, schema, patterns, terms):
    """The errors of one declaration read from config/agent-env/<stem>.json."""
    errors = [f'schema {problem}' for problem in json_schema.validate(schema, declaration)]
    if not isinstance(declaration, dict):
        return errors
    if declaration.get('id') != stem:
        errors.append(f'schema: id {declaration.get("id")!r} is not the file name {stem!r}')
    for index, secret in enumerate(declaration.get('secrets') or []):
        prefix = PREFIXES.get(secret.get('store'), '').format(id=stem)
        ref = secret.get('ref', '')
        if prefix and not (ref.startswith(prefix) and len(ref) > len(prefix)):
            errors.append(f'prefix: secrets[{index}].ref {ref!r} is outside {prefix}')
    for where, name in names(declaration):
        rule = refused(name, patterns, terms)
        if rule:
            errors.append(f'denied: {where} {name} is refused by {rule}')
    return errors


def declarations(root):
    return sorted((Path(root) / DECLARATIONS).glob('*.json'))


def check(root):
    """The errors of every declaration, each prefixed with its path."""
    root = Path(root)
    schema = json.loads((root / SCHEMA).read_text())
    patterns, terms = denied_patterns(root), vendor_terms(root)
    errors = []
    for path in declarations(root):
        where = path.relative_to(root)
        try:
            declaration = json.loads(path.read_text())
        except json.JSONDecodeError as error:
            errors.append(f'{where}: not JSON ({error})')
            continue
        errors += [f'{where}: {problem}' for problem in validate(declaration, path.stem, schema, patterns, terms)]
    return errors


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--root', default=str(Path(__file__).resolve().parents[2]))
    args = parser.parse_args(argv)
    errors = check(args.root)
    for error in errors:
        print(error)
    print(f'agent-env: {len(declarations(args.root))} declaration(s), {len(errors)} error(s)')
    return 1 if errors else 0


if __name__ == '__main__':
    sys.exit(main())
