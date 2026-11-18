"""The merge train (TRAIN-FRONT-FIRST, Daniel 09/11 10:48 BRT): one queue of deliveries per base branch, kept by the port.

PR #410 sat over an hour because every PR that landed ahead of it moved the base, so it merged the base again and was
judged again, and went back to the end. The train gives the front of the queue the priority and nobody overtakes it:

  join     a delivery takes its place at the end of its base's queue when it starts (the port's work.train, in arrival order)
  check    every delivery runs its checks at once, speculatively; only its landing waits
  front    the landing of the entry at the front goes ahead; the others block in until_front() on the port's long poll
           (POST /v1/train/wait: the server LISTENs on tower_train and answers on the front's landed/left event; its
           own timeout is a safety, and the answer `queued, timed_out` only makes this ask again, it is not a poll)
  moved    when the front landed, the next entry re-merges and re-judges only if the base's changes reach it (stale());
           else its verdict stands and it lands as it is, and the checks it does re-run come from the judge's cache.
           BASE-MOVED-SWAP: the changes reach a code-only entry when they are inputs of the code bundle (its head's
           bundle would not be the merge's and the landing could not swap to it in a second: it would wait ten minutes on
           the slow path); the second judgment runs before the landing, where the long time belongs
  lease    every entry holds a lease its own delivery renews on each event of its own (joined, checks started, checks decided,
           every long poll it asks); the port marks an entry whose lease ran out `expired` (a dead delivery) and the next
           waiter is woken by the NOTIFY: a safety timeout for a dead process, never a clock the live ones follow
  leave    a red entry, one that gave up or one that failed leaves at once (an event), so it never blocks the train

The port is any object with call(method, path, body); the tests give it an in-memory one.
"""
import fnmatch
import time

import deploy_classify

# Files every check reads: a change to the gate itself reaches every delivery, whatever it touches.
GATE_FILES = ('scripts/gate*', 'scripts/lib/gate_*', 'scripts/lib/structure*', 'config/management/*',
              'config/registry/gate*', 'config/registry/gate/*', 'config/registry/gate-infra/*')


class Left(RuntimeError):
    """The entry is not in the queue any more (removed by someone), or the wait ran out of rounds."""


class Stale(RuntimeError):
    """The front landed and moved the base in a way that reaches this entry: it must merge the base and be judged again."""

    def __init__(self, tip, why):
        super().__init__(why)
        self.tip, self.why = tip, why


def stale(changed, files, depends=GATE_FILES):
    """Why the files the base changed since this delivery was judged reach it, or None. They reach it when they are
    files the PR also changes (a conflict is only possible there, and its checks read them), files every check
    depends on (the gate's own) or, for a code-only PR, inputs of the code bundle (BASE-MOVED-SWAP: gate_infra.landed_code
    would say bundle_same false and the landing would not swap)."""
    changed, own = sorted(set(changed)), set(files)
    shared = [name for name in changed if name in own]
    if shared:
        return f"the base changed files this PR also changes: {', '.join(shared[:5])}{' ...' if len(shared) > 5 else ''}"
    gate = [name for name in changed if any(fnmatch.fnmatch(name, pattern) for pattern in depends)]
    if gate:
        return f"the base changed files its checks depend on: {', '.join(gate[:5])}"
    inputs = tuple(map(str, deploy_classify.CODE_INPUTS))
    bundle = [name for name in changed if any(name == each or name.startswith(each + '/') for each in inputs)]
    if bundle and deploy_classify.code_only(sorted(own))[0]:
        return (f"the base changed the code bundle's inputs ({', '.join(bundle[:5])}): this head's bundle would not be "
                "the merge's and the landing would wait for the slow path")
    return None


class Train:
    def __init__(self, port, base, pr, head, files=(), rounds=360, out=print, lease_s=900):
        self.port, self.base, self.pr, self.head, self.files = port, base, str(pr), head, list(files)
        self.rounds, self.out, self.over, self.lease_s = rounds, out, False, lease_s
        self.gave_up = []  # SUCCESSOR-CRASH-RED: the roles whose successor of this entry's code its supervisor gave up on
        self.renewed = None  # TRAIN-LEASE-IN-JUDGMENT: when the lease was last renewed by the judgment's own progress

    def join(self):
        state = self.port.call('POST', '/v1/train/join', {'base': self.base, 'pr': self.pr, 'head': self.head,
                                                          'files': self.files,
                                                          'lease_s': self.lease_s})
        place = next((e['position'] for e in state['entries'] if e['pr'] == self.pr), 0)
        self.out(f"deliver: #{self.pr} joined the {self.base} train at place {place + 1}"
                 + (' (the front)' if place == 0 else f" behind #{state['entries'][0]['pr']}"))
        return state

    def moved(self, head):
        """TRAIN-HEAD-FOLLOWS: the delivery merged the base and has a new head: the entry says it (the port's join of an
        open entry keeps its place and takes the head). Who asks the train by head (the prewarm's PREWARM-TRAIN-SLOT: the
        standbys' slot belongs to a head in the train) was told no for the head being judged, and gave its slot to a
        later push. A port that does not answer is not a reason to fail, as in renew()."""
        self.head = head
        if self.over:
            return
        try:
            self.port.call('POST', '/v1/train/join', {'base': self.base, 'pr': self.pr, 'head': head, 'files': self.files,
                                                      'lease_s': self.lease_s})
        except Exception:  # noqa: BLE001 - never fails the delivery
            return

    def ready(self, branch, wait_s, poll_s, sleep=time.sleep, clock=time.monotonic):
        """READY-BEFORE-LANDING: at the front, before the landing: wait until the in-task successors of this branch's
        bundle are warm in both roles (platform.deploy.successor {state: warm}, GET /v1/deploy/status), wait_s at most.
        The merge is the landing, and when it comes is the delivery's choice: a few seconds here make the swap a
        second (live 11/11, #539: the successors had started 6 to 10 s before the merge and the swap took 1.25 s).
        Answers the seconds waited; None when there is nothing to wait for (no want of this branch: not a code-only
        head, or the successors are off) or the port does not answer. Past wait_s the delivery lands as it is."""
        if self.over or not branch or wait_s <= 0:
            return None
        began = clock()
        while True:
            try:
                said = self.port.call('GET', '/v1/deploy/status').get('successor') or []
            except Exception:  # noqa: BLE001 - fail open, as the rest of the train
                return None
            want = next((each for each in said if each.get('state') == 'wanted' and each.get('branch') == branch), None)
            if want is None:
                return None
            newest = next((each for each in said if each.get('digest') == want.get('digest')
                           and each.get('state') in ('wanted', 'withdrawn')), want)
            if newest.get('state') != 'wanted':
                return None  # withdrawn since: no successor will come
            # WARM-PER-PROCESS: a role is warm when the newest thing its successor of the bundle said is `warm`: one that
            # started again says `up` anew (the status is newest first), and is not warm until it says so itself
            newest_of = {}
            for each in said:
                if each.get('digest') == want.get('digest') and each.get('state') in ('up', 'warm', 'failed'):
                    newest_of.setdefault(each.get('role'), each.get('state'))
            warm = {role for role, state in newest_of.items() if state == 'warm'}
            # FRONT-WAITS-RUNNER-BACK: the wait is long enough for a task Spot took to come back with its successor
            # (delivery.successor_wait_s); a successor its supervisor gave up on (SUCCESSOR-GAVE-UP: failed) will not
            # come, and the delivery does not wait for it
            gave_up = sorted(str(role) for role, state in newest_of.items() if state == 'failed')
            if gave_up:
                # SUCCESSOR-CRASH-RED: a successor is wanted for a code-only head only (no infra changes), and it runs the
                # PR merged with the base, the code that lands: one its supervisor gave up on (it ended more than
                # supervisor.RESTARTS times) is that code failing to start the role on the infra it lands on. #715 landed
                # so (14/11 00:52 UTC): its service raised ValueError at its start, the swap was refused, and the base held
                # code the next slow deploy would have started the engine on. The delivery says it; _front_gate leaves
                self.gave_up = gave_up
                self.out(f"deliver: #{self.pr}: the successor of {', '.join(gave_up)} on its code gave up "
                         f"(it ended more than 3 times at its start)")
                return clock() - began
            # READY-BY-BEATS: and they beat now, by the read the landing's own statement makes (a successor says warm
            # once: one that said it and is gone since still counted). None: a port with no such route, or away: as before
            beating = self.beating(want.get('digest')) if {'runner', 'service'} <= warm else set()
            waited = clock() - began
            if {'runner', 'service'} <= warm and (beating is None or {'runner', 'service'} <= beating):
                if waited >= poll_s:
                    self.out(f"deliver: #{self.pr} waited {waited:.0f} s at the front for its successors to be warm")
                return waited
            if waited >= wait_s:
                self.out(f"deliver: #{self.pr} lands though its successors are not warm after {waited:.0f} s "
                         f"(warm: {', '.join(sorted(str(role) for role in warm)) or 'none'}"
                         + (f"; beating: {', '.join(sorted(beating)) or 'none'})" if {'runner', 'service'} <= warm else ')'))
                return waited
            sleep(poll_s)

    def beating(self, digest):
        """READY-BY-BEATS: the roles whose standby of the bundle beats now (GET /v1/deploy/ready/<sha256>); None when the
        port cannot say (an older port, a call that fails): the wait then goes by the events alone."""
        try:
            return {str(role) for role in self.port.call('GET', f'/v1/deploy/ready/{digest}').get('roles') or []}
        except Exception:  # noqa: BLE001 - fail open, as the rest of the train
            return None

    def renew(self, event):
        """The delivery's own event renews the entry's lease (`event` says which, for the line when it matters). Left when
        the entry is not open any more (its lease ran out while the process was away, or it was dropped). A port that
        stopped answering is not a reason to fail: the same fail-open as the rest of the train (the caller's wait or
        landing meets it too)."""
        if self.over:
            return None
        try:
            state = self.port.call('POST', '/v1/train/renew', {'base': self.base, 'pr': self.pr, 'lease_s': self.lease_s})
        except Exception:  # noqa: BLE001 - OSError, gate_infra.Refused (404 before the deploy): never fails the delivery
            return None
        if state.get('state') == 'gone':
            raise Left(f'#{self.pr} is not in the {self.base} train any more (its lease ran out or it was dropped; at {event})')
        return state  # FRONT-AT-ONCE: the train's state as the renewal read it (`front` when this entry is the front)

    def progress(self, clock=time.monotonic):
        """TRAIN-LEASE-IN-JUDGMENT: the judgment of this delivery goes on (its judge read the log again): the lease is
        renewed, a third of it apart at most. The delivery renewed only at its marks (joined, checks started, checks
        decided); a judgment longer than the lease lost its place though its process was alive and judging (live 12/11
        01:09 UTC: #553, 19 minutes with two deliveries sharing the runner, dropped at `checks decided`). The lease is
        still what it was for: a delivery whose process died renews nothing."""
        now = clock()
        if self.over or (self.renewed is not None and now - self.renewed < self.lease_s / 3):
            return
        self.renewed = now
        self.renew('its judgment')

    def end(self, ended, reason=None):
        """Leave the queue once (the port's call is idempotent too); the event wakes whoever waits behind."""
        if self.over:
            return
        self.over = True
        self.port.call('POST', '/v1/train/end', {'base': self.base, 'pr': self.pr, 'ended': ended, 'reason': reason})
        self.out(f"deliver: #{self.pr} {ended} the {self.base} train" + (f' ({reason})' if reason else ''))

    def until_front(self):
        """Block until this entry is the front, on the port's long poll; Left when it is not in the queue or after
        `rounds` asks. Returns the state."""
        told = False
        for _ in range(self.rounds):
            state = self.port.call('POST', '/v1/train/wait', {'base': self.base, 'pr': self.pr,
                                                           'lease_s': self.lease_s})  # the long poll renews the lease
            if state['state'] == 'front':
                if told:
                    self.out(f'deliver: #{self.pr} is the front of the {self.base} train')
                return state
            if state['state'] == 'gone':
                raise Left(f'#{self.pr} is not in the {self.base} train any more')
            if not told:
                self.out(f"deliver: #{self.pr} waits for the front of the {self.base} train "
                         f"(#{state['entries'][0]['pr']} first, place {next(e['position'] for e in state['entries'] if e['pr'] == self.pr) + 1})")
                told = True
        raise Left(f'#{self.pr} waited {self.rounds} long polls for the front of the {self.base} train')


def render(state):
    """The queues of GET /v1/train as lines, front first."""
    lines = []
    for base, entries in sorted(state['queues'].items()):
        lines.append(f'{base}:')
        lines += [f"  {entry['position'] + 1}. #{entry['pr']} {entry['head'][:12]}"
                  + (' (front)' if entry['position'] == 0 else '') for entry in entries]
    return lines or ['no merge train: every queue is empty']
