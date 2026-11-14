"""rest_fake routes of the gate's own commit status (engine-gate-report)."""
from http import HTTPStatus


def create_status(handler, method, parts, directory):
    if parts.path.startswith('/repos/') and '/statuses/' in parts.path and method == 'POST':
        handler._body()
        handler._json(HTTPStatus.CREATED, {})
        return True
    return False


ROUTES = (create_status,)
