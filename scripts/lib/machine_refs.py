"""Machine-internal ref pushes (GATE-SPEED, D-091): the pre-push hook's fast path for the train's and runner's records.

The train and the Tower runner write their lock and log refs (prepush.machine_ref_keys: train.lock_ref, train.wake_ref,
gate.shared_results_ref) through forge_git_ref, one commit per record whose tree is record.json alone. Those pushes carry no
code, yet the hook ran commit_check and the pre-push tests on them; on the e2-micro that outlasted train.git_timeout_s
and the runner lost train/lock. `--stdin-refs` reads git's pre-push lines and exits 0 only when every pushed ref is one of
those refs and every commit it adds is a record; anything else (a code branch, a delete, a record ref carrying a file
besides record.json) exits 1 and the hook runs every check.
"""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config  # noqa: E402

RECORD_FILE = 'record.json'


def is_zero(sha):
    """git's all-zero object name: a ref that does not exist (a create's old value, a delete's new one)."""
    return set(sha) == {'0'}


def names():
    return {f'refs/heads/{config.get(key)}' for key in config.get('prepush.machine_ref_keys')}


def git(root, *args):
    return subprocess.run(['git', *args], cwd=root, capture_output=True, text=True)


def is_record(root, sha):
    listed = git(root, 'ls-tree', '--name-only', sha)
    return listed.returncode == 0 and listed.stdout.split() == [RECORD_FILE]


def machine_only(lines, root='.'):
    """True when every pre-push line (<local ref> <local sha> <remote ref> <remote sha>) pushes record commits to a
    machine-internal ref. No line, a delete or any other ref is False: the full checks run."""
    refs, pushed = names(), [line.split() for line in lines if line.strip()]
    if not pushed:
        return False
    for fields in pushed:
        try:
            _, local, target, remote = fields
        except ValueError:
            return False
        if target not in refs or is_zero(local):
            return False
        span = [local] if is_zero(remote) else [local, f'^{remote}']
        listed = git(root, 'rev-list', *span)
        shas = listed.stdout.split()
        if listed.returncode != 0 or not shas or not all(is_record(root, sha) for sha in shas):
            return False
    return True


def main(argv):
    if argv[1:] != ['--stdin-refs']:
        print('usage: machine_refs.py --stdin-refs  (git pre-push lines on stdin); anything else is not a machine push',
              file=sys.stderr)
        return 1
    return 0 if machine_only(sys.stdin.read().splitlines()) else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv))
