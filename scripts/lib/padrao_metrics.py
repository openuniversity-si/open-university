"""The PADRAO-DEV panel (docs/programs/padrao-dev/phases/F1.md): the measures the program's analysis took by hand, as a command.

The gate selects the script tests of a diff by their covers manifests (gate_script_tests.select) and keys each test's
cache on the files its covers names (gate_test_cache.key). A test that executes a file its covers does not name is
neither selected nor re-run when that file changes. This module measures how often that happens, from what each test
really opened:

  trace TEST [TEST ...] --out DIR [--workers N]
      runs each scripts/tests/<name>.test.sh under `strace -f`, writing DIR/<name>.strace (every successful openat and
      execve) and DIR/<name>.exit (the test's exit status, or `cut` when rules.metrics_trace_timeout_s stopped it)
  selection --traces DIR [--json FILE]
      for every traced test, the tracked code files it opened, those outside its covers, and those whose change alone
      the gate's own selection would not select it for: the silent-skip pairs. A test that opens more than
      rules.metrics_scanner_files code files is a scanner (it reads the code as data) and is counted apart.

The registry, the generated modules and the other paths of gate-trace.covers_trace_ignore, the gate's common inputs
(gate.test_cache_common_inputs) and the test files themselves (scripts/tests/**) are not counted: the selection treats
them by other means (key readers, the cache key, the test's own manifest).
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

import config  # noqa: E402
from gate_areas import glob_match  # noqa: E402
import gate_script_tests  # noqa: E402
from registry_readers import SUFFIXES  # noqa: E402

TESTS_DIR = 'scripts/tests/'
TEST_SUFFIX = '.test.sh'
CODE_ROOTS = ('scripts/', 'infra/', 'services/')
# One successful open or exec in strace's -f output: `<pid>  openat(AT_FDCWD, "<path>", ...) = <fd>` or
# `<pid>  execve("<path>", [...], ...) = 0`. A failed call ends in `= -1 <ERRNO>` and does not match.
CALL = re.compile(r'(?:openat\(AT_FDCWD, |execve\()"((?:[^"\\]|\\.)*)".*\)\s+=\s+\d+')
# Python imports a module from its cached bytecode when the cache is fresh: it opens `<dir>/__pycache__/<name>.<tag>.pyc`
# and only stats `<dir>/<name>.py`. The import is of the source file.
BYTECODE = re.compile(r'^(?P<dir>(?:.*/)?)__pycache__/(?P<name>[^/.]+)\.[^/]+\.pyc$')


def setting(name, root=ROOT):
    return config.get(name, root)


def tracked(root=ROOT):
    """The tracked files of the checkout at `root`."""
    listed = subprocess.run(['git', 'ls-files', '-z'], cwd=root, capture_output=True, check=True).stdout
    return {name for name in listed.decode().split('\0') if name}


def is_code(path):
    """Code the selection must reach: a source file, or an extensionless executable script, under the code roots."""
    if not path.startswith(CODE_ROOTS) or path.startswith(TESTS_DIR):
        return False
    name = path.rsplit('/', 1)[-1]
    return name.endswith(SUFFIXES) or '.' not in name


def parse_trace(text, root, files):
    """The tracked files (checkout-relative) that a strace output opened or executed with success."""
    prefix = str(root).rstrip('/') + '/'
    found = set()
    for line in text.splitlines():
        match = CALL.search(line)
        if not match:
            continue
        path = match.group(1)
        if path.startswith('/'):
            if not path.startswith(prefix):
                continue
            path = path[len(prefix):]
        path = os.path.normpath(path)
        cached = BYTECODE.match(path)
        if cached:
            path = f'{cached["dir"]}{cached["name"]}.py'
        if path in files:
            found.add(path)
    return found


def test_name(script):
    """`scripts/tests/<name>.test.sh` -> `<name>`."""
    return script[len(TESTS_DIR):-len(TEST_SUFFIX)]


def trace_one(script, out, root=ROOT, run=subprocess.run, timeout=None):
    """Runs one script test under strace; writes <out>/<name>.strace and <out>/<name>.exit and returns the status."""
    name = test_name(script)
    log = Path(out) / f'{name}.strace'
    hermetic = str(Path(root) / 'scripts' / 'lib' / 'hermetic')
    env = {**os.environ, 'OU_CONFIG_STORE': 'file',
           'PYTHONPATH': hermetic + (os.pathsep + os.environ['PYTHONPATH'] if os.environ.get('PYTHONPATH') else '')}
    command = ['strace', '-f', '-qq', '-e', 'trace=openat,execve', '-e', 'signal=none', '-o', str(log),
               'bash', str(Path(root) / script)]
    try:
        status = str(run(command, cwd=root, env=env, capture_output=True,
                         timeout=timeout or setting('rules.metrics_trace_timeout_s', root)).returncode)
    except subprocess.TimeoutExpired:
        status = 'cut'
    (Path(out) / f'{name}.exit').write_text(status + '\n')
    return status


def trace(scripts, out, root=ROOT, workers=None, run=subprocess.run):
    """Traces every script test in `scripts`; returns {script: status}."""
    Path(out).mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=workers or os.cpu_count()) as pool:
        statuses = pool.map(lambda script: trace_one(script, out, root, run), scripts)
        return dict(zip(scripts, statuses))


def covered(path, patterns):
    return any(glob_match(path, pattern) for pattern in patterns)


def selection(traces, root=ROOT, mapping=None, files=None, select=None):
    """The completeness of the gate's selection over `traces` ({script: strace text}): totals, per test and per file."""
    mapping = mapping if mapping is not None else gate_script_tests.load(root)
    files = files if files is not None else tracked(root)
    select = select or (lambda path: set(gate_script_tests.select([path], mapping)[0]))
    ignore = tuple(setting('gate-trace.covers_trace_ignore', root)) + tuple(setting('gate.test_cache_common_inputs', root))
    scanner_files = setting('rules.metrics_scanner_files', root)
    covers = {item['script']: (item['script'], *item['covers']) for item in mapping['tests']}
    selected_by = {}
    tests = []
    for script in sorted(traces):
        if script not in covers:
            continue
        opened = sorted(path for path in parse_trace(traces[script], root, files)
                        if is_code(path) and not covered(path, ignore))
        outside = [path for path in opened if not covered(path, covers[script])]
        skipped = []
        for path in outside:
            if path not in selected_by:
                selected_by[path] = select(path)
            if script not in selected_by[path]:
                skipped.append(path)
        tests.append({'test': script, 'opened': len(opened), 'outside': len(outside), 'skipped': skipped,
                      'scanner': len(opened) > scanner_files})
    files_skipping = {}
    for item in tests:
        for path in item['skipped']:
            files_skipping[path] = files_skipping.get(path, 0) + 1
    plain = [item for item in tests if not item['scanner']]
    return {
        'tests': len(tests),
        'pairs': sum(item['opened'] for item in tests),
        'outside': sum(item['outside'] for item in tests),
        'skipped': sum(len(item['skipped']) for item in tests),
        'tests_skipped': sum(1 for item in tests if item['skipped']),
        'scanners': len(tests) - len(plain),
        'plain_tests_skipped': sum(1 for item in plain if item['skipped']),
        'plain_skipped': sum(len(item['skipped']) for item in plain),
        'files_skipping': dict(sorted(files_skipping.items(), key=lambda kv: (-kv[1], kv[0]))),
        'per_test': tests,
    }


def read_traces(directory):
    """{script: strace text} for every <name>.strace in `directory`."""
    return {f'{TESTS_DIR}{path.name[:-len(".strace")]}{TEST_SUFFIX}': path.read_text(errors='replace')
            for path in sorted(Path(directory).glob('*.strace'))}


def summary(found):
    share = 100 * found['outside'] / found['pairs'] if found['pairs'] else 0
    lines = [
        f'selection: {found["tests"]} traced test(s), {found["pairs"]} test x code-file pair(s) opened, '
        f'{found["outside"]} outside the test\'s covers ({share:.0f} %)',
        f'silent skips: {found["skipped"]} pair(s) in {found["tests_skipped"]} test(s) the gate would not run when '
        f'that file alone changes; {found["scanners"]} scanner(s); without them {found["plain_skipped"]} pair(s) in '
        f'{found["plain_tests_skipped"]} test(s)',
    ]
    top = list(found['files_skipping'].items())[:setting('gate-trace.covers_trace_max_listed')]
    lines += [f'  {count} {path}' for path, count in top]
    return '\n'.join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(prog='scripts/padrao-metrics', description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest='command', required=True)
    traced = commands.add_parser('trace', help='run script tests under strace')
    traced.add_argument('tests', nargs='+', help='scripts/tests/<name>.test.sh paths')
    traced.add_argument('--out', required=True)
    traced.add_argument('--workers', type=int)
    chosen = commands.add_parser('selection', help='the completeness of the gate selection from traces')
    chosen.add_argument('--traces', required=True)
    chosen.add_argument('--json')
    args = parser.parse_args(argv)
    if args.command == 'trace':
        wrong = [script for script in args.tests if not (script.startswith(TESTS_DIR) and script.endswith(TEST_SUFFIX)
                                                         and (ROOT / script).is_file())]
        if wrong:
            parser.error(f'not a script test (scripts/tests/<name>.test.sh): {", ".join(wrong)}')
        statuses = trace(args.tests, args.out, workers=args.workers)
        for script, status in statuses.items():
            print(f'{status} {script}')
        return 0
    found = selection(read_traces(args.traces))
    if args.json:
        Path(args.json).write_text(json.dumps(found, indent=1) + '\n')
    print(summary(found))
    return 0


if __name__ == '__main__':
    sys.exit(main())
