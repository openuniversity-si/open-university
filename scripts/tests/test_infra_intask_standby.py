"""IN-TASK-STANDBY (docs/operations/aws.md 22.9): the standby of a code-only head is a successor process inside the ECS
task of its role, held by the task's first process, a supervisor.

1. The supervisor, with real processes: `tower_infra.supervisor.run` in a subprocess with a stub role process (the fakes
   cannot show a process-level bug). Its child is the role's process and that child's end is the task's; SIGTERM is
   forwarded and the supervisor leaves after its children; a want starts a successor with the standby's environment and a
   withdrawn one stops it; a successor that dies is started again and then reported; a yield makes the successor the
   role's process (it is told to adopt) and the one that yielded leaves after its work; only the role's process keeps the
   task's health file fresh. RESERVE-NO-DB: beside the successor the task holds a reserve of its bundle, loaded and with
   no connection to the database; when the successor ends unasked the reserve is the successor at once and a new
   reserve stands behind it; a bundle whose code has no such command gets none, and never a second successor; the
   reserve is held only while the task has room for it, measured.
2. The wiring: only the container's first process of a role's command becomes the supervisor, before it boots any code.
3. The successor (deploy.intask_standbys above 0), on Postgres with the real statements, the service's real dispatch tick
   and the runner's real TAKE: (a) a landing with no Spot standby swaps in its own statement onto the successors the ECS
   tasks hold, in under a second, and once the swap's canary is green the previous processes give the role away (no reload
   by exec) and the successors adopt it: live with no pointer, {state: reloaded} of both roles and deploy.live_code, which
   is what the build reads to skip the image and the rollouts; (b) a landing that finds no successor is ordered, the tasks
   start one each instead of draining, the look swaps when both beat, and a runner whose slot has a run in flight for
   minutes gives the new runs to the new code at once, in its other slot; (d) the canary red: the previous processes take
   the role back and work on, and the want drops the bundle (the supervisor stops the successor).
4. The parts: the look with the datum off or with no supervisor is today's; a successor leaves at once on SIGTERM; a
   slot's checkout is one process's at a time; the measure counts a landing swapped by its order once (GATE-LOOKS-GONE,
   D-316: the prewarm that said and withdrew the want left; the merge queue's prepare says it, queue_deploy).
"""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent.parent
SERVICE = ROOT / 'infra' / 'service'
sys.path.insert(0, str(SERVICE))
sys.path.insert(0, str(ROOT / 'scripts' / 'tests'))
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
from tower_infra import __main__ as service_main, autodeploy, canary, code_bundle, config_data, live_image  # noqa: E402
from tower_infra import database, port as service_port, queue_deploy, reserve, runner, supervisor  # noqa: E402
import medir  # noqa: E402
import test_infra_reload_nostandby as nostandby  # noqa: E402
import test_infra_swap_failover as failover  # noqa: E402
import test_infra_swap_reload as reload  # noqa: E402
import test_infra_swap_tighten as tighten  # noqa: E402
from test_infra_swap_ready import workflows_with  # noqa: E402

URL = os.environ.get('TEST_DATABASE_URL', '')
ECS, MERGE, PR_HEAD, BASE = reload.ECS, tighten.MERGE, tighten.PR_HEAD, tighten.BASE  # the code the ECS tasks run; the landing
COMMANDS = nostandby.COMMANDS

S, T = 'a' * 64, 'b' * 64  # two bundles
KEY = f'artifacts/lambda/tower-code/{S}.zip'
# The role's process, as the supervisor's child: it says what it was started with, beats its health file, and does what its
# command file says through the child's side of the protocol (supervisor.want, supervisor.give)
STUB = '''
import json, os, signal, sys, time
from pathlib import Path
sys.path.insert(0, os.environ['STUB_SERVICE'])
from tower_infra import supervisor
journal, commands = Path(os.environ['STUB_JOURNAL']), Path(os.environ['STUB_COMMANDS'])
held = sys.argv[1:2] == ['reserve']  # RESERVE-NO-DB: the supervisor's word for a reserve, before the role's command
me = ('reserve:' if held else '') + os.environ['TOWER_IMAGE_DIGEST'] if os.environ.get('TOWER_STANDBY') else 'main'
def say(what, **more):
    with open(journal, 'a') as out:
        out.write(json.dumps({'pid': os.getpid(), 'me': me, 'what': what, **more}) + chr(10))
seen = {}
signal.signal(signal.SIGTERM, lambda *_: seen.update(term=True))
signal.signal(signal.SIGUSR1, lambda *_: seen.update(adopt=True))
signal.signal(signal.SIGUSR2, lambda *_: seen.update(lost=True))  # SUCCESSOR-LOST: only a process that heeds is sent it
say('start', argv=sys.argv[1:], environ={name: os.environ.get(name) for name in (
    'TOWER_STANDBY', 'TOWER_CODE_KEY', 'TOWER_CODE_SHA256', 'TOWER_IMAGE_DIGEST', 'TOWER_CODE_ROOT', 'TOWER_HEALTH_FILE',
    'TOWER_SUPERVISOR', 'TOWER_CODE_LOADED', 'TOWER_CODE_RELOADED', 'PYTHONPATH', 'TOWER_IMAGE', 'KEPT')})
if held:
    if os.environ.get('STUB_NO_RESERVE'):  # a bundle of a code before RESERVE-NO-DB: `reserve` is no command of it
        sys.exit(2)
    from tower_infra import reserve
    reserve.hold('serve', prepare=lambda command, environ: [])  # the real wait: ready, then SIGUSR2
    me = os.environ['TOWER_IMAGE_DIGEST']
    say('go', went=os.environ.get('TOWER_RESERVE_WENT_S'))
    signal.signal(signal.SIGTERM, lambda *_: seen.update(term=True))  # the role's command sets its own, as it starts
    signal.signal(signal.SIGUSR2, lambda *_: seen.update(lost=True))
beats, leave = True, None
while True:
    order = commands / me
    if order.exists():
        said = json.loads(order.read_text())
        order.unlink()
        if said.get('heeds'):
            supervisor.heeds()
        if 'want' in said:
            supervisor.want([tuple(each) for each in said['want']])
        if 'give' in said:
            supervisor.give(said['give'])
            leave = time.monotonic() + said.get('work_s', 0)  # what it has in flight
        if 'exit' in said:
            sys.exit(said['exit'])
        beats = said.get('beats', beats)
    if seen.pop('adopt', None):
        say('adopt')
    if seen.pop('lost', None):
        say('lost', ended=supervisor.lost())
    if seen.get('term'):
        say('term')
        sys.exit(0)
    if leave is not None and time.monotonic() >= leave:
        say('left')
        sys.exit(0)
    if beats:
        Path(os.environ['TOWER_HEALTH_FILE']).touch()
    time.sleep(0.01)
'''
DRIVER = ('import os, sys; sys.path.insert(0, os.environ["STUB_SERVICE"]); from tower_infra import supervisor; '
          'sys.exit(supervisor.run("serve", ["serve"], spawn=[sys.executable, os.environ["STUB"], "serve"]))')
# TASK-POOLER: a stub pool, a process that says it started and its environment, and ends on SIGTERM after a word
POOL_STUB = r'''
import json, os, signal, sys, time
def say(what):
    with open(os.environ['STUB_JOURNAL'], 'a') as out:
        out.write(json.dumps({'pid': os.getpid(), 'me': 'pool', 'what': what, 'argv': sys.argv[1:],
                              'pool': os.environ.get('TOWER_DB_POOL')}) + chr(10))
signal.signal(signal.SIGTERM, lambda *_: (say('term'), sys.exit(0)))
say('start')
while True:
    time.sleep(0.01)
'''
POOL_DRIVER = ('import os, sys; sys.path.insert(0, os.environ["STUB_SERVICE"]); from tower_infra import supervisor; '
               'sys.exit(supervisor.Supervisor("serve", ["serve"], os.environ, spawn=[sys.executable, os.environ["STUB"], "serve"], '
               'pool=[sys.executable, os.environ["POOL_STUB"], "pooler", "serve"]).run())')


class Task:
    """A task: the supervisor in a subprocess, with the stub as the role's process."""

    def __init__(self, case, **environ):
        self.dir = Path(tempfile.mkdtemp(prefix='its-task-'))
        case.addCleanup(self.end)
        (self.dir / 'stub.py').write_text(STUB)
        (self.dir / 'commands').mkdir()
        self.journal, self.health = self.dir / 'journal', self.dir / 'healthy'
        self.journal.touch()
        self.process = subprocess.Popen([sys.executable, '-c', DRIVER], env={
            **os.environ, 'STUB': str(self.dir / 'stub.py'), 'STUB_SERVICE': str(SERVICE), 'STUB_JOURNAL': str(self.journal),
            'STUB_COMMANDS': str(self.dir / 'commands'), 'TOWER_HEALTH_FILE': str(self.health), 'TMPDIR': str(self.dir),
            'TOWER_SUPERVISOR_RESTART_S': '0.05', 'TOWER_SUPERVISOR_TICK_S': '0.05', 'PYTHONDONTWRITEBYTECODE': '1',
            'TOWER_RESERVE': '0',  # RESERVE-NO-DB: no reserve but in the tests of it (1: always, whatever the room)
            'TOWER_RESERVE_SETTLE_S': '0',  # RESERVE-SETTLE: a new reserve at once behind one that went, but in its test
            **environ})

    def end(self):
        if self.process.poll() is None:
            self.process.kill()
        self.process.wait()
        for each in self.said('start'):  # a child the test left behind
            try:
                os.kill(each['pid'], signal.SIGKILL)
            except ProcessLookupError:
                pass

    def said(self, what=None, me=None):
        # only the lines already ended: the role's process may be in the middle of writing its newest one (the gate's
        # red of #580, 12/11: a line of 800 characters read half written, `Unterminated string`)
        found = [json.loads(line) for line in self.journal.read_text().split('\n')[:-1] if line]
        return [each for each in found if what in (None, each['what']) and me in (None, each['me'])]

    def tell(self, me, **said):
        # whole or not there: the role's process reads its command file as soon as it exists, and one it found created
        # and not yet written was an empty text it could not parse (the stub died, was started again and the command
        # was lost: a test waiting for its effect ran out of time)
        order = self.dir / 'commands' / me
        draft = order.with_name(f'.{me}.draft')
        draft.write_text(json.dumps(said))
        os.replace(draft, order)

    def state(self):
        spool = self.said('start')[0]['environ']['TOWER_SUPERVISOR']
        try:
            return json.loads((Path(spool) / 'state.json').read_text())
        except (OSError, ValueError):
            return {}

    def kinds(self):
        return sorted((each['kind'], each['sha']) for each in self.state().get('children') or [])


class TheJournalIsReadWhileItIsWritten(unittest.TestCase):
    def test_a_line_still_being_written_is_not_read_yet(self):
        task = Task.__new__(Task)  # the reader alone: no supervisor
        with tempfile.TemporaryDirectory() as tmp:
            task.journal = Path(tmp) / 'journal'
            whole = json.dumps({'what': 'start', 'me': 'serve', 'pid': 1})
            task.journal.write_text(whole + '\n' + json.dumps({'what': 'start', 'me': 'x', 'environ': {'A': 'b' * 800}})[:700])
            self.assertEqual(task.said('start'), [{'what': 'start', 'me': 'serve', 'pid': 1}])  # the half line waits
            task.journal.write_text(whole + '\n' + whole + '\n')
            self.assertEqual(len(task.said('start')), 2)
            task.journal.write_text('')
            self.assertEqual(task.said(), [])

    def test_a_command_is_whole_when_its_file_appears(self):
        task = Task.__new__(Task)  # the writer alone: no supervisor
        with tempfile.TemporaryDirectory() as tmp:
            task.dir = Path(tmp)
            (task.dir / 'commands').mkdir()
            seen = []
            real = os.replace

            def replace(source, target):  # what a reader could find at each instant of the write
                seen.append((Path(target).exists(), json.loads(Path(source).read_text())))
                return real(source, target)
            with mock.patch.object(os, 'replace', replace):
                task.tell('main', want=[['key', 'sha']], beats=False)
            self.assertEqual(seen, [(False, {'want': [['key', 'sha']], 'beats': False})])  # never created empty
            self.assertEqual(sorted(each.name for each in (task.dir / 'commands').iterdir()), ['main'])
            self.assertEqual(json.loads((task.dir / 'commands' / 'main').read_text()), {'want': [['key', 'sha']], 'beats': False})


def until(check, seconds=20.0):
    limit = time.monotonic() + seconds
    while time.monotonic() < limit:
        found = check()
        if found:
            return found
        time.sleep(0.01)
    raise AssertionError('not in time')


def started(pid):
    """The process's start time in clock ticks since boot (/proc/<pid>/stat, field 22)."""
    return int(Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[19])


def alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


class TheSupervisorHoldsTheRolesProcesses(unittest.TestCase):
    def test_its_child_is_the_roles_process_with_the_tasks_environment_and_that_childs_end_is_the_tasks(self):
        task = Task(self, KEPT='as given', TOWER_CODE_LOADED='/somewhere', PYTHONPATH='/somewhere')
        main = until(lambda: task.said('start'))[0]
        # exactly the task's process: the command, the names it was given (boot() runs in the child, on them)
        self.assertEqual((main['argv'], main['me'], main['environ']['KEPT'], main['environ']['TOWER_CODE_LOADED'],
                          main['environ']['PYTHONPATH'], main['environ']['TOWER_STANDBY']),
                         (['serve'], 'main', 'as given', '/somewhere', '/somewhere', None))
        self.assertTrue(Path(main['environ']['TOWER_SUPERVISOR']).is_dir())  # the mark of a supervised process
        self.assertEqual(until(task.kinds), [('main', None)])
        task.tell('main', exit=7)
        self.assertEqual(task.process.wait(20), 7)  # the role's process ended: so did the task, with its code

    def test_sigterm_is_forwarded_to_every_child_and_the_supervisor_leaves_after_them(self):
        task = Task(self)
        main = until(lambda: task.said('start'))[0]
        task.tell('main', want=[[KEY, S]])
        successor = until(lambda: task.said('start', S))[0]
        task.process.send_signal(signal.SIGTERM)
        self.assertEqual(task.process.wait(20), 0)  # the children's own handlers ended them: the role's exit code
        self.assertEqual(sorted(each['pid'] for each in task.said('term')), sorted([main['pid'], successor['pid']]))
        self.assertFalse(alive(main['pid']) or alive(successor['pid']))
        self.assertFalse(Path(main['environ']['TOWER_SUPERVISOR']).exists())

    def test_a_successor_that_ends_unasked_is_told_at_once_to_the_role_s_process_that_heeds(self):
        """SUCCESSOR-LOST: a successor that ends with no word (a kill: what losing the standby at the instant of the swap
        is) left the role with no process until the supervisor's new one was up (5 to 8 s of boot) or the watch's limit
        passed (deploy.live_stale_s, 10 s). The supervisor knows at once (it reaps the child): it counts the loss in
        its state and signals the role's process, which then covers the role (live_image.Gate.lost)."""
        task = Task(self)
        main = until(lambda: task.said('start'))[0]
        task.tell('main', heeds=True, want=[[KEY, S]])
        first = until(lambda: task.said('start', S))[0]
        self.assertEqual(task.said('lost'), [])
        os.kill(first['pid'], signal.SIGKILL)
        told = until(lambda: task.said('lost'))[0]
        self.assertEqual((told['pid'], told['ended']), (main['pid'], {S: 1}))  # the state said it before the signal came
        second = until(lambda: [each for each in task.said('start', S) if each['pid'] != first['pid']])[0]  # started again, as before
        os.kill(second['pid'], signal.SIGKILL)
        self.assertEqual(until(lambda: task.said('lost')[1:])[0]['ended'], {S: 2})  # a count: each loss is one more
        third = until(lambda: [each for each in task.said('start', S) if each['pid'] not in (first['pid'], second['pid'])])[0]
        task.tell('main', want=[])  # withdrawn: stopped by the supervisor itself, which is no loss
        until(lambda: not alive(third['pid']))
        time.sleep(0.3)
        self.assertEqual(len(task.said('lost')), 2)
        self.assertTrue(alive(main['pid']))

    def test_a_role_s_process_that_never_said_it_heeds_is_never_signalled(self):
        # a process of a code before this one has no handler for SIGUSR2, whose default would end it, and the task with it
        task = Task(self)
        main = until(lambda: task.said('start'))[0]
        task.tell('main', want=[[KEY, S]])
        first = until(lambda: task.said('start', S))[0]
        os.kill(first['pid'], signal.SIGKILL)
        until(lambda: [each for each in task.said('start', S) if each['pid'] != first['pid']])
        time.sleep(0.3)
        self.assertEqual((task.said('lost'), alive(main['pid'])), ([], True))
        self.assertEqual(task.state()['lost'], {S: 1})  # counted all the same

    def test_a_want_starts_a_successor_with_the_standbys_environment_and_a_withdrawn_one_is_stopped(self):
        base = json.dumps({'TOWER_CODE_KEY': 'k0', 'TOWER_CODE_SHA256': None, 'TOWER_IMAGE_DIGEST': 'image@sha256:1',
                           'TOWER_IMAGE': 'tower:1', 'TOWER_MIGRATIONS': None})
        task = Task(self, TOWER_CODE_BASE=base, TOWER_CODE_LOADED='/tmp/tower-code-old', TOWER_CODE_RELOADED='{"turn": 0}',
                    TOWER_CODE_KEY='k1', TOWER_CODE_SHA256=T, TOWER_IMAGE_DIGEST=T, TOWER_IMAGE='tower:1+code.bbbb',
                    PYTHONPATH='/tmp/tower-code-old', TOWER_CODE_PRIOR_PYTHONPATH='-', TOWER_CODE_PRIOR_PYTHONSAFEPATH='-')
        main = until(lambda: task.said('start'))[0]
        task.tell('main', want=[[KEY, S]])
        found = until(lambda: task.said('start', S))[0]
        environ = found['environ']
        # today's standby environment, on what ECS gave the task: the bundle is loaded by the successor's own boot
        self.assertEqual((found['argv'], environ['TOWER_STANDBY'], environ['TOWER_CODE_KEY'], environ['TOWER_CODE_SHA256'],
                          environ['TOWER_IMAGE_DIGEST'], environ['TOWER_IMAGE'], environ['TOWER_CODE_LOADED'],
                          environ['TOWER_CODE_RELOADED'], environ['PYTHONPATH']),
                         (['serve'], 'intask', KEY, S, S, 'tower:1', None, None, None))
        # a directory of its own for its code, a health file of its own, the same spool
        self.assertTrue(Path(environ['TOWER_CODE_ROOT']).is_dir())
        self.assertNotIn(environ['TOWER_HEALTH_FILE'], (str(task.health), main['environ']['TOWER_HEALTH_FILE']))
        self.assertEqual(environ['TOWER_SUPERVISOR'], main['environ']['TOWER_SUPERVISOR'])
        self.assertEqual(until(lambda: len(task.kinds()) == 2 and task.kinds()), [('main', None), ('successor', S)])
        task.tell('main', want=[[KEY, S]])  # the same want again: nothing new
        time.sleep(0.3)
        self.assertEqual(len(task.said('start')), 2)
        task.tell('main', want=[])  # withdrawn: a newer push, a closed PR, the slot given to another head
        until(lambda: task.said('term', S))
        until(lambda: task.kinds() == [('main', None)])
        self.assertFalse(alive(found['pid']))
        self.assertFalse(Path(environ['TOWER_CODE_ROOT']).exists())  # its code went with it
        time.sleep(0.3)
        self.assertEqual((len(task.said('start')), task.process.poll()), (2, None))  # not started again; the task goes on

    def test_a_successor_that_dies_is_started_again_and_one_that_keeps_dying_is_reported_and_left(self):
        task = Task(self)
        until(lambda: task.said('start'))
        task.tell('main', want=[[KEY, S]])
        for n in range(1, supervisor.RESTARTS + 2):
            until(lambda: len(task.said('start', S)) == n)
            task.tell(S, exit=3)
        until(lambda: task.state().get('failed') == [S])  # reported: the role's process reads it
        time.sleep(0.3)
        self.assertEqual((len(task.said('start', S)), task.kinds(), task.process.poll()),
                         (supervisor.RESTARTS + 1, [('main', None)], None))
        task.tell('main', want=[[KEY, S]])  # wanted anew: tried anew
        until(lambda: len(task.said('start', S)) == supervisor.RESTARTS + 2)

    def test_a_yield_makes_the_successor_the_roles_process_and_the_one_that_yielded_leaves_after_its_work(self):
        task = Task(self)
        main = until(lambda: task.said('start'))[0]
        task.tell('main', want=[[KEY, S]])
        successor = until(lambda: task.said('start', S))[0]
        task.tell('main', give=S, work_s=0.5)  # promoted and proven: the role is the successor's for good
        until(lambda: task.said('adopt', S))  # told at once, while the previous process still works
        self.assertEqual((task.said('left'), alive(main['pid'])), ([], True))
        # the state follows the signal (the supervisor tells first, then writes): wait for it, not for any state of two
        until(lambda: task.kinds() == [('main', S), ('retiring', None)])
        until(lambda: task.said('left'))  # its work in flight ended: it left by itself, and was reaped
        until(lambda: task.kinds() == [('main', S)])
        self.assertEqual((task.said('term'), task.process.poll()), ([], None))  # nobody was stopped; the task goes on
        task.tell('main', want=[[KEY, S]])  # a want of the bundle the role's process runs starts nothing
        task.tell(S, want=[[KEY, S], [KEY.replace(S, T), T]])  # the adopted one is the role's process: its want counts
        until(lambda: task.said('start', T))
        self.assertEqual(len(task.said('start')), 3)
        task.tell(S, exit=5)  # and its end is the task's: the successor it held is stopped
        self.assertEqual(task.process.wait(20), 5)
        until(lambda: task.said('term', T))
        self.assertFalse(alive(successor['pid']))

    def test_only_the_roles_process_keeps_the_tasks_health_file_fresh(self):
        task = Task(self)
        until(lambda: task.said('start'))
        first = until(lambda: task.health.exists() and task.health.stat().st_mtime_ns)
        until(lambda: task.health.stat().st_mtime_ns > first)  # the main child's beat is the task's
        task.tell('main', want=[[KEY, S]])
        until(lambda: task.said('start', S))
        task.tell('main', beats=False)  # the role's process stops beating; its successor, standing by, goes on
        time.sleep(0.3)
        stale = task.health.stat().st_mtime_ns
        time.sleep(0.5)
        self.assertEqual(task.health.stat().st_mtime_ns, stale)  # a standby never keeps the task healthy
        task.tell('main', give=S, work_s=30)
        until(lambda: task.health.stat().st_mtime_ns > stale)  # the successor is the role's process: its beat counts
        task.tell(S, beats=False)  # and a process finishing its work does not keep the task healthy either
        time.sleep(0.3)
        stale = task.health.stat().st_mtime_ns
        time.sleep(0.5)
        self.assertEqual(task.health.stat().st_mtime_ns, stale)


class TheTaskKeepsItsConnections(unittest.TestCase):
    """TASK-POOLER, with real processes: the supervisor starts the task's pool first, names it to every child, starts
    it again when it ends, and stops it last; the pool's end is never the task's."""

    def task(self, **environ):
        task = Task.__new__(Task)
        task.dir = Path(tempfile.mkdtemp(prefix='its-task-'))
        self.addCleanup(task.end)
        (task.dir / 'stub.py').write_text(STUB)
        (task.dir / 'pool.py').write_text(POOL_STUB)
        (task.dir / 'commands').mkdir()
        task.journal, task.health = task.dir / 'journal', task.dir / 'healthy'
        task.journal.touch()
        task.process = subprocess.Popen([sys.executable, '-c', POOL_DRIVER], env={
            **os.environ, 'STUB': str(task.dir / 'stub.py'), 'POOL_STUB': str(task.dir / 'pool.py'), 'STUB_SERVICE': str(SERVICE),
            'STUB_JOURNAL': str(task.journal), 'STUB_COMMANDS': str(task.dir / 'commands'), 'TOWER_HEALTH_FILE': str(task.health),
            'TMPDIR': str(task.dir), 'TOWER_SUPERVISOR_RESTART_S': '0.05', 'TOWER_SUPERVISOR_TICK_S': '0.05',
            'PYTHONDONTWRITEBYTECODE': '1', 'TOWER_RESERVE': '0', 'TOWER_DB_HOST': 'db.example', **environ})
        return task

    def test_the_pool_comes_first_its_place_is_named_to_every_child_and_it_comes_back_when_it_ends(self):
        task = self.task()
        pool = until(lambda: [each for each in task.said('start') if each['me'] == 'pool'])[0]
        main = until(lambda: [each for each in task.said('start') if each['me'] == 'main'])[0]
        self.assertLess(pool['pid'], main['pid'] + 10 ** 9)
        # before the role's process: by the kernel's start time of each, not by the order their own journal lines came
        # in (each stub writes its line when it runs: under load the role's came first, the pre-gates of #699 and #702,
        # 13/11 22:3x UTC, though the supervisor had started the pool first)
        self.assertLessEqual(started(pool['pid']), started(main['pid']))
        self.assertEqual(pool['argv'], ['pooler', 'serve'])
        place = main['environ'].get('TOWER_SUPERVISOR')
        self.assertTrue(pool['pool'].startswith(place) and pool['pool'].endswith('/pool'))
        task.tell('main', want=[[KEY, S]])
        successor = until(lambda: task.said('start', S))[0]
        self.assertEqual(successor['environ']['TOWER_SUPERVISOR'], place)
        os.kill(pool['pid'], signal.SIGKILL)  # the pool ends: the task does not
        again = until(lambda: [each for each in task.said('start') if each['me'] == 'pool' and each['pid'] != pool['pid']])[0]
        self.assertEqual(again['pool'], pool['pool'])
        self.assertTrue(alive(main['pid']) and alive(successor['pid']))
        self.assertIsNone(task.process.poll())
        state = until(lambda: json.loads((Path(place) / 'state.json').read_text()))
        pools = until(lambda: [each for each in json.loads((Path(place) / 'state.json').read_text())['children']
                               if each['kind'] == 'pooler' and each['pid'] == again['pid']])
        self.assertEqual(len(pools), 1)  # the state names the pool (the memory's measure finds it there), the new one
        self.assertEqual(state['lost'], {})  # and its end is no successor lost

    def test_the_pool_is_stopped_last_and_the_task_ends_with_the_role_s_code(self):
        task = self.task()
        until(lambda: [each for each in task.said('start') if each['me'] == 'pool'])
        main = until(lambda: [each for each in task.said('start') if each['me'] == 'main'])[0]
        task.process.send_signal(signal.SIGTERM)
        self.assertEqual(task.process.wait(20), 0)
        ended = [each['me'] for each in task.said('term')]
        self.assertEqual(ended[-1], 'pool')  # after the role's process, whose handback goes through it
        self.assertIn('main', ended)
        self.assertFalse(alive(main['pid']))

    def test_a_task_with_no_database_or_with_the_pool_off_has_none(self):
        for environ in ({'TOWER_POOLER': '0'}, {'TOWER_DB_HOST': ''}):
            task = self.task(**environ)
            until(lambda: [each for each in task.said('start') if each['me'] == 'main'])
            time.sleep(0.3)
            self.assertEqual([each for each in task.said('start') if each['me'] == 'pool'], [])
            self.assertIsNone(until(lambda: task.said('start'))[0]['environ'].get('TOWER_DB_POOL'))
            task.process.send_signal(signal.SIGTERM)
            task.process.wait(20)


class TheTaskHoldsAReserve(unittest.TestCase):
    """RESERVE-NO-DB, with real processes: the supervisor and the reserve's real wait (tower_infra.reserve.hold)."""

    def reserve_of(self, task, sha=S, skip=()):
        return until(lambda: [each for each in task.said('start', f'reserve:{sha}') if each['pid'] not in skip])[0]

    def ready(self, task, pid):
        return until(lambda: [each for each in task.state().get('children') or []
                              if each['pid'] == pid and each['kind'] == 'reserve' and each.get('ready')])[0]

    def test_a_wanted_bundle_has_a_reserve_beside_its_successor_told_apart_ready_and_measured(self):
        task = Task(self, TOWER_RESERVE='1')
        until(lambda: task.said('start'))
        task.tell('main', want=[[KEY, S]])
        successor, spare = until(lambda: task.said('start', S))[0], self.reserve_of(task)
        self.assertEqual(spare['argv'], ['reserve', 'serve'])  # the word before the role's command: no code before this obeys it
        for name in ('TOWER_STANDBY', 'TOWER_CODE_KEY', 'TOWER_CODE_SHA256', 'TOWER_IMAGE_DIGEST', 'TOWER_SUPERVISOR'):
            self.assertEqual(spare['environ'][name], successor['environ'][name], name)  # it boots the bundle as a successor does
        for name in ('TOWER_CODE_ROOT', 'TOWER_HEALTH_FILE'):
            self.assertNotEqual(spare['environ'][name], successor['environ'][name], name)  # in a directory of its own
        self.ready(task, spare['pid'])
        state = task.state()
        self.assertEqual((task.kinds(), state['reserve']), ([('main', None), ('reserve', S), ('successor', S)], 'held'))
        # what each process holds, by the kernel, when the reserve said it was ready (measured after the pass's words)
        # the measure of the state where the reserve said it is ready (each change is measured after the pass's words:
        # one taken as the reserve was just spawned finds it with no page yet, and the next replaces it)
        def measured():
            found = (task.state().get('memory') or {}).get('children') or {}
            return len(found) == 3 and all(each.get('rss_mb', 0) > 0 for each in found.values()) and found
        sizes = until(measured)
        self.assertEqual(len(sizes), 3)
        self.assertEqual(task.said('go'), [])  # it waits: nobody told it to go
        self.assertEqual(len(task.said('start', f'reserve:{S}')), 1)  # one reserve a task

    def test_the_reserve_is_the_successor_the_instant_the_successor_ends_and_a_new_reserve_stands_behind_it(self):
        task = Task(self, TOWER_RESERVE='1')
        main = until(lambda: task.said('start'))[0]
        task.tell('main', heeds=True, want=[[KEY, S]])
        first, spare = until(lambda: task.said('start', S))[0], self.reserve_of(task)
        self.ready(task, spare['pid'])
        os.kill(first['pid'], signal.SIGKILL)  # the successor lost, with no word
        went = until(lambda: task.said('go'))[0]
        self.assertEqual(went['pid'], spare['pid'])  # the process that was loaded, not a new one
        self.assertIsNotNone(went['went'])  # and it knows how old it was when the word came (its boot is after)
        self.assertEqual(until(lambda: task.said('lost'))[0]['ended'], {S: 1})  # the role's process is told, as before
        behind = self.reserve_of(task, skip=(spare['pid'],))  # a new reserve behind the new successor
        self.ready(task, behind['pid'])
        self.assertEqual(len(task.said('start', S)), 1)  # no successor was started: the reserve is it
        self.assertEqual(sorted((each['kind'], each['pid']) for each in task.state()['children']), sorted(
            [('main', main['pid']), ('successor', spare['pid']), ('reserve', behind['pid'])]))
        task.tell('main', give=S)  # the swap's end: the role is given to the successor, which is the reserve that went
        self.assertEqual(until(lambda: task.said('adopt'))[0]['pid'], spare['pid'])
        until(lambda: not alive(behind['pid']))  # the bundle runs the role: its reserve is no longer wanted
        until(lambda: not alive(main['pid']))
        self.assertTrue(alive(spare['pid']))
        # the main that ended is said 'retiring' until the supervisor reaps it (the pre-gate of #691, 13/11 21:17 UTC, read
        # it in that instant on a runner with four slots busy): the children as they settle
        until(lambda: task.kinds() == [('main', S)])
        self.assertEqual(task.kinds(), [('main', S)])

    def test_no_reserve_is_started_behind_one_that_just_went_until_the_task_settled(self):
        # RESERVE-SETTLE: at a swap the previous process, the reserve that took over and a new reserve were up together
        # (the service's task peaked at 424 MB of 512), and seconds later the new reserve was stopped unused
        task = Task(self, TOWER_RESERVE='1', TOWER_RESERVE_SETTLE_S='60')
        until(lambda: task.said('start'))
        task.tell('main', heeds=True, want=[[KEY, S]])
        first, spare = until(lambda: task.said('start', S))[0], self.reserve_of(task)
        self.ready(task, spare['pid'])
        os.kill(first['pid'], signal.SIGKILL)
        self.assertEqual(until(lambda: task.said('go'))[0]['pid'], spare['pid'])  # the reserve went, as before
        until(lambda: task.state().get('reserve') == 'waiting')
        time.sleep(0.5)  # ten of the supervisor's ticks
        self.assertEqual(len(task.said('start', f'reserve:{S}')), 1)  # none behind it
        self.assertEqual(task.kinds(), [('main', None), ('successor', S)])
        task.tell('main', give=S)  # the swap ends: the bundle runs the role
        self.assertEqual(until(lambda: task.said('adopt'))[0]['pid'], spare['pid'])
        until(lambda: task.kinds() == [('main', S)])
        self.assertEqual(len(task.said('start', f'reserve:{S}')), 1)

    def test_a_new_reserve_is_started_once_the_task_settled_or_the_bundle_is_wanted_anew(self):
        now = [100.0]
        held = supervisor.Supervisor('serve', ['serve'], {'TOWER_RESERVE': '1', 'TOWER_RESERVE_SETTLE_S': '60'},
                                     spawn=['/bin/true', 'serve'], clock=lambda: now[0])
        self.addCleanup(lambda: __import__('shutil').rmtree(held.dir, ignore_errors=True))
        started, sent = [], []
        held.start = lambda kind, key=None, sha=None: started.append((kind, sha))
        held.send = lambda pid, signum: sent.append((pid, signum))
        health = held.dir / 'h.2'
        health.touch()
        held.wanted = [(KEY, S)]
        held.children = {11: {'kind': 'reserve', 'sha': S, 'key': KEY, 'n': 2, 'health': health, 'root': None, 'ready': True}}
        self.assertTrue(held.promote(S))
        held.spare(set())
        self.assertEqual((started, held.reserve), ([], 'waiting'))
        now[0] += 59.9
        held.spare(set())
        self.assertEqual(started, [])
        now[0] += 0.2
        held.spare(set())  # the successor still stands by a minute later (no swap took it): it gets a reserve again
        self.assertEqual((started, held.reserve), ([('reserve', S)], 'held'))
        self.assertEqual(held.settle_s, 60.0)
        self.assertEqual(supervisor.Supervisor('serve', ['serve'], {}, spawn=['/bin/true', 'serve']).settle_s, 60.0)

    def test_the_state_and_the_pass_s_words_come_before_the_measure_of_the_memory(self):
        # STATE-BEFORE-MEASURE: the measure (the cgroup, every child's pages) was taken before the state was written, on
        # the way of the word that a successor ended; a slow one held the cover's start, and at the gate a state read
        # right after a signal was still the one before it
        held = supervisor.Supervisor('serve', ['serve'], {'TOWER_RESERVE': '0'}, spawn=['/bin/true', 'serve'])
        self.addCleanup(lambda: __import__('shutil').rmtree(held.dir, ignore_errors=True))
        order = []
        held.measured = lambda: order.append('measured') or {'used_mb': 300.0}
        held.children = {5: {'kind': 'main', 'sha': None, 'key': None, 'n': 1, 'health': held.dir / 'h.1', 'root': None}}
        held.say()
        state = json.loads((held.dir / 'state.json').read_text())
        self.assertEqual((order, state['memory'], [each['kind'] for each in state['children']]), ([], {}, ['main']))
        held.measure()
        self.assertEqual((order, json.loads((held.dir / 'state.json').read_text())['memory']), (['measured'], {'used_mb': 300.0}))
        held.measure()  # nothing changed: nothing is measured again
        held.say()
        self.assertEqual(order, ['measured'])
        source = Path(supervisor.__file__).read_text()
        loop = source[source.index('    def run(self):'):]
        self.assertLess(loop.index('self.send(pid, signal.SIGUSR2)'), loop.index('self.measure()'))

    def test_a_reserve_that_is_not_ready_is_not_told_and_the_successor_is_started_again_as_before(self):
        task = mock.Mock(dir=Path(tempfile.mkdtemp(prefix='its-task-')))  # the supervisor's own rule: no process
        self.addCleanup(lambda: __import__('shutil').rmtree(task.dir, ignore_errors=True))
        held = supervisor.Supervisor('serve', ['serve'], {'TOWER_HEALTH_FILE': str(task.dir / 'h'), 'TOWER_RESERVE': '1'},
                                     spawn=['/bin/true', 'serve'])
        self.addCleanup(lambda: __import__('shutil').rmtree(held.dir, ignore_errors=True))
        sent = []
        held.send = lambda pid, signum: sent.append((pid, signum))
        held.wanted = [(KEY, S)]
        held.children = {11: {'kind': 'reserve', 'sha': S, 'key': KEY, 'n': 2, 'health': task.dir / 'h.2', 'root': None}}
        self.assertFalse(held.promote(S))  # still loading: SIGUSR2 would end it (its default), so it is never sent
        self.assertEqual((sent, held.children[11]['kind']), ([], 'reserve'))
        held.children[11]['ready'] = True
        self.assertFalse(held.promote(T))  # another bundle's
        self.assertTrue(held.promote(S))
        self.assertEqual((sent, held.children[11]['kind'], held.tries[S][0]), ([(11, signal.SIGUSR2)], 'successor', 1))
        held.children[12] = {'kind': 'reserve', 'sha': S, 'key': KEY, 'n': 3, 'health': task.dir / 'h.3', 'root': None, 'ready': True}
        held.tries[S] = (supervisor.RESTARTS + 1, 0.0)
        self.assertFalse(held.promote(S))  # a bundle whose successors keep ending is given up on, as before

    def test_a_bundle_whose_code_has_no_such_command_gets_no_reserve_and_never_a_second_successor(self):
        task = Task(self, TOWER_RESERVE='1', STUB_NO_RESERVE='1')
        main = until(lambda: task.said('start'))[0]
        task.tell('main', want=[[KEY, S]])
        first = until(lambda: task.said('start', S))[0]
        until(lambda: task.state().get('reserve') == 'not its code')
        time.sleep(0.5)  # ten of the supervisor's ticks
        self.assertEqual(len(task.said('start', f'reserve:{S}')), 1)  # tried once, ended (2), never again for this bundle
        self.assertEqual(task.kinds(), [('main', None), ('successor', S)])  # and it never ran as a successor
        os.kill(first['pid'], signal.SIGKILL)
        until(lambda: [each for each in task.said('start', S) if each['pid'] != first['pid']])  # started again, as before
        self.assertEqual(len(task.said('start', f'reserve:{S}')), 1)
        self.assertTrue(alive(main['pid']))

    def test_the_reserve_goes_with_its_bundle_s_want_and_with_the_task(self):
        task = Task(self, TOWER_RESERVE='1')
        until(lambda: task.said('start'))
        task.tell('main', want=[[KEY, S]])
        spare = self.reserve_of(task)
        self.ready(task, spare['pid'])
        task.tell('main', want=[])
        until(lambda: not alive(spare['pid']))
        self.assertEqual(task.state()['lost'], {})  # stopped by the supervisor: no loss, and no mark against the bundle
        task.tell('main', want=[[KEY, S]])
        again = self.reserve_of(task, skip=(spare['pid'],))  # wanted anew: held anew
        self.ready(task, again['pid'])
        task.process.send_signal(signal.SIGTERM)
        self.assertEqual(task.process.wait(20), 0)
        self.assertFalse(alive(again['pid']))  # a reserve holds nothing: the task's stop ends it at once

    def test_with_the_reserve_off_a_task_is_as_before(self):
        task = Task(self)  # TOWER_RESERVE=0
        until(lambda: task.said('start'))
        task.tell('main', want=[[KEY, S]])
        until(lambda: task.said('start', S))
        until(lambda: task.state().get('reserve') == 'off')
        self.assertEqual((task.said('start', f'reserve:{S}'), task.kinds()), ([], [('main', None), ('successor', S)]))


class TheReserveIsHeldOnlyWithRoomMeasured(unittest.TestCase):
    def cgroup(self, files):
        root = Path(tempfile.mkdtemp(prefix='its-cgroup-'))
        self.addCleanup(lambda: __import__('shutil').rmtree(root, ignore_errors=True))
        for name, text in files.items():
            (root / name).parent.mkdir(parents=True, exist_ok=True)
            (root / name).write_text(text)
        return root

    def test_the_container_s_memory_is_read_from_its_cgroup_of_either_version(self):
        mb = 1024 * 1024
        two = self.cgroup({'memory.current': str(300 * mb), 'memory.peak': str(410 * mb), 'memory.max': str(512 * mb),
                           'memory.stat': f'anon {200 * mb}\ninactive_file {60 * mb}\nactive_file {40 * mb}\n'})
        self.assertEqual(supervisor.cgroup(two), {'used_mb': 240.0, 'peak_mb': 410.0, 'limit_mb': 512.0})  # less the pages nothing reads
        (two / 'memory.max').write_text('max\n')
        self.assertEqual(supervisor.cgroup(two), {'used_mb': 240.0, 'peak_mb': 410.0})  # no limit of its own: the task's
        one = self.cgroup({'memory/memory.usage_in_bytes': str(300 * mb), 'memory/memory.max_usage_in_bytes': str(410 * mb),
                           'memory/memory.limit_in_bytes': str(9223372036854771712),
                           'memory/memory.stat': f'rss {200 * mb}\ntotal_inactive_file {100 * mb}\n'})
        self.assertEqual(supervisor.cgroup(one), {'used_mb': 200.0, 'peak_mb': 410.0})  # v1's "no limit" is a number
        self.assertEqual(supervisor.cgroup(self.cgroup({})), {})

    def test_a_process_s_size_is_the_kernel_s_and_the_task_s_limit_is_its_metadata_s(self):
        proc = self.cgroup({'7/smaps_rollup': 'Rss:   81408 kB\nPss:   61440 kB\nPss_Anon:  100 kB\n'})
        self.assertEqual(supervisor.resident(7, proc), {'rss_mb': 79.5, 'pss_mb': 60.0})
        self.assertEqual(supervisor.resident(8, proc), {})  # gone
        self.assertGreater(supervisor.resident(os.getpid()).get('rss_mb', 0), 0)  # this process, for real
        asked = []
        said = json.dumps({'Limits': {'CPU': 0.25, 'Memory': 512}}).encode()
        self.assertEqual(supervisor.task_limit({'ECS_CONTAINER_METADATA_URI_V4': 'http://169.254.170.2/v4/x'},
                                               fetch=lambda url: asked.append(url) or said), 512.0)
        self.assertEqual(asked, ['http://169.254.170.2/v4/x/task'])
        self.assertIsNone(supervisor.task_limit({}, fetch=lambda url: self.fail('not in ECS: nothing is asked')))
        self.assertIsNone(supervisor.task_limit({'ECS_CONTAINER_METADATA_URI_V4': 'http://x'}, fetch=lambda url: b'{}'))

    def held(self, used_mb, limit, **environ):
        mb = 1024 * 1024
        root = self.cgroup({'memory.current': str(used_mb * mb), 'memory.stat': 'inactive_file 0\n', 'memory.max': 'max\n'})
        found = supervisor.Supervisor('serve', ['serve'], {'TOWER_CGROUP': str(root), **environ}, spawn=['/bin/true', 'serve'])
        self.addCleanup(lambda: __import__('shutil').rmtree(found.dir, ignore_errors=True))
        found.limit = limit  # what the task's metadata said
        return found

    def test_a_reserve_needs_the_room_it_is_given_within_the_task_s_limit_and_a_limit_that_is_known(self):
        self.assertTrue(self.held(240, 512.0).room())  # 240 + 160 fits in 512: the service with one successor
        self.assertFalse(self.held(354, 512.0).room())  # two successors: no room, so no reserve
        self.assertTrue(self.held(352, 512.0).room())
        self.assertFalse(self.held(240, None).room())  # a task whose limit is not known holds none
        self.assertTrue(self.held(240, 512.0, TOWER_RESERVE_ROOM_MB='272').room())
        self.assertFalse(self.held(240, 512.0, TOWER_RESERVE_ROOM_MB='273').room())
        self.assertFalse(self.held(1, 8192.0, TOWER_RESERVE='0').room())  # off
        self.assertTrue(self.held(500, None, TOWER_RESERVE='1').room())  # the gate's tests: always
        self.assertEqual(self.held(240, 512.0).measured()['limit_mb'], 512.0)

    def test_the_reserve_waits_for_its_successor_s_first_beat_and_says_why_there_is_none(self):
        task = self.held(240, 512.0)
        started = []
        task.start = lambda kind, key=None, sha=None: started.append((kind, sha))
        health = task.dir / 'h.1'
        task.wanted = [(KEY, S)]
        task.children = {5: {'kind': 'successor', 'sha': S, 'key': KEY, 'n': 1, 'health': health, 'root': None}}
        task.spare(set())
        self.assertEqual((started, task.reserve), ([], 'waiting'))  # the successor first: its warm-up is what a landing waits for
        health.touch()
        task.spare(set())
        self.assertEqual((started, task.reserve), ([('reserve', S)], 'held'))
        short = self.held(400, 512.0)
        short.start = lambda *a, **k: self.fail('no room: none is started')
        short.wanted, short.children = [(KEY, S)], {5: {**task.children[5]}}
        short.spare(set())
        self.assertEqual(short.reserve, 'no room')
        short.spare({S})  # the bundle runs the role: there is nothing to reserve
        self.assertIsNone(short.reserve)
        sent = []
        task.send = lambda pid, signum: sent.append((pid, signum))
        task.children = {9: {'kind': 'reserve', 'sha': S, 'key': KEY, 'n': 2, 'health': task.dir / 'h.2', 'root': None}}
        task.spare(set())  # its successor ended and is being started again: the reserve that is loading is kept
        self.assertEqual((sent, task.reserve), ([], 'held'))
        task.wanted = [(KEY, T)]
        task.spare(set())  # another bundle is wanted: this one's reserve is stopped
        self.assertEqual((sent, task.reserve), ([(9, signal.SIGTERM)], 'waiting'))

    def test_a_child_says_the_task_s_memory_and_its_reserve_s_from_the_state(self):
        spool = self.cgroup({'state.json': json.dumps({
            'children': [{'n': 1, 'pid': 1, 'kind': 'main', 'sha': None}, {'n': 3, 'pid': 7, 'kind': 'reserve', 'sha': S, 'ready': True}],
            'reserve': 'held', 'memory': {'limit_mb': 512.0, 'used_mb': 300.0, 'peak_mb': 320.0}})})
        proc = self.cgroup({'7/smaps_rollup': 'Rss:   81408 kB\nPss:   61440 kB\n'})
        environ = {'TOWER_SUPERVISOR': str(spool)}
        self.assertEqual(supervisor.memory(environ, root=str(spool / 'none'), proc=proc), {
            'task_mb': 300.0, 'task_peak_mb': 320.0, 'task_limit_mb': 512.0, 'reserve': 'held', 'reserve_mb': 60.0,
            'reserve_rss_mb': 79.5})
        self.assertEqual(supervisor.reserved(environ), ('held', S))
        self.assertEqual((supervisor.memory({}), supervisor.reserved({})), ({}, (None, None)))  # no supervisor: nothing

    def test_a_successor_says_how_its_reserve_stands_once_each_time_it_changes(self):
        table = failover.Table()
        gate = live_image.Gate(table.scope, 'service', S, strict=True, intask=True, clock=table.clock, task='host:x')
        sent = []
        gate.sent = lambda sql, params, db=None: sent.append(json.loads(params['payload'])) or []
        stands = [('waiting', None)]
        measure = lambda: {'task_mb': 300.0, 'task_limit_mb': 512.0, 'reserve_mb': 60.0, 'reserve': 'stale'}  # noqa: E731
        self.assertIsNone(gate.spared(stands=lambda: stands[0], measure=measure))  # not started yet: nothing to say
        stands[0] = ('held', None)
        self.assertIsNone(gate.spared(stands=lambda: stands[0], measure=measure))  # held, still loading: its memory is not its size yet
        stands[0] = ('held', T)
        self.assertIsNone(gate.spared(stands=lambda: stands[0], measure=measure))  # another bundle's
        stands[0] = ('held', S)
        self.assertEqual(gate.spared(stands=lambda: stands[0], measure=measure), {
            'role': 'service', 'digest': S, 'task': 'host:x', 'state': 'reserve', 'task_mb': 300.0, 'task_limit_mb': 512.0,
            'reserve_mb': 60.0, 'reserve': 'held'})
        self.assertIsNone(gate.spared(stands=lambda: stands[0], measure=measure))  # once
        stands[0] = ('no room', None)
        self.assertEqual(gate.spared(stands=lambda: stands[0], measure=measure)['reserve'], 'no room')
        self.assertEqual(len(sent), 2)
        gate.sent = mock.Mock(side_effect=RuntimeError('the database is away'))
        stands[0] = ('off', None)
        with mock.patch.object(live_image.LOG, 'exception'):
            self.assertIsNone(gate.spared(stands=lambda: stands[0], measure=measure))  # a measure: never the beat's failure


class TheReserveWaitsLoadedWithNoConnection(unittest.TestCase):
    def test_it_holds_the_word_back_loads_says_it_is_ready_waits_and_is_then_born_as_the_successor(self):
        did, environ = [], {'TOWER_SUPERVISOR_CHILD': '4'}
        ages = iter([12.5, 40.0])
        before = live_image.BORN
        self.addCleanup(setattr, live_image, 'BORN', before)
        live_image.BORN = '1'
        said = reserve.hold(
            'serve', environ, wait=lambda signals: did.append(('wait', signals)),
            tell=lambda name, said, environ: did.append(('tell', name, said['ready_s'], said['command'])),
            prepare=lambda command, environ: did.append(('prepare', command)) or [], age=lambda: next(ages),
            mask=lambda how, signals: did.append(('mask', how, signals)), handle=lambda signum, how: did.append(('handle', signum, how)),
            lower=lambda: did.append('lower') or 0, raise_=lambda before: did.append(('raise', before)))
        go = {signal.SIGUSR2}
        self.assertEqual(did, [('mask', signal.SIG_BLOCK, go), ('handle', signal.SIGTERM, signal.SIG_DFL),
                               ('handle', signal.SIGINT, signal.SIG_DFL), 'lower', ('prepare', 'serve'), ('tell', 'ready.4.json', 12.5, 'serve'),
                               ('wait', go), ('raise', 0), ('handle', signal.SIGUSR2, signal.SIG_IGN),
                               ('mask', signal.SIG_UNBLOCK, go)])
        self.assertEqual(environ['TOWER_RESERVE_WENT_S'], '40.0')  # its boot, for the swap's record, is what comes after
        self.assertGreater(int(live_image.BORN), 1)  # SWAP-DRILL: the drill that ended the one before it is older than it
        self.assertGreater(said['rss_mb'], 0)  # what it holds while it waits, by the kernel

    def test_what_it_loads_ahead_needs_no_database_and_a_part_that_fails_is_left_to_the_command(self):
        loaded, made, signed = [], [], []
        fake = mock.Mock()
        fake.client = lambda name, region_name=None: made.append((name, region_name))
        base = mock.Mock()
        base.settings = lambda environ: {'region': environ['AWS_REGION']}
        base.signer = lambda region: signed.append(region)
        base.iam_connection = base.iam_engine = base.password_connection = lambda *a, **k: self.fail('no connection is made')

        def load(name):
            loaded.append(name)
            if name == 'dbos':
                raise ImportError('not in this image')
            return {'boto3': fake, 'tower_infra.database': base}.get(name)
        compiled = []
        failed = reserve.ready('serve', {'AWS_REGION': 'us-east-1'}, load=load,
                               compile_all=lambda where, **how: compiled.append((Path(where).name, how)))
        self.assertEqual(failed, ['dbos'])
        self.assertEqual(loaded[:5], ['psycopg', 'sqlalchemy', 'sqlalchemy.dialects.postgresql.psycopg', 'boto3', 'dbos'])
        self.assertIn('tower_infra.sessions', loaded)  # RESERVE-AFTER-GO: what serve imports between its read and its launch
        self.assertIn('tower_infra.live_image', loaded)
        self.assertNotIn('tower_infra.workflows', loaded)  # registered against the DBOS the command makes first
        self.assertEqual(compiled, [('tower_infra', {'quiet': 2, 'workers': 1})])
        self.assertEqual((signed, made), (['us-east-1'], [('ssm', 'us-east-1'), ('sns', 'us-east-1')]))  # models loaded, no call
        loaded.clear()
        self.assertEqual(reserve.ready('run-container', {'AWS_REGION': 'us-east-1'}, load=load, compile_all=lambda *a, **k: None), [])
        self.assertIn('tower_infra.runner', loaded)
        self.assertNotIn('dbos', loaded)

    def test_its_priority_is_the_lowest_while_it_loads_only_where_it_can_be_given_back(self):
        put = []
        self.assertEqual(reserve.quiet(get=lambda which, who: 0, put=lambda which, who, value: put.append(value),
                                       may=lambda before: True), 0)
        self.assertEqual(put, [19])
        # a container with no CAP_SYS_NICE could never raise it again: nothing is changed (the successor it becomes
        # would run the role at the low priority for good)
        self.assertIsNone(reserve.quiet(get=lambda which, who: 0, put=lambda *a: self.fail('never lowered'), may=lambda before: False))
        status = Path(tempfile.mkdtemp(prefix='its-status-')) / 'status'
        self.addCleanup(lambda: __import__('shutil').rmtree(status.parent, ignore_errors=True))
        status.write_text('Name:\tpython\nCapEff:\t00000000a80425fb\n')  # Docker's default set: no bit 23
        self.assertFalse(reserve.restorable(0, str(status), limit=0))
        status.write_text('Name:\tpython\nCapEff:\t000001ffffffffff\n')  # every capability
        self.assertTrue(reserve.restorable(0, str(status), limit=0))
        self.assertTrue(reserve.restorable(0, str(status.parent / 'none'), limit=20))  # its limit allows it
        self.assertFalse(reserve.restorable(0, str(status.parent / 'none'), limit=0))
        back = []
        tasks = Path(tempfile.mkdtemp(prefix='its-tasks-'))
        self.addCleanup(lambda: __import__('shutil').rmtree(tasks, ignore_errors=True))
        for name in ('101', '102'):
            (tasks / name).mkdir()
        reserve.loud(0, put=lambda which, who, value: back.append((who, value)), tasks=str(tasks))
        self.assertEqual(sorted(back), [(101, 0), (102, 0)])  # every thread: a priority is a thread's
        reserve.loud(None, put=lambda *a: self.fail('nothing was lowered'))

    def test_the_command_reserve_is_the_role_s_command_held_and_only_of_a_supervised_process(self):
        calls = []
        with mock.patch.object(service_main, 'serve', lambda: calls.append('serve') or 0), \
                mock.patch.object(reserve, 'hold', lambda command: calls.append(('hold', command))), \
                mock.patch.object(code_bundle, 'boot', lambda command, args: calls.append(('boot', command, args))), \
                mock.patch.object(code_bundle, 'entered', lambda: None), \
                mock.patch.object(service_main.lifecycle if hasattr(service_main, 'lifecycle') else __import__(
                    'tower_infra.lifecycle', fromlist=['said']), 'said', lambda work: work()):
            with mock.patch.dict(os.environ, {'TOWER_SUPERVISOR': '/tmp/spool', 'TOWER_SUPERVISE': '0'}):
                self.assertEqual(service_main.main(['reserve', 'serve']), 0)
            # the bundle is booted with the same words: a bundle of a code before this one ends at `reserve` (2)
            self.assertEqual(calls, [('boot', 'serve', ['reserve', 'serve']), ('hold', 'serve'), 'serve'])
            calls.clear()
            with mock.patch.dict(os.environ, {'TOWER_SUPERVISE': '0'}):
                os.environ.pop('TOWER_SUPERVISOR', None)
                self.assertEqual(service_main.main(['reserve', 'serve']), 2)  # no supervisor: no such command
            self.assertEqual(calls, [('boot', 'reserve', ['reserve', 'serve'])])

    def test_a_reserve_told_to_go_says_its_boot_from_the_word_and_how_long_it_had_waited(self):
        self.assertIn("self.boot = {'boot_s': round(max(0.0, age - went), 3), 'held_s': went, 'reserve': True}",
                      Path(live_image.__file__).read_text())

    def test_one_client_signs_every_login_of_a_process(self):
        made = []

        class Client:
            def generate_db_auth_token(self, **asked):
                return f"token for {asked['DBUsername']}"

        def make(name, region_name=None):
            made.append((name, region_name))
            return Client()
        with mock.patch.object(database, 'SIGNERS', {}):
            first = database.signer('us-east-1', make)
            self.assertIs(database.signer('us-east-1', make), first)
            self.assertIsNot(database.signer('eu-west-1', make), first)
            self.assertEqual(made, [('rds', 'us-east-1'), ('rds', 'eu-west-1')])
            where = {'host': 'db', 'port': 5432, 'region': 'us-east-1'}
            self.assertEqual([database.auth_token(where, 'tower_runner', {}) for _ in range(3)], ['token for tower_runner'] * 3)
            self.assertEqual(len(made), 2)  # LOGIN-ONE-SIGNER: a login made a client of its own each time


class OnlyTheContainersFirstProcessSupervises(unittest.TestCase):
    def test_pid_1_of_a_roles_command_and_never_a_supervised_process_or_another_command(self):
        due = supervisor.due
        self.assertEqual([due('serve', {}, pid=1), due('run-container', {}, pid=1), due('serve', {}, pid=77),
                          due('healthy', {}, pid=1), due('init', {}, pid=1)], [True, True, False, False, False])
        self.assertFalse(due('serve', {supervisor.DIR: '/spool'}, pid=1))  # a child of a supervisor: the role's process
        self.assertFalse(due('serve', {supervisor.FORCE: '0'}, pid=1))  # the way out: the task's process as before
        self.assertTrue(due('serve', {supervisor.FORCE: '1'}, pid=77))  # the gate's tests

    def test_the_first_process_under_the_containers_init_supervises_too(self):
        # RUNNER-SUPERVISED: the runner's task has an init at pid 1 (InitProcessEnabled: the orphans of checks are reaped), so
        # its process was never pid 1 and never became a supervisor: live 11/11, the service's successor was up 10 s after
        # the want and the runner's never came (platform.process.started of the runner said supervised false)
        due = supervisor.due
        self.assertEqual([due('run-container', {}, pid=7, parent=1), due('serve', {}, pid=7, parent=1)], [True, True])
        self.assertFalse(due('run-container', {}, pid=7, parent=3))  # a process someone else started is no task's first
        self.assertFalse(due('run-container', {supervisor.DIR: '/spool'}, pid=7, parent=1))  # a supervised orphan stays a role's process
        self.assertFalse(due('run-container', {supervisor.FORCE: '0'}, pid=7, parent=1))
        self.assertFalse(due('healthy', {}, pid=7, parent=1))  # the health check ECS runs beside it
        # (GATE-SHUTDOWN, D-314: the runner's task definition, whose init at pid 1 made the rule needed, left 50-runner.json)

    def test_the_supervisor_comes_before_the_boot_and_a_supervised_process_boots_and_serves_as_before(self):
        order = []
        with mock.patch.object(supervisor, 'run', side_effect=lambda command, args: order.append(('supervise', command, args)) or 9), \
                mock.patch.object(code_bundle, 'boot', side_effect=lambda command, args: order.append(('boot', command))), \
                mock.patch.object(service_main, 'serve', side_effect=lambda: order.append(('serve',))), \
                mock.patch.dict(os.environ, {supervisor.FORCE: '1'}):
            self.assertEqual(service_main.main(['serve']), 9)  # its exit code is the role's process's
            self.assertEqual(order, [('supervise', 'serve', ['serve'])])  # no code is booted in the supervisor
            del order[:]
            with mock.patch.dict(os.environ, {supervisor.DIR: '/spool'}):
                self.assertEqual(service_main.main(['serve']), 0)
            self.assertEqual(order, [('boot', 'serve'), ('serve',)])

    def test_a_word_to_the_supervisor_is_a_whole_file_and_a_signal_and_nothing_without_one(self):
        self.assertFalse(supervisor.want([(KEY, S)], {}))
        with tempfile.TemporaryDirectory() as spool:
            sent = []
            self.assertTrue(supervisor.want([(KEY, S)], {supervisor.DIR: spool, supervisor.PID: '41'},
                                            kill=lambda pid, signum: sent.append((pid, signum))))
            self.assertEqual(json.loads((Path(spool) / 'want.json').read_text()), {'successors': [{'key': KEY, 'sha': S}]})
            self.assertEqual((sent, os.listdir(spool)), ([(41, signal.SIGUSR1)], ['want.json']))


def heir(role):
    return f'ecs-{role}:{S[:12]}'


@unittest.skipUnless(URL, 'needs TEST_DATABASE_URL (Postgres; local port 54322)')
class OnPostgres(unittest.TestCase):
    """The real statements. Each process is its gate and its looks on the test's database; the supervisor is what the
    processes told it (supervisor.want, supervisor.give), and its SIGUSR1 is `told`. The gates' clock is injected; the
    log's is the database's."""

    def setUp(self):
        import threading
        from runner_world import RunnerWorld
        self.world = type('World', (RunnerWorld,), {'runTest': lambda self: None})()
        self.world.setUp()
        self.addCleanup(self.world.doCleanups)
        self.db, self.port, self.threading = self.world.db, self.world.port, threading
        self.port('PUT', '/v1/queues/checks', 'torre', {'policy': 'rank'})
        self.tenant = self.db.rows("select id::text from work.tenant where name = 'torre'")[0][0]
        push = {'refUpdates': [{'ref': 'refs/heads/mod/roadmap-integration', 'before': '0' * 40, 'after': BASE}]}
        self.db.rows("insert into log.event (event_id, tenant_id, type, occurred_at, producer, subject, payload) values "
                     "('push:1', %(tenant)s::uuid, 'forge.repository.pushed', clock_timestamp() - interval '1 minute', "
                     "'forge/origin', 'app/origin', %(payload)s::jsonb)",
                     {'tenant': self.tenant, 'payload': json.dumps({'delivery': {'event': {'payload': push}}})})
        self.db.rows("insert into work.config_value (tenant_id, key, value, actor, reason) "
                     "values (%(tenant)s::uuid, 'deploy.intask_standbys', '1'::jsonb, 'test', 'IN-TASK-STANDBY: on')",
                     {'tenant': self.tenant})
        self.workflows, self.published, self.clock = workflows_with([]), [], failover.Clock()
        self.bundle, self.away = reload.Bundle(), nostandby.Away()
        self.wants, self.gave, self.told = [], [], set()  # what the supervisor was told; the successors it told to adopt
        for name, said in (('supervised', lambda environ=None: '/spool'), ('want', lambda want, *_: self.wants.append(list(want))),
                           ('give', lambda sha, *_: self.gave.append(sha))):
            patch = mock.patch.object(supervisor, name, side_effect=said)
            patch.start()
            self.addCleanup(patch.stop)
        settings = config_data.Config(live_image.kept(self.db), 'torre')
        settings.refresh()
        self.watcher = autodeploy.AutoDeploy(live_image.kept(self.db), {}.get, lambda _: {}, clock=time.time, config=settings)
        self.watcher.alert, self.watcher.landed_at[MERGE] = self.published.append, time.time() - 0.2
        self.service, self.runner = self.process('service'), self.process('runner')

    def process(self, role, successor=False, slots=1):
        """A process of the role's ECS task: the task's own (the code ECS gave it), or its successor on the bundle S."""
        found = mock.Mock()
        name = heir(role) if successor else f'ecs-{role}'
        found.gate = live_image.Gate(live_image.kept(self.db), role, S if successor else ECS, task=name, clock=self.clock,
                                     strict=successor)
        if successor:  # live_image.heed and the wiring: TOWER_STANDBY=intask, and the supervisor's SIGUSR1
            found.gate.intask, found.gate.told_adopt = True, lambda: role in self.told
        found.gate.refresh()
        found.order = live_image.Order(found.gate, COMMANDS[role], hold=role == 'runner', stage=self.bundle.stage,
                                       execute=self.bundle.execute, afresh=self.away)
        found.reload = live_image.Reload(found.gate, COMMANDS[role], stage=self.bundle.stage, execute=self.bundle.execute)
        found.slots = [runner.Runner(self.db, self.world.fetch, self.world.prepare, self.world.upload, self.world.workdir,
                                     name=name if not n else f'{name}/{n}', gate=found.gate, order=found.order,
                                     reload=found.reload) for n in range(slots)]
        found.slot = found.slots[0]
        found.live = canary.Live(found.gate, live_image.kept(self.db), publish=self.published.append)
        return found

    def heard(self):
        """The gates' listeners: every process reads the pointer again (the NOTIFY of tower_config)."""
        for each in (self.service, self.runner, *getattr(self, 'heirs', ())):
            each.gate.refresh()

    def standby(self, process):
        """A standby pass of a process, one second later: its beat (an ECS task's watches) and its reload's look. Answers
        'exec' when the look replaced the process."""
        self.clock.now += 1
        process.gate.beat(self.db)
        try:
            process.reload.step(self.db)
        except reload.Replaced:
            return 'exec'
        return None

    def look(self, process, later=1):
        self.clock.now += later
        try:
            process.order.step(self.db)
        except reload.Replaced:
            return 'exec'
        return None

    def tick(self, process, later=1):
        """A live service's pass (serve's loop), `later` seconds on: its look, the dispatch tick, its first work recorded,
        its live beat, the role adopted or handed over, its canaries. Answers the runs the tick started."""
        if self.look(process, later):
            return 'exec'
        scope = mock.patch.object(self.workflows, 'connected', lambda: __import__('contextlib').nullcontext(self.db))
        with scope:
            started = self.workflows.tick('5 minutes')
        process.gate.working()
        process.gate.live_beat()
        process.gate.back()
        process.live.step()
        return started

    def take(self, process, slot=0):
        """A live runner slot's pass (Runner.loop, once): its TAKE and run, then its look."""
        stop = self.threading.Event()
        each = process.slots[slot]
        each.wait = lambda timeout: stop.set()
        before = len(self.world.fetched)
        each.loop(stop, 1.0)
        return len(self.world.fetched) - before

    def pointers(self):
        return dict(self.db.rows("select key, value #>> '{}' from work.config_value where key like 'deploy.live_image_%%'"))

    def said(self, kind, state=None):
        found = [json.loads(row[0]) for row in self.db.rows(
            "select payload::text from log.event where type = %(type)s order by occurred_at", {'type': kind})]
        return [each for each in found if state in (None, each.get('state'))]

    def swap(self):
        """Both pointers onto S in one statement and its platform.deploy.image_swap, the autodeploy's swap of a landed
        bundle (SWAP_WRITE, as reloads() writes it onto the successors). LANDING-PREWARM-GONE (D-316): the landing's own
        swap left with the prewarm; this is the swap the successors take the role on."""
        found = self.db.rows(autodeploy.SWAP_WRITE, {
            'tenant': 'torre', 'digest': S, 'keys': ','.join(live_image.KEYS[role] for role in ('runner', 'service')),
            'reason': 'test', 'id': f'{autodeploy.SWAP}:{MERGE}', 'landed_at': time.time(), 'payload': json.dumps(
                {'digest': S, 'key': KEY, 'head': MERGE, 'pr_head': PR_HEAD, 'by': 'autodeploy'})})  # judged by its canary
        return json.loads(found[0][0])

    def taken_by(self, job):
        return [row[0] for row in self.db.rows(
            "select payload->>'runner' from log.event where type = 'run.running' and subject = 'job/' || %(job)s", {'job': job})]

    def wanted(self):
        """The want of the bundle S (the merge queue's, queue_deploy.WANT), and each ECS task's process telling its supervisor on its next look."""
        self.db.rows(queue_deploy.WANT, {'id': f'platform.deploy.successor:{S}:wanted:1', 'payload': json.dumps(
            {'digest': S, 'key': KEY, 'branch': 'units/a', 'state': 'wanted'})})
        self.heard()
        self.tick(self.service)
        self.take(self.runner)

    def successors(self, slots=1):
        """What the supervisors started: the successor of S in each task, standing by and beating."""
        self.heirs = [self.process('service', True), self.process('runner', True, slots)]
        for each in self.heirs:
            each.gate.beat(self.db)
        return self.heirs

    def proven(self, service, runner_):
        """The swap's canary: fired by the service that took the role, dispatched by its tick, run by the runner."""
        self.assertEqual(len(self.tick(service) or self.tick(service)), 1)
        self.assertEqual(self.take(runner_), 1)
        [verdict] = [each for each in self.db.rows("select state from work.job where idempotency_key like 'canary:swap:%%'")]
        return verdict[0]

    def test_a_landing_with_no_spot_standby_swaps_under_a_second_onto_the_successors_and_they_keep_the_role(self):
        self.wanted()
        self.assertEqual(self.wants, [[(KEY, S)], [(KEY, S)]])  # each task's process told its supervisor: one successor
        # SUCCESSOR-HOLDS-SAID: and said so in the engine's log, which the status shows: who holds what, and why
        holds = self.said(live_image.SUCCESSOR, 'holds')
        self.assertEqual([(each['role'], each['task'], each['digests'], each['order']) for each in holds],
                         [('service', 'ecs-service', [S], None), ('runner', 'ecs-runner', [S], None)])
        status = self.port('GET', '/v1/deploy/status', 'torre')['successor']
        self.assertEqual(len([each for each in status if each.get('state') == 'holds']), 2)
        self.assertEqual((self.bundle.staged, self.service.gate.reloading, self.runner.gate.reloading), ([], False, False))
        service, runner_ = self.successors()
        self.assertEqual([(each['role'], each['task'], each['state']) for each in self.said(live_image.SUCCESSOR, 'up')],
                         [('service', heir('service'), 'up'), ('runner', heir('runner'), 'up')])
        self.assertEqual(self.said('platform.deploy.standby'), [])  # no Spot standby anywhere
        began = time.monotonic()
        swapped = self.swap()  # both pointers in one statement
        self.assertEqual((swapped['swapped'], swapped['by']), (True, 'autodeploy'))
        self.heard()
        self.assertEqual([each.gate.active() for each in (service, runner_, self.service, self.runner)], [True, True, False, False])
        self.assertEqual(self.tick(service, later=0), [])  # the successors work: the first tick, the first TAKE on the bundle
        self.take(runner_)
        self.assertLess(time.monotonic() - began, 1.0)  # the landing to both roles working, statements and all
        live = {each['role']: each for each in self.said('platform.deploy.image_live')}
        self.assertEqual({role: each['task'] for role, each in live.items()}, {role: heir(role) for role in ('service', 'runner')})
        status = self.port('GET', '/v1/deploy/status', 'torre')
        [seconds] = medir.from_deploy_status(status)['image_code_landing_s']
        self.assertLess(seconds, 1.0)
        # the status shows the want and the successors that stand by: what an operator reads before a landing
        self.assertEqual([(each.get('role'), each['state'], each['digest']) for each in reversed(status['successor'])],
                         [(None, 'wanted', S), ('service', 'holds', S), ('runner', 'holds', S),  # SUCCESSOR-HOLDS-SAID
                          ('service', 'up', S), ('runner', 'up', S)])
        # the canary of the swap, judged by the processes on the previous code: green, they give the role away for good
        self.assertEqual(self.proven(service, runner_), 'succeeded')
        for process in (self.service, self.runner):
            self.assertIsNone(self.standby(process))  # the pass that sees the swap
            self.assertIsNone(self.standby(process))  # and the look: no staging, no claim, no exec
        self.assertEqual((self.gave, self.bundle.staged, self.bundle.execed), ([S, S], [], []))
        self.assertEqual([(each['role'], each['from'], each['heir']) for each in self.said(live_image.RELOAD, 'yielded')],
                         [('service', ECS, heir('service')), ('runner', ECS, heir('runner'))])
        self.assertEqual([self.service.gate.gone, self.runner.gate.gone, self.pointers()],
                         [True, True, {key: S for key in live_image.KEYS.values()}])
        self.assertEqual(self.take(self.runner), 0)  # its slots end: the process leaves once its runs in flight ended
        # the supervisor tells the successors (SIGUSR1): they adopt the role on their next good pass
        self.told.update(('service', 'runner'))
        self.tick(service)
        self.take(runner_)
        self.assertEqual((service.gate.strict, runner_.gate.strict), (False, False))
        self.assertEqual(sorted(each['role'] for each in self.said(live_image.RELOAD, 'reloaded') if each['digest'] == S),
                         ['runner', 'service'])  # what deploy.sh's code_live reads: both roles run the bundle
        # ... and hand the pointer over once the process that yielded no longer beats on the code it ran (ALONE)
        self.assertEqual(self.pointers(), {key: S for key in live_image.KEYS.values()})
        self.db.rows("update work.standby_beat set beat_at = beat_at - interval '10 seconds' where digest = %(was)s", {'was': ECS})
        self.clock.now += live_image.LIVE_BEAT_S
        self.tick(service)
        self.take(runner_)
        self.assertEqual(self.pointers(), {key: '' for key in live_image.KEYS.values()})
        self.heard()
        self.assertEqual([each.gate.active() for each in (service, runner_, self.service, self.runner)], [True, True, False, False])
        self.assertEqual(sorted((each['role'], each['by'], each.get('reloaded')) for each in self.said('platform.deploy.image_retired')),
                         [('runner', 'handover', True), ('service', 'handover', True)])
        self.watcher.live_code(self.db, MERGE)  # the look of the service that has the role: the durable datum
        self.assertEqual(self.port('GET', '/v1/deploy/status', 'torre')['live_code'], f'{S}@{MERGE}')
        work = self.world.job('after-the-landing', 'true')  # live with no pointer: the next job, on the bundle
        self.assertEqual(len(self.tick(service)), 1)
        self.take(runner_)
        self.assertEqual((self.world.state(work), self.taken_by(work)), ('succeeded', [heir('runner')]))
        self.assertEqual(self.published, [])

    def test_a_landing_with_no_successor_is_swapped_when_they_beat_and_a_run_in_flight_never_holds_the_new_runs(self):
        with self.runner.gate.engaged('ecs-runner'):  # a check that lasts minutes is in flight in the runner
            self.watcher.order(self.db, MERGE, S, KEY, PR_HEAD)  # the landing found no standby: the order
            self.heard()
            self.assertEqual(self.take(self.runner), 0)
            # the order is a want: the supervisor starts the successor; the runner does not drain (its slots go on taking)
            self.assertEqual((self.wants, self.runner.gate.reloading, self.bundle.staged), ([[(KEY, S)]], False, []))
            slow = runner.Held(self.world.workdir, 0)  # that check holds the first slot's checkout
            self.assertTrue(slow.take())
            self.assertEqual(self.tick(self.service), [])
            self.assertEqual(self.wants, [[(KEY, S)]] * 2)
            self.watcher.reloads(self.db, [MERGE])  # no successor beats yet: nothing is swapped
            self.assertEqual(self.pointers(), {})
            service, runner_ = self.successors(slots=2)
            for each in runner_.slots:
                each.held = runner.Held(self.world.workdir, runner_.slots.index(each))
            self.watcher.reloads(self.db, [MERGE])  # the look their first beat wakes: both beat, both pointers
            self.assertEqual(self.pointers(), {key: S for key in live_image.KEYS.values()})
            [swap] = self.said('platform.deploy.image_swap')
            self.assertEqual((swap['by'], swap['digest'], swap['head'], swap['swapped']), ('order', S, MERGE, True))
            self.assertLess(swap['landed_s'], 5.0)  # the landing to the pointers: the successors' boot, not a drain
            self.assertEqual([each['by'] for each in self.said(live_image.RELOAD, 'done')], ['successors'])
            self.assertEqual((self.watcher.reload, self.watcher.reloading(MERGE, time.time())), (None, None))
            self.clock.now += 1  # a look of the runner before its listener read the pointer: the bundle stays wanted
            self.assertEqual((self.take(self.runner), self.runner.gate.pointer, self.wants), (0, '', [[(KEY, S)]] * 2))
            self.heard()
            work = self.world.job('after-the-landing', 'true')  # a new run, the check of minutes still in flight
            self.assertEqual(len(self.tick(service)), 1)  # dispatched by the new code
            self.assertEqual(self.take(runner_, 0), 0)  # its first slot waits for the checkout the old run is in
            self.assertEqual(self.take(runner_, 1), 1)  # its second takes it at once, on the new code
            self.assertEqual((self.world.state(work), self.taken_by(work)), ('succeeded', [f"{heir('runner')}/1"]))
            self.assertEqual(self.proven(service, mock.Mock(slots=runner_.slots[1:])), 'succeeded')
            for process in (self.service, self.runner):
                self.standby(process)
                self.assertIsNone(self.standby(process))
            self.assertEqual((self.gave, self.bundle.execed, self.runner.gate.gone), ([S, S], [], True))
        slow.give()  # the check ended: the process that had the role has nothing in flight and leaves
        self.assertEqual((self.take(self.runner), self.take(runner_, 0)), (0, 0))
        status = self.port('GET', '/v1/deploy/status', 'torre')
        self.assertEqual(len(medir.from_deploy_status(status)['image_code_landing_s']), 1)  # one landing, by its swap

    def test_a_landing_while_every_slot_is_in_a_check_has_its_canary_run_at_once_by_the_successors_spare_loop(self):
        # CANARY-OWN-SLOT: the runner's two slots of this world are in checks of minutes when the landing swaps: the
        # capacity has no slot of theirs free and their checkouts are held by the process that had the role
        self.port('PUT', f'/v1/config/{canary.SLOT}', 'torre', {'value': 1, 'reason': 'test'})
        self.wanted()
        service, runner_ = self.successors(slots=3)  # the task's two slots and the loop more it keeps for the canary
        for each in runner_.slots:
            each.held = runner.Held(self.world.workdir, runner_.slots.index(each))
        self.db.rows("update work.capacity set in_use = slots where executor = 'script-runner'")
        checks = [runner.Held(self.world.workdir, n) for n in (0, 1)]
        self.assertEqual([each.take() for each in checks], [True, True])
        waits = self.world.job('a-check-that-waits', 'true')
        began = time.monotonic()
        self.assertTrue(self.swap()['swapped'])
        self.heard()
        # the service that took the role fires the swap's canary and its tick dispatches it, on the canary's own slot
        self.assertEqual(len(self.tick(service, later=0) or self.tick(service, later=0)), 1)
        self.assertEqual([self.take(runner_, n) for n in range(3)], [0, 0, 1])  # the spare loop: its checkout is free
        self.assertLess(time.monotonic() - began, 2.0)  # proven on the new code with no check ended (it waited for one)
        [(state, selector)] = self.db.rows("select state, selector->>'account' from work.job "
                                           "where idempotency_key like 'canary:swap:%%'")
        self.assertEqual((state, selector, self.world.state(waits)), ('succeeded', 'canary', 'queued'))
        self.assertEqual(self.db.rows("select account, in_use from work.capacity where executor = 'script-runner' "
                                      "order by account"), [('canary', '0'), ('fargate', '2')])
        live = {each['role']: each['task'] for each in self.said('platform.deploy.image_live')}
        self.assertEqual(live, {role: heir(role) for role in ('service', 'runner')})  # both roles worked on the bundle
        self.assertEqual(self.said(canary.WAITED), [])
        for each in checks:
            each.give()

    def test_a_want_withdrawn_right_after_the_swap_never_stops_the_successor_that_took_the_role(self):
        # PROMOTED-SUCCESSOR-STAYS: the landing swapped onto the successors; the want's sayer, woken by the landing's word,
        # lets the merged branch go and withdraws the bundle's want; the processes that had the role look at the wants
        # (that notification) before their listeners read the pointer, so the order's look does not stand aside
        self.wanted()
        service, runner_ = self.successors()
        self.assertTrue(self.swap()['swapped'])
        self.db.rows(queue_deploy.WANT, {'id': f'platform.deploy.successor:{S}:withdrawn:2', 'payload': json.dumps(
            {'digest': S, 'key': KEY, 'branch': None, 'state': 'withdrawn', 'why': 'units/a: its PR was merged'})})
        for process in (self.service, self.runner):
            process.gate.reads += 1  # the notification of the withdrawal: a look that reads the wants is owed
        self.assertEqual((self.service.gate.pointer, self.runner.gate.pointer), ('', ''))  # the swap not read yet
        self.look(self.service)
        self.take(self.runner)
        # before: both told their supervisor to hold none, and it stopped the successors that had just been promoted
        # (live 11/11 23:58 UTC: the handback emptied the pointers 8 s after a swap of 0.7 s, and the head was deployed
        # the slow way, with a rollout that lost three runs of the gate)
        self.assertEqual(self.wants, [[(KEY, S)]] * 2)
        self.heard()  # the listeners: the pointer names S; the role goes to the successors and they keep it
        self.assertEqual([each.gate.active() for each in (service, runner_, self.service, self.runner)], [True, True, False, False])
        self.assertEqual(self.proven(service, runner_), 'succeeded')
        self.assertEqual((self.wants, self.said('platform.deploy.image_retired')), ([[(KEY, S)]] * 2, []))

    def test_a_task_that_starts_later_holds_the_wanted_bundle_and_not_the_one_of_an_order_long_done(self):
        # STALE-ORDER-FREES-SLOT: a landing with no standby was swapped onto the successors its order started (done, by:
        # successors). Minutes later a rollout starts new tasks, on another code; a delivery in the train wants its bundle
        self.watcher.order(self.db, MERGE, S, KEY, PR_HEAD)
        self.heard()
        self.take(self.runner)
        self.tick(self.service)
        self.successors()
        self.watcher.reloads(self.db, [MERGE])
        self.assertEqual([each['by'] for each in self.said(live_image.RELOAD, 'done')], ['successors'])
        self.db.rows(f"update log.event set occurred_at = occurred_at - interval '{live_image.ORDER_LIMIT_S + 60} seconds' "
                     f"where type = '{live_image.RELOAD}'")  # the order is of minutes ago
        self.db.rows("update work.config_value set value = '\"\"'::jsonb where key like 'deploy.live_image_%%'")
        other, its = 'c' * 64, f"artifacts/lambda/tower-code/{'c' * 64}.zip"
        self.db.rows(queue_deploy.WANT, {'id': f'platform.deploy.successor:{other}:wanted:9', 'payload': json.dumps(
            {'digest': other, 'key': its, 'branch': 'units/b', 'state': 'wanted'})})
        self.wants.clear()
        late = self.process('runner')  # the task the rollout started: its first look
        late.gate.reads += 1
        self.take(late)
        self.assertEqual(self.wants, [[(its, other)]])  # before: [(KEY, S)], the old order's bundle, in its one slot

    def test_the_port_says_whether_a_landing_of_the_bundle_would_swap_now_by_the_successors_beats(self):
        # READY-BY-BEATS: what the delivery at the front asks before it lands: the landing statement's own evidence
        def ready():
            return self.port('GET', f'/v1/deploy/ready/{S}', 'torre')
        self.assertEqual((ready()['roles'], ready()['ready']), ([], False))
        self.wanted()
        self.successors()
        said = ready()
        self.assertEqual((said['digest'], said['roles'], said['ready'], said['fresh_s']), (S, ['runner', 'service'], True, 3.0))
        # READY-REHEARSAL: ready is said to the listeners too (tower_config, as a swap's write would): on real Postgres,
        # a session that listens hears it when both roles beat and nothing when one does not
        from infra_db.psql import PLACEHOLDER, literal
        asked = PLACEHOLDER.sub(lambda found: literal({'digest': S, 'fresh_s': 3.0}[found.group(1)]), service_port.READY_ROLES)
        heard = self.db.call(['-A', '-t', '-c', f'listen tower_config; {asked}'])
        self.assertIn('"tower_config" with payload "deploy.ready"', heard)
        # the runner's successor is gone (a rollout replaced its task): it said up and warm once, and beats no more
        self.db.rows("update work.standby_beat set beat_at = beat_at - interval '10 seconds' where role = 'runner'")
        self.assertEqual((ready()['roles'], ready()['ready']), (['service'], False))
        self.assertNotIn('tower_config', self.db.call(['-A', '-t', '-c', f'listen tower_config; {asked}']))

    def test_the_canary_red_stops_the_successor_and_the_previous_process_works_on(self):
        self.wanted()
        service, runner_ = self.successors()
        self.swap()
        self.heard()
        self.tick(service)  # its first work, and the swap's canary fired
        [(job,)] = self.db.rows("select id::text from work.job where idempotency_key like 'canary:swap:%%'")
        service_port.cancel_job(self.db, ('tenant', self.tenant), job)  # it ends and not succeeded: red
        with self.assertLogs('tower_infra.live_image', 'WARNING'):
            self.standby(self.service)  # the judge is the process on the previous code
        self.heard()
        self.assertEqual(self.pointers(), {key: '' for key in live_image.KEYS.values()})
        self.assertEqual([each.gate.active() for each in (service, runner_, self.service, self.runner)], [False, False, True, True])
        self.assertEqual([(each['by'], each['role']) for each in self.said('platform.deploy.image_retired')], [('canary', 'service')])
        work = self.world.job('after-the-red-canary', 'true')
        self.assertEqual(len(self.tick(self.service)), 1)  # the previous processes work on, on the code they had
        self.assertEqual(self.take(self.runner), 1)
        self.assertEqual((self.world.state(work), self.taken_by(work)), ('succeeded', ['ecs-runner']))
        # the bundle is refused: the want drops it, so the supervisors stop the successors; nobody gave any role away
        self.assertEqual((self.wants[:2], self.wants[2:], self.gave), ([[(KEY, S)]] * 2, [[], []], []))
        self.told.update(('service', 'runner'))  # and a successor is never the role's process by a stray word
        self.tick(service)
        self.assertEqual((service.gate.strict, service.gate.active(), self.bundle.execed), (True, False, []))


class TheSuccessorsWarmUp(unittest.TestCase):
    def test_a_successor_warms_only_the_checkout_its_task_does_not_keep_yet(self):
        # CANARY-OWN-SLOT: the task started with two slots; its successor has the loop more, whose checkout is not there
        from tower_infra import container
        with tempfile.TemporaryDirectory() as workdir:
            boxes = [container.Container(workdir, environ={}, slot=n) for n in range(3)]
            for box in boxes[:2]:
                (box.checkout_of({'repo': 'o/r'}) / '.git').mkdir(parents=True)
            warm = mock.Mock()
            warm.prewarm.return_value = (True, 1.5)
            environ = {'TOWER_PREWARM_REPO': 'o/r', 'TOWER_STANDBY': 'intask', 'TOWER_HEALTH_FILE': f'{workdir}/health'}
            with mock.patch.dict(os.environ, environ):
                self.assertEqual(service_main.prewarm(warm, boxes, None, 'heir'), 1.5)
                self.assertEqual(warm.prewarm.call_args.args[0], boxes[2:])  # the others are in the task's runs
                (boxes[2].checkout_of({'repo': 'o/r'}) / '.git').mkdir(parents=True)
                warm.prewarm.reset_mock()
                self.assertIsNone(service_main.prewarm(warm, boxes, None, 'heir'))  # the next successor: nothing to warm
                warm.prewarm.assert_not_called()


class Log(nostandby.Log):
    """RELOAD-WITHOUT-STANDBY's log with what WANTS answers: the datum as stored and the bundles the prewarm wants."""

    def __init__(self, limit=1, wants=()):
        super().__init__()
        self.limit, self.wants = limit, list(wants)
        self.held = []  # SUCCESSOR-HOLDS-SAID

    def rows(self, sql, params=None):
        if sql == getattr(live_image, 'HOLDS', None):  # SUCCESSOR-HOLDS-SAID: what the task said it holds
            self.held.append(json.loads(params['payload']))
            return []
        if sql == live_image.UP and json.loads(params['payload']).get('state') == 'failed':  # SUCCESSOR-GAVE-UP
            self.sent.append(sql)
            self.gave_up = getattr(self, 'gave_up', []) + [(params['id'], json.loads(params['payload']))]
            return []
        if sql != getattr(live_image, 'WANTS', None):
            return super().rows(sql, params)
        self.sent.append(sql)
        return [(None if self.limit is None else json.dumps(self.limit),
                 json.dumps([{'digest': digest, 'key': key} for key, digest in self.wants]))]


class TheTasksLookAtItsSuccessors(unittest.TestCase):
    def looked(self, log, role='runner', spool='/spool'):
        told = []
        with mock.patch.object(supervisor, 'supervised', return_value=spool), \
                mock.patch.object(supervisor, 'want', side_effect=lambda want: told.append(list(want))):
            task = nostandby.Task(log, role)
            went = [task.step() for _ in range(3)]
        return task, told, went

    def test_a_successor_the_supervisor_gave_up_on_is_said_in_the_log_once(self):
        # SUCCESSOR-GAVE-UP: a successor that ended four times was a line of the task's own log and of state.json, in a
        # task no session reads: a landing then found no successor beating and nothing said why
        log = Log(wants=[(KEY, S)])
        log.order = None
        with mock.patch.object(supervisor, 'supervised', return_value='/spool'), \
                mock.patch.object(supervisor, 'want', side_effect=lambda want: None), \
                mock.patch.object(supervisor, 'failed', side_effect=lambda: [S], create=True):
            task = nostandby.Task(log, 'service')
            for _ in range(3):
                task.gate.reads += 1  # a notification: a look is owed
                task.step()
        [(ident, said)] = log.gave_up
        self.assertEqual(ident, f'{live_image.SUCCESSOR}:service:{S}:{task.gate.task}:failed')
        self.assertEqual({name: said.get(name) for name in ('role', 'digest', 'task', 'state')},
                         {'role': 'service', 'digest': S, 'task': task.gate.task, 'state': 'failed'})
        self.assertIn('ended', said['why'])

    def test_the_bundles_given_up_on_are_read_from_the_supervisors_state(self):
        with tempfile.TemporaryDirectory() as spool:
            environ = {supervisor.DIR: spool}
            self.assertEqual(supervisor.failed(environ), [])  # no state yet
            (Path(spool) / supervisor.STATE).write_text(json.dumps({'children': [], 'failed': [S]}))
            self.assertEqual(supervisor.failed(environ), [S])
            (Path(spool) / supervisor.STATE).write_text('{half')
            self.assertEqual(supervisor.failed(environ), [])  # read between a write and its rename: asked again later
        self.assertEqual(supervisor.failed({}), [])  # a process no supervisor started

    def test_with_the_datum_off_or_no_supervisor_the_order_is_obeyed_by_exec_as_before(self):
        task, told, went = self.looked(Log(limit=0))  # the datum off
        self.assertEqual((told, went[0]['said']['state'], task.bundle.staged), ([[]], 'started', [(KEY, S)]))
        # DEFAULTS-AS-LIVE: no row is the default, which is on (the engine as it runs): the successor is told the order's bundle
        task, told, went = self.looked(Log(limit=None))
        self.assertEqual(told, [[(KEY, S)]])
        log = Log()
        task, told, went = self.looked(log, spool=None)  # a process no supervisor started: nothing is read, nothing told
        self.assertEqual((told, went[0]['said']['state'], live_image.WANTS in log.sent), ([], 'started', False))

    def test_the_wants_are_told_when_they_change_newest_first_within_the_datum_and_never_the_code_it_runs(self):
        log = Log(wants=[('k-t', T), ('k-ecs', ECS)])
        log.order = None
        task, told, went = self.looked(log)
        self.assertEqual((told, went), ([[('k-t', T)]], [None] * 3))  # told once; the same set is not said again
        log = Log()  # an order that is open comes first: its landing is waiting
        log.wants = [('k-t', T)]
        task, told, went = self.looked(log)
        self.assertEqual((told, went, task.bundle.staged, task.gate.reloading), ([[(KEY, S)]], [None] * 3, [], False))

    def test_a_supervisor_that_cannot_be_told_never_stops_the_order(self):
        log = Log()
        with mock.patch.object(supervisor, 'supervised', return_value='/spool'), \
                mock.patch.object(supervisor, 'want', side_effect=OSError('no spool')), \
                self.assertLogs('tower_infra.live_image', 'ERROR'):
            task = nostandby.Task(log, 'runner')
            self.assertEqual(task.step()['said']['state'], 'started')  # followed the old way: staged, claimed, exec

    def test_a_promoted_successor_is_not_the_sole_service_until_it_adopted_the_role(self):
        table = failover.Table(S)
        gate = live_image.Gate(table.scope, 'service', S, strict=True, intask=True, clock=table.clock)
        spot = live_image.Gate(table.scope, 'service', S, strict=True, clock=table.clock)
        self.assertEqual((gate.active(), gate.sole(), spot.sole()), (True, False, True))  # the prewarm's duties: one service
        gate.strict = False  # adopted, the pointer still to hand over: as a reloaded ECS task, sharing
        self.assertFalse(gate.sole())
        table.value = ''
        gate.refresh()
        self.assertTrue(gate.sole())

    def test_a_promoted_standby_asks_the_pointer_before_it_runs_the_duties_of_the_sole_service(self):
        # PREWARM-ONE-PAIR: live 11/11 (#529's landing): the adopted successor handed the pointer over, and that statement's
        # notification woke the prewarm's look in the Spot standby too, before its listener had read the pointer: both
        # were the sole service for an instant and each started a pair for the next branch (four Spot tasks, not two)
        table = failover.Table(S)
        spot = live_image.Gate(table.scope, 'service', S, strict=True, clock=table.clock)
        self.assertTrue(spot.sole())
        table.value = ''  # the handover's write; the standby's listener has not run yet
        self.assertEqual((spot.live, spot.sole()), (True, False))  # it asked the pointer itself
        self.assertEqual((spot.live, spot.active()), (False, False))  # and stands by from that read on
        ecs = live_image.Gate(table.scope, 'service', S, clock=table.clock)  # not strict: live with no pointer
        reads = ecs.reads
        self.assertTrue(ecs.sole())
        self.assertEqual(ecs.reads, reads + 1)  # only its first read: an ECS task's look costs no statement more
        self.assertTrue(ecs.sole())
        self.assertEqual(ecs.reads, reads + 1)

    def test_an_order_swapped_onto_the_successors_keeps_them_wanted_whatever_pointer_the_look_has_read(self):
        # the look swapped and said the order done; this task's listener has not read the pointer yet (its gate still
        # says none): a look now must not drop the bundle, or the supervisor would stop the successor that has the role
        log = Log()
        log.told = [{'state': 'done', 'digest': S, 'head': nostandby.MERGE, 'order': nostandby.MERGE, 'by': 'successors', 'at': 99.0}]
        task, told, went = self.looked(log)
        self.assertEqual((told, went, task.gate.pointer, task.bundle.staged), ([[(KEY, S)]], [None] * 3, '', []))
        log.refused = True  # its canary red: the bundle is dropped, the successor stopped
        task.gate.refresh()
        with mock.patch.object(supervisor, 'supervised', return_value='/spool'), \
                mock.patch.object(supervisor, 'want', side_effect=lambda want: told.append(list(want))):
            task.step()
        self.assertEqual(told[1:], [[]])
        log = Log()  # an order the tasks ended by exec (done, by the look's ORDER_DONE) is nobody's to hold
        log.told = [{'state': 'done', 'digest': S, 'head': nostandby.MERGE, 'order': nostandby.MERGE, 'at': 99.0}]
        self.assertEqual(self.looked(log)[1], [[]])

    def test_an_order_a_task_obeys_by_exec_or_one_past_its_limit_is_not_for_the_successors(self):
        log = Log()
        log.told = [{'role': 'runner', 'digest': S, 'task': 'ecs-runner-2', 'state': 'started', 'order': nostandby.MERGE, 'at': 99.0}]
        task, told, went = self.looked(log, 'service')
        self.assertEqual(told, [[]])  # a task with no supervisor reloads by exec: every task follows the order that way
        log = Log()
        log.age = live_image.ORDER_LIMIT_S + 1
        self.assertEqual(self.looked(log)[1], [[]])


class TheParts(unittest.TestCase):
    def test_a_successor_has_its_own_name_and_leaves_at_once_on_sigterm(self):
        environ = {'TOWER_STANDBY': 'intask', 'TOWER_IMAGE_DIGEST': S}
        self.assertEqual((live_image.named('host', environ), live_image.named('host', {'TOWER_STANDBY': '1', 'TOWER_IMAGE_DIGEST': S}),
                          live_image.heir_of(f'host:{T[:12]}', S)), (f'host:{S[:12]}', 'host', f'host:{S[:12]}'))
        table = failover.Table()
        gate = live_image.Gate(table.scope, 'service', S, strict=True, intask=True, clock=table.clock)
        gate.refresh()
        stopped = __import__('threading').Event()
        live_image.on_term(gate, table.scope, stopped.set)()
        self.assertTrue(stopped.wait(5))  # no grace (SPOT-STANDBY-GONE: nor any standby's now)

    def test_the_supervisors_signal_is_heard_from_the_start_of_a_successor_only(self):
        with mock.patch.object(live_image.signal, 'signal') as installed, mock.patch.object(live_image, 'TOLD', []):
            self.assertFalse(live_image.heed({'TOWER_STANDBY': '1'}))
            installed.assert_not_called()
            self.assertTrue(live_image.heed({'TOWER_STANDBY': 'intask'}))
            signum, handler = installed.call_args[0]
            handler(signum, None)
            self.assertEqual((signum, live_image.TOLD), (signal.SIGUSR1, [True]))
            self.assertTrue(live_image.Gate(None, 'runner', S).told_adopt())

    def test_a_slot_that_waits_for_its_checkout_keeps_the_roles_live_beat(self):
        # PROMOTED-RUNNER-WAITS-ALIVE: with every slot waiting for a checkout no TAKE sent the live beat, and the ECS task's
        # watchdog took the swap back when its own first slot freed (58 s, live 11/11)
        gate, beats, took = mock.Mock(), [], []
        gate.active.return_value = True
        gate.live_beat.side_effect = lambda db: beats.append(db)
        held = mock.Mock()
        held.take.return_value = False
        stop = threading.Event()
        slot = runner.Runner('db', None, None, None, '/work', name='slot', gate=gate, held=held,
                             beat=lambda: stop.set(), wait=lambda seconds: None)
        slot.once = lambda: took.append(1)
        with mock.patch.object(live_image, 'engaged') as engaged:
            engaged.return_value.__enter__.return_value = True
            slot.loop(stop, 0.01)
        self.assertEqual((took, beats, held.give.call_count), ([], ['db'], 0))  # nothing taken; alive; no lock to give back

    def test_a_slots_checkout_is_one_process_at_a_time(self):
        with tempfile.TemporaryDirectory() as workdir:
            mine, other = runner.Held(workdir, 1), runner.Held(workdir, 1)
            self.assertEqual((mine.take(), other.take(), runner.Held(workdir, 0).take()), (True, False, True))
            mine.give()
            self.assertTrue(other.take())
        with self.assertLogs('tower_infra.runner', 'ERROR'):  # a disk that cannot lock never stops the runner
            broken = runner.Held('/proc/nowhere', 0)
            self.assertEqual((broken.take(), broken.take(), broken.give()), (True, True, None))

    def test_a_process_that_gave_its_role_away_waits_for_what_it_has_in_flight(self):
        clock = failover.Clock()
        gate = live_image.Gate(None, 'service', ECS, clock=clock)
        pending, waits = ['workflow-1'], []

        def wait(seconds):
            waits.append(seconds)
            clock.now += seconds
            if len(waits) == 3:
                del pending[:]
        self.assertEqual((live_image.finish(gate, lambda: pending, wait=wait), len(waits)), ([], 3))
        pending.append('stuck')  # DRAIN_S at most, as a reload waited
        self.assertEqual(live_image.finish(gate, lambda: pending, wait=wait), ['stuck'])
        self.assertLessEqual(clock.now, 100 + 2 + live_image.DRAIN_S + 1)

    def test_the_measure_counts_a_landing_swapped_by_its_order_once(self):
        status = {'image_swap': [
            {'head': 'h1', 'swapped': True, 'by': 'order', 'digest': S, 'landed_s': 6.5,
             'versions': {'deploy.live_image_runner': 3, 'deploy.live_image_service': 3}},
            {'head': 'h1', 'swapped': False, 'why': 'no healthy runner or service standby'},
            {'head': 'h0', 'swapped': False, 'why': 'the base moved'}],
            'image_live': [{'role': role, 'digest': S, 'version': 3, 'swap_s': 0.25} for role in ('runner', 'service')]}
        self.assertEqual(medir.image_code_landing(status), [6.75, medir.SLOW_S])

    def test_the_measure_counts_the_landings_since_a_point_so_a_change_is_judged_by_its_own_landings(self):
        """MEDIR-LANDINGS-SINCE: the goal is a p99 over N >= 10 landings, and a change that should move it (12/11 05:46
        UTC: the database's shared_buffers) is judged by the landings after it. The measure read the status's newest
        20 whatever --since said, so the ten after a change were mixed with those before. With a point, only the
        landings recorded from it on count (the status says when each was: STATUS-EVENTS-AT); one with no time is left
        out, never guessed."""
        live = [{'role': role, 'digest': S, 'version': version, 'swap_s': swap_s}
                for version, swap_s in ((3, 1.25), (4, 0.25), (5, 0.125)) for role in ('runner', 'service')]
        swaps = [{'head': f'h{version}', 'swapped': True, 'by': 'landing', 'digest': S, 'landed_s': 0.0, 'at': at,
                  'versions': {'deploy.live_image_runner': version, 'deploy.live_image_service': version}}
                 for version, at in ((5, 3000.5), (4, 2000.0), (3, 1000.0))]
        swaps.append({'head': 'h2', 'swapped': False, 'why': 'the base moved'})  # before STATUS-EVENTS-AT: no time
        status = {'image_swap': swaps, 'image_live': live}
        self.assertEqual(medir.image_code_landing(status), [0.125, 0.25, 1.25, medir.SLOW_S])
        self.assertEqual(medir.image_code_landing(status, since=2000.0), [0.125, 0.25])
        self.assertEqual(medir.from_deploy_status(status, since=2000.0)['image_code_landing_s'], [0.125, 0.25])
        self.assertNotIn('image_code_landing_s', medir.from_deploy_status(status, since=4000.0))


if __name__ == '__main__':
    unittest.main()
