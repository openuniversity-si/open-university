"""LOOKS-AFTER-WORK (docs/operations/aws.md 22.9): a process the role waits for (the reserve told to go at a drill, a
process started under a pointer that names it) makes the autodeploy's look, and their AWS clients,
in the looks' own threads once its first work is recorded (FIRST_WORK_S at most), not before its loop's first pass;
any other process makes them where it always did. The looks already waited for that first work to look (after_work).
"""
import os
from pathlib import Path
import sys
import threading
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'infra' / 'service'))
from tower_infra import autodeploy, live_image  # noqa: E402

ENV = {'TOWER_DOORBELL_FUNCTION': 'tower-doorbell', 'TOWER_STANDBY_CLUSTER': 'tower', 'TOWER_STANDBY_SUBNETS': 's-1',
       'TOWER_STANDBY_SECURITY_GROUPS': 'g-1', 'TOWER_ARTIFACT_BUCKET': 'b'}


class Gate:
    def __init__(self, boot):
        self.boot, self.worked = boot, threading.Event()

    def engaged(self, name):
        import contextlib
        return contextlib.nullcontext(True)


class Watcher:
    doorbell = 'tower-doorbell'

    def __init__(self, stop):
        self.stop, self.config, self.looks = stop, None, 0

    def safety_s(self):
        return 0

    def step(self, force=False):
        self.looks += 1
        self.stop.set()

    def cap(self):
        return 1

    def forget(self):
        pass


class Made:
    def __init__(self, stop):
        self.stop, self.calls, self.made = stop, [], threading.Event()

    def __call__(self):
        self.calls.append(threading.current_thread().name)
        self.made.set()
        return Watcher(self.stop)


class TheLooksOfAProcessTheRoleWaitsFor(unittest.TestCase):
    def started(self, module, gate):
        stop, make = threading.Event(), None
        make = Made(stop)
        with mock.patch.dict(os.environ, ENV):
            thread = module.start(None, stop, wait=lambda _: None, gate=gate, make=make)
        return thread, make, stop

    def test_are_made_in_their_threads_after_its_first_work(self):
        for module in (autodeploy,):  # GATE-LOOKS-GONE: the prewarm's look left
            gate = Gate(boot={'boot_s': 0.1})
            thread, make, stop = self.started(module, gate)
            self.assertIsNotNone(thread)
            self.assertFalse(make.made.wait(0.2), module.__name__)  # nothing made before the role's first work
            gate.worked.set()
            self.assertTrue(make.made.wait(5), module.__name__)
            thread.join(5)
            self.assertEqual(make.calls, [module.__name__.rsplit('.', 1)[-1]])  # in the look's own thread
            stop.set()

    def test_of_any_other_process_are_made_before_it_goes_on_as_always(self):
        for module in (autodeploy,):
            for gate in (Gate(boot={}), None):
                thread, make, stop = self.started(module, gate)
                self.assertEqual(make.calls, ['MainThread'], module.__name__)
                stop.set()
                thread.join(5)

    def test_who_the_role_waits_for(self):
        self.assertIs(live_image.waited_for(None), False)
        self.assertIs(live_image.waited_for(Gate(boot={})), False)
        self.assertIs(live_image.waited_for(Gate(boot={'boot_s': 0.2})), True)


if __name__ == '__main__':
    unittest.main()
