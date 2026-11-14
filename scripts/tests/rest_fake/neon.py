"""rest_fake routes of Neon for the delivery tail and gate-db: the project, its branches and the connection URI."""
import json

PARENT = 'br-parent-fixture'
DEFAULT_BRANCHES = [
    {'id': PARENT, 'name': 'production', 'default': True, 'protected': True},
    {'id': 'br-preview', 'name': 'v1-preview', 'parent_id': PARENT, 'default': False, 'protected': False,
     'created_at': '2020-01-01T00:00:00Z'},
    {'id': 'br-pr-9', 'name': 'pr-9', 'parent_id': PARENT, 'default': False, 'protected': False,
     'created_at': '2020-01-01T00:00:00Z'},
]
URI = 'postgresql://tower_v1_app:sentinel-secret@127.0.0.1:1/tower_v1?sslmode=require'
PREFIX = '/api/v2/projects/'


def _branches(directory):
    path = directory / 'neon.json'
    if not path.is_file():
        return [dict(item) for item in DEFAULT_BRANCHES], False
    data = json.loads(path.read_text())
    branches = data.get('branches')
    if not isinstance(branches, list):
        return [dict(item) for item in DEFAULT_BRANCHES], False
    return branches, True


def _save_branches(directory, branches):
    path = directory / 'neon.json'
    data = json.loads(path.read_text()) if path.is_file() else {}
    data['branches'] = branches
    path.write_text(json.dumps(data))


def _project(parts):
    return parts.path[len(PREFIX):] if parts.path.startswith(PREFIX) else ''


def project(handler, method, parts, directory):
    project = _project(parts)
    if project and '/' not in project and method == 'GET':
        handler._json(200, {'project': {'id': project}})
        return True
    return False


def list_branches(handler, method, parts, directory):
    if _project(parts).endswith('/branches') and method == 'GET':
        branches, _stored = _branches(directory)
        handler._json(200, {'branches': branches})
        return True
    return False


def delete_branch(handler, method, parts, directory):
    project = _project(parts)
    if '/branches/' in project and method == 'DELETE':
        branch_id = project.split('/branches/', 1)[1]
        branches, stored = _branches(directory)
        branches = [item for item in branches if item.get('id') != branch_id]
        if stored:
            _save_branches(directory, branches)
        with (directory / 'deleted').open('a') as handle:
            handle.write(branch_id + '\n')
        handler._json(200, {})
        return True
    return False


def connection_uri(handler, method, parts, directory):
    if _project(parts).endswith('/connection_uri') and method == 'GET':
        handler._json(200, {'uri': URI})
        return True
    return False


ROUTES = (project, list_branches, delete_branch, connection_uri)
