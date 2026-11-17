"""The hermetic-tests check (plan v3 H1, D-069 item 5), a module of the gate's "gate maps" stage (gate_maps.py, D-322).

check(root, base) returns (errors, warnings). A unit or script test (a file under tests.check_roots named test_*.py,
*_test.py, *.test.ts or *.test.mjs; integration, performance and heavy files are judged by their own stage) must not:
  wall_clock  read the wall clock (time.time/monotonic/perf_counter, datetime.now/utcnow/today, date.today, Date.now,
              new Date() without an argument, performance.now): it takes the injected clock (hermetic.clock());
  random      use an unseeded random source (random.<function>, random.Random(), uuid4, os.urandom, secrets,
              Math.random, randomUUID, randomBytes): it takes tests.random_seed (hermetic.rng(), seeded());
  socket      open a socket or a request to a host outside tests.loopback_hosts (socket.socket, create_connection,
              urlopen/fetch of a non-loopback literal URL, net.connect): fixture servers bind to the loopback;
  harness     drop the hermetic sitecustomize for a child (hermetic.without_harness), which only a child that downloads
              by design may do (the toolchain bootstrap): each site is listed.
Python files are read with ast (a string that spells a call is not a call); TypeScript and mjs with line patterns that
skip comment lines. A file that predates the rules is listed in tests.unhermetic_sites as path:RULE; against the base that
list only shrinks (a gained site is admitted only when the base file already offended that rule: disclosed debt, never new
debt), and a listed site that no longer offends is an error (remove it): a stale site hid that F51 moved the uid-0
probe's harness site to another file. warnings is kept for the stage's (errors, warnings) interface and is empty.
"""
import ast
import python_source
import fnmatch
import json
from pathlib import Path
import re
import subprocess

import config

PY_NAMES = ('test_*.py', '*_test.py')
JS_NAMES = ('*.test.ts', '*.test.mjs')
JS_SKIP = ('*.int.test.ts', '*.perf.test.ts', '*.heavy.test.ts')

PY_CLOCK = {'time.time', 'time.time_ns', 'time.monotonic', 'time.perf_counter', 'datetime.now', 'datetime.utcnow',
            'datetime.today', 'datetime.datetime.now', 'datetime.datetime.utcnow', 'datetime.datetime.today',
            'date.today', 'datetime.date.today'}
PY_RANDOM_OK = {'random.seed', 'random.getstate', 'random.setstate', 'random.SystemRandom'}
PY_RANDOM = {'uuid.uuid4', 'uuid4', 'os.urandom', 'secrets.token_hex', 'secrets.token_bytes', 'secrets.token_urlsafe',
             'secrets.choice', 'secrets.randbelow'}
PY_SOCKET = {'socket.socket', 'socket.create_connection', 'create_connection'}

LOOPBACK = r'(?:127\.\d+\.\d+\.\d+|localhost|\[::1\]|\$\{)'
JS_RULES = (
    ('wall_clock', re.compile(r'\bDate\.now\(|\bnew Date\(\s*\)|\bperformance\.now\(')),
    ('random', re.compile(r'\bMath\.random\(|\brandomUUID\(|\brandomBytes\(')),
    ('socket', re.compile(r'\bnet\.(?:connect|createConnection)\(|\bfetch\(\s*[\'"`]https?://(?!' + LOOPBACK + ')')),
)
REMEDY = {
    'wall_clock': 'inject the clock (hermetic.clock() / clock)',
    'random': 'seed the random source (tests.random_seed)',
    'socket': 'keep sockets on the loopback',
    'harness': 'list the site in tests.unhermetic_sites with its reason, or keep the child hermetic',
}


def _dotted(node):
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return '.'.join(reversed(parts))


def _local_family(node):
    """socket.socket(socket.AF_UNIX, ...): a socket on a path of this machine never reaches the network (GATE-SPEED F4)."""
    family = node.args[0] if node.args else next((k.value for k in node.keywords if k.arg == 'family'), None)
    return family is not None and _dotted(family).endswith('AF_UNIX')


def python_rules(text):
    found = set()
    try:
        tree = python_source.parse(text)
    except SyntaxError:
        return found
    for node in python_source.select(tree, ast.Call):
        if not isinstance(node, ast.Call):
            continue
        name = _dotted(node.func)
        if name in PY_CLOCK:
            found.add('wall_clock')
        elif name in PY_RANDOM or (name.startswith('random.') and name not in PY_RANDOM_OK and not (
                name == 'random.Random' and (node.args or node.keywords))):
            found.add('random')
        elif (name in PY_SOCKET and not _local_family(node)) or (name.endswith('urlopen') and node.args and isinstance(node.args[0], ast.Constant)
                                   and isinstance(node.args[0].value, str) and node.args[0].value.startswith('http')
                                   and not re.match(r'https?://' + LOOPBACK, node.args[0].value)):
            found.add('socket')
        elif name == 'without_harness' or name.endswith('.without_harness'):
            found.add('harness')
    return found


def script_rules(text):
    found = set()
    for line in text.splitlines():
        if line.lstrip().startswith(('//', '*', '/*')):
            continue
        for rule, pattern in JS_RULES:
            if pattern.search(line):
                found.add(rule)
    return found


def _git(root, *args):
    return subprocess.run(['git', '-C', str(root), *args], capture_output=True, text=True)


def judged(path, roots):
    name = Path(path).name
    if not any(path.startswith(prefix) for prefix in roots):
        return None
    if any(fnmatch.fnmatch(name, pattern) for pattern in PY_NAMES) and name.endswith('.py'):
        return 'py'
    if any(fnmatch.fnmatch(name, pattern) for pattern in JS_NAMES) and not any(fnmatch.fnmatch(name, p) for p in JS_SKIP):
        return 'js'
    return None


def sites(root, files=None, roots=None):
    """{path:RULE} for every offence of every judged test file."""
    root = Path(root)
    roots = config.get('tests.check_roots', root) if roots is None else roots
    exempt = set(config.get('tests.harness_files', root))
    if files is None:
        listed = _git(root, 'ls-files')
        files = listed.stdout.split() if listed.returncode == 0 else []
    found = set()
    for path in files:
        kind = judged(path, roots)
        if kind is None or path in exempt or not (root / path).is_file():
            continue
        text = (root / path).read_text(encoding='utf-8', errors='replace')
        for rule in (python_rules(text) if kind == 'py' else script_rules(text)):
            found.add(f'{path}:{rule}')
    return found


def _offended_at(root, base, site):
    path, rule = site.rsplit(':', 1)
    kind = judged(path, config.get('tests.check_roots', root))
    shown = _git(root, 'show', f'{base}:{path}')
    if kind is None or shown.returncode != 0:
        return False
    return rule in (python_rules(shown.stdout) if kind == 'py' else script_rules(shown.stdout))


def check(root, base=None):
    root = Path(root)
    if not (root / 'config' / 'registry' / 'tests.json').is_file():
        return [], []
    errors, warnings = [], []
    listed = set(config.get('tests.unhermetic_sites', root))
    found = sites(root)
    for site in sorted(found - listed):
        path, rule = site.rsplit(':', 1)
        errors.append(f'{path}: a unit test breaks the hermetic rule {rule} (D-069 item 5): {REMEDY[rule]}')
    for site in sorted(listed - found):
        errors.append(f'tests.unhermetic_sites lists {site}, which no longer offends: remove the site (a moved '
                      'offence lists its new file; F51 left the old one listed)')
    if base:
        shown = _git(root, 'show', f'{base}:config/registry/tests.json')
        if shown.returncode == 0:
            old = set(json.loads(shown.stdout)['properties']['tests.unhermetic_sites']['default'])
            for site in sorted(listed - old):
                if _offended_at(root, base, site):
                    continue
                errors.append(f'tests.unhermetic_sites gains {site}; the list only shrinks (D-069 item 5)')
    return errors, warnings
