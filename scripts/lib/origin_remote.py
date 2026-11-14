"""Point this checkout's origin at Origin, and git's sign-in at the origin CLI (Daniel 04/11 16:57 BRT).

A cloud session's checkout can come with origin on the archived GitHub repository, and a push then goes to the wrong
forge (I-4257299c): one incident and one extra round per push. scripts/cloud/setup.sh runs this after its own fetch:
an origin on another forge's host becomes the registry's repository (forge-events.repo) on its first Origin git host
(origin-client.git_hosts); an origin already on Origin, on a local path (the gate's own fixtures and pinned worktrees)
or absent is left alone. When the origin CLI is found where the registry says it may be (origin-client.cli_env,
then PATH, then origin-client.cli_dirs), the checkout's own git config signs in to the Origin host through it, a token
minted from the Cursor key in the environment on each call. It reads the registry, never the adapter's modules (D-069
item 7: the forge is reached through its port). It prints what it changed,
never a credential, and never fails the setup: .githooks/pre-push stays the safety net.

  python3 scripts/lib/origin_remote.py <checkout>
"""
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config  # noqa: E402


def remote_url():
    """The registry's repository on its first Origin git host."""
    return '://'.join(('https', f"{config.get('origin-client.git_hosts')[0]}/{config.get('forge-events.repo')}.git"))


def host_of(url):
    """The lowercased host a git remote names (https://host/o/n, ssh://u@host/o/n, u@host:o/n), or '' for a local
    path."""
    if '://' in url:
        return (urlsplit(url).hostname or '').lower()
    authority, colon, _ = url.partition(':')
    return authority.rpartition('@')[-1].lower() if colon and '/' not in authority else ''


def cli_found():
    """The origin CLI the registry points at: its environment variable, then PATH, then its folders; or None."""
    name = config.get('origin-client.cli')
    found = os.environ.get(config.get('origin-client.cli_env')) or shutil.which(name)
    for folder in ([] if found else config.get('origin-client.cli_dirs')):
        candidate = Path(folder).expanduser() / name
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return found


def git(root, *args, check=True):
    done = subprocess.run(['git', '-C', str(root), *args], capture_output=True, text=True, check=False)
    if check and done.returncode:
        raise RuntimeError(f"git {args[0]}: {(done.stderr or done.stdout).strip()}")
    return done


def helper(cli):
    quoted = shlex.quote(cli)
    return f'!f() {{ CURSOR_AUTH_TOKEN="$({quoted} auth token 2>/dev/null)" exec {quoted} credential-helper "$@"; }}; f'


def point(root, cli=None):
    """Make origin Origin's remote and sign git in through the CLI; answers the lines of what changed."""
    said, url = [], remote_url()
    current = git(root, 'remote', 'get-url', 'origin', check=False).stdout.strip()
    host = host_of(current)
    if host and host not in {item.lower() for item in config.get('origin-client.git_hosts')}:
        git(root, 'remote', 'set-url', 'origin', url)
        said.append(f'origin: {current} -> {url}')
    cli = cli or cli_found()
    if not cli:
        said.append('origin: no origin CLI, so git cannot sign in to Origin yet (scripts/cloud/preflight names it)')
        return said
    key = f"credential.{'://'.join(('https', config.get('origin-client.git_hosts')[0]))}.helper"
    wanted = ['', helper(cli)]  # the empty entry drops any helper set before it for this host
    if git(root, 'config', '--local', '--get-all', key, check=False).stdout.splitlines() != wanted:
        git(root, 'config', '--local', '--unset-all', key, check=False)
        for value in wanted:
            git(root, 'config', '--local', '--add', key, value)
        said.append(f'origin: git signs in to Origin through {cli}')
    return said


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print(__doc__.splitlines()[-1].strip(), file=sys.stderr)
        return 1
    try:
        for line in point(Path(args[0])):
            print(line)
    except Exception as error:  # noqa: BLE001 - the setup goes on; the push hook refuses a wrong remote
        print(f'origin: not pointed at Origin ({type(error).__name__}: {error})', file=sys.stderr)
    return 0


if __name__ == '__main__':
    sys.exit(main())
