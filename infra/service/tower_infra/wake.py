"""The wake of the service's loop and of the runner (INFRA-SVC 5; P6 F1, the 1 s path).

Migration 0006 notifies when work frees: channel tower_work when a job is created or cancelled, a run ends, a job is
served from the cache or an executor's capacity is set (the dispatcher's work), and channel tower_runs when a run starts
(the runner's: a run handed over to its executor). A loop that waited a fixed tick waits instead until the next
notification or the tick, whichever comes first. On 04/11 #306's landing waited 0.62 s of its 1.98 s from ready to landed
for the dispatcher's 1 s tick, and each check on the one runner waited for the tick and then for the runner's poll.

A notification only wakes: what to do is read from the tables as before, so a lost one costs a tick, never work. A wait
drains the notifications that came with the first, so a burst is one pass; one that arrives during the pass wakes the
next wait at once. A listener that fails is dropped and the wait sleeps its tick; the next wait listens again.

DB-LISTEN-ONE (docs/operations/aws.md 14.1): a Wake is a connection, and a service process kept five of them, a runner
one per slot and one more, on a database of 79 connections where every listening backend is signalled by every NOTIFY.
A process of the engine now keeps one Hub: one connection that listens for all its waiters, read by one thread that
hands each notification over to the waiters of its channel. Wake stays for the port's Lambda, whose long poll listens
for the length of one invocation.
"""
import logging
import threading
import time

LOG = logging.getLogger('tower_infra.wake')
WORK, RUNS, DEPLOY, CONFIG, TRAIN = 'tower_work', 'tower_runs', 'tower_deploy', 'tower_config', 'tower_train'

CHANNELS = (WORK, RUNS, DEPLOY, CONFIG, TRAIN)
RETRY_S = (1.0, 30.0)  # DB-LISTEN-ONE: a hub that lost its connection listens again after 1 s, then 2, 4... up to 30
# DB-LISTEN-ONE: libpq's keepalive for the hub's connection, which only ever reads: a peer that went away without a
# word is noticed in about a minute (the system's default is hours), and the hub listens again
KEEPALIVE = {'keepalives_idle': 30, 'keepalives_interval': 10, 'keepalives_count': 3}


def channels_of(channel, known=CHANNELS):
    """A channel or a tuple of them, each one of `known`: a name goes into a LISTEN statement as it is."""
    channels = (channel,) if isinstance(channel, str) else tuple(channel)
    for each in channels or (None,):
        if each not in known:
            raise ValueError(f'{each!r} is not a channel of migrations 0006, 0009, 0010 and 0011' if known is CHANNELS
                             else f'{each!r} is not a channel this hub listens to ({", ".join(known)})')
    return channels


class Wake:
    """wait(timeout_s): until a notification on `channel` or the timeout; answers whether a notification woke it.
    connect() gives a new psycopg connection; this one only listens, in autocommit. `channel` may be a tuple of channels
    (IMAGE-PREWARM-B2: the prewarm wakes on a push, tower_deploy, and on its bundle job's end, tower_work)."""

    def __init__(self, connect, channel, sleep=time.sleep):
        self.connect, self.channels, self.sleep, self.connection = connect, channels_of(channel), sleep, None

    def listening(self):
        if self.connection is None:
            connection = self.connect()
            connection.autocommit = True
            for channel in self.channels:
                connection.execute(f'listen {channel}')
            self.connection = connection
        return self.connection

    def wait(self, timeout_s):
        try:
            connection = self.listening()
            woken = any(True for _ in connection.notifies(timeout=timeout_s, stop_after=1))
            if woken:
                for _ in connection.notifies(timeout=0):  # the burst that came with it: one pass serves them all
                    pass
            return woken
        except Exception as error:  # noqa: BLE001 - a lost listener costs latency, never work: the tick goes on
            LOG.warning('wake: %s: %s; waiting the tick, listening again next time', ','.join(self.channels), error)
            self.close()
            self.sleep(timeout_s)
            return False

    def close(self):
        connection, self.connection = self.connection, None
        if connection is not None:
            try:
                connection.close()
            except Exception:  # noqa: BLE001 - it is being dropped
                pass


class Hub:
    """DB-LISTEN-ONE: the one connection of a process that listens, for every waiter of the process. connect() gives a
    new psycopg connection (called again after one is lost: a new IAM token); it listens on `channels` in autocommit and
    one daemon thread reads it, setting the flag of every waiter of a notification's channel: a thread hand-off, no poll.
    The channels are fixed when the hub is made, not added by each waiter: psycopg holds the connection's lock while the
    thread waits on it, so a LISTEN sent later from another thread would wait for the next notification.
    A connection that fails costs latency, never work: the waiters time out at their own timeout, the thread listens
    again after a pause (sleep(seconds); None: until close()) that doubles from RETRY_S[0] to RETRY_S[1] until a
    notification comes again, and once it listens again every waiter is woken once, since a notification may have been
    lost meanwhile."""

    def __init__(self, connect, channels=CHANNELS, sleep=None, later=False):
        self.connect, self.channels = connect, channels_of(channels)
        self.flags = {channel: [] for channel in self.channels}  # the waiters' flags, by channel
        self.lock, self.closed, self.connection = threading.Lock(), threading.Event(), None
        self.sleep = sleep or self.closed.wait
        self.thread = threading.Thread(target=self.listen, name='wake-hub', daemon=True)
        if not later:
            self.thread.start()

    def begin(self):
        """POOL-KEEPS: a hub made `later` listens from now (its login is no part of what comes before): once."""
        if not self.thread.is_alive() and self.thread.ident is None:
            self.thread.start()
        return self

    def wake(self, channel):
        """What Wake(connect, channel) was to its caller: wait(timeout_s), on this hub's connection."""
        waiter = Waiter(self, channels_of(channel, self.channels))
        with self.lock:
            for each in waiter.channels:
                self.flags[each].append(waiter.flag)
        return waiter

    def forget(self, waiter):
        with self.lock:
            for each in waiter.channels:
                if waiter.flag in self.flags[each]:
                    self.flags[each].remove(waiter.flag)

    def tell(self, channels):
        with self.lock:
            flags = [flag for channel in channels for flag in self.flags.get(channel, ())]
        for flag in flags:
            flag.set()

    def listen(self):
        """The thread: connect, LISTEN, hand every notification over; on a failure, pause and start again."""
        pause, again = 0.0, False
        while not self.closed.is_set():
            try:
                self.connection = self.connect()
                self.connection.autocommit = True
                for channel in self.channels:
                    self.connection.execute(f'listen {channel}')
                if self.closed.is_set():  # closed while it connected: nothing to listen for
                    break
                if again:  # it was away: a notification may have been lost, and a wake only makes a loop read its tables
                    LOG.info('wake: the hub of %s listens again', ','.join(self.channels))
                    self.tell(self.channels)
                for notification in self.connection.notifies():  # psycopg hands each one over as it arrives
                    pause = 0.0  # it hears: the next loss starts from the first pause
                    self.tell((notification.channel,))
                raise ConnectionError('the connection stopped giving notifications')
            except Exception as error:  # noqa: BLE001 - a lost listener costs latency, never work: the waiters' ticks go on
                pause = min(max(pause * 2, RETRY_S[0]), RETRY_S[1])
                if not self.closed.is_set():
                    LOG.warning('wake: the hub of %s: %s; listening again in %.0f s', ','.join(self.channels),
                                ' '.join(str(error).split()), pause)
            again = True
            self.drop()
            if not self.closed.is_set():
                self.sleep(pause)
        self.drop()

    def drop(self):
        connection, self.connection = self.connection, None
        if connection is not None:
            try:
                connection.close()
            except Exception:  # noqa: BLE001 - it is being dropped
                pass

    def close(self):
        """The process is ending (a test's is): the thread stops and its connection is closed."""
        self.closed.set()
        self.drop()
        self.thread.join(RETRY_S[0])


class Waiter:
    """Hub.wake's: wait(timeout_s) answers whether a notification on its channels came since its last wait, at once when
    one already did (so one that arrives during the caller's pass wakes the next wait, and a burst is one wake), else
    when one comes or at the timeout. wait(0) is the drain: it answers and clears without waiting. Nothing here touches
    the database; listening() and close() are Wake's, for a caller that holds either."""

    def __init__(self, hub, channels):
        self.hub, self.channels, self.flag = hub, channels, threading.Event()

    def listening(self):
        return self.hub

    def wait(self, timeout_s):
        woken = self.flag.wait(timeout_s)
        if woken:
            self.flag.clear()
        return woken

    def close(self):
        self.hub.forget(self)
