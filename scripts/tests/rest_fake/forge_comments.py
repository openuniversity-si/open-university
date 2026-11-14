"""rest_fake routes of PR comments: the forge_events GitHub adapter (M2, TR1) and comment edits (GX-FIX-forge-rate)."""
from http import HTTPStatus
import json


def _store(directory, number):
    return directory / f'comments-{number}.json'


def create_comment(handler, method, parts, directory):
    path = parts.path
    if path.startswith('/repos/') and '/issues/' in path and path.endswith('/comments') and method == 'POST':
        # Stored per issue so the forge_events GitHub adapter can read back what it appended.
        number = path.split('/issues/', 1)[1].split('/')[0]
        store = _store(directory, number)
        comments = json.loads(store.read_text()) if store.is_file() else []
        try:
            body = json.loads(handler._body() or b'{}').get('body', '')
        except ValueError:
            body = ''
        # ids count every stored comment of every issue, so an edit by id finds one comment
        unique = sum(len(json.loads(other.read_text())) for other in directory.glob('comments-*.json')) + 1
        comments.append({'id': unique, 'body': body, 'author_association': 'OWNER'})
        store.write_text(json.dumps(comments))
        handler._json(201, {'id': comments[-1]['id']})
        return True
    return False


def _edit_comment(directory, comment_id, raw):
    for store in directory.glob('comments-*.json'):
        comments = json.loads(store.read_text())
        for item in comments:
            if str(item['id']) == comment_id:
                item['body'] = json.loads(raw or b'{}').get('body', '')
                store.write_text(json.dumps(comments))
                return True
    return False


def edit_comment(handler, method, parts, directory):
    path = parts.path
    if path.startswith('/repos/') and '/issues/comments/' in path and method == 'PATCH':
        if _edit_comment(directory, path.rsplit('/', 1)[1], handler._body()):
            handler._json(HTTPStatus.OK, {'id': int(path.rsplit('/', 1)[1])})
        else:
            handler._json(HTTPStatus.NOT_FOUND, {})
        return True
    return False


def list_comments(handler, method, parts, directory):
    path = parts.path
    if path.startswith('/repos/') and '/issues/' in path and path.endswith('/comments') and method == 'GET':
        number = path.split('/issues/', 1)[1].split('/')[0]
        store = _store(directory, number)
        comments = json.loads(store.read_text()) if store.is_file() else []
        query = dict(item.split('=', 1) for item in parts.query.split('&') if '=' in item)
        size, page = int(query.get('per_page', '30')), int(query.get('page', '1'))
        handler._json(200, comments[(page - 1) * size:page * size])
        return True
    return False


def issue(handler, method, parts, directory):
    path = parts.path
    if path.startswith('/repos/') and '/issues/' in path and method == 'GET' and path.split('/issues/', 1)[1].isdigit():
        store = _store(directory, path.split('/issues/', 1)[1])
        handler._json(200, {'comments': len(json.loads(store.read_text())) if store.is_file() else 0})
        return True
    return False


ROUTES = (create_comment, edit_comment, list_comments, issue)
