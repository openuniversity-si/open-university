"""The source of truth's remote (D-314): whether a git remote is a repository on GitHub, where pull requests, the merge
queue and tower/gate live since 14/11/2026. A GitHub adapter of the vendor catalog (scripts/lib/adapters/engine-vendors.json),
so the Origin adapter asks it instead of naming GitHub's host itself. Its one call on GitHub is api(), a read of
GitHub's REST API through the gh CLI (QUEUE-REARM, scripts/lib/queue_wait.py); the merge_group job's read of main left
with GITHUB-HOOK (the push webhook rings `landed` at the doorbell)."""
import json
import subprocess

HOST = 'github.com'


def on_github(url, repo, host_of):
    """Whether `url` is `repo` on GitHub; host_of is the caller's parser of a git remote's host."""
    path = url.removesuffix('.git').rstrip('/')
    return host_of(url) == HOST and any(path.endswith(mark + repo) for mark in '/:')


def api(path, paginate=False, run=subprocess.run):
    """QUEUE-REARM: the JSON GitHub's REST API answers for `path` (`gh api`); with paginate, the list of every page."""
    args = ['gh', 'api', *(['--paginate', '--slurp'] if paginate else []), path]
    done = run(args, capture_output=True, text=True)
    if done.returncode != 0:
        raise RuntimeError(f'gh api {path}: {done.stderr.strip()}')
    return json.loads(done.stdout)
