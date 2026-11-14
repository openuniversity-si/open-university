"""The registry-<owner> targets of scripts/generate (GATE-SPEED, D-095): a registry file assembled from one file per key.

Every session that adds a parameter used to edit the same central JSON (config/registry/gate.json held 75 keys), so two
PRs that each add a key conflicted. A split owner keeps its sources in config/registry/<owner>/: `_owner.json` holds the
file's header (everything but `properties`) and each `<key>.json` holds one parameter, named by its full key. The
aggregate config/registry/<owner>.json is generated from them, keys in name order, and merges itself by regeneration
(.gitattributes `merge=regenerate`): two PRs that add two keys add two files and never conflict. Every reader of the
registry (config.py, the generated types, the checks) keeps reading the aggregate unchanged.

A target's output is the aggregate's path; its owner is the output's stem. A key file whose name does not start with
`<owner>.`, a key file that is not one JSON object, or a missing `_owner.json` stops the generator.
"""
import json
from pathlib import Path

HEADER = '_owner.json'


class RegistrySplitError(ValueError):
    pass


def assemble(root, owner):
    """The aggregate registry file of a split owner, as text."""
    folder = Path(root) / 'config' / 'registry' / owner
    header_path = folder / HEADER
    if not header_path.is_file():
        raise RegistrySplitError(f'{folder}: no {HEADER}')
    header = json.loads(header_path.read_text())
    if 'properties' in header:
        raise RegistrySplitError(f'{header_path}: the header holds no properties; each key is its own file')
    properties = {}
    for path in sorted(folder.glob('*.json')):
        if path.name == HEADER:
            continue
        key = path.name[:-len('.json')]
        if not key.startswith(f'{owner}.'):
            raise RegistrySplitError(f'{path}: a key of {owner} is named {owner}.<name>')
        value = json.loads(path.read_text())
        if not isinstance(value, dict):
            raise RegistrySplitError(f'{path}: one parameter, a JSON object')
        properties[key] = value
    return _text(dict(header, properties=properties))


def split(root, owner):
    """One-time migration: write config/registry/<owner>/ from the aggregate (keys in name order). Returns the paths."""
    source = Path(root) / 'config' / 'registry' / f'{owner}.json'
    data = json.loads(source.read_text())
    folder = source.with_suffix('')
    folder.mkdir(exist_ok=True)
    header = {key: value for key, value in data.items() if key != 'properties'}
    written = [folder / HEADER]
    written[0].write_text(_text(header))
    for key, value in data['properties'].items():
        path = folder / f'{key}.json'
        path.write_text(_text(value))
        written.append(path)
    return written


def _text(document):
    """The registry's own spelling: two-space indent, UTF-8 kept, a final newline."""
    return json.dumps(document, indent='  ', ensure_ascii=False) + '\n'


def main(argv):
    """`generate_registry.py <owner> [--check]`: write (or compare) config/registry/<owner>.json from its key files, the
    way to regenerate while the registry-<owner> target is disabled (D-096)."""
    import sys
    owner, root = argv[1], Path(__file__).resolve().parents[1].parent
    target = root / 'config' / 'registry' / f'{owner}.json'
    text = assemble(root, owner)
    if argv[1:][1:] == ['--check']:
        same = target.is_file() and target.read_text() == text
        print(f'{target.relative_to(root)}: {"current" if same else "differs from its key files"}', file=sys.stderr)
        return 0 if same else 1
    target.write_text(text)
    return 0


def owners(root):
    """Every split owner: a config/registry/<owner>/ folder holding _owner.json, in name order."""
    return sorted(path.parent.name for path in (Path(root) / 'config' / 'registry').glob(f'*/{HEADER}'))


def render(root, target):
    """registry-<owner>: that owner's aggregate (the target's output). registry (output: the registry directory, owns_output
    false): every split owner's aggregate, so a new owner needs a folder, not a target."""
    output = target['output']
    if output.endswith('.json'):
        return {output: assemble(root, Path(output).stem)}
    return {f'{output.rstrip("/")}/{owner}.json': assemble(root, owner) for owner in owners(root)}


if __name__ == '__main__':
    import sys
    sys.exit(main(sys.argv))
