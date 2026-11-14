"""The merge train v0 (plan v3 M3; D-065 V3 and items (4) and (5); D-068; D-069 items 3, 6, 7, 8 and 11).

Driven by events only, through the forge_events port: the queue is every open change whose latest `pr.ready` names
its current head, rests on a `gate.passed` of that head, and has no later `pr.conflicted`, `pr.ejected` or
`pr.merged` for it. Replaying the logs rebuilds the queue (D-069 item 4); nothing else holds train state. The queue
index (train_queue.py, train.queue_since_last_batch) replays once per run, then reads only the PRs with new events.

A batch takes the first train.batch_size PRs of the queue (FIFO by `pr.ready`) and builds the combined head on the
integration tip, one merge commit per PR in critical-path order (train_queue.critical_first: most dependent units
first, then FIFO; MQ1), so prefixes and bisection follow it (train_git, plain git). The batch line the role prints
names the tier-2 verdict's event_id (the run's engine.step.measured; self.verdicts by batch id); the train.batch.*
payloads gain the field with their next contract version. A PR that does not merge onto the
combined head leaves the batch with `pr.conflicted`. Before that, the ownership check (train_ownership, U0's
manifests at the tip; a no-op until they exist) refuses a head that changes another lane's unit without its owner's
approval, with `pr.refused`.

Tier 2 (train.tier2_command; fresh caches, or the box content cache under train.tier2_test_cache box, D-297 (c)) runs on the combined head: scripts/gate-batch --tier 2, the union plan of
the members (gate_batch.py; GX-30, B-20 (a)), which reads the base and the member heads of the judged commit from
GATE_BATCH_BASE and GATE_BATCH_MEMBERS (gate_env); a bisection probe gets the members of its prefix. Before a run the
judge path asks train_reuse (GX-31, GA-P02 strict): a verified v4 gate.passed on the repository channel whose
input_digest is the one the train recomputes for that commit (tree, base, plan, selection, attested toolchain_id,
gate_version) is the verdict and nothing runs; anything else runs. train-reuse.reuse_attested_proofs off looks up
nothing (the one-key rollback). Green: each member merges through the port as a
merge commit only if its head is still the tested one (--match-head-commit), then the tree proof checks that the
merged tip's tree equals the tested combined tree; `pr.merged`, `train.batch.green` and `integration.advanced`
follow. A member the forge refuses leaves this run's queue (Train.refused: `pr.conflicted` only when it really
conflicts with the new tip, with its files, D-078); the members merged before it (the proven prefix) are
still proved against the tested prefix of the combined head and announced, and the members after it are rebuilt on
the new tip and judged again. A base that moved between build and merge rebuilds the whole batch on the new tip
instead of halting. Both share train.rebuild_max per batch (F-16, GX-30); past it a base move halts and refused
leftovers wait for the next batch.

Red: `train.batch.red`, then bisection over the prefixes of the combined head (one merge commit per member, so a
prefix is a commit that already exists): the first red prefix names the culprit, which leaves with `pr.ejected`
(cause culprit). The prefix before it was judged green by the bisection's last green probe, so it merges in the same
run on that verdict (D-297 (a), VAZÃO F36): `pr.merged` with the batch id, the tree proof against that probe, and no
`train.batch.green` (the batch was red); a tip that moved or a forge refusal leaves the prefix queued instead, and so
does train.merge_proven_prefix false (the one-key rollback). The
members after the culprit stay queued and the next batch retries them. A batch of B members needs at most
ceil(log2 B) tier-2 runs; the train refuses to start when train.bisection_max_runs is lower. No bisection run is
retried (D-025); the one extra run is the culprit recheck (D-297, Train.recheck): before `pr.ejected` the culprit's
prefix runs tier 2 once more, and green there makes the red a proven flake instead of an ejection.
Only a code failure ejects. A red combined head or bisection probe whose class (the gate's class line, GX-01, read by
engine_role.CommandGate over the whole output) is in train.halt_classes (default env and contract) raises TrainHalt
before any pr.ejected, and the batch stays queued; env first emits env.drift for the env lane (GX-02). With the list
empty the train ejects on any class again (the one-key rollback).

A flake (M7, scripts/lib/quarantine.py) is a red run on a sha that already has a green tier-2 run: in this batch, or
in the repository log (`engine.step.measured` train:tier2, train:bisect or train:recheck with result ok). Combined commits are dated
from their parents, so a batch that rebuilds content the train already judged runs it on the same sha. A red batch
whose verdict rests on a proven flake (the combined head or any bisection probe) ejects nobody: the bisection stops,
`test.flaked` and `test.quarantined` (owned by the unit owner) are emitted, the batch step is measured blocked, its
members stay queued and the role ends its drain with the outcome 'flaked', so the same content is not run again in
this invocation; the next event (pr.ready) runs the next batch. A quarantined test stays blocking. When a merged PR's
body names an open quarantine on a `Stabilizes:` line, `test.unquarantined` ends it.

The role (D-065 (1), EVENTS.md "Transport v0"): whoever emits pr.ready runs `scripts/train run`, which takes the lock
(train.lock_ref) until the run's deadline and runs batches until
the queue is empty, emitting `train.queue.growing` when the queue left at a batch end exceeds
train.queue_growing_batches batches and `train.queue.empty` before it releases the lock. After the release it looks
once more, so a pr.ready whose producer found the lock taken is never stranded. `scripts/train run --pr <n>` (GATE-ON-PUSH
R3) is the unit of work of one wake: the queue is that PR's entry alone, from its own log and head (two reads, while
it is open on the base branch), one batch, no second read of the queue, no bootstrap and no look after the release;
the full run stays the sweep. `scripts/train run --box` (VAZÃO F36, D-297) is one batch of the box queue inside the
box's lock, led by a waiting `deliver` (train_box.py).

Every run has one budget (D-291, service_budget): the deadline is the runner's (TOWER_JOB_DEADLINE) or, run by hand,
the start plus service.job_budget_s. The lock's lease ends at the deadline and is never renewed past it, its owner is
the one the runner named for the job (TOWER_JOB_OWNER) or the session's, and the deadline's alarm and TERM end the
run through OverBudget, which releases the lock with `died`. A run prints its phases (`phase: <name> @<epoch>`) for
the runner's result. While train.enabled (an x-flag,
default on since GX-06, because with train.trigger_mode emit_only only the train-role session runs the train) is false the command does nothing and the per-session merge rule of AGENTS.md holds; switching it on is
a config.changed event (scripts/config set), never a code change. The switch is the shared one: a run whose change
store is machine-local (OU_CONFIG_STORE=file) and overrides train.enabled refuses to run (GA-PG8). With
train.trigger_mode emit_only (train_trigger.py) a producer of pr.ready starts nothing; the train-role session runs the
train (docs/operations/train.md, GX-06).

The merge rule is the registry's (config/registry/merge.json, GX-22, read here as merge-phase reads it, never restated):
merge.require_exact_head off halts the train before it builds anything, because the forge port merges only a pinned
head (--match-head-commit), the same refusal merge-phase gives; every member's distance from the tip is printed with
merge_behind.limit_line ("N behind, limit merge.max_behind_base"). A member behind the tip needs no re-gate here: tier 2
re-proves the whole batch on the tip it merges on. merge.require_mergeable is met by construction (a member that does
not merge onto the combined head leaves with pr.conflicted before tier 2) and merge.tier1_requires_base_merge is the
tier-1 rule (commit_check), so neither changes what the train does.

Aggregates (plan v3 U1) are not written by PRs; with train.publish_aggregates on, the train keeps the ones that must stay in
git on train.aggregates_ref after each integration.advanced (train_aggregates.py).

Every tunable is a registry entry (config/registry/train.json) read with config.get; every step emits
`engine.step.measured` through forge_events.measured with the injected clock. The lock loop, the measured run and the
prefix bisection are engine_role's, shared with the battery role (M6).
"""
import argparse
import hashlib
import math
import sys
import traceback

import config
import engine_role
import forge_events
import merge_behind
import quarantine
import regime
import service_budget
import train_aggregates
import train_base_gate
import train_queue
import train_reuse
import train_shard
import train_verdict

Entry, OUT_OF_QUEUE, queue_entry = train_queue.Entry, train_queue.OUT_OF_QUEUE, train_queue.queue_entry
BATCH_BASE_ENV, BATCH_MEMBERS_ENV = 'GATE_BATCH_BASE', 'GATE_BATCH_MEMBERS'  # read by scripts/gate-batch --tier 2
DIED = 'train: died:'  # the last stderr line of a run that raised; its reason is also on the lock's release record


def batch_id(base, entries):
    """Deterministic id of a batch: the same base and heads give the same id, so re-emitting is a no-op."""
    material = base + ''.join(f',{entry.pr}:{entry.sha}' for entry in entries)
    return 'b-' + hashlib.sha256(material.encode()).hexdigest()[:engine_role.setting('train.batch_id_chars')]


class TrainError(RuntimeError):
    """The registry values cannot drive the train."""


class TrainHalt(engine_role.RoleHalt):
    """The train must stop for a person: the integration tip is not what the train tested or merged."""


def bisection_runs(members):
    """Most tier-2 runs a bisection over this many members spends."""
    return math.ceil(math.log2(members)) if members > 1 else 0


def size_for_red(red, table, cap):
    """k_max for the observed red share `red` (VAZÃO F36, train.batch_size_by_red): the size of the first row whose
    red_max `red` does not pass, never above `cap` (train.batch_size); 1 (no batch) past the last row or when `red` is
    unknown (the meter could not be read: the box delivers one PR at a time)."""
    if red is None:
        return 1
    for row in table:
        if red <= row['red_max']:
            return min(row['size'], cap)
    return 1


def check_sizes(table, max_runs):
    """The rows of train.batch_size_by_red the train refuses: bounds out of order, or a size whose bisection needs more
    than train.bisection_max_runs, so a red batch could end without a culprit."""
    errors = []
    bounds = [row['red_max'] for row in table]
    if bounds != sorted(bounds):
        errors.append(f'train.batch_size_by_red: red_max must ascend ({bounds})')
    errors += [f'train.batch_size_by_red: size {row["size"]} needs {bisection_runs(row["size"])} bisection runs; '
               f'train.bisection_max_runs is {max_runs}' for row in table if bisection_runs(row['size']) > max_runs]
    return errors


def observed_red(window, measure=None):
    """The red share p of the gate over the last `window` merged PRs (flow_metrics.measured_gate_runs, VAZÃO F24, read
    once per leadership), or None when it cannot be read or nothing was measured."""
    if measure is None:
        import flow_metrics
        measure = lambda count: flow_metrics.measured_gate_runs(  # noqa: E731
            engine_role.ROOT, f'origin/{engine_role.setting("train.base_branch")}', flow_metrics.SINCE, count)
    row = measure(window)
    if 'error' in row or not row.get('runs'):
        return None
    return row['p']


class Train(train_verdict.Verdicts, engine_role.LockedRole):
    """One train role over one repository: the forge port (events, changes, merges), a git workspace, tier 2; with
    train.admit_mode verdict, a PR alone on its own verdict first (train_verdict, D-075)."""

    Halt = TrainHalt

    def __init__(self, adapter, clock, workspace, gate, repo=None, ownership=None):
        self.adapter, self.clock, self.workspace, self.gate = adapter, clock, workspace, gate
        self.ownership = ownership
        self.repo = repo or engine_role.setting('forge-events.repo')
        self.base_branch = engine_role.setting('train.base_branch')
        self.producer = engine_role.setting('train.producer')
        self.batch_size = engine_role.setting('train.batch_size')
        self.step_prefix = engine_role.setting('train.step_prefix')
        self.combined_ref_prefix = engine_role.setting('train.combined_ref_prefix')
        self.bisection_max_runs = engine_role.setting('train.bisection_max_runs')
        self.lock_ref = engine_role.setting('train.lock_ref')
        self.deadline = None  # set by main (service_budget.deadline()): the lock is held until it (D-291)
        self.queue_growing_batches = engine_role.setting('train.queue_growing_batches')
        self.publish_aggregates = engine_role.setting('train.publish_aggregates')
        self.aggregates_ref = engine_role.setting('train.aggregates_ref')
        self.published_aggregates = engine_role.setting('train.published_aggregates')
        self.halt_classes = engine_role.setting('train.halt_classes')
        self.rebuild_max = engine_role.setting('train.rebuild_max')
        self.merge_proven_prefix = bool(engine_role.setting('train.merge_proven_prefix'))  # D-297 (a)
        self.reuse = train_reuse.Reuse(self.repo, getattr(workspace, 'root', None), engine_role.ROOT)
        self.quarantine = quarantine.Quarantine(self.repo, ownership)
        self.runs, self.flaked, self.prefixes = [], None, {}
        self.weights, self.verdicts = None, {}
        self.skipped = set()  # (pr, sha) the forge refused to merge in this run: out of this run's queue (refused)
        self.only = None  # run --pr <n>: the queue is that PR's entry alone (one log, one head)
        self.box = None  # run --box: one batch from the box queue (train_box, VAZÃO F36); the queue folder or True
        self.verdict_settings()
        self.base_hold = bool(engine_role.setting('train.base_hold'))  # unit R1: a red real result holds the queue
        self.base_release = engine_role.setting('train.base_hold_release')
        self.index = train_queue.QueueIndex(self.repo, self.base_branch, clock,
                                            engine_role.setting('train.queue_since_last_batch'))
        if bisection_runs(self.batch_size) > self.bisection_max_runs:
            raise TrainError(f'train.batch_size {self.batch_size} needs {bisection_runs(self.batch_size)} bisection '
                             f'runs; train.bisection_max_runs is {self.bisection_max_runs}')
        self.sizes_by_red = engine_role.setting('train.batch_size_by_red')  # VAZÃO F36: k_max by the red share
        self.red_window = engine_role.setting('train.batch_red_window')
        refused_sizes = check_sizes(self.sizes_by_red, self.bisection_max_runs)
        if refused_sizes:
            raise TrainError('; '.join(refused_sizes))

    def size_now(self, measure=None):
        """(k_max, p) for one leadership on the box: p read once from the meter, k_max from train.batch_size_by_red."""
        red = observed_red(self.red_window, measure)
        return size_for_red(red, self.sizes_by_red, self.batch_size), red

    def queue(self):
        """Every PR waiting for the train, oldest pr.ready first (train_queue: after the first build of this run, only
        the PRs with events since the previous build are read again). Under run --pr, that PR's entry or nothing."""
        built = self.index.build(self.port('queue')) if self.only is None else self.one(self.port('queue'), self.only)
        entries = [entry for entry in built if (entry.pr, entry.sha) not in self.skipped]
        return sorted(entries, key=lambda entry: (entry.ready_at, entry.pr))

    def one(self, port, number):
        """[the entry] of PR `number` from its own log and head when it waits for the train on the base branch, else []."""
        change = port.change(self.repo, number)
        if not change.get('open', True) or change.get('base_ref') not in (None, self.base_branch):
            return []
        entry = train_queue.queue_entry(port.read(self.repo, number), change['head'])
        return [entry] if entry else []

    def subject(self, entry=None, sha=None):
        if entry is None:
            return forge_events.subject(self.repo, None, sha)
        return forge_events.subject(self.repo, entry.pr, entry.sha, entry.premises, entry.unit)

    def owned(self, port, base, entry):
        """False (and pr.refused) when the head changes another lane's unit without its owner's approval."""
        if self.ownership is None:
            return True
        refused = self.ownership.refusals(base, self.workspace.changed_files(base, entry.sha), entry.lane_id,
                                          lambda: port.approvals(self.repo, entry.pr), entry.sha)  # D-112
        if refused:
            port.emit('pr.refused', dict(self.subject(entry), reason='ownership',
                                         units=sorted({item['unit'] for item in refused}),
                                         files=sorted({path for item in refused for path in item['files']})))
        return not refused

    def refused(self, port, entry, tip, error):
        """A merge the forge refused (D-078: never a pr.conflicted with no file). The head leaves this run's queue; a
        head that moved waits for its owner's next pr.ready, a pinned head that does not merge onto `tip` leaves with
        pr.conflicted and its files, and anything else (the forge's own refusal of a clean merge) stays queued for the
        next run. Nobody is told of a conflict that is not one."""
        self.skipped.add((entry.pr, entry.sha))
        head = port.change(self.repo, entry.pr).get('head')
        if head != entry.sha:
            print(f'train: #{entry.pr} not merged: its head moved to {head}; it waits for its next pr.ready ({error})')
            return
        self.workspace.fetch(tip)
        files = self.workspace.merge_tree(tip, entry.sha)[1]
        if files:
            port.emit('pr.conflicted', train_verdict.conflicted(
                self.subject(entry), tip, f'the forge refused the merge onto {tip} ({error})', files))
            print(f'train: #{entry.pr} not merged: it conflicts with {tip} in {", ".join(sorted(files))}')
            return
        reason = train_queue.skip_reason(port.read(self.repo, entry.pr), head, str(error))
        print(f'train: #{entry.pr} not merged: {reason}')

    def build(self, port, base, entries):
        """Combined head of the entries on base: (members, one combined commit per member). Conflicts leave."""
        members, commits, combined = [], [], base
        with self.step(port, 'build', base):
            self.workspace.fetch(*(entry.sha for entry in entries))
            for entry in [entry for entry in entries if self.owned(port, base, entry)]:
                commit, files = self.workspace.combine(combined, entry.sha, f'train: merge #{entry.pr} ({entry.sha})')
                if commit is None:
                    port.emit('pr.conflicted', train_verdict.conflicted(self.subject(entry), base,
                                                                        f'#{entry.pr} does not merge onto {combined}',
                                                                        files))
                    continue
                members.append(entry)
                commits.append(commit)
                combined = commit
        return members, commits

    def start_batch(self, entries):
        """Build the next batch on the integration tip and announce it: (port, batch id, base, members, commits)."""
        service_budget.phase('build')
        base = self.workspace.tip(self.base_branch)
        bid = batch_id(base, entries)
        port = self.port(bid)
        members, commits = self.build(port, base, entries)
        if members:
            self.workspace.keep(self.combined_ref_prefix + bid, commits[-1])
            port.emit('train.batch.started', dict(self.subject(sha=base), batch_id=bid,
                                                  prs=[entry.pr for entry in members]))
            train_shard.announce(self.workspace, port, self.subject(sha=base), bid, base, members)
        return port, bid, base, members, commits

    def record(self, step, commit, result):
        """Every judged tier-2 run (engine_role.LockedRole.judge) is kept as flake evidence."""
        self.last_result, self.last_commit = result, commit
        tests = () if result.ok else quarantine.failing_tests(result, self.step_prefix + step)
        self.runs.append(quarantine.Run(commit, result.ok, tests, result.log or None))

    def green_runs(self, port):
        """The green tier-2 runs in the newest window of the repository log (the measured train:tier2 and train:bisect
        steps). The window, not the whole channel: the log issue outgrows forge-events.github_max_pages (#548), and
        fewer green runs only makes a flake harder to prove, never easier."""
        steps = {self.step_prefix + 'tier2', self.step_prefix + 'bisect', self.step_prefix + 'recheck'}
        events, _complete = port.read_window(self.repo, None)
        return [quarantine.Run(event['payload']['sha'], True, (), None) for event in events
                if event['type'] == 'engine.step.measured' and event['payload']['step'] in steps
                and event['payload']['result'] == 'ok']

    def halt(self, port, result, commit):
        """A red run whose class (the gate's class line, GX-01) is in train.halt_classes blames the machine (env) or the
        rules (contract), never a member: env emits env.drift for the env lane, then the train halts for a person
        before anyone is ejected and the batch stays queued. Only another class (code) goes on to bisect and eject."""
        kind = result.kind
        if kind not in self.halt_classes:
            return
        stage = result.stage or self.step_prefix + 'tier2'
        if kind == 'env':
            port.emit('env.drift', dict(self.subject(sha=commit), stage=stage, tool=None, versions=[]))
        raise TrainHalt(f'tier 2 on {commit} failed with class {kind} (stage {stage}; train.halt_classes); nobody '
                        f'ejected, the batch stays queued: fix the {"machine" if kind == "env" else "conflicting rules"} '
                        f'and run the train again')

    def flake(self, port, bid):
        """True (and the quarantine events) when the latest red run is a proven flake: nobody may be ejected."""
        if not quarantine.proven_flaky(self.runs[-1], self.runs):
            return False
        self.quarantine.report(port, quarantine.flaked(self.runs))
        self.flaked = bid
        return True

    def recheck(self, port, bid, commit):
        """D-297, before any pr.ejected: the culprit's prefix (its own head on top of the proven prefix, the commit the
        bisection named red) runs tier 2 once more, fresh (no reused proof, step recheck). Green there makes the red
        run a proven flake (quarantine.proven_flaky: the same sha has a green run): test.flaked and test.quarantined,
        nobody is ejected and the members stay queued. Red keeps the ejection; a halt class still halts. Without this
        a test that failed on the combined head and once more on the last prefix ejected the last member (the batch
        whose shorter prefixes all pass). Nothing merges on this run's verdict, so it is no gate retry (D-025)."""
        print(f'train: re-running tier 2 on {commit} before ejecting its culprit from {bid}')
        result = engine_role.LockedRole.judge(self, port, 'recheck', commit)
        if not result.ok:
            self.halt(port, result, commit)
            return False
        found = quarantine.flaked(self.runs)
        if not found:
            return False
        self.quarantine.report(port, found)
        self.flaked = bid
        return True

    def exact_head(self):
        """merge.require_exact_head (GX-22): off, the train refuses to run, as merge-phase does; it merges only pinned
        heads."""
        if not engine_role.setting('merge.require_exact_head'):
            raise TrainHalt('merge.require_exact_head is off, but the forge port merges only a pinned head '
                            '(--match-head-commit); turn it back on')

    def behind_lines(self, base, members):
        """Each member's distance from the tip it merges on, in the merge rule's verdict line (merge_behind.limit_line)."""
        limit = engine_role.setting('merge.max_behind_base')
        for entry in members:
            behind = self.workspace.count(entry.sha, base)
            print(f'train: #{entry.pr} {merge_behind.limit_line(behind, limit)} (tier 2 re-proved it on the tip)')

    def critical_first(self, entries):
        """The batch in critical-path order (train_queue.critical_first over this checkout's unit manifests); a map
        that cannot be read leaves the queue order (FIFO)."""
        if self.weights is None:
            import units
            try:
                self.weights = train_queue.dependents(units.manifests(engine_role.ROOT))
            except (units.UnitError, OSError, ValueError) as error:
                print(f'train: unit map unreadable ({error}); batch order stays FIFO')
                self.weights = {}
        return train_queue.critical_first(entries, self.weights)

    def gate_env(self, commit):
        """The union plan's input for tier 2 on `commit` (the combined head or a bisection prefix): its base and the
        heads it holds, in batch order."""
        if commit not in self.prefixes:
            return {}
        base, heads = self.prefixes[commit]
        return {BATCH_BASE_ENV: base, BATCH_MEMBERS_ENV: ' '.join(heads)}

    def judge(self, port, step, commit):
        """GX-31: a verified proof of exactly this run's key (train_reuse) is the verdict, measured nowhere and run
        nowhere; anything else is LockedRole.judge, a fresh tier-2 run."""
        lifted = self.lifted_by_regime(port, step, commit)
        if lifted is not None:
            return lifted
        proof = self.proof(port, commit)
        if proof is None:
            return super().judge(port, step, commit)
        self.renew(port)
        self.last_run_ms, self.last_verdict = 0, proof['event_id']
        result = engine_role.GateResult(True, None, f'reused proof {proof["event_id"]}')
        self.record(step, commit, result)
        return result

    def lifted_by_regime(self, port, step, commit):
        """D-260: while the exception regime lifts the 'gate' lock the combined head is not run: the verdict is green, marked, and
        regime.lift has printed the warning and emitted lock.lifted (lock, sha, lane, time), so gate-noite lists it. None while
        the lock holds (the train judges as always) or when the regime cannot be read."""
        try:
            lifted = regime.lift('gate', commit, self.owner or 'train', port, self.repo)
        except Exception as error:  # an unreadable regime is no regime: the lock holds
            print(f'train: the regime could not be read ({type(error).__name__}); tier 2 runs')
            return None
        if not lifted:
            return None
        self.renew(port)
        self.last_run_ms, self.last_verdict = 0, None
        result = engine_role.GateResult(True, None, 'tier 2 lifted by the exception regime (lock gate)')
        self.record(step, commit, result)
        return result

    def proof(self, port, commit):
        """The verified proof train_reuse finds for `commit`, or None (switch off, unknown members, no exact match)."""
        if commit not in self.prefixes or not train_reuse.enabled(engine_role.ROOT):
            return None
        base, heads = self.prefixes[commit]
        found, reason = self.reuse.find(port, base, heads, commit)
        print(f'train: tier 2 on {commit} {"reuses " + found["event_id"] if found else "runs"} ({reason})')
        return found

    def tier2(self, port, commit):
        return self.judge(port, 'tier2', commit)

    def pending(self):
        return self.only is None and not self.box and bool(self.queue())  # run --pr: no look after the release (the sweep's job)

    def run(self, owner):
        """The role: 'busy' (another owner holds the lock), 'drained' (the queue is empty) or 'flaked' (a batch stayed
        queued on a proven flake until the next event). The flag is the entry point's (main), so a disabled train
        never builds a port, reads a log or takes the lock. A run always has a deadline (D-291): main's, else now plus
        the budget."""
        if self.deadline is None:
            self.deadline = service_budget.deadline()
        return super().run(owner, 'queue')

    def base_held(self):
        """True while the base tip's newest real result is red and train.base_hold is on: the queue waits (unit R1,
        docs/units/R1/plan.md). Unknown tips are reported and run; a released tip runs. Nothing is merged, ejected or
        emitted here, so the queue keeps every PR it holds."""
        if not self.base_hold:
            return False
        tip = self.workspace.tip(self.base_branch)
        state, failing = train_base_gate.verdict(self.workspace.root, tip, self.base_release)
        if state == train_base_gate.UNKNOWN:
            print(f'train: no real result of {self.base_branch} {tip} on this host; the merge goes on '
                  '(unknown tips are reported, not held)')
        if state != train_base_gate.RED:
            return False
        print(f'train: held: the real gate of {self.base_branch} {tip} is red ({", ".join(failing) or "failed"}); '
              'the queue waits until the tip is green or train.base_hold_release names it')
        return True

    def drain(self, port):
        """'drained' once the queue is empty, or 'flaked' when a batch stayed queued on a proven flake: the next event
        runs it, never this invocation, so the same content is not run again here (D-025). With train.admit_mode
        verdict the oldest PR is taken alone (train_verdict.admit) and only the tier2 fallback runs a batch, of one;
        under requeue an empty queue first takes the open PRs left behind the tip (train_verdict.bootstrap)."""
        if self.box:  # VAZÃO F36: one batch of the box queue per leadership, never a drain
            import train_box
            return train_box.lead(self, port, None if self.box is True else self.box)
        service_budget.phase('queue')
        entries = self.queue()
        if entries and self.base_held():  # unit R1: the queue waits while the base tip's real result is red
            return 'held'
        while entries or (self.only is None and self.bootstrap(port)):  # bootstrap: one PR behind the tip resynced, read the queue again
            self.renew(port)
            if entries and self.admit_mode != 'verdict':
                self.run_batch(entries[:self.batch_size])
            elif entries:
                self.ahead = entries[1:]  # D-076: the PRs whose verdicts may run beside a resync (verdicts ahead)
                admitted = self.admit(port, entries[0])
                self.ahead = []  # never stale for a bootstrap resync of an empty queue
                if not admitted:
                    self.run_batch(entries[:1])
            if self.flaked:
                return 'flaked'
            if self.only is not None:  # run --pr: one wake, one batch; the sweep reads the queue again (D-291)
                return 'drained'
            entries = self.queue()
            if len(entries) > self.queue_growing_batches * self.batch_size:
                port.emit('train.queue.growing', dict(self.subject(sha=self.workspace.tip(self.base_branch)),
                                                      queue_size=len(entries), batch_size=self.batch_size,
                                                      tier2_ms=self.last_run_ms))
        port.emit('train.queue.empty', self.subject(sha=self.workspace.tip(self.base_branch)))
        return 'drained'

    def run_batch(self, entries):
        """One batch from the head of the queue to merged or red. Returns the members that merged.

        A base move between build and merge, or a forge refusal after a proven prefix merged, rebuilds what is left on
        the new tip and judges it again (F-16, GX-30), at most train.rebuild_max times per batch: a base move past the
        bound halts as before, refused leftovers past it stay queued for the next batch."""
        self.flaked = None
        self.exact_head()
        merged, rebuilds = [], 0
        entries = self.critical_first(entries)
        while entries:
            port, bid, base, members, commits = self.start_batch(entries)
            if not members:
                return merged
            self.prefixes = {commit: (base, [entry.sha for entry in members[:index + 1]])
                             for index, commit in enumerate(commits)}
            self.runs = self.green_runs(port)
            with self.step(port, 'batch', base) as measurement:
                service_budget.phase('tier2')
                result = self.tier2(port, commits[-1])
                self.verdicts[bid] = self.last_verdict
                print(f'train: batch {bid} tier 2 {"green" if result.ok else "red"} on {commits[-1]}: '
                      f'verdict {self.last_verdict}')
                if not result.ok:
                    port.emit('train.batch.red', dict(self.subject(sha=base), batch_id=bid,
                                                      prs=[entry.pr for entry in members], stage=result.stage))
                    self.halt(port, result, commits[-1])
                    culprit = None if self.flake(port, bid) else self.bisect(port, bid, members, commits, result)
                    measurement.result = 'fail' if culprit else 'blocked'
                    if culprit:
                        merged += self.proven_prefix(port, bid, base, members, commits, culprit)
                    return merged
                done, entries = self.merge(port, bid, base, members, commits, rebuilds < self.rebuild_max)
            merged += done
            if entries:
                rebuilds += 1
                print(f'train: rebuilding {len(entries)} member(s) of {bid} on the new tip '
                      f'({rebuilds} of train.rebuild_max {self.rebuild_max})')
        return merged

    def merge(self, port, bid, base, members, commits, rebuild=False, whole=True):
        """Merge the tested members through the port, prove the tree and announce the new tip. Returns (merged, the
        members to rebuild on the new tip): all of them when the base moved before any merge, the ones after a
        refused member when a proven prefix merged; none when `rebuild` is false (the bound is spent). `whole` false
        is the proven prefix of a red batch: it merges and is announced, but the batch is not `train.batch.green`."""
        merged, merge_shas = [], []
        service_budget.phase('merge')
        with self.step(port, 'merge', commits[-1]) as measurement:
            if self.workspace.tip(self.base_branch) != base:
                measurement.result = 'blocked'
                if rebuild:
                    return [], list(members)
                raise TrainHalt(f'{self.base_branch} moved after batch {bid} was built on {base}; nothing merged '
                                f'(train.rebuild_max {self.rebuild_max} rebuilds spent)')
            self.behind_lines(base, members)
            rest = []
            for index, entry in enumerate(members):
                try:
                    merge_shas.append(port.merge(self.repo, entry.pr, entry.sha))
                except Exception as error:  # the forge refused this change (head moved, not mergeable)
                    self.refused(port, entry, merge_shas[-1] if merge_shas else base, error)
                    rest = list(members[index + 1:]) if rebuild else []
                    break
                merged.append(entry)
            if not merged:
                return [], rest
            tip = merge_shas[-1]
            service_budget.phase('proof')
            self.workspace.fetch(tip)
            tested = commits[len(merged) - 1]
            proved = self.workspace.tree(tip) == self.workspace.tree(tested)
            for entry, merge_sha in zip(merged, merge_shas):
                port.emit('pr.merged', dict(self.subject(entry), merge_sha=merge_sha, batch_id=bid), repository=True)
            if not proved:
                measurement.result = 'fail'
                raise TrainHalt(f'tree proof failed: {tip} does not have the tree of the tested {tested}')
            if self.quarantine.open(port):
                for entry, merge_sha in zip(merged, merge_shas):
                    self.quarantine.release(port, entry.pr, entry.lane_id, merge_sha,
                                            port.change(self.repo, entry.pr).get('body'))
            if whole and len(merged) == len(members):
                port.emit('train.batch.green', dict(self.subject(sha=base), batch_id=bid,
                                                    prs=[entry.pr for entry in merged], merge_shas=merge_shas,
                                                    tree_sha=self.workspace.tree(tip)))
            history, _complete = port.read_window(self.repo, None)
            port.emit('integration.advanced',
                      dict(self.subject(sha=tip), batch_id=bid, prs=[entry.pr for entry in merged],
                           prs_since_release=train_verdict.prs_since_release(history) + len(merged)))
        if self.publish_aggregates:
            self.keep_aggregates(port, tip)
        return merged, rest

    def keep_aggregates(self, port, tip):
        """What must stay in git is written here, never by a PR (plan v3 U1, V4): the aggregates commit of the new tip."""
        with self.step(port, 'aggregates', tip):
            commit = train_aggregates.snapshot(self.workspace, tip, self.published_aggregates)
            if commit:
                self.workspace.keep(self.aggregates_ref, commit)

    def proven_prefix(self, port, bid, base, members, commits, culprit):
        """D-297 (a): merge the members before the culprit on the bisection's verdict. first_red moves its lower bound
        only past a green probe, so a culprit at index f > 0 means commits[f - 1] was judged green this run. A tip that
        moved or a refused member leaves the rest of the prefix queued (rebuild is never done here). Returns the
        members that merged."""
        index = members.index(culprit)
        if not index or not self.merge_proven_prefix:
            return []
        if self.workspace.tip(self.base_branch) != base:
            print(f'train: proven prefix of {bid} stays queued: {self.base_branch} moved after the build')
            return []
        print(f'train: merging the proven prefix of {bid} ({", ".join(f"#{e.pr}" for e in members[:index])}) '
              f'on the green probe {commits[index - 1]}')
        done, _rest = self.merge(port, bid, base, members[:index], commits[:index], rebuild=True, whole=False)
        return done

    def bisect(self, port, bid, members, commits, result):
        """Eject the member whose prefix of the combined head first turns red. Returns the culprit, or None when a
        red probe is a proven flake (the bisection stops there and nobody is ejected)."""
        found = engine_role.first_red(len(members), lambda index: self.judge(port, 'bisect', commits[index]), result,
                                      self.bisection_max_runs,
                                      lambda: self.halt(port, self.last_result, self.last_commit) or self.flake(port, bid))
        if found is None:
            return None
        if found.low != found.high:
            raise TrainHalt(f'bisection of {bid} spent {found.runs} runs, train.bisection_max_runs, without a culprit')
        if self.recheck(port, bid, commits[found.high]):
            return None
        culprit, failing = members[found.high], found.failing
        port.emit('pr.ejected', dict(self.subject(culprit), batch_id=bid, stage=failing.stage or 'tier2',
                                     test=', '.join(getattr(failing, 'tests', None) or ()) or None,
                                     log=failing.log or None, cause='culprit'))
        return culprit


def default_owner():
    """train@<runner>/<job id> when a runner runs the job (TOWER_JOB_OWNER), else train@<session> or train@host:pid."""
    named = service_budget.owner()
    producer = engine_role.setting('train.producer')
    if named:
        return f'{producer}@{named}'
    return engine_role.default_owner(producer, engine_role.setting('train.session_id_env'))


def local_override():
    """The refusal when this run's change store is machine-local and overrides train.enabled (GA-PG8), else None."""
    adapter = config.store(engine_role.ROOT).port.adapter  # the store in use, not only what $OU_CONFIG_STORE names
    if isinstance(adapter, forge_events.FileAdapter) and 'train.enabled' in config.overrides(engine_role.ROOT):
        return (f'train: refused: train.enabled is overridden by a machine-local change log ({adapter.directory}); '
                'the switch is the shared registry value: revert the local change (scripts/config history train.enabled)')
    return None


def from_config():
    """The train over the registry's adapter and clock, this checkout and the real tier 2."""
    import train_git
    import train_ownership
    workspace = train_git.GitWorkspace()
    return Train(forge_events.adapter_from_config(), forge_events.clock_from_config(), workspace,
                 train_git.Tier2Gate(), ownership=train_ownership.UnitOwnership(workspace))


def main(argv=None):
    parser = argparse.ArgumentParser(prog='scripts/train', description='The merge train v0 (plan v3 M3, D-065 V3).')
    sub = parser.add_subparsers(dest='command', required=True)
    run = sub.add_parser('run', help='take the lock and run batches until the queue is empty (off: does nothing)')
    run.add_argument('--owner', help='lock owner name (default: producer@host:pid)')
    run.add_argument('--pr', type=int, help="one wake: only this PR's entry, no bootstrap (default: the whole queue)")
    run.add_argument('--box', action='store_true', help='VAZÃO F36: one batch of the box queue inside the box lock '
                     '(delivery.box_queue_dir), results written for each resolved member')
    run.add_argument('--queue', help='with --box: the box queue folder (default delivery.box_queue_dir)')
    sub.add_parser('queue', help='print the queue the train would take, oldest pr.ready first')
    sub.add_parser('serve', help='train-role session only: wait on train.wake_ref, one run --pr per wake, a full run '
                                 'at start and every train.sweep_interval_s, exit at train.serve_max_s')
    args = parser.parse_args(argv)
    if args.command == 'serve':
        import train_serve
        return train_serve.main()
    if args.command == 'run':
        refusal = local_override()
        if refusal:
            print(refusal, file=sys.stderr)
            return 1
        if not engine_role.setting('train.enabled'):
            print('train: off (train.enabled is false); the per-session merge rule holds')
            return 0
    role = from_config()
    if args.command == 'queue':
        for entry in role.queue():
            print(f'#{entry.pr} {entry.sha} ready {entry.ready_at}')
        if role.admit_mode == 'verdict' and role.verdict_fallback == 'requeue':
            for entry in role.open_candidates(role.port('queue'), role.workspace.tip(role.base_branch)):
                print(f'#{entry.pr} {entry.sha} resync (bootstrap: no live pr.ready, last gate not on the tip)')
        return 0
    role.only = args.pr
    role.box = (args.queue or True) if args.box else None
    role.deadline = service_budget.deadline()
    try:
        service_budget.guard(role.deadline)  # the alarm and TERM raise OverBudget, which releases the lock (D-291)
        if role.box:
            import box_queue
            with box_queue.hold():
                outcome = role.run(args.owner or default_owner())
        else:
            outcome = role.run(args.owner or default_owner())
        print(f'train: {outcome}')
    except service_budget.OverBudget as error:
        print(f'{DIED} {engine_role.death(error)}', file=sys.stderr)
        return 1
    except TrainHalt as error:
        print(f'train: halted: {error}', file=sys.stderr)
        return 1
    except Exception as error:  # a run that dies says why as its last line, after the traceback (TRAIN-TEMP-FIX R1)
        traceback.print_exc()
        print(f'{DIED} {engine_role.death(error)}', file=sys.stderr)
        return 1
    finally:
        service_budget.disarm()
        counts = forge_calls(role)
        print(rest_line(counts))
    if outcome != 'busy':
        measure_rest(role, counts, args.pr)
    return 0


REST_BUDGET = 'train.rest_calls_per_run_max'


def forge_calls(role):
    """GATE-ON-PUSH R4: {sent, not_modified} of this run's forge requests through the port, or None when the adapter
    counts nothing."""
    if not hasattr(role, 'port'):  # a role without a forge port (a test double) has nothing to count
        return None
    port = role.port('rest')  # construction failures are required demand, not optional accounting
    try:
        return port.calls()
    except forge_events.ForgeEventsError:
        return None


def rest_line(counts):
    """This run's REST calls against train.rest_calls_per_run_max."""
    if counts is None:
        return 'train: REST calls not counted (the adapter counts nothing)'
    return (f'train: {counts["sent"]} REST call(s), {counts["not_modified"]} not modified '
            f'(budget {engine_role.setting(REST_BUDGET)})')


def measure_rest(role, counts, pr=None):
    """budget.measured of this run's REST calls (metric train.rest_calls_per_run_max), best effort: a run that held
    the lock publishes it; a 'busy' run, which did nothing, publishes nothing."""
    if counts is None:
        return
    try:
        role.port('rest').emit('budget.measured', dict(forge_events.subject(role.repo, pr, None), metric=REST_BUDGET,
                                                       value=counts['sent']))
    except Exception as error:  # noqa: BLE001 - a measurement never changes the run's result
        print(f'train: REST count not published ({error})', file=sys.stderr)


if __name__ == '__main__':
    sys.exit(main())
