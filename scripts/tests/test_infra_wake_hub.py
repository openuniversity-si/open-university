"""DB-LISTEN-ONE (docs/operations/aws.md 14.1; architecture review, finding 13): one listening connection per process.

The database is a db.t4g.micro of 79 connections. Live on 11/11 its engine held 42 of them idle and 54 at the peak of an
hour of deliveries, and a service process kept five that only listened (the loop's wake, the settings, the gate, the
autodeploy, the prewarm), a runner one per slot and the gate's: with a standby pair, 20 backends that every NOTIFY
signals at once, on the second of a landing. wake.Hub is the one connection of a process that listens, for every waiter
of the process: a thread reads it and sets the flag of each waiter of a notification's channel.

What is pinned here: the waiter's contract is Wake's (woken at once by what came since its last wait, a burst is one
wake, wait(0) drains without the database, a timeout is False); a waiter hears its channels only; a hub that loses its
connection never raises and never spins, listens again after a bounded pause, and then wakes every waiter once; serve
and run-container make one hub each and no listener of their own. OnPostgres: a real NOTIFY reaches every waiter of its
channel through the hub in milliseconds.

Hermetic: Line stands for the psycopg connection. OnPostgres needs TEST_DATABASE_URL; the gate's Python has no psycopg
and psql shows a notification only with its next command, so the listener there is the toolchain's libpq through ctypes
(Libpq), the library psycopg wraps; with psycopg installed, it is psycopg.
"""
import ctypes
import logging
import os
from pathlib import Path
import queue
import select
import statistics
import sys
import threading
import time
import types
import unittest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'infra' / 'service'))
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
from tower_infra import wake  # noqa: E402

URL = os.environ.get('TEST_DATABASE_URL', '')
MAIN = (ROOT / 'infra/service/tower_infra/__main__.py').read_text(encoding='utf-8')
SERVE = MAIN[MAIN.index('def serve('):MAIN.index('\ndef ', MAIN.index('def serve(') + 1)]
RUN = MAIN[MAIN.index('def run_container('):MAIN.index('\ndef ', MAIN.index('def run_container(') + 1)]
SOON = 5  # seconds a test waits for what should come at once


class Line:
    """A psycopg connection as the hub uses it: autocommit, execute, notifies() (blocks until notify(channel) or
    lose()), close."""

    def __init__(self):
        self.autocommit, self.heard, self.told, self.closed, self.read = False, [], queue.Queue(), False, False

    def execute(self, sql):
        self.heard.append(sql)

    def notifies(self):
        self.read = True
        while True:
            said = self.told.get()
            if isinstance(said, Exception):
                raise said
            yield types.SimpleNamespace(channel=said)

    def notify(self, *channels):
        for channel in channels:
            self.told.put(channel)

    def lose(self):
        self.told.put(OSError('the connection was lost'))

    def close(self):
        self.closed = True
        self.lose()


class Ended(Line):
    """A connection whose notifications end at once, without an error."""

    def notifies(self):
        return iter(())


class Lines:
    """connect() for a hub: each call follows the script (a failure is raised, a connection is given), then gives a new
    Line; `made` is what it gave."""

    def __init__(self, *script):
        self.script, self.made = list(script), []

    def __call__(self):
        given = self.script.pop(0) if self.script else Line()
        if isinstance(given, Exception):
            raise given
        self.made.append(given)
        return given

    def line(self, count=1):
        """The count-th connection, once the hub reads its notifications."""
        for _ in range(SOON * 1000):
            if len(self.made) >= count and self.made[count - 1].read:
                return self.made[count - 1]
            time.sleep(0.001)
        raise AssertionError(f'the hub reads {len(self.made)} connection(s), not {count}')


class Pauses:
    """sleep() for a hub: records each pause and holds the hub's thread until go()."""

    def __init__(self):
        self.asked, self.gone = queue.Queue(), threading.Semaphore(0)

    def __call__(self, seconds):
        self.asked.put(seconds)
        self.gone.acquire(timeout=SOON)

    def go(self):
        """The next pause the hub asks for, which then ends."""
        seconds = self.asked.get(timeout=SOON)
        self.gone.release()
        return seconds


class Hubs(unittest.TestCase):
    def hub(self, *script, channels=(wake.WORK, wake.CONFIG)):
        self.lines, self.pauses = Lines(*script), Pauses()
        hub = wake.Hub(self.lines, channels, sleep=self.pauses)
        self.addCleanup(hub.close)
        return hub


class TheWaiter(Hubs):
    def test_one_connection_listens_for_every_waiter_and_a_notification_wakes_those_of_its_channel(self):
        hub = self.hub()
        work, config, both = [hub.wake(wake.WORK) for _ in range(4)], hub.wake(wake.CONFIG), hub.wake((wake.CONFIG, wake.WORK))
        line = self.lines.line()
        self.assertEqual((line.heard, line.autocommit), (['listen tower_work', 'listen tower_config'], True))
        line.notify(wake.WORK)
        self.assertEqual([each.wait(SOON) for each in work] + [both.wait(SOON)], [True] * 5)  # one notification, all of them
        self.assertFalse(config.wait(0))  # not its channel
        line.notify(wake.CONFIG)
        self.assertEqual((config.wait(SOON), both.wait(SOON)), (True, True))
        self.assertEqual([each.wait(0) for each in work], [False] * 4)
        self.assertEqual(len(self.lines.made), 1)  # seven waiters, one connection

    def test_a_burst_is_one_wake_and_what_comes_during_the_pass_wakes_the_next_wait_at_once(self):
        hub = self.hub()
        work, other, mark = hub.wake(wake.WORK), hub.wake(wake.WORK), hub.wake(wake.CONFIG)
        line = self.lines.line()
        line.notify(wake.WORK, wake.WORK, wake.WORK, wake.CONFIG)
        self.assertTrue(mark.wait(SOON))  # the hub read the three before it
        self.assertEqual((work.wait(SOON), work.wait(0)), (True, False))  # three notifications: one wake
        line.notify(wake.WORK)  # during the caller's pass
        self.assertTrue(other.wait(SOON))
        began = time.monotonic()
        self.assertTrue(work.wait(30))  # the next wait: at once, not its 30 s
        self.assertLess(time.monotonic() - began, 1)

    def test_a_wait_of_nothing_drains_and_answers_at_once_without_the_database(self):
        hub = self.hub()
        work, mark = hub.wake(wake.WORK), hub.wake(wake.CONFIG)
        line = self.lines.line()
        for _ in range(3):  # a standby's passes: what was notified to another task is drained, never waited on
            line.notify(wake.WORK, wake.CONFIG)
            self.assertTrue(mark.wait(SOON))  # the hub read both
            began = time.monotonic()
            self.assertEqual((work.wait(0), work.wait(0)), (True, False))
            self.assertLess(time.monotonic() - began, 0.1)
        self.assertEqual((len(self.lines.made), line.heard), (1, ['listen tower_work', 'listen tower_config']))

    def test_a_wait_that_nothing_wakes_ends_at_its_timeout_as_false(self):
        work = self.hub().wake(wake.WORK)
        began = time.monotonic()
        self.assertFalse(work.wait(0.05))
        self.assertGreaterEqual(time.monotonic() - began, 0.05)

    def test_only_the_hubs_channels_are_waited_on(self):
        with self.assertRaises(ValueError):
            wake.Hub(Lines(), ('tower_work; drop table work.job',))
        with self.assertRaises(ValueError):
            wake.Hub(Lines(), ())
        hub = self.hub(channels=(wake.RUNS, wake.CONFIG))
        for channel in (wake.WORK, 'tower_runs; drop table work.job', (wake.RUNS, wake.DEPLOY), ()):
            with self.assertRaises(ValueError):
                hub.wake(channel)
        self.assertEqual(self.lines.line().heard, ['listen tower_runs', 'listen tower_config'])

    def test_a_waiter_keeps_wakes_surface_and_a_closed_one_is_forgotten(self):
        hub = self.hub()
        work = hub.wake(wake.WORK)
        self.assertIs(work.listening(), hub)
        self.assertEqual(work.channels, (wake.WORK,))
        work.close()
        self.assertEqual(hub.flags, {wake.WORK: [], wake.CONFIG: []})
        self.lines.line().notify(wake.WORK)
        self.assertFalse(work.wait(0.05))


class TheConnection(Hubs):
    def setUp(self):
        logging.disable(logging.CRITICAL)  # the losses are logged on purpose
        self.addCleanup(logging.disable, logging.NOTSET)

    def test_a_lost_connection_times_the_waiters_out_then_listens_again_and_wakes_every_one_once(self):
        hub = self.hub()
        work, config = hub.wake(wake.WORK), hub.wake(wake.CONFIG)
        first = self.lines.line()
        first.lose()
        began = time.monotonic()
        self.assertEqual((work.wait(0.05), config.wait(0)), (False, False))  # its own timeout: no raise, no wake
        self.assertGreaterEqual(time.monotonic() - began, 0.05)
        self.assertEqual((self.pauses.go(), first.closed), (1.0, True))  # the lost one is closed; a second, then again
        second = self.lines.line(2)
        self.assertEqual((second.heard, second.autocommit), (['listen tower_work', 'listen tower_config'], True))
        # a notification may have been lost while it was away: every waiter is woken, once
        self.assertEqual((work.wait(SOON), config.wait(SOON), work.wait(0), config.wait(0)), (True, True, False, False))
        second.notify(wake.CONFIG)
        self.assertEqual((config.wait(SOON), work.wait(0)), (True, False))  # and it hears again

    def test_a_database_that_stays_away_is_asked_again_with_a_pause_that_doubles_to_its_bound(self):
        away = [OSError('no route')] * 7
        hub = self.hub(*away)
        work = hub.wake(wake.WORK)
        self.assertEqual([self.pauses.go() for _ in away], [1.0, 2.0, 4.0, 8.0, 16.0, 30.0, 30.0])  # never a spin
        self.assertFalse(work.wait(0))  # nothing woke it meanwhile
        line = self.lines.line()
        self.assertTrue(work.wait(SOON))  # listening at last: woken once
        line.notify(wake.WORK)
        self.assertTrue(work.wait(SOON))
        line.lose()
        self.assertEqual(self.pauses.go(), 1.0)  # it had heard: the pause starts again from a second

    def test_a_connection_that_ends_without_an_error_is_a_lost_one(self):
        hub = self.hub(Ended(), Ended())
        work = hub.wake(wake.WORK)
        self.assertEqual((self.pauses.go(), self.pauses.go()), (1.0, 2.0))  # it heard nothing: the pause grows, never a spin
        self.lines.line(3)
        self.assertEqual((work.wait(SOON), [each.closed for each in self.lines.made]), (True, [True, True, False]))

    def test_close_ends_the_thread_and_its_connection(self):
        hub = self.hub()
        line = self.lines.line()
        hub.close()
        self.assertEqual((hub.thread.is_alive(), line.closed, len(self.lines.made)), (False, True, 1))


class TheWiring(unittest.TestCase):
    """What each process of the engine listens with, counted from serve() and run_container()."""

    def test_the_service_makes_one_hub_for_its_five_waiters(self):
        self.assertEqual((SERVE.count('wake.Hub('), SERVE.count('wake.Wake('), SERVE.count('hub.wake(')), (1, 0, 6))  # DRILLS, LAMBDA-PRUNE: their looks (GATE-LOOKS-GONE, D-316)
        self.assertIn("hub = wake.Hub(lambda: connection(database, where, user, password, purpose='listen', "
                      "**wake.KEEPALIVE),\n                   (wake.WORK, wake.CONFIG, wake.DEPLOY), later=late_listen)", SERVE)
        for waiter in ('woken = hub.wake(wake.WORK)', 'config_data.listen(settings, stop, hub.wake(wake.CONFIG).wait)',
                       'config_data.listen(gate, stop, hub.wake(wake.CONFIG).wait)',
                       'autodeploy.start(workflows.connected, stop, wait=hub.wake(wake.DEPLOY).wait,'):
            self.assertIn(waiter, SERVE)

    def test_every_waiter_of_each_hub_asks_a_channel_its_hub_listens_to(self):
        # HUB-TRAIN: #715's merge-ready look asked hub.wake(wake.TRAIN) of a hub made with WORK, CONFIG and DEPLOY: the
        # service's process raised ValueError as it started, and its successor ended more than 3 times (14/11 00:51 UTC)
        import re
        for source in (SERVE, RUN):
            made = re.search(r'hub = wake\.Hub\(.*?\n\s*\(([^)]*)\)', source, re.S)
            listened = set(re.findall(r'wake\.([A-Z]+)', made.group(1)))
            asked = {name for call in re.findall(r'hub\.wake\((\(?[^)]*\)?)\)', source)
                     for name in re.findall(r'wake\.([A-Z]+)', call)}
            self.assertTrue(asked and asked <= listened, (sorted(asked), sorted(listened)))

    def test_the_runner_makes_one_hub_for_its_slots_and_its_gate(self):
        self.assertEqual((RUN.count('wake.Hub('), RUN.count('wake.Wake('), RUN.count('hub.wake(')), (1, 0, 4))  # CANCEL-WAKES-RUNNER
        self.assertIn("hub = wake.Hub(lambda: connection(database, where, user, password, purpose='listen', "
                      "**wake.KEEPALIVE),\n                   (wake.RUNS, wake.CONFIG, wake.DEPLOY))", RUN)
        self.assertIn('stop, hub.wake(wake.DEPLOY).wait,', RUN)  # HEAD-ON-PUSH: the pushes, on the same connection
        slots = RUN[RUN.index("for slot in range(max(1, int(number('TOWER_RUNNER_SLOTS', 1))) + 1)"):]  # CANARY-OWN-SLOT
        self.assertIn('wait=hub.wake(wake.RUNS).wait', slots)  # a waiter per slot, on the one connection
        self.assertLess(RUN.index('hub = wake.Hub('), RUN.index("for slot in range("))
        self.assertIn('config_data.listen(gate, stop, hub.wake(wake.CONFIG).wait)', RUN)

    def test_the_ports_long_poll_keeps_its_own_listener_for_its_invocation(self):
        port = (ROOT / 'infra/service/tower_infra/http_port.py').read_text(encoding='utf-8')
        self.assertIn("return wake.Wake(lambda: connect(purpose='wait'), channel) if connect else None", port)
        self.assertNotIn('wake.Hub(', port)


class PGnotify(ctypes.Structure):
    _fields_ = [('relname', ctypes.c_char_p), ('be_pid', ctypes.c_int), ('extra', ctypes.c_char_p)]


QUIET = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_char_p)(lambda _, said: None)  # libpq prints notices by default


def libpq():
    """The toolchain's libpq, beside its psql; None when there is none."""
    import test_db
    try:
        library = Path(test_db.psql_binary()).resolve().parent.parent / 'postgres' / 'lib'
        pq = ctypes.CDLL(str((sorted(library.glob('libpq.so*')) or sorted(library.glob('libpq*.dylib')))[0]))
    except (IndexError, OSError, test_db.TestDatabaseError):
        return None
    for name, answers in (('PQconnectdb', ctypes.c_void_p), ('PQexec', ctypes.c_void_p), ('PQerrorMessage', ctypes.c_char_p),
                          ('PQnotifies', ctypes.POINTER(PGnotify)), ('PQstatus', ctypes.c_int), ('PQsocket', ctypes.c_int),
                          ('PQresultStatus', ctypes.c_int), ('PQconsumeInput', ctypes.c_int), ('PQfinish', None),
                          ('PQclear', None), ('PQfreemem', None)):
        function = getattr(pq, name)
        function.restype = answers
        function.argtypes = [ctypes.c_char_p] if name == 'PQconnectdb' else [ctypes.c_void_p] + (
            [ctypes.c_char_p] if name == 'PQexec' else [])
    return pq


class Libpq:
    """A connection as the hub uses psycopg's (autocommit, execute, notifies, close), over libpq. Like psycopg's wait, the
    read looks up ten times a second, so a close from another thread ends it."""

    def __init__(self, pq, url):
        self.pq, self.autocommit, self.closed, self.lock = pq, False, False, threading.Lock()
        self.connection = pq.PQconnectdb(url.encode())
        if pq.PQstatus(self.connection) != 0:
            raise OSError(self.error())
        pq.PQsetNoticeProcessor(ctypes.c_void_p(self.connection), QUIET, None)  # e.g. the word of a backend that is ended

    def error(self):
        return (self.pq.PQerrorMessage(self.connection) or b'').decode().strip()

    def execute(self, sql):
        with self.lock:
            result = self.pq.PQexec(self.connection, sql.encode())
            ok = self.pq.PQresultStatus(result) in (1, 2)  # PGRES_COMMAND_OK, PGRES_TUPLES_OK
            self.pq.PQclear(result)
            if not ok:
                raise OSError(self.error())

    def notifies(self):
        while True:
            ready = select.select([self.pq.PQsocket(self.connection)], [], [], 0.1)[0]
            found = []
            with self.lock:
                if self.closed:
                    raise OSError('the connection is closed')
                if ready and not self.pq.PQconsumeInput(self.connection):
                    raise OSError(self.error())
                while ready:
                    notified = self.pq.PQnotifies(self.connection)
                    if not notified:
                        break
                    found.append(types.SimpleNamespace(channel=notified.contents.relname.decode()))
                    self.pq.PQfreemem(notified)
            yield from found

    def close(self):
        with self.lock:
            if not self.closed:
                self.closed = True
                self.pq.PQfinish(self.connection)


@unittest.skipUnless(URL, 'needs TEST_DATABASE_URL (Postgres; local port 54322)')
class OnPostgres(unittest.TestCase):
    """LISTEN and NOTIFY for real: one hub, the service's five waiters and a runner's slots on it."""

    def setUp(self):
        import test_db
        from infra_db.psql import database_url
        self.name = test_db.create(URL)
        self.addCleanup(test_db.destroy, URL, self.name)
        self.url, self.made = database_url(URL, self.name), []
        try:
            import psycopg
            self.connect = lambda: psycopg.connect(self.url)
        except ImportError:
            pq = libpq()
            if pq is None:
                self.skipTest('neither psycopg nor the toolchain\'s libpq is here')
            self.connect = lambda: Libpq(pq, self.url)
        self.sender = self.connect()
        self.sender.autocommit = True
        self.addCleanup(self.sender.close)

    def hub(self, channels=wake.CHANNELS):
        def connect():
            self.made.append(self.connect())
            return self.made[-1]
        hub = wake.Hub(connect, channels)
        self.addCleanup(hub.close)
        mark = hub.wake(channels[-1])  # the last channel: no test below waits on it
        for _ in range(SOON * 100):  # until it listens: a notification to it comes back
            self.sender.execute(f"select pg_notify('{channels[-1]}', 'are you there')")
            if mark.wait(0.01):
                break
        else:
            self.fail('the hub never listened')
        mark.close()
        return hub

    def notified(self, channel, waiters):
        """Seconds from just before the NOTIFY is sent until the last of `waiters`, each waiting in a thread of its own,
        is woken."""
        woken, ready = [], threading.Barrier(len(waiters) + 1)

        def wait(waiter):
            ready.wait(SOON)
            woken.append(time.monotonic() if waiter.wait(SOON) else None)
        threads = [threading.Thread(target=wait, args=(waiter,), daemon=True) for waiter in waiters]
        for thread in threads:
            thread.start()
        ready.wait(SOON)
        time.sleep(0.01)  # every thread is in its wait
        began = time.monotonic()
        self.sender.execute(f"select pg_notify('{channel}', 'job.created')")
        for thread in threads:
            thread.join(SOON * 2)
        self.assertEqual((len(woken), None in woken), (len(waiters), False))
        return max(woken) - began

    def test_one_notification_reaches_every_waiter_of_its_channel_in_milliseconds(self):
        hub = self.hub()
        work, config = [hub.wake(wake.WORK) for _ in range(8)], hub.wake(wake.CONFIG)
        took = [self.notified(wake.WORK, work) for _ in range(9)]
        # the round trip of the NOTIFY and the hand-off to eight threads: the median of nine, so a busy runner's one
        # slow round is not the measure, and a hub that polled its connection (psycopg looks up every 0.1 s) would be
        self.assertLess(statistics.median(took), 0.05, took)
        self.assertFalse(config.wait(0))  # not its channel
        self.assertEqual((len(self.made), self.made[0].autocommit), (1, True))  # nine waiters, one backend that listens

    def test_the_services_and_the_runners_waiters_are_woken_by_their_channels_only(self):
        hub = self.hub()
        loop, settings, gate = hub.wake(wake.WORK), hub.wake(wake.CONFIG), hub.wake(wake.CONFIG)
        autodeploy, prewarm = hub.wake(wake.DEPLOY), hub.wake((wake.DEPLOY, wake.WORK))
        slots = [hub.wake(wake.RUNS) for _ in range(4)]
        # the landing's commit (live_image.WOKEN): the pointer's write, the deploy's look, the work
        self.assertLess(self.notified(wake.CONFIG, [settings, gate]), SOON)
        self.sender.execute("select pg_notify('tower_deploy', 'x'), pg_notify('tower_work', 'x')")
        self.assertEqual([each.wait(SOON) for each in (loop, autodeploy, prewarm)], [True] * 3)
        self.assertEqual([each.wait(0) for each in (settings, gate, *slots)], [False] * 6)
        self.sender.execute("select pg_notify('tower_runs', 'run.started')")
        self.assertEqual([each.wait(SOON) for each in slots], [True] * 4)  # every idle slot, by one notification
        self.assertEqual([each.wait(0) for each in (loop, settings, gate, autodeploy, prewarm)], [False] * 5)

    def test_a_hub_whose_backend_is_ended_listens_again_and_wakes_its_waiters(self):
        logging.disable(logging.CRITICAL)
        self.addCleanup(logging.disable, logging.NOTSET)
        hub = self.hub((wake.WORK, wake.CONFIG))
        work = hub.wake(wake.WORK)
        self.assertFalse(work.wait(0))
        self.sender.execute("select pg_terminate_backend(pid) from pg_stat_activity where pid <> pg_backend_pid() "
                            "and datname = current_database() and query ilike 'listen%'")
        self.assertTrue(work.wait(wake.RETRY_S[0] + SOON))  # after its pause: woken once, on a new connection
        self.assertEqual(len(self.made), 2)
        self.assertLess(self.notified(wake.WORK, [work]), SOON)  # and it hears again


if __name__ == '__main__':
    unittest.main()
