"""Runs one script test in a throwaway worktree without the files a covers pattern would stop covering: PASS means the pattern can go (D-178).

`scripts/covers-prove TEST --without GLOB [GLOB ...]` checks out HEAD in a detached worktree, deletes every tracked file that
matches a GLOB, runs scripts/tests/TEST.test.sh there and prints PASS (the test does not read what the globs name, so they can leave
its covers manifest) or FAIL with the lines of the test's output that say why (it reads one of them). A GLOB that matches no tracked file is
refused, so a typo never proves anything. The repository is left as it was.
"""
import argparse
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

from gate_areas import glob_match  # noqa: E402

PASS, FAIL, REFUSED = 0, 1, -1
REFUSED_EXIT = FAIL + 1
TOOLCHAIN = '.toolchain'
SIGN = re.compile(r'Error|FAIL|No such file|not found|Traceback')


def tracked(root):
    out = subprocess.run(['git', '-C', str(root), 'ls-files', '-z'], capture_output=True, text=True, check=True).stdout
    return [path for path in out.split('\0') if path]


def matching(paths, globs):
    """{glob: the tracked paths it names}."""
    return {pattern: [path for path in paths if glob_match(path, pattern)] for pattern in globs}


def scratch(euid=os.geteuid):
    """A new temporary directory for the throwaway worktree. mkdtemp makes it 0700; under uid 0 a test's unprivileged
    child could not read the tree inside it, so there it is opened to 0755 (VAZAO F66)."""
    path = Path(tempfile.mkdtemp(prefix='covers-prove-'))
    if euid() == 0:
        path.chmod(0o755)
    return path


def prove(root, test, globs, run=subprocess.run):
    """(verdict, names, tail): PASS, FAIL or REFUSED, the glob that matched nothing (REFUSED), the lines of the test's output that say why."""
    root = Path(root)
    wrapper = f'scripts/tests/{test}.test.sh'
    paths = tracked(root)
    if wrapper not in paths:
        return REFUSED, [wrapper], f'{wrapper} is not a tracked script test'
    named = matching(paths, globs)
    empty = [pattern for pattern, found in named.items() if not found]
    if empty:
        return REFUSED, empty, 'matches no tracked file: ' + ', '.join(empty)
    if any(wrapper in found for found in named.values()):
        return REFUSED, [wrapper], 'a glob names the test itself'
    work = scratch() / 'tree'
    subprocess.run(['git', '-C', str(root), 'worktree', 'add', '--quiet', '--detach', str(work), 'HEAD'], check=True)
    try:
        if (root / TOOLCHAIN).exists():
            (work / TOOLCHAIN).symlink_to((root / TOOLCHAIN).resolve())
        for found in named.values():
            for path in found:
                (work / path).unlink()
        done = run(['bash', str(work / wrapper)], cwd=work, capture_output=True, text=True, check=False,
                   env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})
    finally:
        subprocess.run(['git', '-C', str(root), 'worktree', 'remove', '--force', str(work)], check=False, capture_output=True)
    said = (done.stdout + done.stderr).strip().splitlines()
    tail = '\n'.join(line for line in said if SIGN.search(line)) or '\n'.join(said[-1:])
    return (PASS if done.returncode == 0 else FAIL), [], tail


def main(argv=None, root=ROOT):
    parser = argparse.ArgumentParser(prog='scripts/covers-prove', description=__doc__.split('\n\n')[0])
    parser.add_argument('test', help='the script test name, as in scripts/tests/<test>.test.sh')
    parser.add_argument('--without', nargs='+', required=True, metavar='GLOB', help='tracked files to delete before the test runs')
    args = parser.parse_args(argv)
    verdict, _names, tail = prove(root, args.test, args.without)
    if verdict == REFUSED:
        print(f'REFUSED {args.test}: {tail}', file=sys.stderr)
        return REFUSED_EXIT
    print(f'{"PASS" if verdict == PASS else "FAIL"} {args.test} without {" ".join(args.without)}')
    if verdict == FAIL:
        print(tail)
    return verdict


if __name__ == '__main__':
    sys.exit(main())
