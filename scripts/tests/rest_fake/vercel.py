"""rest_fake routes of Vercel for the delivery tail: the project and its production deployment."""


def project(handler, method, parts, directory):
    path = parts.path
    if path.startswith('/v9/projects/') and method == 'GET':
        project_id = path.split('/')[3]
        handler._json(200, {'id': project_id, 'targets': {'production': {'id': 'dpl_fixture'}}})
        return True
    return False


def deployment(handler, method, parts, directory):
    if parts.path.startswith('/v13/deployments/') and method == 'GET':
        handler._json(200, {
            'id': 'dpl_fixture', 'readyState': 'READY', 'target': 'production',
            'url': 'fixture.vercel.app', 'projectId': 'prj_fixture',
            'meta': {'githubCommitSha': 'a' * 40},
        })
        return True
    return False


ROUTES = (project, deployment)
