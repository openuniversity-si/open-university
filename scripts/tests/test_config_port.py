"""DEP9 step 2, hermetic: scripts/config set/get of the service's keys through the port (no git), the webhook consumer's rules
read from the table (defaults compiled), the service's observed config_version on the status route, and scripts/config-latency
(no value left changed). The port is the real http_port.handle over a fake table; the 'service' is the real Config."""
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import urllib.error

ROOT = Path(__file__).resolve().parent.parent.parent
for sub in ('infra/service', 'scripts/tests', 'scripts/lib'):
    sys.path.insert(0, str(ROOT / sub))
import config_cli  # noqa: E402
import config_latency  # noqa: E402
import test_infra_config_data as base  # noqa: E402
from tower_infra import config_data, forge_webhooks, webhook_consumer  # noqa: E402

ENV = {'TOWER_PORT_URL': 'https://port.invalid', 'TOWER_PORT_TOKEN': base.TOKEN}


class Table(base.Table):
    def __init__(self):
        super().__init__()
        self.observed = {}
        self.warm = []
        self.live = []

    def rows(self, sql, params=None):
        if sql.startswith('insert into log.event'):
            self.observed[params['name']] = json.loads(params['payload'])['version']
            return []
        if sql.startswith("select payload::text from log.event where type = 'platform.runner.warm'"):
            assert 'tenant_id is null' in sql  # the runner's warm-ups are the installation's, never a tenant's
            return [(json.dumps(each),) for each in self.warm]
        if "from log.event where type = 'platform.deploy.image_live'" in sql:  # STATUS-EVENTS-AT: with the event's time
            assert 'tenant_id is null' in sql  # IMAGE-PREWARM-A: the swaps are the installation's, never a tenant's
            return [(json.dumps(each),) for each in self.live]
        if sql.startswith('select payload::text from log.event') or " || payload)::text from log.event" in sql:
            return []
        if "v.key = 'deploy.live_code'" in sql:  # SLOW-PATH-NO-ROLLOUT-WAIT: the status's live code datum; none written here
            return []
        if sql.startswith('select distinct on'):
            return [(name, version, '2026-11-09 01:00:00+00') for name, version in self.observed.items()]
        return super().rows(sql, params)


class Answer(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class Wire:
    """urlopen over http_port.handle; a PUT wakes the service (Config.refresh), as the table's NOTIFY does."""

    def __init__(self, table, service=None, wake=True):
        self.table, self.service, self.wake, self.requests = table, service, wake, []

    def __call__(self, request, timeout=None):
        path = request.full_url.replace('https://port.invalid', '')
        method = request.get_method()
        self.requests.append((method, path))
        body = json.loads(request.data) if request.data else {}
        status, said = base.call(self.table, method, path, body, request.headers['Authorization'].split()[-1])
        if status >= 400:
            raise urllib.error.HTTPError(request.full_url, status, 'x', {}, io.BytesIO(json.dumps(said).encode()))
        if method == 'PUT' and self.service is not None and self.wake:
            self.service.refresh()
        return Answer(json.dumps(said).encode())


def run(argv, table, **kwargs):
    out, err = io.StringIO(), io.StringIO()
    wire = kwargs.pop('wire', None) or Wire(table)
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = config_cli.main(argv, environ=kwargs.pop('environ', ENV), opener=wire, **kwargs)
    return code, out.getvalue(), err.getvalue(), wire


class SetThroughThePort(unittest.TestCase):
    def test_a_service_key_is_written_through_the_port_not_git(self):
        table = Table()
        with tempfile.TemporaryDirectory() as root:
            code, out, _, wire = run(['set', 'service.dispatch_s', '2.5', '--actor', 'ana', '--reason', 'slower tick'], table, root=root)
            self.assertEqual(code, 0, out)
            self.assertEqual(table.rows_['service.dispatch_s'][0], 2.5)
            self.assertIn('through the port, no git', out)
            self.assertEqual([m for m, _ in wire.requests], ['GET', 'PUT'])
            self.assertEqual(list(Path(root).iterdir()), [])  # nothing in the registry store
        self.assertEqual(table.events[-1]['reason'], 'slower tick (actor: ana)')

    def test_get_reads_the_live_value(self):
        table = Table()
        self.assertEqual(run(['get', 'service.dispatch_s'], table)[1].strip(), '1.0')  # default
        table.put('service.dispatch_s', 4.0, 3)
        self.assertEqual(run(['get', 'service.dispatch_s'], table)[1].strip(), '4.0')

    def test_default_writes_the_default_value(self):
        table = Table()
        table.put('service.dispatch_s', 4.0, 3)
        self.assertEqual(run(['set', 'service.dispatch_s', '--default', '--actor', 'a', '--reason', 'back'], table)[0], 0)
        self.assertEqual(table.rows_['service.dispatch_s'], (1.0, 4))

    def test_no_token_says_why_and_writes_nothing(self):
        code, _, err, wire = run(['set', 'service.dispatch_s', '2', '--actor', 'a', '--reason', 'r'], Table(), environ={})
        self.assertEqual(code, 1)
        self.assertIn('TOWER_PORT_URL', err)
        self.assertEqual(wire.requests, [])

    def test_the_port_refusal_is_shown_and_the_exit_is_1(self):
        table = Table()
        code, _, err, _ = run(['set', 'service.dispatch_s', '-1', '--actor', 'a', '--reason', 'r'], table)
        self.assertEqual(code, 1)
        self.assertIn('400', err)
        self.assertEqual(table.rows_, {})

    def test_other_keys_keep_the_file_path(self):
        with tempfile.TemporaryDirectory() as root:
            code, _, err, wire = run(['get', 'service.control_timeout_s'], Table(), root=root)
        self.assertEqual(wire.requests, [])  # never asks the port
        self.assertNotIn('port', err)

    def test_every_service_key_is_in_the_one_list(self):
        self.assertIs(config_cli.service_keys(), config_data.SPEC)


class ConsumerRules(unittest.TestCase):
    def test_defaults_when_no_row_or_the_table_is_down(self):
        table = Table()
        want = {'tolerance_s': 300, 'drop_stale': True, 'drop_bad_signature': True}
        self.assertEqual(webhook_consumer.rules(table), want)
        table.broken = True

        class Down:
            def rows(self, *_):
                raise RuntimeError('down')
        self.assertEqual(webhook_consumer.rules(Down()), want)

    def test_rows_override_and_an_invalid_row_does_not(self):
        table = Table()
        table.put('service.webhook_tolerance_s', 900)
        table.put('service.webhook_drop_stale', False)
        table.put('service.webhook_drop_bad_signature', 'yes')  # invalid: default stays
        self.assertEqual(webhook_consumer.rules(table), {'tolerance_s': 900, 'drop_stale': False, 'drop_bad_signature': True})

    def test_the_window_is_the_rule_and_drop_or_retry_follows_it(self):
        calls = []
        real = forge_webhooks.verified

        def fake(headers, raw, keys, now, tolerance=300):
            calls.append(tolerance)
            return 401, 'stale'
        record = {'messageId': 'm', 'body': '{}', 'attributes': {'SentTimestamp': '1000'},
                  'messageAttributes': {'webhook-id': {'stringValue': 'w'}, 'webhook-timestamp': {'stringValue': '1'},
                                        'webhook-signature': {'stringValue': 'v1ed,x'}}}
        forge_webhooks.verified = fake
        try:
            table = Table()
            self.assertEqual(webhook_consumer.consume({'Records': [record]}, table), {'batchItemFailures': []})  # dropped
            table.put('service.webhook_tolerance_s', 900)
            table.put('service.webhook_drop_stale', False)
            self.assertEqual(webhook_consumer.consume({'Records': [record]}, table),
                             {'batchItemFailures': [{'itemIdentifier': 'm'}]})  # retried
        finally:
            forge_webhooks.verified = real
        self.assertEqual(calls, [300, 900])

    def test_the_ports_own_check_keeps_the_compiled_window(self):
        self.assertEqual(forge_webhooks.TOLERANCE_S, 300)
        self.assertEqual(config_data.SPEC['service.webhook_tolerance_s'][1], forge_webhooks.TOLERANCE_S)


class Observed(unittest.TestCase):
    def test_the_service_records_the_version_it_reads_once_and_status_shows_it(self):
        table = Table()
        service = config_data.Config(table.scope)
        table.put('service.dispatch_s', 2.0, 5)
        service.refresh()
        self.assertEqual(table.observed, {'service.dispatch_s': 5})
        table.observed.clear()
        service.refresh()  # no new version, no new observation
        self.assertEqual(table.observed, {})
        status, said = base.call(table, 'GET', '/v1/deploy/status')
        table.observed['service.dispatch_s'] = 5
        status, said = base.call(table, 'GET', '/v1/deploy/status')
        self.assertEqual(status, 200)
        self.assertEqual(said['config_version']['service.dispatch_s']['version'], 5)

    def test_the_engine_s_own_state_is_not_observed_so_a_swap_s_second_carries_no_insert_of_it(self):
        """SWAP-SECOND-QUIET: the pointers of a swap (deploy.live_image_<role>) and deploy.live_code are rows of the same
        table, written by the engine itself; each service process recorded platform.config.observed for them on the
        notification, i.e. on the swap's second (live 12/11 03:26 UTC: those inserts, in both service processes, were
        the longest statements still running when the roles first worked, 1.07 and 1.31 s on a stalled host). What
        reads a pointer says so itself (platform.deploy.image_live, the reload's events): nothing is observed for
        them, and a setting that moves in the same refresh is observed as before."""
        table = Table()
        service = config_data.Config(table.scope)
        for version, name in enumerate(('deploy.live_image_service', 'deploy.live_image_runner', 'deploy.live_code'), 3):
            table.put(name, 'a' * 64, version)
        self.assertEqual(sorted(service.refresh()), ['deploy.live_code', 'deploy.live_image_runner', 'deploy.live_image_service'])
        self.assertEqual(table.observed, {})  # the values are read (the refresh answers them); nothing is written
        table.put('deploy.live_image_service', 'b' * 64, 9)
        table.put('service.dispatch_s', 2.0, 5)
        service.refresh()
        self.assertEqual(table.observed, {'service.dispatch_s': 5})
        self.assertEqual(config_data.OWN, config_data.EMPTY_OK)  # the three the engine writes: the ones that may be ''

    def test_status_shows_the_runner_warm_ups_of_the_installation(self):
        table = Table()
        self.assertEqual(base.call(table, 'GET', '/v1/deploy/status')[1]['runner_warm'], [])
        table.warm = [{'task': 'runner-1', 'seconds': 41.5, 'ok': True}]
        status, said = base.call(table, 'GET', '/v1/deploy/status')
        self.assertEqual((status, said['runner_warm']), (200, [{'task': 'runner-1', 'seconds': 41.5, 'ok': True}]))

    def test_status_shows_the_image_swaps_of_the_installation(self):
        # IMAGE-PREWARM-A: platform.deploy.image_live is written with tenant_id null by the standby that turned live
        table = Table()
        self.assertEqual(base.call(table, 'GET', '/v1/deploy/status')[1]['image_live'], [])
        table.live = [{'role': 'runner', 'digest': 'sha256:new', 'version': 1, 'task': 'standby-1', 'swap_s': float('0.04')}]
        answered = base.call(table, 'GET', '/v1/deploy/status')
        self.assertEqual(answered[1]['image_live'], table.live)

    def test_status_no_longer_shows_spot_standbys(self):
        # SPOT-STANDBY-GONE (D-316): platform.deploy.standby was the prewarm's; the status reads it no more
        self.assertNotIn('standby', base.call(Table(), 'GET', '/v1/deploy/status')[1])


class Latency(unittest.TestCase):
    def clocked(self, step):
        now = [0.0]

        def clock():
            now[0] += step
            return now[0]
        return clock, lambda s: now.__setitem__(0, now[0] + s)

    def test_measures_and_leaves_the_value_unchanged(self):
        table = Table()
        table.put('medir.webhook_ack_limit_s', 2.0, 7)
        service = config_data.Config(table.scope)
        service.refresh()
        clock, sleep = self.clocked(0.01)
        found = config_latency.measure('medir.webhook_ack_limit_s', ENV, Wire(table, service), clock=clock, sleep=sleep,
                                       stamp=lambda: 1)
        self.assertEqual(table.rows_['medir.webhook_ack_limit_s'][0], 2.0)  # the same value
        self.assertEqual(found['version'], 8)
        self.assertGreater(found['observed_ms'], 0)
        self.assertIn('config-latency probe', table.events[-1]['reason'])

    def test_a_service_that_never_reads_it_times_out_with_a_message(self):
        table = Table()
        service = config_data.Config(table.scope)
        clock, sleep = self.clocked(1.0)
        with self.assertRaises(config_cli.PortError) as caught:
            config_latency.measure('medir.webhook_ack_limit_s', ENV, Wire(table, service, wake=False), timeout_s=5,
                                   clock=clock, sleep=sleep)
        self.assertIn('not observed', str(caught.exception))

    def test_the_command_prints_milliseconds_and_refuses_a_foreign_key(self):
        table = Table()
        service = config_data.Config(table.scope)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = config_latency.main(['--look-ms', '1'], environ=ENV, opener=Wire(table, service))
        self.assertEqual(code, 0)
        self.assertIn(' ms after the PUT started', out.getvalue())
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(config_latency.main(['--key', 'service.control_url'], environ=ENV), 1)
        self.assertNotIn(base.TOKEN, out.getvalue() + err.getvalue())

    def test_the_wrapper_runs(self):
        done = subprocess.run([str(ROOT / 'scripts' / 'config-latency'), '--help'], capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)


if __name__ == '__main__':
    unittest.main()
