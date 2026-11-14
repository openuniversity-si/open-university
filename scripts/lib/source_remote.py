"""The source of truth's remote (D-314): whether a git remote is a repository on GitHub, where pull requests, the merge
queue and tower/gate live since 14/11/2026. A GitHub adapter of the vendor catalog (scripts/lib/adapters/engine-vendors.json),
so the Origin adapter asks it instead of naming GitHub's host itself. It calls nothing on GitHub."""

HOST = 'github.com'


def on_github(url, repo, host_of):
    """Whether `url` is `repo` on GitHub; host_of is the caller's parser of a git remote's host."""
    path = url.removesuffix('.git').rstrip('/')
    return host_of(url) == HOST and any(path.endswith(mark + repo) for mark in '/:')
