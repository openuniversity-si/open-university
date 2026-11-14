"""A branch starts from the base in one command (F2, D-211): `scripts/branch-start NAME`.

It fetches the base, refuses a dirty tree (a commit would carry someone else's edit) and a name already on the remote (a push to it
would be refused or would rewrite it), then creates NAME at the base. Local changes to the checkout are never touched.
"""
import argparse
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent.parent
BASE = 'origin/mod/roadmap-integration'
REMOTE, BASE_BRANCH = 'origin', 'mod/roadmap-integration'


def git(root, *args):
    return subprocess.run(['git', '-C', str(root), *args], capture_output=True, text=True)


def dirty(root):
    """The tracked or staged changes of the checkout (untracked files are not a commit's, and do not count)."""
    return [line for line in git(root, 'status', '--porcelain', '--untracked-files=no').stdout.splitlines() if line.strip()]


def remote_has(root, name):
    return bool(git(root, 'ls-remote', '--heads', REMOTE, f'refs/heads/{name}').stdout.strip())


def start(root, name):
    """(ok, message). Nothing is created when a refusal applies."""
    if dirty(root):
        return False, 'the tree has changes to tracked files; commit or stash them first'
    if remote_has(root, name):
        return False, f'{name} is already on the remote; choose another name'
    fetched = git(root, 'fetch', '--quiet', REMOTE, BASE_BRANCH)
    if fetched.returncode != 0:
        return False, f'the base could not be fetched: {fetched.stderr.strip()}'
    created = git(root, 'checkout', '-q', '-B', name, BASE)
    if created.returncode != 0:
        return False, f'could not create {name}: {created.stderr.strip()}'
    return True, f'{name} starts at {BASE}'


def main(argv=None, root=ROOT):
    parser = argparse.ArgumentParser(prog='scripts/branch-start', description=__doc__.split('\n\n')[0])
    parser.add_argument('name', help='the new branch name, e.g. claude/fluxo-amplo-v8-topic')
    args = parser.parse_args(argv)
    ok, message = start(root, args.name)
    print(message, file=sys.stdout if ok else sys.stderr)
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
