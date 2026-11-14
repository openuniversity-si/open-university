"""rest_fake routes of the GitHub adapter's compare (GX-22, engine-train), which the forge port's compare reads."""
from http import HTTPStatus
import json


def compare(handler, method, parts, directory):
    path = parts.path
    if path.startswith('/repos/') and '/compare/' in path and method == 'GET':
        # GX-22: the compare of a span; compare.json maps a span (base...head) to its answer, default not behind.
        spans = directory / 'compare.json'
        found = json.loads(spans.read_text()) if spans.is_file() else {}
        handler._json(HTTPStatus.OK, found.get(path.split('/compare/', 1)[1], {'behind_by': 0, 'files': []}))
        return True
    return False


ROUTES = (compare,)
