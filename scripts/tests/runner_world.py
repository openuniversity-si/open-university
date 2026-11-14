"""RUNNER-WORLD (docs/operations/aws.md 22.9): the world the runner's tests and the infra suites that drive the port share: a
throwaway database migrated by the toolchain's PostgreSQL, the port's routes in process, a runner with local fetch, prepare
and upload, and a forge on the disk. Its own module, so a suite that only builds this world covers it, not every test of
scripts/tests/test_infra_runner.py (which brought 18 suites into a gate whenever a runner test changed).
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'tests'))
from infra_db.psql import migrated  # noqa: E402
import test_db  # noqa: E402
from tower_infra import forge, http_port, mechanisms, port, runner  # noqa: E402

URL = os.environ.get('TEST_DATABASE_URL', '')
COMMIT = '0123456789abcdef0123456789abcdef01234567'
QUICK = float('0.05')  # how often the runner renews in the test: soon, so a stop is seen at once
KEY = b'the-signing-key-of-the-test'
REPO = 'openuniversity-si/open-university'
SETUP = """#!/usr/bin/env bash
set -euo pipefail
test -L .toolchain
readlink .toolchain >> "$SETUP_LOG"
"""


def git(*args):
    return subprocess.run(['git', '-c', 'user.name=fixture', '-c', 'user.email=fixture@example.invalid', *args],
                          check=True, capture_output=True, text=True).stdout.strip()


class Forge:
    """A forge on the disk: a bare repository at <root>/forge/<repo>.git and a clone that makes its commits."""

    def __init__(self, root):
        self.root = Path(root)
        self.bare, self.work = self.root / 'forge' / f'{REPO}.git', self.root / 'work'
        git('init', '--quiet', '--bare', str(self.bare))
        git('init', '--quiet', str(self.work))
        self.commit({'scripts/cloud/setup.sh': SETUP, 'scripts/cloud/toolchain.json': '{"tools": "first"}',
                     'config/registry/toolchain.json': '{}', 'check.sh': 'echo checked'})

    def url(self):
        return (self.root / 'forge').as_uri()

    def commit(self, files, branch='base'):
        for name, body in files.items():
            (self.work / name).parent.mkdir(parents=True, exist_ok=True)
            (self.work / name).write_text(body + '\n')
        git('-C', str(self.work), 'add', '-A')
        git('-C', str(self.work), 'commit', '--quiet', '-m', 'a commit of the test')
        git('-C', str(self.work), 'push', '--quiet', '--force', str(self.bare), f'HEAD:refs/heads/{branch}')
        return git('-C', str(self.work), 'rev-parse', 'HEAD')


class Bucket:
    """S3's put_object, kept in memory."""

    def __init__(self):
        self.kept = {}

    def put_object(self, Bucket, Key, Body, ContentType):  # noqa: N803 - boto3's names
        self.kept[(Bucket, Key)] = Body.decode()


class RunnerWorld(unittest.TestCase):
    def setUp(self):
        self.name, self.db = migrated(URL)
        self.addCleanup(test_db.destroy, URL, self.name)
        for method, path, token, body in (
                ('POST', '/v1/tenants', 'installation', {'name': 'torre', 'token_sha256': port.sha256('torre')}),
                ('POST', '/v1/executors', 'installation', {'name': 'script-runner', 'adapter': 'container'}),
                ('PUT', '/v1/executors/script-runner/capacity/fargate', 'installation', {'slots': '2'}),
                ('POST', '/v1/executors', 'installation', {'name': 'origin-forge', 'adapter': 'forge'}),
                ('PUT', '/v1/executors/origin-forge/capacity/origin', 'installation', {'slots': '1'}),
                ('PUT', '/v1/queues/default', 'torre', {'policy': 'fifo'})):
            self.port(method, path, token, body)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.fetched, self.prepared, self.kept = [], [], {}
        self.workdir = tmp.name
        self.runner = self.runner_with(lambda: KEY)

    def runner_with(self, key):
        return runner.Runner(self.db, self.fetch, self.prepare, self.upload, self.workdir, name='runner-of-the-test',
                             renew_every_s=QUICK, signing_key=key)

    def port(self, method, path, token, body=None):
        answer = http_port.handle({'rawPath': path, 'requestContext': {'http': {'method': method}},
                                   'headers': {'Authorization': f'Bearer {token}'}, 'body': json.dumps(body or {})},
                                  self.db, port.sha256('installation'))
        return json.loads(answer['body'])

    def fetch(self, spec, checkout):
        checkout.mkdir(parents=True, exist_ok=True)
        self.fetched.append(spec['commit'])

    def prepare(self, checkout):
        self.prepared.append(checkout.name)

    def upload(self, run, log):
        self.kept[run['run']] = log.read_text()
        return f"kept:{run['run']}"

    def job(self, key, script, executor='script-runner', digest=None, memoize=False, **more):
        spec = {'repo': 'openuniversity-si/open-university', 'ref': 'base', 'commit': COMMIT,
                'command': ['sh', '-c', script], **more}
        return self.port('POST', '/v1/jobs', 'torre', {'executor': executor, 'input_uri': forge.encode(spec),
                                                       'input_digest': 'sha256:' + (digest or key),
                                                       'idempotency_key': key, 'memoize': memoize})['id']

    def check(self, key, commit, command, **more):
        spec = {'repo': REPO, 'ref': 'base', 'commit': commit, 'command': command, **more}
        return self.port('POST', '/v1/jobs', 'torre', {'executor': 'script-runner', 'input_uri': forge.encode(spec),
                                                       'input_digest': 'sha256:' + key, 'idempotency_key': key})['id']

    def running(self, job):
        return self.db.rows("select 1 from work.run where job_id = %(id)s::uuid and state = 'running'", {'id': job})

    def state(self, job):
        return self.db.rows('select state from work.job where id = %(id)s::uuid', {'id': job})[0][0]

    def started(self, job):
        """Dispatch, then wait in a thread for the runner to take and run the job."""
        mechanisms.dispatch(self.db)
        ended = {}
        thread = threading.Thread(target=lambda: ended.update(self.runner.once() or {}))
        thread.start()
        return thread, ended
