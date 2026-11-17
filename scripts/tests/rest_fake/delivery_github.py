"""rest_fake routes of GitHub for the delivery tail (ship-tail, the migration step of D-035, merge-phase): user, pulls, merge."""
import json


def _pull(directory, number):
    pulls = directory / 'pulls.json'
    if pulls.is_file():
        data = json.loads(pulls.read_text())
        if isinstance(data, dict) and str(number) in data:
            return data[str(number)]
    one = directory / 'pull.json'
    if one.is_file():
        return json.loads(one.read_text())
    tsv = directory / 'pr.tsv'
    if not tsv.is_file():
        return None
    parts = tsv.read_text().strip().split('\t')
    while len(parts) < 7:
        parts.append('')
    state, draft, base_ref, head_ref, head_sha, mergeable, url = parts[:7]
    base_sha = ''
    diff = directory / 'diff.json'
    if diff.is_file():
        try:
            payload = json.loads(diff.read_text())
        except ValueError:
            payload = {}
        if isinstance(payload, dict) and isinstance(payload.get('baseRefOid'), str):
            base_sha = payload['baseRefOid']
    return {
        'state': 'open' if state == 'OPEN' else state.lower(),
        'draft': draft == 'true',
        'merged_at': '2020-01-01T00:00:00Z' if state == 'MERGED' else None,
        'mergeable': {'MERGEABLE': True, 'CONFLICTING': False}.get(mergeable),
        'html_url': url,
        'base': {'ref': base_ref, 'sha': base_sha},
        'head': {'ref': head_ref, 'sha': head_sha},
        'merge_commit_sha': None,
    }


def user(handler, method, parts, directory):
    if parts.path == '/user' and method == 'GET':
        handler._json(200, {'login': 'octo'})
        return True
    return False


def pull_files(handler, method, parts, directory):
    path = parts.path
    if path.startswith('/repos/') and path.rstrip('/').endswith('/files') and method == 'GET':
        listed = directory / 'pull-files.json'
        payload = json.loads(listed.read_text()) if listed.is_file() else []
        handler._json(200, payload if isinstance(payload, list) else [])
        return True
    return False


def pull(handler, method, parts, directory):
    path = parts.path
    if path.startswith('/repos/') and '/pulls/' in path and method == 'GET' and path.endswith('/merge') is False:
        number = path.rstrip('/').split('/')[-1]
        if number.isdigit():
            found = _pull(directory, number)
            if found is None:
                handler._json(404, {})
                return True
            try:
                with (directory / 'views').open('a') as handle:
                    handle.write('view\n')
            except OSError:
                pass
            handler._json(200, found)
            return True
    return False


def merge(handler, method, parts, directory):
    path = parts.path
    if path.startswith('/repos/') and path.endswith('/merge') and method == 'PUT':
        (directory / 'merged').write_bytes(handler._body())
        handler._json(200, {'merged': True, 'sha': 'm' * 40})
        return True
    return False


def git_ref(handler, method, parts, directory):
    if parts.path.startswith('/repos/') and '/git/refs/' in parts.path and method in ('PATCH', 'DELETE'):
        handler._body()
        handler._json(200, {})
        return True
    return False


def edit_pull(handler, method, parts, directory):
    if parts.path.startswith('/repos/') and '/pulls/' in parts.path and method == 'PATCH':
        handler._body()
        handler._json(200, {})
        return True
    return False


def branch(handler, method, parts, directory):
    path = parts.path
    if path.startswith('/repos/') and '/branches/' in path and method == 'GET':
        name = path.rstrip('/').split('/')[-1]
        sha = 'b' * 40
        main = directory / 'main.sha'
        if name == 'main' and main.is_file():
            sha = main.read_text().strip() or sha
        handler._json(200, {'commit': {'sha': sha}})
        return True
    return False


ROUTES = (user, pull_files, pull, merge, git_ref, edit_pull, branch)
