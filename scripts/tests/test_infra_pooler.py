"""TASK-POOLER (tower_infra.pooler; docs/operations/aws.md 22.9): the task keeps its connections to the database, and a
process that takes the place of one that was lost has them with no login.

1. On a throwaway database of the toolchain's PostgreSQL, migrated by the service's runner, with the real client
   (psql: libpq) through the real pool: a client has a session of its own (what it asked in its startup, a LISTEN, a
   transaction), and when it leaves, or is killed in the middle of a transaction, a COPY or a statement, nothing of
   it is left and the next client has the same backend at once, with no login. The provoked loss of each role: the
   runner's real TAKE and the service's real dispatch, by a process that connects after the one before it was killed.
2. The login the pool makes is RDS's: TLS asked and given, the token asked in clear inside it. A front that does
   exactly that stands before the real server (the toolchain's trusts every local login).
3. The parts: the startup's options, the frames, the task role's credentials, and the client's side
   (tower_infra.database): through the pool when it listens, by a login of its own when it does not.
Local PostgreSQL only, no network.
"""
import json
import os
from pathlib import Path
import select
import shutil
import signal
import socket
import ssl
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock
from urllib.parse import urlencode, urlsplit

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'tests'))
from infra_db import psql  # noqa: E402
import test_db  # noqa: E402
from test_infra_mechanisms import World  # noqa: E402
from tower_infra import database, mechanisms, pooler, runner  # noqa: E402

END = '__the_statement_ended__'


def where_of(url, sslmode='disable'):
    found = urlsplit(url)
    return {'host': found.hostname, 'port': found.port, 'name': found.path.lstrip('/'), 'region': 'us-east-1',
            'sslmode': sslmode, 'role': 'service'}, found.username


class Pooled:
    """A pool in this process, on a directory of its own, before the database of `url`."""

    def __init__(self, case, url, where=None, password=lambda: '', **how):
        base, self.user = where_of(url)
        self.where = where or base
        self.dir = tempfile.mkdtemp(prefix='tp-')
        self.pool = pooler.Pool(self.where, self.user, password, 'tower-service:pooled', path=self.dir, **how)
        self.listener = pooler.listen(self.dir, self.where['port'])
        self.stop = threading.Event()
        self.thread = threading.Thread(target=pooler.serve, args=(self.pool, self.listener, self.stop, 0.05), daemon=True)
        self.thread.start()
        self.url = f"postgresql:///{base['name']}?" + urlencode({'host': self.dir, 'port': self.where['port'], 'user': self.user})
        case.addCleanup(self.end)

    def end(self):
        self.stop.set()
        self.listener.close()
        self.thread.join(5)
        shutil.rmtree(self.dir, ignore_errors=True)

    def said(self):
        self.pool.say()
        return json.loads((Path(self.dir) / pooler.STATE).read_text())


class Session:
    """One psql process kept open on one connection: rows(sql) from a call to the next; kill() ends it with no word."""

    def __init__(self, url, **environ):
        self.process = subprocess.Popen(
            [str(test_db.psql_binary()), url, '-X', '-q', '-A', '-t', '-F', psql.SEPARATOR],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env={**os.environ, **environ})

    def send(self, sql):
        self.process.stdin.write(f'{sql.rstrip().rstrip(";")};\n\\echo {END}\n')
        self.process.stdin.flush()

    def rows(self, sql):
        self.send(sql)
        lines = []
        while True:
            line = self.process.stdout.readline()
            if not line:
                raise AssertionError(self.process.stderr.read())
            if line.rstrip('\n') == END:
                return [tuple(line.split(psql.SEPARATOR)) for line in lines if line]
            lines.append(line.rstrip('\n'))

    def kill(self):
        self.process.kill()
        self.process.wait()
        for pipe in (self.process.stdin, self.process.stdout, self.process.stderr):
            pipe.close()

    def close(self):
        if self.process.poll() is None:
            self.process.stdin.close()
            self.process.wait(timeout=30)
            for pipe in (self.process.stdout, self.process.stderr):
                pipe.close()


def until(check, seconds=10.0):
    limit = time.monotonic() + seconds
    while time.monotonic() < limit:
        found = check()
        if found:
            return found
        time.sleep(0.01)
    raise AssertionError('not in time')


class ThePoolOnPostgres(World):
    def setUp(self):
        super().setUp()
        self.pooled = Pooled(self, self.db.url)
        self.through = psql.Psql(self.pooled.url)  # a process, a connection and a session of the pool each statement

    def session(self, **environ):
        found = Session(self.pooled.url, **environ)
        self.addCleanup(found.close)
        return found

    def backends(self):
        """The connections the pool holds in the database: (pid, application_name, state)."""
        return self.db.rows("select pid::text, application_name, state from pg_stat_activity where datname = "
                            "current_database() and pid <> pg_backend_pid() and backend_type = 'client backend' order by pid")

    def test_a_client_has_a_session_as_it_asked_and_the_next_has_the_same_connection_clean(self):
        first = self.session(PGAPPNAME='tower-runner:slot', PGOPTIONS='-c statement_timeout=4321 -c work_mem=3MB')
        pid, name, timeout, memory = first.rows(
            "select pg_backend_pid(), current_setting('application_name'), current_setting('statement_timeout'), "
            "current_setting('work_mem')")[0]
        self.assertEqual((name, timeout, memory), ('tower-runner:slot', '4321ms', '3MB'))  # its startup's, as a server gives
        self.assertEqual(self.backends(), [(pid, 'tower-runner:slot', 'idle')])  # the database says who holds it and what for
        first.rows('prepare one as select 1')
        first.rows("select set_config('tower.mine', 'yes', false)")
        first.close()  # it left with a word (Terminate): the connection stays
        until(lambda: self.pooled.said()['idle'] == 1)
        self.assertEqual(self.backends(), [(pid, 'tower-service:pooled', 'idle')])  # reset: the pool's own name again
        again = self.session()
        self.assertEqual(again.rows("select pg_backend_pid(), current_setting('statement_timeout'), current_setting('work_mem'), "
                                    "current_setting('tower.mine', true), (select count(*) from pg_prepared_statements)"),
                         [(pid, '0', self.db.rows("select current_setting('work_mem')")[0][0], '', '0')])
        said = self.pooled.said()
        self.assertEqual((said['logins'], said['reused'], said['connections']), (1, 1, 1))  # one login for both clients
        both = self.session()  # while the other stays: a connection of its own
        self.assertNotEqual(both.rows('select pg_backend_pid()')[0][0], pid)
        self.assertEqual(self.pooled.said()['logins'], 2)

    def test_a_client_killed_in_the_middle_leaves_nothing_and_its_connection_serves_the_next_at_once(self):
        lost = self.session()
        pid = lost.rows('select pg_backend_pid()')[0][0]
        lost.rows('listen tower_work')
        lost.rows('select pg_advisory_lock(4242)')
        lost.rows("set work_mem = '2MB'")
        lost.rows('begin')
        lost.rows("insert into work.tenant (name) values ('left-in-the-middle')")
        lost.rows('create temp table mine (n int)')
        lost.kill()  # no word: a process lost as the swap promoted it
        began = time.monotonic()
        found = self.through.rows(
            "select pg_backend_pid(), (select count(*) from work.tenant where name = 'left-in-the-middle'), "
            "(select count(*) from pg_listening_channels()), current_setting('work_mem') = %(usual)s, "
            "to_regclass('pg_temp.mine') is null, (select count(*) from pg_locks where locktype = 'advisory')",
            {'usual': self.db.rows("select current_setting('work_mem')")[0][0]})
        took = time.monotonic() - began
        # the same backend, with nothing of the one that died: no row, no LISTEN, no setting, no table, no lock
        self.assertEqual(found, [(pid, '0', '0', 't', 't', '0')])
        self.assertLess(took, 2.0)  # a psql process and one statement; the reset was three round trips behind it
        said = self.pooled.said()
        self.assertEqual((said['logins'], said['reused'], said['closed']), (1, 1, 0))  # and no login: the task's connection

    def test_the_runner_s_first_take_after_its_process_is_lost_has_no_login(self):
        """The provoked loss, the runner: its successor stood by with its slot's connection, warmed by the real TAKE
        rolled back, and was killed as the swap promoted it. The process that takes its place connects and takes the
        run that waits, on the backend the lost one warmed, with no login."""
        handed = self.job('handed', selector={'adapter': 'container'}, queue='ranked', rank='9')
        tenants = dict(self.db.rows('select name, id::text from work.tenant'))
        self.assertEqual(mechanisms.dispatch_one(self.db, tenants['torre'], 'ranked', '5 minutes', '50')['job'], handed)
        take = psql.PLACEHOLDER.sub(lambda found: psql.literal({'adapter': 'container', 'runner': 'warm-up'}[found.group(1)]),
                                    runner.TAKE)
        successor = self.session(PGAPPNAME='tower-runner:slot')
        pid = successor.rows('select pg_backend_pid()')[0][0]
        successor.rows('begin')
        self.assertEqual(len(successor.rows(take)), 1)  # its warm-up: the real TAKE, to be rolled back
        successor.kill()
        began = time.monotonic()
        reserve = self.session(PGAPPNAME='tower-runner:slot')
        taken = reserve.rows(take.replace('warm-up', 'the-reserve') + '; select pg_backend_pid()')
        took = time.monotonic() - began
        self.assertEqual((taken[0][1], taken[0][-1], taken[1]), (handed, 't', (pid,)))  # the run, taken, on the same backend
        self.assertEqual(self.db.rows("select r.state from work.run r where r.job_id = %(job)s::uuid", {'job': handed}), [('running',)])
        said = self.pooled.said()
        self.assertEqual((said['logins'], said['reused']), (1, 1))  # the lost process's login is the only one there was
        self.assertLess(took, 1.0)  # connect and take, a psql's start included

    def test_the_service_s_first_dispatch_after_its_process_is_lost_has_no_login(self):
        """The provoked loss, the service: its successor's loop connection ran the first pass's statements and the
        process was killed. The one that takes its place dispatches the job that waits through the same backend."""
        waiting = self.job('waiting', selector={'adapter': 'container'}, queue='ranked', rank='9')
        tenants = dict(self.db.rows('select name, id::text from work.tenant'))
        successor = self.session(PGAPPNAME='tower-service:loop')
        pid = successor.rows('select pg_backend_pid()')[0][0]
        for sql in (mechanisms.REAP, mechanisms.QUEUES):  # what its standby pass warms (SWAP-TAIL-CUT), rolled back
            successor.rows('begin')
            successor.rows(sql)
            successor.rows('rollback')
        successor.rows('begin')  # and it dies inside a transaction
        successor.kill()
        began = time.monotonic()
        claimed = mechanisms.dispatch_one(self.through, tenants['torre'], 'ranked', '5 minutes', '50')
        took = time.monotonic() - began
        self.assertEqual(claimed['job'], waiting)
        self.assertEqual(self.through.rows('select pg_backend_pid()'), [(pid,)])
        said = self.pooled.said()
        self.assertEqual((said['logins'], said['connections']), (1, 1))  # every statement since: sessions of one connection
        self.assertLess(took, 2.0)

    def test_a_statement_the_client_left_running_is_cancelled_so_the_connection_is_not_behind_it(self):
        lost = self.session()
        pid = lost.rows('select pg_backend_pid()')[0][0]
        lost.send('select pg_sleep(60)')
        until(lambda: (pid, 'psql', 'active') in self.backends())
        lost.kill()
        began = time.monotonic()
        self.assertEqual(self.through.rows('select pg_backend_pid()'), [(pid,)])  # not after 60 s, and not a new login
        self.assertLess(time.monotonic() - began, 4.0)
        said = self.pooled.said()
        self.assertEqual((said['logins'], said['cancelled'], said['closed']), (1, 1, 0))

    def test_the_lost_process_s_connection_still_being_reset_is_waited_for_not_replaced_by_a_login(self):
        """POOL-KEEPS, the case of the drill of 12/11 22:21 UTC: the successor is lost with a statement in flight; its
        connection's reset waits for the cancel, which goes on a connection of its own (a TLS handshake with RDS: 0.3 to
        0.9 s, 1.2 s here); the process that takes its place asks for a connection meanwhile. It logged in (a second of
        TLS and IAM) after waiting 1 s; it waits for the reset and has the lost one's connection, with no login."""
        real = self.pooled.pool.cancel

        def slow(pid, key):
            time.sleep(1.2)
            real(pid, key)
        holder = self.session()
        holder.rows('begin')
        holder.rows('select pg_advisory_lock(77)')
        with mock.patch.object(self.pooled.pool, 'cancel', slow):
            lost = self.session()
            pid = lost.rows('select pg_backend_pid()')[0][0]
            lost.send('select pg_advisory_lock(77)')  # blocked behind the holder: in flight when the process dies
            until(lambda: any(each[0] == pid and each[2] == 'active' for each in self.backends()))
            lost.kill()
            time.sleep(0.05)
            self.assertEqual(self.through.rows('select pg_backend_pid()'), [(pid,)])  # the same backend: no login
        said = self.pooled.said()
        self.assertEqual((said['logins'], said['login_while_resetting'], said['dirty'], said['cancelled'], said['waited']),
                         (2, 0, 0, 1, 1))  # two logins: the holder's and the lost one's, before
        self.assertGreater(said['waited_ms_max'], 1000.0)
        self.assertGreater(said['reset_ms_max'], 1000.0)

    def test_no_cancel_is_sent_for_a_statement_that_ended_before_it_could_go(self):
        """POOL-KEEPS: a cancel sent for a statement that ended meanwhile lands on the reset itself."""
        started = []
        real = pooler.threading.Thread

        def later(*args, target=None, name=None, daemon=None, **how):
            if name != 'pool-cancel':
                return real(*args, target=target, name=name, daemon=daemon, **how)
            def slower():
                time.sleep(0.5)  # the cancel's own login would be this late
                started.append(1)
                target()
            return real(target=slower, name=name, daemon=daemon)
        sent = []
        with mock.patch.object(pooler.threading, 'Thread', later), \
                mock.patch.object(self.pooled.pool, 'cancel', lambda pid, key: sent.append(pid)):
            lost = self.session()
            pid = lost.rows('select pg_backend_pid()')[0][0]
            lost.send('select pg_sleep(0.1)')  # a short poll, in flight when the process dies
            until(lambda: any(each[0] == pid and each[2] == 'active' for each in self.backends()))
            lost.kill()
            until(lambda: started)
        self.assertEqual(sent, [])  # it had ended: nothing sent
        self.assertEqual(self.through.rows('select pg_backend_pid()'), [(pid,)])
        said = self.pooled.said()
        self.assertEqual((said['cancel_skipped'], said['dirty'], said['logins']), (1, 0, 1))

    def test_a_reset_that_does_not_end_in_its_time_closes_the_connection_and_the_next_client_logs_in(self):
        slow = Pooled(self, self.db.url, reset_s=0.3)
        with mock.patch.object(slow.pool, 'cancel', lambda pid, key: None):  # the cancel is lost
            lost = Session(slow.url)
            self.addCleanup(lost.close)
            pid = lost.rows('select pg_backend_pid()')[0][0]
            lost.send('select pg_sleep(60)')
            until(lambda: any(each[0] == pid and each[2] == 'active' for each in self.backends()))
            lost.kill()
            until(lambda: slow.said()['closed'] == 1)
        self.assertNotEqual(psql.Psql(slow.url).rows('select pg_backend_pid()'), [(pid,)])
        self.assertEqual((slow.said()['logins'], slow.said()['connections']), (2, 1))  # never more than its clients need
        self.db.rows('select pg_terminate_backend(%(pid)s::int)', {'pid': pid})

    def test_a_connection_nobody_took_for_its_idle_time_is_closed(self):
        now = [1000.0]
        timed = Pooled(self, self.db.url, idle_s=120.0, clock=lambda: now[0])
        psql.Psql(timed.url).rows('select 1')
        until(lambda: timed.said()['idle'] == 1)
        self.assertEqual(len([each for each in self.backends() if each[1] == 'tower-service:pooled']), 1)
        now[0] += 119.0
        self.assertEqual(timed.pool.sweep(), 0)  # the next process of a swap finds it
        now[0] += 2.0
        self.assertEqual(timed.pool.sweep(), 1)  # nobody came: the database gets its connection back
        until(lambda: not [each for each in self.backends() if each[1] == 'tower-service:pooled'])
        self.assertEqual((timed.said()['connections'], timed.said()['idle']), (0, 0))

    def test_a_refusal_is_said_in_the_server_s_words_and_the_connection_goes_back_clean(self):
        refused = subprocess.run([str(test_db.psql_binary()), self.pooled.url, '-X', '-Atc', 'select 1'], capture_output=True,
                                 text=True, env={**os.environ, 'PGOPTIONS': '-c no_such_setting=1'})
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn('unrecognized configuration parameter "no_such_setting"', refused.stderr)  # the server's own words
        self.assertEqual(self.through.rows('select 1'), [('1',)])
        self.assertEqual((self.pooled.said()['logins'], self.pooled.said()['closed']), (1, 0))
        other = self.pooled.url.replace('user=' + self.pooled.user, 'user=somebody_else')
        refused = subprocess.run([str(test_db.psql_binary()), other, '-X', '-Atc', 'select 1'], capture_output=True, text=True)
        self.assertIn("this pool is", refused.stderr)  # one user, one database: the role's own
        self.assertEqual(self.pooled.said()['logins'], 1)

    def test_a_notification_and_a_cancel_of_the_client_pass_through(self):
        listener = self.session()
        listener.rows('listen tower_config')
        self.through.rows("select pg_notify('tower_config', 'the pointer moved')")
        said = listener.rows('select 1')  # psql says a notification after the statement that found it
        self.assertTrue(any('the pointer moved' in cell for row in said for cell in row), said)
        pid = listener.rows('select pg_backend_pid()')[0][0]
        listener.send('select pg_sleep(60)')
        until(lambda: any(each[0] == pid and each[2] == 'active' for each in self.backends()))
        listener.process.send_signal(signal.SIGINT)  # psql asks the server it knows (the pool) to cancel
        # psql says 'Cancel request sent' first, then the server's refusal of the statement
        until(lambda: 'canceling statement' in listener.process.stderr.readline())
        self.assertEqual(self.pooled.said()['cancelled'], 1)

    def test_what_a_task_s_process_is_told_of_its_connection(self):
        asked = []
        real = pooler.message

        def spy(kind, body=b''):
            asked.append((kind, body))
            return real(kind, body)
        with mock.patch.object(pooler, 'message', spy):
            self.through.rows('select 1')
            self.through.rows('select 1')
        told = [body.split(b'\0')[1].decode() for kind, body in asked if kind == b'S' and body.startswith(b'tower_pool\0')]
        self.assertEqual(len(told), 2)
        self.assertTrue(told[0].startswith('login tcp=') and ' auth=' in told[0] and ' start=' in told[0], told)  # its parts, in ms
        self.assertEqual(told[1], 'reused')


class Front(threading.Thread):
    """What RDS is to a login, before the real server: TLS asked and given, the password asked in clear inside it and
    checked (an IAM user's token), then the session relayed to the server behind (which trusts the local login)."""

    def __init__(self, behind, folder, token):
        super().__init__(daemon=True)
        made = subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1', '-subj', '/CN=localhost',
                               '-keyout', f'{folder}/key.pem', '-out', f'{folder}/cert.pem'], capture_output=True, check=False)
        self.ok = made.returncode == 0
        self.behind, self.token, self.seen = behind, token, []
        self.listener = socket.create_server(('127.0.0.1', 0))
        self.port = self.listener.getsockname()[1]
        if self.ok:
            self.context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            self.context.load_cert_chain(f'{folder}/cert.pem', f'{folder}/key.pem')

    def run(self):
        while True:
            try:
                client, _ = self.listener.accept()
            except OSError:
                return
            threading.Thread(target=self.one, args=(client,), daemon=True).start()

    def one(self, client):
        try:
            size, code = struct.unpack('!II', pooler.exactly(client, 8))
            if code != pooler.SSL_REQUEST:
                self.seen.append('no TLS asked')
                return
            client.sendall(b'S')
            inside = self.context.wrap_socket(client, server_side=True)
            size = int.from_bytes(pooler.exactly(inside, 4), 'big')
            startup = pooler.exactly(inside, size - 4)
            inside.sendall(pooler.message(b'R', struct.pack('!I', 3)))  # AuthenticationCleartextPassword
            kind, body = pooler.one(inside)
            self.seen.append((inside.version(), kind, body.rstrip(b'\0').decode()))
            if body.rstrip(b'\0').decode() != self.token:
                inside.sendall(pooler.failure('PAM authentication failed for user "tower_service"', '28P01'))
                return
            behind = socket.create_connection(self.behind)
            try:
                behind.sendall(struct.pack('!I', size) + startup)
                while True:
                    ready = [inside] if inside.pending() else select.select([inside, behind], [], [])[0]
                    for each in ready:
                        data = each.recv(65536)
                        if not data:
                            return
                        (behind if each is inside else inside).sendall(data)
            finally:
                behind.close()
                inside.close()
        except (OSError, pooler.Gone, ssl.SSLError):
            pass
        finally:
            client.close()


class TheLoginIsRdsS(World):
    def front(self, token):
        folder = tempfile.mkdtemp(prefix='tp-front-')
        self.addCleanup(shutil.rmtree, folder, True)
        where, _ = where_of(self.db.url)
        front = Front((where['host'], where['port']), folder, token)
        if not front.ok:
            self.skipTest('no openssl to make the front its certificate')
        self.addCleanup(front.listener.close)
        front.start()
        return front, {**where, 'host': '127.0.0.1', 'port': front.port, 'sslmode': 'require'}

    def test_tls_is_asked_and_the_token_goes_in_clear_inside_it(self):
        front, where = self.front('the-token-of-now')
        tokens = iter(['the-token-of-now', 'the-token-of-later'])
        pooled = Pooled(self, self.db.url, where=where, password=lambda: next(tokens))
        self.assertEqual(psql.Psql(pooled.url).rows("select current_setting('application_name')"), [('psql',)])
        self.assertEqual(psql.Psql(pooled.url).rows('select 41 + 1'), [('42',)])
        self.assertEqual(len(front.seen), 1)  # one login for both, and a token asked only when a login is made
        version, kind, token = front.seen[0]
        self.assertEqual((kind, token), (b'p', 'the-token-of-now'))
        self.assertTrue(version.startswith('TLSv1'), version)
        said = pooled.said()
        self.assertEqual(sorted(said['login_ms']), ['auth', 'start', 'tcp', 'tls'])  # where a login's time goes, in its parts
        self.assertEqual((said['logins'], said['reused']), (1, 1))

    def test_a_token_the_database_refuses_is_said_to_the_client_in_its_words(self):
        front, where = self.front('the-token-of-now')
        pooled = Pooled(self, self.db.url, where=where, password=lambda: 'a-token-that-expired')
        refused = subprocess.run([str(test_db.psql_binary()), pooled.url, '-X', '-Atc', 'select 1'], capture_output=True, text=True)
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn('PAM authentication failed', refused.stderr)  # the client then logs in by itself and finds the same
        self.assertEqual((pooled.said()['connections'], pooled.said()['refused']), (0, 1))

    def test_a_database_that_refuses_tls_is_not_logged_in_to(self):
        where, user = where_of(self.db.url, sslmode='require')  # the toolchain's server has no TLS
        with self.assertRaisesRegex(pooler.PoolError, 'refused TLS'):
            pooler.login(where, user, lambda: 'never sent', 'tower-service:pooled')


class TheParts(unittest.TestCase):
    def test_the_startup_s_options_are_the_settings_a_server_would_apply(self):
        self.assertEqual(pooler.options('-c statement_timeout=5000'), [('statement_timeout', '5000')])
        self.assertEqual(pooler.options('-cwork_mem=3MB --lock-timeout=2s -c search_path=a,\\ b'),
                         [('work_mem', '3MB'), ('lock_timeout', '2s'), ('search_path', 'a, b')])
        self.assertEqual(pooler.options(None), [])
        with self.assertRaises(pooler.PoolError):
            pooler.options('-d 5')
        self.assertEqual(pooler.settings({'user': 'u', 'database': 'd', 'application_name': "it's", 'options': '-c a.b=1'}),
                         "SET application_name = 'it''s'; SET a.b = '1'")
        self.assertIsNone(pooler.settings({'user': 'u', 'database': 'd'}))
        with self.assertRaises(pooler.PoolError):
            pooler.settings({'user': 'u', 'database': 'd', 'x; drop table y': '1'})

    def test_a_stream_is_cut_into_whole_messages(self):
        frames = pooler.Frames()
        stream = pooler.message(b'Q', b'select 1\0') + pooler.message(b'X') + pooler.message(b'D', b'x' * 70000)
        found = []
        for at in range(0, len(stream), 4096):
            found += frames.feed(stream[at:at + 4096])
        self.assertEqual([(each[:1], len(each)) for each in found], [(b'Q', 14), (b'X', 5), (b'D', 70005)])
        self.assertEqual(frames.kept, b'')
        with self.assertRaises(pooler.PoolError):
            pooler.Frames().feed(b'Q\0\0\0\1')

    def test_the_task_role_s_credentials_are_asked_of_the_container_s_endpoint_and_kept_until_they_expire(self):
        asked, kept, now = [], {}, [1000.0]
        said = json.dumps({'AccessKeyId': 'AKIA', 'SecretAccessKey': 'secret', 'Token': 'session',
                           'Expiration': '1970-01-01T01:00:00Z'}).encode()
        environ = {'AWS_CONTAINER_CREDENTIALS_RELATIVE_URI': '/v2/credentials/abc'}

        def fetch(url):
            asked.append(url)
            return said
        found = pooler.credentials(environ, fetch, kept, lambda: now[0])
        self.assertEqual(found, {'AWS_ACCESS_KEY_ID': 'AKIA', 'AWS_SECRET_ACCESS_KEY': 'secret', 'AWS_SESSION_TOKEN': 'session'})
        self.assertEqual(asked, ['http://169.254.170.2/v2/credentials/abc'])
        now[0] = 3299.0  # an hour's credentials, five minutes before their end: still the kept ones
        pooler.credentials(environ, fetch, kept, lambda: now[0])
        self.assertEqual(len(asked), 1)
        now[0] = 3301.0
        pooler.credentials(environ, fetch, kept, lambda: now[0])
        self.assertEqual(len(asked), 2)
        own = {'AWS_ACCESS_KEY_ID': 'k', 'AWS_SECRET_ACCESS_KEY': 's'}
        self.assertEqual(pooler.credentials(own, lambda url: self.fail('the environment has them')), own)
        self.assertEqual(pooler.credentials({}, lambda url: self.fail('nowhere to ask')), {})  # boto3 then signs
        # and the token is the one the port's Lambda signs with the same names (database.auth_token: no boto3)
        where = {'host': 'db.example', 'port': 5432, 'region': 'us-east-1'}
        token = database.auth_token(where, 'tower_runner', found)
        self.assertTrue(token.startswith('db.example:5432/?Action=connect&DBUser=tower_runner&'), token)
        self.assertIn('X-Amz-Security-Token=session', token)

    def test_a_process_connects_through_its_pool_when_it_listens_and_by_itself_when_it_does_not(self):
        folder = tempfile.mkdtemp(prefix='tp-')
        self.addCleanup(shutil.rmtree, folder, True)
        where = {'host': 'db.example', 'port': 5432, 'name': 'tower', 'region': 'us-east-1', 'sslmode': 'require', 'role': 'runner'}
        self.assertIsNone(database.pooled(where, {}))
        self.assertIsNone(database.pooled(where, {'TOWER_DB_POOL': folder}))  # named, not listening yet
        (Path(folder) / '.s.PGSQL.5432').touch()
        self.assertEqual(database.pooled(where, {'TOWER_DB_POOL': folder}), folder)
        asked = []

        class Found:
            def __init__(self, said):
                self.info = mock.Mock(parameter_status=lambda name: said if name == 'tower_pool' else None)

        def connect(**how):
            asked.append(how)
            if how['host'] == folder and len(asked) == 3:
                raise OSError('connection refused')
            return Found('reused' if len(asked) == 1 else 'login tcp=1.5 tls=40.0 auth=700.5 start=2.0' if how['host'] == folder else None)
        psycopg = mock.Mock(connect=connect)
        with mock.patch.dict(sys.modules, {'psycopg': psycopg}), mock.patch.dict(os.environ, {'TOWER_DB_POOL': folder}), \
                mock.patch.object(database, 'CAME', {'reused': 0, 'login': 0, 'direct': 0, 'login_ms': {}, 'slowest_ms': {}, 'login_by': {}}), \
                mock.patch.object(database, 'auth_token', lambda where, user: 'a-token'), \
                mock.patch.object(database.LOG, 'warning') as warned:
            database.iam_connection(where, 'tower_runner', purpose='slot', autocommit=True)
            self.assertEqual(asked[0], {'host': folder, 'port': 5432, 'dbname': 'tower', 'user': 'tower_runner', 'sslmode': 'disable',
                                        'application_name': 'tower-runner:slot', 'autocommit': True})  # no TLS, no token
            database.iam_connection(where, 'tower_runner', purpose='gate')
            database.iam_connection(where, 'tower_runner', purpose='quick', connect_timeout=5)  # the pool refuses: by itself
            self.assertEqual(asked[3], {'host': 'db.example', 'port': 5432, 'dbname': 'tower', 'user': 'tower_runner',
                                        'password': 'a-token', 'sslmode': 'require', 'application_name': 'tower-runner:quick',
                                        'connect_timeout': 5})
            self.assertEqual(warned.call_count, 1)
            said = database.pool_said()
            said['pool'].pop('login_by', None)
            self.assertEqual(said, {'pool': {'reused': 1, 'login': 1, 'direct': 1, 'login_ms': {
                'tcp': 1.5, 'tls': 40.0, 'auth': 700.5, 'start': 2.0}, 'slowest_ms': {'tcp': 1.5, 'tls': 40.0, 'auth': 700.5, 'start': 2.0}}})
        self.assertEqual(database.pool_said({}), {})  # a process with no pool says nothing of one

    def test_a_process_says_which_connections_needed_a_login_and_what_its_task_s_pool_did(self):
        folder = tempfile.mkdtemp(prefix='tp-')
        self.addCleanup(shutil.rmtree, folder, True)
        (Path(folder) / 'pool.json').write_text(json.dumps({'connections': 8, 'idle': 1, 'waited': 2, 'waited_ms_max': 840.0,
                                                           'login_while_resetting': 0, 'dirty': 0, 'reset_ms_max': 900.5,
                                                           'logins': 9, 'at': 1.0}))

        class Found:
            def __init__(self, said, name):
                self.info = mock.Mock(parameter_status=lambda key: said if key == 'tower_pool' else name)
        with mock.patch.object(database, 'CAME', {'reused': 0, 'login': 0, 'direct': 0, 'login_ms': {}, 'slowest_ms': {}, 'login_by': {}}):
            database.came(Found('login tcp=1 tls=200 auth=700 start=0', 'tower-service:listen'))
            database.came(Found('login tcp=1 tls=200 auth=700 start=0', 'tower-service:pool'))
            database.came(Found('reused', 'tower-service:loop'))
            said = database.pool_said({'TOWER_DB_POOL': folder})
        self.assertEqual(said['pool']['login_by'], {'tower-service:listen': 1, 'tower-service:pool': 1})
        self.assertEqual(said['pool_task'], {'connections': 8, 'idle': 1, 'waited': 2, 'waited_ms_max': 840.0, 'reset_ms_max': 900.5,
                                             'logins': 9})

    def test_a_late_service_listens_after_its_first_work(self):
        from tower_infra import wake
        made = []
        hub = wake.Hub(lambda: made.append(1) or (_ for _ in ()).throw(OSError('no database here')), ('tower_work',),
                       sleep=lambda seconds: True, later=True)
        time.sleep(0.1)
        self.assertEqual((made, hub.thread.is_alive()), ([], False))  # no login before its first work
        self.assertIs(hub.begin(), hub)
        until(lambda: made)
        hub.begin()  # once
        hub.closed.set()
        source = (ROOT / 'infra/service/tower_infra/__main__.py').read_text(encoding='utf-8')
        self.assertIn("(wake.WORK, wake.CONFIG, wake.DEPLOY, wake.TRAIN), later=late_listen)", source)
        self.assertLess(source.index('started = workflows.tick(lease, **timed)'), source.index('            hub.begin()'))

    def test_the_engine_s_connections_come_through_the_pool_too(self):
        folder = tempfile.mkdtemp(prefix='tp-')
        self.addCleanup(shutil.rmtree, folder, True)
        (Path(folder) / '.s.PGSQL.5432').touch()
        hooks = {}
        sqlalchemy = mock.Mock()
        sqlalchemy.event.listens_for = lambda engine, name: (lambda function: hooks.update({name: function}) or function)
        where = {'host': 'db.example', 'port': 5432, 'name': 'tower', 'region': 'us-east-1', 'sslmode': 'require', 'role': 'service'}
        with mock.patch.dict(sys.modules, {'sqlalchemy': sqlalchemy}):
            database.iam_engine(where, 'tower_service', token=lambda: 'a-token')
        dialect = mock.Mock()
        dialect.connect.return_value = 'a connection of the pool'
        with mock.patch.dict(os.environ, {'TOWER_DB_POOL': folder}):
            cparams = {'host': 'db.example', 'port': 5432, 'sslmode': 'require', 'application_name': 'tower-service:pool'}
            self.assertEqual(hooks['do_connect'](dialect, None, [], cparams), 'a connection of the pool')
            dialect.connect.assert_called_once_with(host=folder, port=5432, sslmode='disable', application_name='tower-service:pool')
            dialect.connect.side_effect = OSError('connection refused')
            with mock.patch.object(database.LOG, 'warning'):
                self.assertIsNone(hooks['do_connect'](dialect, None, [], cparams))  # SQLAlchemy then connects: as it was
            self.assertEqual((cparams['password'], cparams['host'], cparams['sslmode']), ('a-token', 'db.example', 'require'))
        os.environ.pop('TOWER_DB_POOL', None)
        cparams = {'host': 'db.example'}
        self.assertIsNone(hooks['do_connect'](mock.Mock(connect=lambda *a, **k: self.fail('no pool')), None, [], cparams))
        self.assertEqual(cparams['password'], 'a-token')

    def test_the_pool_is_a_process_of_the_image_named_to_every_child(self):
        from tower_infra import supervisor
        self.assertEqual(supervisor.POOL, database.POOL)
        source = (ROOT / 'infra/service/tower_infra/__main__.py').read_text(encoding='utf-8')
        self.assertIn("    if command == 'pooler':", source)
        self.assertIn('return pooler.main(args[1:])', source)
        calls = []
        with mock.patch.object(pooler, 'Pool', lambda *a, **k: calls.append((a, k)) or mock.Mock()), \
                mock.patch.object(pooler, 'listen', lambda directory, port: mock.Mock()), \
                mock.patch.object(pooler, 'serve', lambda pool, listener, stop: None), \
                mock.patch.object(pooler.signal, 'signal'):
            environ = {'TOWER_DB_POOL': '/tmp/x', 'TOWER_DB_HOST': 'db.example', 'TOWER_DB_PORT': '5432', 'TOWER_DB_NAME': 'tower',
                       'AWS_REGION': 'us-east-1', 'TOWER_DB_USER': 'tower_runner'}
            self.assertEqual(pooler.main(['run-container'], environ), 0)
            self.assertEqual(pooler.main(['serve'], {name: value for name, value in environ.items() if name != 'TOWER_DB_USER'}), 0)
            self.assertEqual(pooler.main(['serve'], {}), 2)  # no directory: nothing to listen on
        (where, user, _, name), how = calls[0]
        self.assertEqual((where['host'], where['sslmode'], user, name, how['idle_s']),
                         ('db.example', 'require', 'tower_runner', 'tower-runner:pooled', 30.0))  # DB-SWAP-CUT: was 120
        self.assertEqual((calls[1][0][1], calls[1][0][3]), ('tower_service', 'tower-service:pooled'))



class EnginePool(unittest.TestCase):
    def test_a_processs_engine_keeps_two_idle_connections_and_fifteen_at_most(self):
        # DB-SWAP-CUT (revisão da arquitetura, achado 37): SQLAlchemy's default kept 5 idle connections a process (the live
        # service's and its successor's), each a backend the db.t4g.micro's host pages; the cap is the same 15
        made = {}

        class Engine:
            pass

        fake = mock.Mock()
        fake.URL.create = lambda *a, **k: 'url'
        fake.create_engine = lambda url, **options: made.update(options) or Engine()
        fake.event.listens_for = lambda *a: (lambda function: function)
        with mock.patch.dict(sys.modules, {'sqlalchemy': fake, 'sqlalchemy.event': fake.event}):
            database.iam_engine({'host': 'h', 'port': 5432, 'name': 'n', 'sslmode': 'require', 'role': 'service'}, 'u',
                                token=lambda: 'x')
        self.assertEqual((made['pool_size'], made['max_overflow'], made['pool_use_lifo']), (2, 13, True))
        self.assertEqual(made['pool_size'] + made['max_overflow'], 5 + 10)  # SQLAlchemy's own 5 + 10: no burst waits more

if __name__ == '__main__':
    unittest.main()
