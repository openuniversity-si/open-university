"""Every Python test runs, exactly once (TX25, D-070; T1/T10): a derived check of scripts/structure-check.

A test is <test-orphans.tests_dir>/<test_glob>, or <tests_dir>/<module>/<test_glob> (the TX24 directory form); the
test-orphans.skip_dirs hold fixtures, not tests. A wrapper is a <tests_dir>/*.test.sh (gate_script_tests.discover, the
script suite's own list). A wrapper runs a test when one of its non-comment lines holds a test_*.py token that matches
the test as a glob: a `<module>/` before the token, or the `-s .../<module>` of a `unittest discover` line, scopes it to
that module directory. It is a lexical reading (no shell parser), so it errs toward the names a reader sees.

check(root) returns the errors, each with its fix:
  a test run by no wrapper (lost coverage: it never ran in a gate),
  a test run by several wrappers (it runs twice per suite and has two owners), unless each of them runs a shard of
    it (SHARD-OWNERS: the line sets a <NAME>_SHARD=<part>, a part of its own: deploy-slow-a/b/c's DEPLOY_TEST_SHARD),
  a wrapper glob that matches no test (a renamed test that a `discover -p` would run zero times without failing).
"""
import argparse
from fnmatch import fnmatchcase
from pathlib import Path
import re
import sys

import config
import gate_script_tests

COMMENT = re.compile(r'(^|\s)#.*$')
DISCOVER_DIR = re.compile(r'''\bdiscover\b.*\s-s\s+["']?([^"'\s]+)''')
SHARD = re.compile(r'(?<![\w$])([A-Z][A-Z0-9_]*_SHARD)=([^\s;]+)')  # SHARD-OWNERS: the part of a test this line runs


def settings(root):
    glob = config.get('test-orphans.test_glob', root)
    head, _, tail = glob.partition('*')
    token = re.compile(rf'(?:(?<![\w$-])([\w-]+)/)?({re.escape(head)}[\w*?\[\]-]*{re.escape(tail)})')
    return config.get('test-orphans.tests_dir', root), glob, set(config.get('test-orphans.skip_dirs', root)), token


def tests(root, tests_dir, glob, skip):
    """{(module or None, file name)} of the tests under tests_dir."""
    base = Path(root) / tests_dir
    found = {(None, path.name) for path in base.glob(glob) if path.is_file()}
    found |= {(path.parent.name, path.name) for path in base.glob(f'*/{glob}')
              if path.is_file() and path.parent.name not in skip}
    return found


def tokens(text, tests_dir, token):
    """[(line number, module or None, glob, shard or None)] of the test names a wrapper runs."""
    top = Path(tests_dir).name
    found = []
    for number, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith('#'):
            continue
        line = COMMENT.sub('', line)
        discover = DISCOVER_DIR.search(line)
        scope = Path(discover.group(1)).name if discover else None
        shard = SHARD.search(line)
        shard = '='.join(shard.groups()) if shard else None
        for module, name in token.findall(line):
            module = module or scope
            found.append((number, None if module in (None, top) else module, name, shard))
    return found


def label(module, name):
    return name if module is None else f'{module}/{name}'


def fix_for(module, name, tests_dir, globs):
    """The fix line for a test no wrapper runs: widen the closest exact name, else add the module's wrapper."""
    stem = name.rsplit('.', 1)[0]
    closest = [(len(glob), wrapper, line, glob) for wrapper, line, scope, glob in globs
               if scope == module and not any(c in glob for c in '*?[') and stem.startswith(glob.rsplit('.', 1)[0])]
    if closest:
        _, wrapper, line, glob = max(closest)
        return f'widen "{glob}" in {wrapper}:{line} to "{glob.rsplit(".", 1)[0]}*.py"'
    owner = module or stem.split('_', 1)[-1].replace('_', '-')
    return (f'add {tests_dir}/{owner}.test.sh running "$root"/{tests_dir}/{label(module, stem)}*.py, '
            f'with its covers manifest')


def sharded(runs):
    """SHARD-OWNERS: several wrappers that each run a part of their own of one test (every line names a shard, no two the
    same) own it together: the suite runs it once, in parts."""
    shards = [shard for *_, shard in runs]
    return all(shards) and len(set(shards)) == len(shards)


def check(root):
    if 'test-orphans.tests_dir' not in config._load(root):
        return []  # a repository without the registry key has no test layout to check
    tests_dir, glob, skip, token = settings(root)
    found = tests(root, tests_dir, glob, skip)
    runs = {test: [] for test in found}
    globs, errors = [], []
    for wrapper in gate_script_tests.discover(root):
        text = (Path(root) / wrapper).read_text(errors='replace')
        for line, module, name, shard in tokens(text, tests_dir, token):
            globs.append((wrapper, line, module, name))
            matched = [test for test in found if test[0] == module and fnmatchcase(test[1], name)]
            if not matched:
                errors.append(f'{wrapper}:{line}: "{label(module, name)}" matches no test under {tests_dir}; '
                              'point it at the renamed test or drop it')
            for test in matched:
                if wrapper not in [run[0] for run in runs[test]]:
                    runs[test].append((wrapper, line, name, shard))
    for test in sorted(found, key=lambda item: label(*item)):
        path = f'{tests_dir}/{label(*test)}'
        if not runs[test]:
            errors.append(f'{path}: run by no wrapper; {fix_for(*test, tests_dir, globs)}')
        elif len(runs[test]) > 1 and not sharded(runs[test]):
            named = ', '.join(f'{wrapper}:{line} "{name}"' for wrapper, line, name, _ in runs[test])
            errors.append(f'{path}: run by {len(runs[test])} wrappers ({named}); '
                          'narrow every glob but the one of the wrapper that owns it')
    return errors


def main(argv=None):
    parser = argparse.ArgumentParser(prog='test_orphans.py', description=__doc__.splitlines()[0])
    parser.add_argument('--root', type=Path, default=gate_script_tests.ROOT, help='repository to check')
    args = parser.parse_args(argv)
    errors = check(args.root)
    for error in errors:
        print(f'ERROR {error}')
    print(f'test orphans: {len(errors)} error(s)')
    return 1 if errors else 0


if __name__ == '__main__':
    sys.exit(main())
