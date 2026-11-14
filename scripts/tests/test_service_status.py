"""The service's status, health and metrics (GATE-TRAIN-SERVICES R3, D-086, ADR-41).

Fake sources for the document's logic, a local bare remote for the git lock, a local HTTP server for the control
plane's GET /status, the contract for its shape. Numbers come from the registry or from 1 (the literal census of a new
unit allows no other); the PR numbers of the closed-PR case are the ones measured on 02/11 (D-290)."""
from datetime import timedelta
import hashlib
import http.server
import json
from pathlib import Path
import re
import statistics
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_forge_events import FakeClock, REPO  # noqa: E402
from test_forge_git_ref import Remote  # noqa: E402
import config  # noqa: E402
import forge_events  # noqa: E402
import json_schema  # noqa: E402
import service  # noqa: E402
import service_status  # noqa: E402

ROOT = Path(__file__).resolve().parents[1].parent
CONTRACT = json.loads((ROOT / 'contracts' / 'service' / 'status.v1.json').read_text())
STALE = config.get('service.heartbeat_stale_s')
OTHER = 1  + 1  # a distinct fixture PR
SAMPLE = re.compile(r'^tower_[a-z_]+(\{[a-z_]+="[^"]*"(,[a-z_]+="[^"]*")*\})? -?[0-9.e+-]+$')


def at(moment):
    return forge_events.rfc3339(moment)


HEAD_A, HEAD_B, HEAD_C = (hashlib.sha1(name).hexdigest() for name in (b'a', b'b', b'c'))
CLOSED = (907, 910, 956, 966)  # closed 01/11, never merged, counted as waiting by the wake-log meter (D-290)
LIVE = 1066  # open on 02/11


def entry(pr, sha, when):
    """One item of the control plane's GET /status queue (services/control-plane/src/core.js status())."""
    return {'pr': pr, 'sha': sha, 'woken_at': at(when)}


class Fake(service_status.Sources):
    """Sources whose reads are plain values; `fail` names the read that raises. `opened` None: every queued PR is open."""

    def __init__(self, clock, lock=None, queue=(), opened=None, merges=(), events=(), runner=None, paused=False,
                 fail=(), landed=(), health=None):
        self.clock, self.root, self._health = clock, ROOT, health
        self._landed = set(landed)
        self._lock, self._queue, self._events, self._runner = lock, list(queue), list(events), runner
        self._opened, self._merges = opened, list(merges)
        self._paused, self._fail = paused, set(fail)

    def lock(self):
        if 'lock' in self._fail:
            raise RuntimeError('fetch failed')
        return self._lock

    def landed(self, sha):
        return sha in self._landed

    def control(self):
        if 'control' in self._fail:
            raise OSError('control plane unreachable')
        return {'queue': self._queue, 'merges': self._merges, **({'health': self._health} if self._health else {})}

    def open_prs(self):
        if 'open' in self._fail:
            raise RuntimeError('the forge refused the list')
        return {item['pr'] for item in self._queue} if self._opened is None else set(self._opened)

    def window(self):
        if 'window' in self._fail:
            raise RuntimeError('the forge is down')
        return self._events, True

    def runner(self):
        return self._runner

    def switches(self):
        return {'paused': self._paused, 'transport': config.get('service.transport'),
                'train_switch': not self._paused, 'trigger_mode': config.get('train.trigger_mode')}


def merged(pr, head, when, batch='v-x'):
    return {'type': 'pr.merged', 'occurred_at': at(when), 'payload': {'pr': pr, 'sha': head, 'batch_id': batch}}


def ready(pr, head, when):
    return {'type': 'pr.ready', 'occurred_at': at(when), 'payload': {'pr': pr, 'sha': head}}


class Status(unittest.TestCase):
    def setUp(self):
        self.enterContext(config.use_adapter(forge_events.MemoryAdapter()))
        self.clock = FakeClock()
        self.start = self.clock.now()
        self.minute = timedelta(minutes=1)

    def document(self, **sources):
        return service_status.status(Fake(self.clock, **sources))

    def test_a_store_still_holding_the_git_route_is_a_failed_check_not_a_quiet_default(self):
        """The shared store held service.transport `git` when the registry made `control` its only value (D-290): the real
        switches() shows the registry default and says the stored value is unreadable, so status never claims a route the
        runner would refuse."""
        real = service_status.config.shared

        def stored(name, *rest):
            if name == 'service.transport':
                raise service_status.config.ConfigError(
                    "config: the stored value of service.transport no longer satisfies its schema ('git' is not one of ['control'])")
            return real(name, *rest)

        with mock.patch.object(service_status.config, 'shared', side_effect=stored):
            found = service_status.Sources.switches(Fake(self.clock))
        self.assertEqual(found['transport'], 'control')
        self.assertIn('service.transport', found['unreadable'][0])
        fake = Fake(self.clock)
        fake.switches = lambda: dict(found)
        document = service_status.status(fake)
        checks = {check['name']: check for check in document['health']['checks']}
        self.assertEqual(checks['switches']['status'], 'fail')
        self.assertIn("'git'", checks['switches']['detail'])
        self.assertEqual(document['health']['status'], 'fail')

    def test_the_document_is_a_status_v1(self):
        runner = {'name': 'box', 'kind': 'box', 'heartbeat': at(self.start), 'results': [
            {'job': f'gate:{1}#{HEAD_A}', 'outcome': 'passed', 'duration_s': STALE}]}
        document = self.document(lock={'sha': HEAD_C, 'owner': 'train@x', 'expires': at(self.start + self.minute)},
                                 queue=[entry(OTHER, HEAD_B, self.start)],
                                 events=[merged(1, HEAD_A, self.start + self.minute)], runner=runner)
        self.assertEqual(json_schema.validate(CONTRACT, document), [])
        self.assertIsNone(document['train']['wake'])  # train/wake is no job channel (D-290)

    def test_passing_checks_do_not_claim_control_plane_availability(self):
        document = self.document(runner={'name': 'box', 'heartbeat': at(self.start)})
        self.assertEqual(document['health']['status'], service_status.PASS)
        self.assertEqual(document['health']['scope'], 'repository_and_machine')
        scopes = {check['name']: check['scope'] for check in document['health']['checks']}
        self.assertEqual(scopes, dict.fromkeys(('git', 'forge', 'forge-open', 'lock', 'queue'), 'repository')
                         | {'runner': 'machine', 'control': 'control_plane'})
        for field in ('runners', 'jobs'):
            self.assertEqual(document['control_plane'][field], 'unknown')
        self.assertEqual(json_schema.validate(CONTRACT, document), [])
        text = service_status.human(document)
        self.assertIn('global availability unknown', text)
        self.assertIn('runners=unknown, jobs=unknown', text)
        self.assertIn('check runner [machine]: pass', text)

    def test_the_meter_drops_a_pr_the_forge_reports_closed(self):
        """The 02/11 case: the store still queues #907 #910 #956 #966 (closed 01/11) beside the open #1066."""
        queue = [entry(pr, head, self.start + self.minute * index) for pr in CLOSED + (LIVE,)
                 for index, head in enumerate((HEAD_A, HEAD_B))]  # the store keeps a job per pushed head
        before = self.document(queue=queue)  # every queued PR open: the count the meter gave without the forge
        after = self.document(queue=queue, opened={LIVE, OTHER})
        self.assertEqual(len(before['queue']), len(CLOSED) + 1)
        self.assertEqual([item['pr'] for item in after['queue']], [LIVE])
        self.assertEqual((before['metrics']['queue_depth'], after['metrics']['queue_depth']),
                         ([[{}, len(CLOSED) + 1]], [[{}, 1]]))
        self.assertEqual(json_schema.validate(CONTRACT, after), [])

    def test_the_queue_is_one_entry_per_pr_its_newest(self):
        queue = [entry(1, HEAD_A, self.start), entry(1, HEAD_B, self.start + self.minute), entry(OTHER, HEAD_C, self.start)]
        document = self.document(queue=queue)
        self.assertEqual(sorted((item['pr'], item['sha']) for item in document['queue']), [(1, HEAD_B), (OTHER, HEAD_C)])

    def test_a_queued_pr_already_in_the_base_history_is_not_waiting(self):
        document = self.document(queue=[entry(1, HEAD_A, self.start), entry(OTHER, HEAD_B, self.start)], landed=[HEAD_A])
        self.assertEqual([(item['pr'], item['sha']) for item in document['queue']], [(OTHER, HEAD_B)])

    def test_an_unreadable_control_plane_fails_and_leaves_the_queue_unknown(self):
        document = self.document(queue=[entry(LIVE, HEAD_A, self.start)], fail={'control'})
        checks = {check['name']: (check['status'], check['detail']) for check in document['health']['checks']}
        self.assertEqual(checks['control'][0], service_status.FAIL)
        self.assertIn('control plane unreachable', checks['control'][1])
        self.assertEqual(checks['queue'][0], service_status.WARN)
        self.assertIn('unknown', checks['queue'][1])
        self.assertEqual(document['queue'], [])
        self.assertNotIn('queue_depth', document['metrics'])  # no number rather than a wrong one
        self.assertIn('queue: unknown', service_status.human(document))
        self.assertEqual(json_schema.validate(CONTRACT, document), [])

    def test_an_unreadable_forge_open_list_fails_and_counts_nothing_unfiltered(self):
        document = self.document(queue=[entry(pr, HEAD_A, self.start) for pr in CLOSED + (LIVE,)], fail={'open'})
        checks = {check['name']: check['status'] for check in document['health']['checks']}
        self.assertEqual((checks['forge-open'], checks['queue']), (service_status.FAIL, service_status.WARN))
        self.assertEqual(document['queue'], [])
        self.assertNotIn('queue_depth', document['metrics'])

    def test_the_real_sources_read_landed_from_git(self):
        # on a repository of its own: the runner's checkout holds the commit it judges, not origin/<base> (#632 on AWS)
        with tempfile.TemporaryDirectory() as root:
            def git(*args):
                return subprocess.run(['git', '-C', root, '-c', 'user.name=t', '-c', 'user.email=t@t', *args],
                                      capture_output=True, text=True, check=True).stdout.strip()
            git('init', '-q')
            git('commit', '-q', '--allow-empty', '-m', 'base')
            tip = git('rev-parse', 'HEAD')
            git('update-ref', 'refs/remotes/origin/' + config.get('train.base_branch'), tip)
            git('commit', '-q', '--allow-empty', '-m', 'not landed')
            sources = service_status.Sources(Path(root), clock=self.clock)
            self.assertFalse(sources.landed(HEAD_A))  # a sha that is no commit of this repository
            self.assertTrue(sources.landed(tip))  # the base tip is in the base's history
            self.assertFalse(sources.landed(git('rev-parse', 'HEAD')))  # a commit past it is not

    def test_the_human_status_gives_the_median_ready_to_merge_and_leaves_out_a_ready_after_the_merge(self):
        late = self.start + self.minute * 4  # the third PR's pr.ready comes after its merge
        short, long = self.start + self.minute, self.start + self.minute * 3
        events = [ready(1, HEAD_A, self.start), ready(OTHER, HEAD_B, self.start), ready(OTHER + 1, HEAD_C, late),
                  merged(1, HEAD_A, short), merged(OTHER, HEAD_B, long), merged(OTHER + 1, HEAD_C, short)]
        lags = [(short - self.start).total_seconds(), (long - self.start).total_seconds()]
        text = service_status.human(self.document(events=events))
        self.assertIn(f'median {statistics.median(lags):.0f} s over {len(lags)} merge(s)', text)

    def test_green_to_merged_is_from_the_ready_to_the_merge_or_the_control_planes_own_measure(self):
        events = [ready(1, HEAD_A, self.start), merged(1, HEAD_A, self.start + self.minute),
                  merged(OTHER, HEAD_B, self.start + self.minute)]
        document = self.document(events=events, merges=[{'pr': OTHER, 'sha': HEAD_B, 'green_to_merged_s': STALE}])
        lags = {item['pr']: item['green_to_merged_s'] for item in document['merges']}
        self.assertEqual(lags, {1: self.minute.total_seconds(), OTHER: STALE})
        self.assertEqual(document['queue'], [])

    def test_a_dead_runner_fails_health_and_a_missing_one_warns(self):
        old = at(self.start - timedelta(seconds=STALE + 1))
        dead = self.document(runner={'name': 'box', 'heartbeat': old})
        self.assertEqual(dead['health']['status'], service_status.FAIL)
        self.assertEqual(self.document()['health']['status'], service_status.WARN)

    def test_a_lock_left_past_its_lease_warns(self):
        late = self.start - timedelta(seconds=config.get('service.lock_stale_s') + 1)
        checks = {check['name']: check['status'] for check in
                  self.document(lock={'sha': HEAD_C, 'owner': 'train@dead', 'expires': at(late)})['health']['checks']}
        self.assertEqual(checks['lock'], service_status.WARN)

    def test_a_lock_released_by_a_run_that_died_warns_with_its_reason(self):
        """TRAIN-TEMP-FIX R1: the reason a dead run left on its release record is a warned check, never a quiet free."""
        dead = {'sha': HEAD_C, 'owner': 'train@vm:1', 'expires': None, 'died': 'ControlError: no events token'}
        document = self.document(lock=dead)
        check = next(check for check in document['health']['checks'] if check['name'] == 'lock')
        self.assertEqual(check['status'], service_status.WARN)
        self.assertIn('train@vm:1', check['detail'])
        self.assertIn('ControlError: no events token', check['detail'])
        self.assertIn('lock: free (released by train@vm:1; that run died: ControlError: no events token)',
                      service_status.human(document))
        clean = dict(dead, died=None)
        self.assertEqual(next(c for c in self.document(lock=clean)['health']['checks'] if c['name'] == 'lock')['status'],
                         service_status.PASS)
        self.assertIn('lock: free (released by train@vm:1)', service_status.human(self.document(lock=clean)))

    def test_a_runner_the_control_plane_reports_silent_is_a_warned_check(self):
        """TRAIN-TEMP-FIX: GET /status warned 'runner the-tower-runner: beat 149770 s ago' while the CLI said
        runners=unknown and nothing about it; its non-passing checks are now relayed."""
        silent = {'status': 'warn', 'checks': [{'name': 'secrets', 'status': 'pass', 'detail': 'all set'},
                                               {'name': 'runner the-tower-runner', 'status': 'warn',
                                                'detail': 'beat 149770 s ago'}]}
        checks = {check['name']: check for check in self.document(health=silent)['health']['checks']}
        self.assertEqual((checks['control-health']['status'], checks['control-health']['scope']),
                         (service_status.WARN, 'control_plane'))
        self.assertEqual(checks['control-health']['detail'], 'runner the-tower-runner: beat 149770 s ago')
        quiet = {'status': 'pass', 'checks': [{'name': 'secrets', 'status': 'pass', 'detail': 'all set'}]}
        names = {check['name'] for check in self.document(health=quiet)['health']['checks']}
        self.assertNotIn('control-health', names)
        self.assertNotIn('control-health', {c['name'] for c in self.document(fail={'control'})['health']['checks']})

    def test_paused_warns(self):
        checks = {check['name'] for check in self.document(paused=True)['health']['checks']}
        self.assertIn('paused', checks)

    def test_an_unreadable_source_is_a_failed_check_not_a_crash(self):
        document = self.document(fail={'window', 'lock'})
        checks = {check['name']: check['status'] for check in document['health']['checks']}
        self.assertEqual((checks['forge'], checks['git']), (service_status.FAIL, service_status.FAIL))
        self.assertEqual(document['window'], {'events': 0, 'complete': False})

    def test_the_metrics_are_prometheus_text(self):
        document = self.document(queue=[entry(OTHER, HEAD_B, self.start)],
                                 events=[merged(1, HEAD_A, self.start + self.minute),
                                         {'type': 'budget.measured', 'occurred_at': at(self.start),
                                          'payload': {'metric': 'train.rest_calls_per_run_max', 'value': STALE}}],
                                 runner={'name': 'box', 'heartbeat': at(self.start), 'results': []})
        text = service_status.metrics(document)
        samples = [line for line in text.splitlines() if not line.startswith('#')]
        self.assertTrue(samples)
        self.assertEqual([line for line in samples if not SAMPLE.match(line)], [])
        self.assertIn('tower_merges_total{admission="v"} 1', samples)
        self.assertIn(f'tower_train_rest_calls {STALE}', samples)
        self.assertIn('tower_queue_depth 1', samples)
        self.assertFalse([line for line in samples if line.startswith('tower_wakes_total')])

    def test_the_cli_exits_1_only_when_a_check_fails(self):
        with mock.patch('sys.stdout'):
            self.assertEqual(service.main(['health'], sources=Fake(self.clock)), 0)
            self.assertEqual(service.main(['health'], sources=Fake(self.clock, fail={'window'})), 1)
            self.assertEqual(service.main(['status', '--json'], sources=Fake(self.clock)), 0)


class GitSources(unittest.TestCase):
    """The lock is read over git from a local bare remote: no REST."""

    def test_the_lock(self):
        remote = Remote(self)
        refs = remote.clone('reader')
        refs.advance(config.get('train.lock_ref'), {'owner': 'train@x', 'expires': 'later'}, None)
        sources = service_status.Sources(root=refs.root, refs=refs, clock=FakeClock())
        self.assertEqual(sources.lock()['owner'], 'train@x')
        refs.advance(config.get('train.lock_ref'), {'owner': 'train@x', 'expires': '', 'died': 'E: why'},
                     refs.read(config.get('train.lock_ref'))[0])
        self.assertEqual((sources.lock()['expires'], sources.lock()['died']), (None, 'E: why'))
        self.assertFalse(hasattr(sources, 'wakes'))  # train/wake is not read (D-290)


class ForgeOpen(unittest.TestCase):
    def test_the_open_prs_are_one_read_of_the_base_drafts_included(self):
        asked = []

        class Port:
            def open_pulls(self, repo, base=None):
                asked.append((repo, base))
                return [{'number': LIVE, 'draft': True, 'head_ref': 'x', 'head_sha': HEAD_A}]

        sources = service_status.Sources(ROOT, port=Port(), clock=FakeClock())
        self.assertEqual(sources.open_prs(), {LIVE})
        self.assertEqual(asked, [(config.get('forge-events.repo'), config.get('train.base_branch'))])


class ControlSource(unittest.TestCase):
    """Sources.control() reads GET /status of service.control_url over HTTP, naming the runner's user agent."""

    def test_the_status_is_read_from_the_control_plane_with_the_user_agent(self):
        seen = []
        body = json.dumps({'queue': [{'pr': LIVE, 'sha': HEAD_A, 'woken_at': None}]}).encode()

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802 - the http.server hook name
                seen.append((self.path, self.headers.get('user-agent')))
                self.send_response(200)
                self.send_header('content-type', 'application/json')
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        server = http.server.HTTPServer(('127.0.0.1', 0), Handler)
        # shutdown() waits for serve_forever's next poll: 10 ms, not the default 0.5 s
        threading.Thread(target=server.serve_forever, kwargs={'poll_interval': 0.01}, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        url = f'http://127.0.0.1:{server.server_address[1]}'
        real = service_status.setting
        with mock.patch.object(service_status, 'setting',
                               lambda name: url if name == 'service.control_url' else real(name)), \
                mock.patch.dict('os.environ', {'NO_PROXY': '127.0.0.1', 'no_proxy': '127.0.0.1'}):
            document = service_status.Sources(ROOT, clock=FakeClock()).control()
        self.assertEqual(document['queue'][0]['pr'], LIVE)
        self.assertEqual(seen, [('/status', config.get('service.user_agent'))])


if __name__ == '__main__':
    unittest.main()
