"""Who reads a registry key, found in the code (GATE-SPEED wave 2, R5; D-100).

Selecting the tests of a registry change by the changed keys' `x-readers` (plan R5 A2) is only safe if every file that
reads a key is declared. This module finds them: a tracked source file (Python, shell, JavaScript or TypeScript under
scripts/ or services/; OU-DECOUPLE F5 (D-113): no product source is left) reads a key when it spells the key's full
name as a quoted string: a `config.get`, `config.shared` or `setting` call, an `ou_config_value` line, a JavaScript reader). Tests, generated modules and the registry itself are not readers. Over-reporting (a docstring that quotes a
key) only widens a selection; under-reporting would hide a break, so the test of this module refuses any gap.

  sites(root)            {key: {file, ...}} found in the code
  names(root, wanted)    {name: {file, ...}} for any key names, the same reader definition
  missing(root)          [(key, file)] found but not declared in the key's x-readers
  fix(root)              add each missing reader to config/registry/<owner>/<key>.json, sorted; returns the count
  expand(paths, root)    the changed paths with each split key file's readers added and its owner's generated
                         aggregate left out when key files explain it (R5 A2, D-102); fail closed otherwise
  registry_readers.py [--fix]   print the gaps (exit 1 when any), or fix them
"""
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1].parent
SOURCES = ('scripts/', 'services/')
SUFFIXES = ('.py', '.sh', '.js', '.mjs', '.ts', '.tsx')
KEY_PATH = ('config', 'registry', '<owner>', '<key>.json')  # a split key's file
HEADER_FILE = '_owner.json'  # generate_registry.HEADER: a split owner's header (D-095)
QUOTED = re.compile(r"""['"]([a-z][a-z0-9-]*\.[a-z][a-z0-9_]*)['"]""")


def keys(root):
    found = {}
    for path in sorted((Path(root) / 'config' / 'registry').glob('*.json')):
        for key, item in json.loads(path.read_text())['properties'].items():
            found[key] = (path.stem, set(item.get('x-readers') or []))
    return found


def reader_file(name, tests=False):
    """A source file that can read a key. Tests are not readers while selecting a run (their reads only widen it), but
    a test that spells a key is a reader when the question is whether the key may leave (D-289)."""
    if not name.startswith(SOURCES) or '/generated/' in name:
        return False
    if not tests and ('/tests/' in name or '.test.' in name):
        return False
    tail = name.rsplit('/', 1)[-1]
    return name.endswith(SUFFIXES) or ('.' not in tail and name.startswith('scripts/'))


def sites(root):
    known, found = keys(root), {}
    listed = subprocess.run(['git', '-C', str(root), 'ls-files', '-z'], capture_output=True, check=True).stdout
    for name in sorted(item.decode() for item in listed.split(b'\0') if item):
        if not reader_file(name):
            continue
        try:
            text = (Path(root) / name).read_text(errors='ignore')
        except OSError:
            continue
        for key in {match.group(1) for match in QUOTED.finditer(text)} & set(known):
            found.setdefault(key, set()).add(name)
    return found


def names(root, wanted):
    """{name: {file, ...}} for the given key names among the reader files, tests included: the same definition of a
    reader as sites(), for a name the registry may no longer hold. A removed key leaves only when this is empty
    (D-289). Prose and records are not readers, and neither are generated modules or the registry itself."""
    wanted, found = set(wanted), {}
    listed = subprocess.run(['git', '-C', str(root), 'ls-files', '-z'], capture_output=True, check=True).stdout
    for name in sorted(item.decode() for item in listed.split(b'\0') if item):
        if not reader_file(name, tests=True):
            continue
        try:
            text = (Path(root) / name).read_text(errors='ignore')
        except OSError:
            continue
        for match in QUOTED.finditer(text):
            if match.group(1) in wanted:
                found.setdefault(match.group(1), set()).add(name)
    return found


def missing(root):
    known = keys(root)
    return sorted((key, name) for key, names in sites(root).items() for name in names if name not in known[key][1])


def fix(root):
    gaps, known = missing(root), keys(root)
    for key, name in gaps:
        owner = known[key][0]
        path = Path(root) / 'config' / 'registry' / owner / f'{key}.json'
        if path.is_file():  # a split owner: the key's own file (D-095)
            item = json.loads(path.read_text())
            item['x-readers'] = sorted(set(item.get('x-readers') or []) | {name})
            path.write_text(_text(item))
            continue
        whole = path.parent.with_suffix('.json')  # generate and config stay whole: their one file
        data = json.loads(whole.read_text())
        item = data['properties'][key]
        item['x-readers'] = sorted(set(item.get('x-readers') or []) | {name})
        whole.write_text(_text(data))
    return len(gaps)


def _text(document):
    return json.dumps(document, indent='  ', ensure_ascii=False) + '\n'


def expand(paths, root):
    """R5 A2 (D-102): a diff of split registry keys selects by the keys' readers. Each changed
    config/registry/<owner>/<key>.json adds its readers to the paths: the x-readers its head's file declares and, since
    PADRAO-DEV F4a (D-317), the readers sites() finds in the code, so a reader nobody declared yet is still selected.
    The owner's aggregate
    config/registry/<owner>.json, generated from the key files (its drift is the gate's generated drift stage), leaves
    the paths when every changed file of that owner is a key file with readers. Fail closed: a key without readers, a
    deleted key, a changed _owner.json or an owner that is not split keeps the aggregate, so the wide selection stays."""
    paths = [str(path) for path in paths]
    registry = Path(root) / 'config' / 'registry'
    explained, unexplained, readers = set(), set(), []
    derived = None  # PADRAO-DEV F4a (D-317): the readers found in the code join the declared ones, computed once
    for path in paths:
        parts = path.split('/')
        if len(parts) != len(KEY_PATH) or not path.startswith('config/registry/'):
            continue
        *_, owner, name = parts
        key_file = Path(root) / path
        if name == HEADER_FILE or not name.endswith('.json') or not key_file.is_file():
            unexplained.add(owner)
            continue
        found = list(json.loads(key_file.read_text()).get('x-readers') or [])
        if derived is None:
            derived = sites(root)
        found += sorted(set(derived.get(name[:-len('.json')], ())) - set(found))
        if not found:
            unexplained.add(owner)
            continue
        explained.add(owner)
        readers += found
    drop = {f'config/registry/{owner}.json' for owner in explained - unexplained if (registry / owner / HEADER_FILE).is_file()}
    kept = [path for path in paths if path not in drop]
    return kept + [reader for reader in dict.fromkeys(readers) if reader not in kept]


def main(argv):
    if argv[1:] == ['--fix']:
        print(f'registry readers: {fix(ROOT)} reader(s) declared')
        return 0
    gaps = missing(ROOT)
    for key, name in gaps:
        print(f'FAIL {key}: read by {name}, not in its x-readers')
    return 1 if gaps else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
