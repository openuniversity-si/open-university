"""The source of truth's remote (D-314): whether a git remote is a repository on GitHub, where pull requests, the merge
queue and tower/gate live since 14/11/2026. A GitHub adapter of the vendor catalog (scripts/lib/adapters/engine-vendors.json),
so the Origin adapter asks it instead of naming GitHub's host itself. Its calls on GitHub are heads(), the merge_group
job's read of main and the queue's branch (QUEUE-RELOAD, scripts/lib/deploy.py queue), and api(), a read of GitHub's
REST API through the gh CLI (QUEUE-REARM, scripts/lib/queue_wait.py)."""
import json
import subprocess

HOST = 'github.com'


def on_github(url, repo, host_of):
    """Whether `url` is `repo` on GitHub; host_of is the caller's parser of a git remote's host."""
    path = url.removesuffix('.git').rstrip('/')
    return host_of(url) == HOST and any(path.endswith(mark + repo) for mark in '/:')


def repo_url(environ):
    """QUEUE-RELOAD: the https URL of the repository a GitHub Actions job runs for (GITHUB_SERVER_URL, GITHUB_REPOSITORY)."""
    return f"{environ.get('GITHUB_SERVER_URL') or 'https://' + HOST}/{environ.get('GITHUB_REPOSITORY', '')}.git"


def heads(url, refs, run=subprocess.run):
    """QUEUE-RELOAD: {ref: sha} of these refs on the repository at url (git ls-remote); {} when it does not answer."""
    try:
        out = run(['git', 'ls-remote', url, *refs], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return {}
    if out.returncode != 0:
        return {}
    return {ref: sha for sha, _, ref in (line.partition('\t') for line in out.stdout.splitlines()) if ref}


def api(path, paginate=False, run=subprocess.run):
    """QUEUE-REARM: the JSON GitHub's REST API answers for `path` (`gh api`); with paginate, the list of every page."""
    args = ['gh', 'api', *(['--paginate', '--slurp'] if paginate else []), path]
    done = run(args, capture_output=True, text=True)
    if done.returncode != 0:
        raise RuntimeError(f'gh api {path}: {done.stderr.strip()}')
    return json.loads(done.stdout)
