"""The merge train (TRAIN-FRONT-FIRST): the front of the queue lands first and nobody overtakes it. Hermetic: a fake port
that keeps the queue as the real one does, whose `wait` runs a scripted event (the front landing or leaving) in place of
a clock, a fake git and a fake gate_infra.land that calls the train's hook where the judge would."""
from pathlib import Path
import subprocess
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import config  # noqa: E402
import deliver  # noqa: E402
import gate_infra  # noqa: E402
import merge_train as train  # noqa: E402

BASE = 'mod/roadmap-integration'
OLD, NEW = '1' * 40, '2' * 40


class FakeTrainPort:
    """/v1/train/* in memory. wait() answers the state; while the pr is not the front it first plays the next scripted
    event (what the real port's LISTEN would deliver), and never sleeps."""

    def __init__(self, events=()):
        self.queue, self.log, self.events = [], [], list(events)
        self.now, self.renewals = 0, []  # TRAIN-LEASE: a clock only the test moves, and who renewed
        self.heads = []  # TRAIN-HEAD-FOLLOWS: (pr, head) of each entry that said a new head
        self.waits = 0  # FRONT-AT-ONCE: the long polls asked

    def expire(self):
        """What the real port does when a join, wait, renew or end arrives: the entries whose lease ran out leave."""
        for entry in [e for e in self.queue if e['lease'] < self.now]:
            self.queue.remove(entry)
            self.log.append(f"expired {entry['pr']}")

    def renew(self, body):
        for entry in self.queue:
            if entry['pr'] == body['pr']:
                entry['lease'] = self.now + body.get('lease_s', 900)
                self.renewals.append(body['pr'])

    def call(self, method, path, body=None):
        body = body or {}
        if path != '/v1/train':
            self.expire()
        if path == '/v1/train/join':
            if not any(e['pr'] == body['pr'] for e in self.queue):
                self.queue.append({'pr': body['pr'], 'head': body['head'], 'files': body['files'],
                                   'lease': self.now + body.get('lease_s', 900)})
                self.log.append(f"join {body['pr']}")
            else:  # the port's upsert: an open entry keeps its place and takes the new head, files and lease
                entry = next(e for e in self.queue if e['pr'] == body['pr'])
                entry.update(head=body['head'], files=body['files'], lease=self.now + body.get('lease_s', 900))
                self.heads.append((body['pr'], body['head']))
            return self.state()
        if path == '/v1/train/renew':
            self.renew(body)
            gone = not any(e['pr'] == body['pr'] for e in self.queue)
            return dict(self.state(), state='gone' if gone else 'front' if self.queue[0]['pr'] == body['pr'] else 'queued')
        if path == '/v1/train/end':
            self.queue = [e for e in self.queue if e['pr'] != body['pr']]
            self.log.append(f"{body['ended']} {body['pr']}")
            return self.state()
        if path == '/v1/train/wait':
            self.waits += 1
            self.renew(body)  # the long poll is the waiting delivery's own event
            state = self.state()
            if not any(e['pr'] == body['pr'] for e in self.queue):
                return dict(state, state='gone')
            if self.queue[0]['pr'] != body['pr'] and self.events:
                self.log.append(f"wait {body['pr']}")
                self.events.pop(0)(self)
                self.expire()
                state = self.state()
            where = [e['pr'] for e in self.queue]
            return dict(state, state='front' if where[0] == body['pr'] else 'queued')
        if path == '/v1/train':
            return {'queues': {BASE: self.state()['entries']}}
        raise AssertionError(path)

    def state(self):
        return {'base': BASE, 'entries': [dict(e, position=i) for i, e in enumerate(self.queue)]}


def lands(port, pr='410', moves_base=True):
    """The event: the front delivery landed (or left) and, when it landed, the base moved."""
    def event(fake):
        fake.call('POST', '/v1/train/end', {'base': BASE, 'pr': pr, 'ended': 'landed' if moves_base else 'left'})
    return event


class Git:
    """The git of one delivery: rev-parse of the base reads `tip`; diffs answer the scripted file lists."""

    def __init__(self, port, changed, own):
        self.port, self.changed, self.own, self.tip = port, changed, own, OLD
        self.calls = []

    def __call__(self, argv, cwd=None, **_options):
        self.calls.append(' '.join(argv))
        line = ' '.join(argv)
        if argv[:2] == ['git', 'rev-parse']:
            out = self.tip
        elif argv[:2] == ['git', 'ls-remote'] and getattr(self, 'remote', False):  # BASE-TIP-BY-LS-REMOTE
            out = f'{self.tip}\trefs/heads/{BASE}'
        elif argv[:3] == ['git', 'diff', '--name-only']:
            out = '\n'.join(self.own if '...' in line else self.changed)
        else:
            out = ''
        return subprocess.CompletedProcess(argv, 0, out, '')


class CrashRed(unittest.TestCase):
    def test_a_delivery_whose_code_does_not_start_a_role_leaves_the_train_and_merges_nothing(self):
        # SUCCESSOR-CRASH-RED: #715 landed code its service's successor crashed on at its start (ValueError, ended more
        # than 3 times); the swap was refused and the base held code the next slow deploy would have started the engine on
        import deliver

        class Entry:
            gave_up, ended = ['service'], []

            def end(self, how, why=None):
                self.ended.append((how, why))
        entry = Entry()
        with self.assertRaises(train.Left) as refused:
            deliver.crashed(entry, '715')
        self.assertIn('does not start the service', str(refused.exception))
        self.assertEqual(entry.ended, [('left', 'the successor of service on its code gave up at its start')])
        entry.gave_up, entry.ended = [], []
        self.assertIsNone(deliver.crashed(entry, '716'))  # warm, or none wanted: it lands as before
        self.assertIsNone(deliver.crashed(None, '716'))  # no train
        self.assertEqual(entry.ended, [])

    def test_the_front_hook_asks_it_once_the_successors_were_read(self):
        source = (Path(__file__).resolve().parent.parent / 'lib' / 'deliver.py').read_text(encoding='utf-8')
        hook = source[source.index('def _front_gate('):source.index('def crashed(')]
        self.assertEqual(hook.count('readied.join()\n'), 2)
        self.assertEqual(hook.count('crashed(tr, pr)'), 2)  # after each join: the base still or the base moved elsewhere


class TrainTests(unittest.TestCase):
    def setUp(self):
        self.lines, self.landings = [], []
        self.rebased, self.fronts = [], []

    def deliver(self, port, git, pr='411', judged_red=False):
        """_judge_on_infra for `pr` with the fake port and a fake land whose judge calls the train's hook."""
        def land(number, head, base, ref, base_ref, root=None, port=None, front=None, **_options):
            self.landings.append((number, base))
            self.fronts.append(front(not judged_red, ['stage:lint'] if judged_red else [], 1.0))
            if judged_red:
                return {'verdict': 'red', 'red': ['stage:lint'], 'landing': {}, 'seconds': 1.0}, None
            return {'verdict': 'green', 'red': [], 'seconds': 1.0, 'checks': 5, 'from_cache': 3 if len(self.landings) > 1 else 0,
                    'landing': {'result': {'merge_sha': 'm' * 40}}}, None

        def with_base(tree, branch, head, remote, base, run, out, port=None):
            self.rebased.append(head)
            return 'r' * 40, 0
        with mock.patch.object(deliver, 'train_port', lambda: port), \
                mock.patch.object(gate_infra, 'land', land), \
                mock.patch.object(deliver, '_with_base', with_base), \
                mock.patch.object(deliver, '_refreshed', lambda *a, **k: 0):
            return deliver._judge_on_infra(int(pr), Path('/home'), Path('/tree'), 'units/x', 'h' * 40, 'origin', BASE,
                                           git, self.lines.append, own_tree=True)

    def test_two_prs_the_second_lands_only_after_the_first(self):
        port = FakeTrainPort([lands(None)])
        port.call('POST', '/v1/train/join', {'base': BASE, 'pr': '410', 'head': 'a' * 40, 'files': ['docs/a.md']})
        git = Git(port, changed=['docs/a.md'], own=['scripts/b.py'])  # the front touched something else
        port.events[0] = lambda fake: (lands(None)(fake), setattr(git, 'tip', NEW))
        self.assertEqual(self.deliver(port, git), 0)
        self.assertEqual(port.log, ['join 410', 'join 411', 'wait 411', 'landed 410', 'landed 411'])
        self.assertEqual(len(self.landings), 1)  # the verdict stood: no second judgment
        self.assertEqual(len(self.rebased), 1)  # only the merge the delivery starts with

    def test_a_base_that_did_not_move_is_read_by_ls_remote_with_no_fetch_and_the_front_says_its_parts(self):
        # BASE-TIP-BY-LS-REMOTE, LANDING-PARTS: the fetch of the base was 2 to 2.5 s of the front's seconds
        port = FakeTrainPort()
        git = Git(port, changed=[], own=['scripts/b.py'])
        git.remote = True
        self.assertEqual(self.deliver(port, git), 0)
        self.assertFalse([call for call in git.calls if call.startswith('git fetch')])
        self.assertTrue(any(call.startswith('git ls-remote origin refs/heads/') for call in git.calls))
        self.assertTrue(any(line.startswith('deliver: #411 at the front: renew ') for line in self.lines), self.lines)

    def test_an_entry_the_renewal_says_is_the_front_asks_no_long_poll_and_one_behind_does(self):
        # FRONT-AT-ONCE (critério 3): the front's long poll took 0.7 to 4.4 s of every landing with no one ahead (#659 to
        # #665); the renewal that comes first already reads the train's state
        port = FakeTrainPort()
        self.assertEqual(self.deliver(port, Git(port, changed=[], own=['scripts/b.py'])), 0)
        self.assertEqual(port.waits, 0)
        port = FakeTrainPort([lands(None, moves_base=False)])
        port.call('POST', '/v1/train/join', {'base': BASE, 'pr': '410', 'head': 'a' * 40, 'files': ['x']})
        self.assertEqual(self.deliver(port, Git(port, changed=[], own=['scripts/b.py'])), 0)
        self.assertEqual(port.waits, 1)  # 410 ahead: it waits for the front as before

    def test_the_successors_readiness_is_read_beside_the_bases_tip_not_after_it(self):
        # READY-BESIDE-BASE (critério 3): the front read the base's tip (ls-remote, 0.4 to 0.6 s) and then the successors'
        # readiness (GET /v1/deploy/status, 134 KB, 0.3 to 0.5 s, 0.5 to 1.0 s with its beats), one after the other; they
        # do not depend on each other. Here the ls-remote waits for the readiness to have begun: one after the other, it
        # never sees it
        import threading
        port = FakeTrainPort()
        git = Git(port, changed=[], own=['scripts/b.py'])
        git.remote = True
        began, seen = threading.Event(), []
        real = git.__call__

        def run(argv, cwd=None, **options):
            if argv[:2] == ['git', 'ls-remote']:
                seen.append(began.wait(2))
            return real(argv, cwd, **options)

        def ready(train, branch, wait_s, poll_s, **_options):
            began.set()
            return None
        with mock.patch.object(train.Train, 'ready', ready):
            self.assertEqual(self.deliver(port, run), 0)
        self.assertEqual(seen, [True])
        self.assertTrue(any(line.startswith('deliver: #411 at the front: renew ') for line in self.lines), self.lines)

    def test_a_red_front_leaves_and_the_second_proceeds(self):
        port = FakeTrainPort([lands(None, moves_base=False)])
        port.call('POST', '/v1/train/join', {'base': BASE, 'pr': '410', 'head': 'a' * 40, 'files': ['x']})
        self.assertEqual(self.deliver(port, Git(port, changed=[], own=['scripts/b.py'])), 0)
        self.assertEqual(port.log, ['join 410', 'join 411', 'wait 411', 'left 410', 'landed 411'])
        self.assertEqual(len(self.landings), 1)

    def test_unrelated_files_in_the_front_mean_no_new_merge_and_no_new_judgment(self):
        port = FakeTrainPort()
        port.call('POST', '/v1/train/join', {'base': BASE, 'pr': '410', 'head': 'a' * 40, 'files': ['docs/a.md']})
        git = Git(port, changed=['docs/a.md'], own=['scripts/b.py'])
        port.events.append(lambda fake: (lands(None)(fake), setattr(git, 'tip', NEW)))
        self.assertEqual(self.deliver(port, git), 0)
        self.assertEqual((len(self.rebased), len(self.landings)), (1, 1))
        self.assertTrue(any('its verdict stands' in line for line in self.lines))
        self.assertEqual(self.fronts, [NEW])  # BASE-MOVED-SWAP: the hook says the base the merge will have as its parent

    def test_a_base_that_did_not_move_says_no_other_base(self):
        port = FakeTrainPort()
        self.assertEqual(self.deliver(port, Git(port, changed=[], own=['scripts/b.py'])), 0)
        self.assertEqual(self.fronts, [None])

    def test_a_front_that_changed_the_code_bundle_makes_a_code_only_entry_merge_and_be_judged_again(self):
        # BASE-MOVED-SWAP: its head's bundle would not be the merge's, and the landing would wait for the slow path
        port = FakeTrainPort()
        port.call('POST', '/v1/train/join', {'base': BASE, 'pr': '410', 'head': 'a' * 40,
                                             'files': ['infra/service/tower_infra/a.py']})
        git = Git(port, changed=['infra/service/tower_infra/a.py'], own=['infra/service/tower_infra/b.py', 'docs/c.md'])
        port.events.append(lambda fake: (lands(None)(fake), setattr(git, 'tip', NEW)))
        self.assertEqual(self.deliver(port, git), 0)
        self.assertEqual((len(self.rebased), len(self.landings)), (2, 2))
        self.assertEqual(port.log[-1], 'landed 411')
        self.assertTrue(any("the base changed the code bundle's inputs" in line for line in self.lines))

    def test_only_a_code_only_entry_is_reached_by_the_bundles_inputs(self):
        code, other = 'infra/service/tower_infra/a.py', 'infra/service/tower_infra/b.py'
        for changed in ([code], ['infra/db/migrations/0099.sql'], ['infra/service/requirements.txt']):
            self.assertIn('code bundle', train.stale(changed, [other, 'docs/x.md']))
        self.assertIsNone(train.stale([code], ['docs/x.md']))  # nothing to swap: no bundle of its own
        self.assertIsNone(train.stale([code], [other, 'infra/aws/stacks/30-service.json']))  # the slow path either way
        self.assertIsNone(train.stale(['docs/a.md', 'infra/service/Dockerfile'], [other]))  # not an input of the bundle

    def test_the_landing_is_announced_against_the_base_the_front_saw(self):
        # BASE-MOVED-SWAP: live 10/11 (204cea22), the base moved elsewhere while #N was judged; its verdict stood, the merge's
        # parent was the new tip, the event said the old base and the port refused the swap: a code-only landing on the slow path
        said = []

        def judge(port, spec, plan, trees, day, shadow=False, metadata=None, before_landing=None, retry=False, progress=None):
            before_landing(True, [], 1.0)
            return {'verdict': 'green', 'landing': {'state': 'succeeded', 'result': {'merge_sha': 'm' * 40}}}
        for moved_to, expected in ((NEW, NEW), (None, OLD)):
            with mock.patch.object(gate_infra, 'judge', judge), mock.patch.object(gate_infra, 'plan_of', lambda *a: {}), \
                    mock.patch.object(gate_infra, 'git', lambda *a: 't'), mock.patch.object(gate_infra, 'kept', lambda j: None), \
                    mock.patch.object(gate_infra, 'announce_landed', lambda port, root, pr, head, base, judged: said.append(base)), \
                    mock.patch('gate_status.check_hooks', lambda *a, **k: None):
                gate_infra.land(411, 'h' * 40, OLD, 'units/x', BASE, root=Path('/tree'), port=object(),
                                front=lambda ok, red, seconds, tip=moved_to: tip)
            self.assertEqual(said.pop(), expected)

    def test_related_files_make_the_next_entry_merge_and_be_judged_again_from_the_front(self):
        port = FakeTrainPort()
        port.call('POST', '/v1/train/join', {'base': BASE, 'pr': '410', 'head': 'a' * 40, 'files': ['scripts/b.py']})
        git = Git(port, changed=['scripts/b.py'], own=['scripts/b.py', 'docs/c.md'])
        port.events.append(lambda fake: (lands(None)(fake), setattr(git, 'tip', NEW)))
        self.assertEqual(self.deliver(port, git), 0)
        self.assertEqual((len(self.rebased), len(self.landings)), (2, 2))
        self.assertEqual(port.log[-1], 'landed 411')
        self.assertTrue(any('changed files this PR also changes' in line for line in self.lines))
        # TRAIN-HEAD-FOLLOWS: the entry says the head it merged the base into. Live 11/11 (#530): the train kept the head
        # of before the merge, the prewarm asked the train for the new one (PREWARM-TRAIN-SLOT), was told no, and gave
        # #530's slot to a later push three minutes before it landed: no standby, no swap
        self.assertEqual(port.heads, [('411', 'r' * 40)])
        self.assertEqual(port.log.count('join 411'), 1)  # it kept its place: one entry, not a new one at the end
        self.assertEqual(sum('joined the' in line for line in self.lines), 1)  # and says so once

    def test_the_front_waits_for_its_branchs_successors_to_be_warm_before_it_lands(self):
        # READY-BEFORE-LANDING: live 11/11 (#539): the front landed 6 to 10 s after its successors started and the swap
        # took 1.25 s. The landing is the delivery's to time: it waits for both roles' {state: warm}
        S, OTHER = 'a' * 64, 'b' * 64

        class Status:
            def __init__(self, *answers):
                self.answers, self.asked = list(answers), 0

            beats = None  # READY-BY-BEATS: the roles that beat now; None: a port with no such route

            def call(self, method, path, body=None):
                if path == f'/v1/deploy/ready/{S}':
                    if self.beats is None:
                        raise OSError('404: no route')
                    return {'digest': S, 'roles': self.beats.pop(0) if len(self.beats) > 1 else self.beats[0]}
                assert (method, path) == ('GET', '/v1/deploy/status')
                self.asked += 1
                found = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
                if isinstance(found, Exception):
                    raise found
                return {'successor': found}
        want = {'state': 'wanted', 'digest': S, 'branch': 'units/x'}
        up = [{'state': 'up', 'role': role, 'digest': S} for role in ('service', 'runner')]
        warm = [{'state': 'warm', 'role': role, 'digest': S} for role in ('service', 'runner')]
        clock, slept, lines = [0.0], [], []

        def sleep(seconds):
            slept.append(seconds)
            clock[0] += seconds

        def waited(port, branch='units/x', wait_s=60):
            del slept[:], lines[:]
            tr = train.Train(port, BASE, '411', 'h' * 40, out=lines.append)
            return tr.ready(branch, wait_s, 2, sleep=sleep, clock=lambda: clock[0])
        port = Status(up + [want], [warm[0]] + up + [want], warm[::-1] + up + [want])
        self.assertEqual((waited(port), slept, port.asked), (4.0, [2, 2], 3))  # up is not warm; one role is not both
        self.assertEqual(lines, ['deliver: #411 waited 4 s at the front for its successors to be warm'])
        self.assertEqual((waited(Status(warm + up + [want])), slept, lines), (0.0, [], []))  # the usual case: no wait, no line
        late = Status([warm[0]] + up + [want])
        self.assertEqual((waited(late, wait_s=6), slept), (6.0, [2, 2, 2]))  # bounded: it lands as it is
        self.assertEqual(lines, ['deliver: #411 lands though its successors are not warm after 6 s (warm: service)'])
        for nothing in (Status([]), Status([{'state': 'wanted', 'digest': OTHER, 'branch': 'units/y'}]),  # no want of this branch
                        Status([{'state': 'withdrawn', 'digest': S}, want]),  # withdrawn since: none will come
                        Status(OSError('the port is away'))):  # fail open
            self.assertEqual((waited(nothing), slept), (None, []))
        self.assertEqual((waited(Status(up + [want]), wait_s=0), waited(Status(up + [want]), branch=None)), (None, None))
        # WARM-PER-PROCESS: the runner's successor started again (it says `up` anew, newest first): its first process's
        # `warm` no longer stands for it; the delivery waits until the new process says its own
        again = Status([up[1]] + warm + up + [want], [warm[1], up[1]] + warm + up + [want])
        self.assertEqual((waited(again), slept), (2.0, [2]))  # before: 0.0, onto a successor that was not warm yet
        # FRONT-WAITS-RUNNER-BACK: live 12/11 01:20 UTC: Spot took the runner's task; the next one was up, warm and holding
        # its successor three minutes later. A delivery at the front in that window waits for it (the default is past it)
        back = Status([warm[0], up[0], want], [warm[0], up[0], want], warm + up + [want])
        self.assertEqual((waited(back, wait_s=config.get('delivery.successor_wait_s')), slept), (4.0, [2, 2]))
        self.assertGreaterEqual(config.get('delivery.successor_wait_s'), 200)  # 01:20:37 to 01:23:34 UTC, with room
        failed = {'state': 'failed', 'role': 'runner', 'digest': S}  # SUCCESSOR-GAVE-UP: it will not come: no wait
        self.assertEqual((waited(Status([failed, warm[0]] + up + [want]), wait_s=240), slept), (0.0, []))
        # SUCCESSOR-CRASH-RED: and it is the code that would land failing to start that role (#715, 14/11 00:52 UTC)
        self.assertEqual(lines, ['deliver: #411: the successor of runner on its code gave up (it ended more than 3 times '
                                 'at its start)'])
        crashed = train.Train(Status([failed, warm[0]] + up + [want]), BASE, '411', 'h' * 40, out=lines.append)
        crashed.ready('units/x', 240, 2, sleep=sleep, clock=lambda: clock[0])
        self.assertEqual(crashed.gave_up, ['runner'])
        # READY-BY-BEATS: live 12/11 00:12 UTC (#547): both roles had said warm, from tasks a rollout replaced since; the new
        # tasks held no successor of the bundle and the landing found no standby. Warm by the events is not enough: they beat
        gone = Status(warm + up + [want])
        gone.beats = [[], ['service'], ['runner', 'service']]
        self.assertEqual((waited(gone), slept), (4.0, [2, 2]))  # before: 0.0, and a landing with no standby
        self.assertEqual(lines, ['deliver: #411 waited 4 s at the front for its successors to be warm'])
        never = Status(warm + up + [want])
        never.beats = [['service']]
        self.assertEqual((waited(never, wait_s=4), slept), (4.0, [2, 2]))
        self.assertEqual(lines, ['deliver: #411 lands though its successors are not warm after 4 s '
                                 '(warm: runner, service; beating: service)'])
        source = (ROOT / 'scripts/lib/deliver.py').read_text(encoding='utf-8')
        self.assertEqual(source.count("tr.ready(branch, config.get('delivery.successor_wait_s'),"), 1)  # READY-BESIDE-BASE
        self.assertEqual(source.count('readied.join()'), 2)  # at the front, whether the base moved or not

    def test_a_red_delivery_leaves_the_train_at_once_and_merges_nothing(self):
        port = FakeTrainPort()
        self.assertEqual(self.deliver(port, Git(port, [], []), judged_red=True), 1)
        self.assertEqual(port.log, ['join 411', 'left 411'])

    def test_the_gates_own_files_reach_every_entry_and_a_missing_entry_is_left(self):
        self.assertIsNone(train.stale(['docs/a.md'], ['scripts/b.py']))
        self.assertIn('depend on', train.stale(['scripts/lib/gate_infra.py'], ['docs/x.md']))
        port = FakeTrainPort()
        tr = train.Train(port, BASE, '9', 'h', rounds=2, out=lambda *_: None)
        with self.assertRaises(train.Left):
            tr.until_front()  # not in the queue
        tr.join()
        port.call('POST', '/v1/train/join', {'base': BASE, 'pr': '8', 'head': 'h', 'files': []})
        port.queue.reverse()
        with self.assertRaises(train.Left):
            tr.until_front()  # the rounds are a bound, never a loop without an end

    def test_a_front_that_died_expires_and_the_next_lands_without_a_manual_drop(self):
        port = FakeTrainPort()
        port.call('POST', '/v1/train/join', {'base': BASE, 'pr': '410', 'head': 'a' * 40, 'files': ['x'], 'lease_s': 900})
        git = Git(port, changed=[], own=['scripts/b.py'])
        port.events.append(lambda fake: (setattr(fake, 'now', 901), fake.renew({'pr': '411'})))  # 410's process died, 411's long polls kept renewing
        self.assertEqual(self.deliver(port, git), 0)
        self.assertEqual(port.log, ['join 410', 'join 411', 'wait 411', 'expired 410', 'landed 411'])
        self.assertEqual([e['pr'] for e in port.queue], [])  # 410 is not left holding the queue, no --queue-drop
        self.assertEqual(len(self.landings), 1)

    def test_a_live_front_keeps_its_place_while_it_renews(self):
        port = FakeTrainPort()
        port.call('POST', '/v1/train/join', {'base': BASE, 'pr': '410', 'head': 'a' * 40, 'files': ['x'], 'lease_s': 900})
        front = train.Train(port, BASE, '410', 'a' * 40, lease_s=900, out=lambda *_: None)

        def alive(seconds):  # 410 is slow but alive: its events renew the lease before it runs out
            def event(fake):
                fake.now += seconds
                front.renew('checks decided')
            return event

        def lands_410(fake):
            fake.now += 600
            front.renew('waiting')
            fake.call('POST', '/v1/train/end', {'base': BASE, 'pr': '410', 'ended': 'landed'})
        port.events.extend([alive(600), alive(600), alive(600), lands_410])  # 2400 s in all, far past one lease
        git = Git(port, changed=['x'], own=['scripts/b.py'])
        git.tip = OLD
        self.assertEqual(self.deliver(port, git), 0)
        self.assertNotIn('expired 410', port.log)
        self.assertEqual(port.log[-1], 'landed 411')
        self.assertEqual(port.log.count('wait 411'), 4)  # 411 kept waiting behind it, on events only
        self.assertGreaterEqual(port.renewals.count('410'), 4)

    def test_a_judgment_longer_than_the_lease_keeps_its_place_while_it_goes_on(self):
        # TRAIN-LEASE-IN-JUDGMENT: live 12/11 01:09 UTC: #553's judgment took 19 minutes with two deliveries sharing the
        # runner; the delivery renewed only at its marks, its lease of 15 minutes ran out and it was dropped though
        # its process was alive and judging
        asked, clock = [], [0.0]

        class Port:
            def call(self, method, path, body=None):
                asked.append((path, body.get('lease_s')))
                return {'state': 'open'}
        tr = train.Train(Port(), BASE, '411', 'h' * 40, out=self.lines.append, lease_s=900)
        for second in range(0, 19 * 60, 5):  # the judge reads the log every few seconds for nineteen minutes
            clock[0] = float(second)
            tr.progress(clock=lambda: clock[0])
        self.assertEqual(asked, [('/v1/train/renew', 900)] * 4)  # at 0, 300, 600 and 900 s: never 900 s without one
        tr.over = True
        tr.progress(clock=lambda: 10_000.0)
        self.assertEqual(len(asked), 4)  # an entry that ended renews nothing

        class Gone:
            def call(self, method, path, body=None):
                return {'state': 'gone'}
        with self.assertRaises(train.Left):  # dropped all the same (a dead port's lease, an operator): the delivery stops
            train.Train(Gone(), BASE, '411', 'h' * 40, out=self.lines.append).progress()
        source = (ROOT / 'scripts/lib/deliver.py').read_text(encoding='utf-8')
        self.assertIn('progress=tr.progress if tr else None)', source)
        judge = (ROOT / 'scripts/lib/gate_infra.py').read_text(encoding='utf-8')
        self.assertIn('retry=True, progress=progress)', judge)  # land() hands it to the judgment

    def test_the_delivery_renews_on_each_of_its_events_and_a_dropped_entry_stops_it(self):
        port = FakeTrainPort()
        self.assertEqual(self.deliver(port, Git(port, [], [])), 0)
        self.assertEqual(port.renewals.count('411'), 2)  # checks started, checks decided (the front then: no long poll, FRONT-AT-ONCE)
        tr = train.Train(port, BASE, '7', 'h', out=lambda *_: None)
        tr.join()
        port.call('POST', '/v1/train/end', {'base': BASE, 'pr': '7', 'ended': 'left'})
        with self.assertRaises(train.Left):
            tr.renew('checks started')  # expired or dropped while the process was away: it must not go on

        class Dead:
            def call(self, *_a, **_k):
                raise OSError('unreachable')
        train.Train(Dead(), BASE, '7', 'h').renew('checks started')  # a port that stopped answering: fail open

    def test_a_port_without_the_train_404_or_unreachable_fails_open_and_the_delivery_lands_as_before(self):
        class NoTrain:
            def __init__(self, error):
                self.error, self.asked = error, []

            def call(self, method, path, body=None):
                self.asked.append(path)
                raise self.error
        for error in (gate_infra.Refused(404, 'no route POST /v1/train/join'), OSError('unreachable')):
            self.lines.clear()
            self.landings.clear()
            port = NoTrain(error)
            git = Git(port, [], ['scripts/b.py'])

            def land(number, head, base, ref, base_ref, root=None, port=None, front=None, **_options):
                self.landings.append(front)
                return {'verdict': 'green', 'red': [], 'seconds': 1.0, 'checks': 5, 'from_cache': 0,
                        'landing': {'result': {'merge_sha': 'm' * 40}}}, None
            with mock.patch.object(deliver, 'train_port', lambda: port), mock.patch.object(gate_infra, 'land', land), \
                    mock.patch.object(deliver, '_with_base', lambda tree, branch, head, *rest, **kw: (head, 0)), \
                    mock.patch.object(deliver, '_refreshed', lambda *a, **k: 0):
                code = deliver._judge_on_infra(411, Path('/home'), Path('/tree'), 'units/x', 'h' * 40, 'origin', BASE,
                                               git, self.lines.append, own_tree=True)
            self.assertEqual((code, self.landings, port.asked), (0, [None], ['/v1/train/join']))  # one try, no hook
            self.assertEqual(sum('no merge train' in line for line in self.lines), 1)

    def test_deliver_queue_prints_the_order(self):
        port = FakeTrainPort()
        for pr in ('410', '411'):
            port.call('POST', '/v1/train/join', {'base': BASE, 'pr': pr, 'head': 'a' * 40, 'files': []})
        lines = []
        self.assertEqual(deliver.show_queue(port=port, out=lines.append), 0)
        self.assertEqual(lines, [f'{BASE}:', '  1. #410 aaaaaaaaaaaa (front)', '  2. #411 aaaaaaaaaaaa'])


if __name__ == '__main__':
    unittest.main()
