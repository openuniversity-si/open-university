"""Git merge plumbing shared by train and gate; sequencing and dates belong to callers."""


def merge_tree(git, onto, head, failure):
    """Return (output lines, named conflicts); malformed/fatal answers use the caller's error type."""
    done = git('merge-tree', '--write-tree', '--name-only', '--no-messages', onto, head, check=False)
    lines = done.stdout.splitlines()
    conflicts = sorted(set(line for line in lines[1:] if line.strip())) if done.returncode == 1 else []
    if done.returncode not in (0, 1) or not lines or (done.returncode == 1 and not conflicts):
        raise failure('merge-tree', done)
    return lines, conflicts


def merge_commit(git, tree, onto, head, message, *, env=None):
    """Create a two-parent commit; omitting env preserves the caller's clock and identity.

    The message goes through stdin, never as `-m`: an argument stops at about 128 KB
    (structure.git_message_argv_allowed, D-206)."""
    args = ('commit-tree', tree, '-p', onto, '-p', head)
    extra = {'input': message if message.endswith('\n') else message + '\n'}  # `-m` ends the message with a newline; stdin does not
    if env is not None:
        extra['env'] = env
    return git(*args, **extra).stdout.strip()
