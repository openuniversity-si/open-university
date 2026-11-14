"""Verdict admission in the train (D-075 as amended 29/10 14:52 and 15:02; P-53, P-54): Train.drain's verdict branch.

With train.admit_mode verdict the train takes the oldest queued PR alone and asks train_admit.admissible whether the
gate.passed its pr.ready rests on (Entry.evidence, read only from the verified source) lets it merge with no tier-2 run:

  strict   the verdict's base is the tip T and the head contains T: the no-fast-forward merge has tree(head) (P-53);
  shard    the verdict's base is an older tip B and train.shard_admit is not off: B is in the head and in T and the
           shard keys of B..head and B..T are disjoint (train_admit.disjoint, manifests at T; P-54). With shadow the
           answer is measured (engine.step.measured train:shard-admit, ok for a would-admit, blocked for a refusal)
           and nothing merges on it; with on the PR merges and the expected tree is the computed merge of the head
           into T (train_git.combine).

An admitted PR merges through the same pin (port.merge, --match-head-commit) and the same tree proof as a batch: the
merged tree must be the expected one, else the train halts. It carries batch_id v-<input_digest> (strict) or
s-<input_digest> (shard) on pr.merged and integration.advanced. Anything else takes train.verdict_fallback; tier2
runs the PR as today's batch of one. requeue (default) is the train's own resync (Daniel 15:02: updating the base is
the train's work, not the owner session's):

  1. merge   a head that already contains the tip is re-verdicted as it is, the same sha, nothing pushed (D-078): a
             refusal for another toolchain, another gate version or an older base means the cold verdict on the tip
             has another input_digest, so it is a new gate.passed event (natural key repo, pr, sha, plan,
             input_digest). Only a verdict refused for warmth alone has the same digest; that head, and a head that
             does not contain the tip, get a merge commit of the tip into the head (parents head, tip; never a
             rebase), with the Train-Resync and Decision trailers, pushed to the PR branch without force. Its tree has
             the generated files regenerated: only the targets the merged tree's `scripts/generate --check` names run
             (train_git.combine_regenerated, TRAIN-VERDICT-FIX B1), still one commit;
  2. verdict train.reverdict_command (scripts/gate-verdict --cold --pr N --head <sha>) judges that head on the tip,
             measured as train:reverdict;
  3. admit   PASSED: the train reads the gate.passed the re-verdict published on the tip from the verified source and
             admits it in the same pass (strict), never through the head's pr.ready, whose natural key (repo, pr,
             sha) keeps a refused one for an unchanged sha (#805, 29/10). A passed re-verdict that still does not
             admit halts the train.

Verdicts ahead (D-076): with train.reverdict_parallel above 1 (0: the gate slots of the box), the resync of the oldest
PR also resyncs the next queued PRs whose verdicts do not admit and runs all their verdicts at once; admission stays
one PR at a time from the queue, so they only warm the content cache (P-56) and give a red PR back early.

The PR goes back to its owner session only on a real textual conflict (pr.conflicted v2, always cause textual, with
at least one file: `conflicted` raises otherwise, D-078) or a red re-verdict (pr.ejected, cause culprit). A branch the
train cannot push (a fork, a moved branch) takes the tier-2 batch of one, which merges the pinned head without pushing
to it; a merge the forge refuses is Train.refused's (a moved head waits for its next pr.ready, a head that does not
merge onto the tip is a textual conflict, anything else stays queued for the next run). An UNOBSERVABLE re-verdict, a
red one of a class in train.halt_classes, or a passed one that does not admit, halts the train (the machine or the
rules, never the PR). With train.shard_admit on, a base that moved only outside the PR's shard admits at once, without
steps 1-2. The ownership check runs first, as for a batch.
Every admission is measured as train:admit.

Self-hosting (D-079, TRAIN-ADMIT-GATE-CHANGE): with train.self_host on, a strict verdict whose toolchain_id is foreign
only because the PR changes the toolchain set (train.self_host_paths, tip...head) is judged by train_admit's dual rule:
the second leg (SelfHostLeg: train.self_host_command, the head's own tooling, cold, report-only, in a checkout of the
head) runs once per head, measured as train:self-host, and admits it when it passes. Either leg red refuses and the PR
takes train.verdict_fallback as any refusal; under requeue a red head leg is not re-verdicted (the same head brings the
same toolchain and the same red leg) but handed back as a red verdict (pr.ejected, cause culprit, stage self-host).
"""
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import re
import subprocess
import tempfile

import engine_role
import forge_events
import gate_digest
from gate_areas import glob_match
import gate_proof
import gate_test_cache
import train_admit
import train_ownership
import train_queue
import train_reuse

VERDICT, SHARD = 'v-', 's-'  # batch_id prefixes of a strict and of a shard admission
PLAN = 'dev'  # the plan of a PR verdict (gate_verdict.PLAN, gate-dev's per-PR plan)
RED = re.compile(r'^red (.+): (\S+)$', re.M)  # gate_verdict.Answer.lines: one line per red stage
REASON = re.compile(r'^reason (.+)$', re.M)  # gate_verdict.Answer.lines: one line per FAIL line of a red stage
RESYNC_TRAILER = 'Train-Resync'
TEXTUAL = 'textual'  # the one pr.conflicted cause the train emits (D-078)


def prs_since_release(events):
    """PRs the integration branch received since the last release.ready, from the repository log (the train passes its
    newest window: a lower bound when the window holds no release.ready)."""
    count = 0
    for event in events:
        if event['type'] == 'release.ready':
            count = 0
        elif event['type'] == 'integration.advanced':
            count += len(event['payload']['prs'])
    return count


def conflicted(subject, tip, detail, files):
    """The pr.conflicted v2 payload, always cause textual with the conflicting files. The guard (D-078): with no file
    it is not a conflict, and an owner session that receives pr.conflicted must find a file to resolve (#805's
    19:27Z event had none), so it raises instead of building one."""
    files = sorted(files)
    if not files:
        raise ValueError(f'pr.conflicted of #{subject.get("pr")} on {tip} names no conflicting file: not a conflict '
                         f'({detail})')
    return dict(subject, files=files, tip_sha=tip, cause=TEXTUAL, detail=detail or TEXTUAL)


class Reverdict:
    """Runs train.reverdict_command for one PR head in the train's checkout: (exit code or None, output)."""

    def __init__(self, root=None):
        self.root = Path(root or engine_role.ROOT)
        self.command = engine_role.setting('train.reverdict_command')
        self.timeout = engine_role.setting('train.tier2_timeout_s')

    def run(self, pr, head):
        try:
            command = [str(self.root / self.command[0]), *self.command[1:], '--pr', str(pr), '--head', head]
            done = subprocess.run(command, cwd=self.root, capture_output=True, text=True, timeout=self.timeout)
        except subprocess.TimeoutExpired:
            return None, f'the re-verdict of {head} exceeded train.tier2_timeout_s'
        except OSError as error:
            return None, f'the re-verdict could not start ({error})'
        return done.returncode, done.stdout + done.stderr


class SelfHostLeg:
    """The second leg of the dual verdict (D-079): the head's own tooling judges the head, cold and report-only, in a
    checkout of that head. run(head) -> (passed, why); never raises, a run that cannot start is red."""

    def __init__(self, root=None):
        self.root = Path(root or engine_role.ROOT)
        self.command = engine_role.setting('train.self_host_command')
        self.timeout = engine_role.setting('train.tier2_timeout_s')
        self.markers = ('FAIL ', engine_role.setting('gate.class_line_prefix'))  # the first of each goes in a red reason
        self.output = {}  # head -> the leg's whole output (D-082): pr.ejected carries its tail, the log keeps it all

    def run(self, head):
        import gate_pin  # the pin's own checkout helpers; imported here, the train loads without them
        import gate_verdict
        try:
            tool, throwaway = gate_pin.head_tooling(self.root, head)
        except Exception as error:  # noqa: BLE001 - no checkout of the head: the leg is red (fail closed)
            return False, f'no checkout of the head tooling ({error})'
        try:
            env = gate_pin.report_env(self.root, gate_pin.gate_version(self.root, head), os.environ)
            with tempfile.TemporaryDirectory(prefix='train-self-host-') as cache:
                env.update(GATE_BUILD_CACHE_DIR=cache, GATE_TEST_CACHE_DIR=os.path.join(cache, 'test-cache'),
                           **{gate_verdict.COLD_ENV: '1'})
                done = subprocess.run([str(Path(tool) / self.command[0]), *self.command[1:], head], cwd=tool, env=env,
                                      capture_output=True, text=True, timeout=self.timeout)
        except subprocess.TimeoutExpired:
            return False, 'the head tooling exceeded train.tier2_timeout_s'
        except OSError as error:
            return False, f'the head tooling could not start ({error})'
        finally:
            gate_pin.drop(self.root, throwaway)
        output = done.stdout + done.stderr
        self.output[head] = output
        lines = output.strip().splitlines()
        why = f'exit {done.returncode}' + (f': {lines[-1]}' if lines else '')
        if done.returncode != 0:  # D-082: the cause is in the whole output, never only its last line (#804, #809, #810)
            first = (next((line for line in lines if line.startswith(marker)), '') for marker in self.markers)
            why += ''.join(f'; {line.strip()}' for line in first if line)
        path = self.keep_log(head, output)
        return done.returncode == 0, why + (f' (full output: {path})' if path else '')

    def keep_log(self, head, output):
        """The leg's whole output in train.trigger_log_dir as self-host-<head>.log; None when it cannot be written."""
        try:
            logs = self.root / engine_role.setting('train.trigger_log_dir')
            logs.mkdir(parents=True, exist_ok=True)
            path = logs / f'self-host-{head}.log'
            path.write_text(output, encoding='utf-8')
            return path.relative_to(self.root)
        except (OSError, ValueError):
            return None


class Verdicts:
    """The verdict branch, mixed into train.Train: it uses the train's workspace, ports, steps and merge helpers."""

    def verdict_settings(self):
        self.admit_mode = engine_role.setting('train.admit_mode')
        self.verdict_fallback = engine_role.setting('train.verdict_fallback')
        self.shard_admit = engine_role.setting('train.shard_admit')
        self.shard_max_behind = engine_role.setting('train.shard_admit_max_behind')
        self.shard_never = engine_role.setting('train.shard_admit_never')
        self.content_reuse = engine_role.setting('gate.content_cache_enabled')  # D-076: admit content-keyed hits
        self.verified_source = train_reuse.verified_source
        self.reverdict = Reverdict()
        self.self_host = engine_role.setting('train.self_host')
        self.self_host_paths = engine_role.setting('train.self_host_paths')
        self.self_host_leg = SelfHostLeg()
        self.self_hosted = {}  # head -> (passed, why): the head leg runs once per head per run
        self.reverdict_parallel = engine_role.setting('train.reverdict_parallel') or gate_test_cache.gate_slots()
        self.ahead = []  # the queue behind the PR being admitted (drain sets it): candidates for verdicts ahead
        self.pushed = {}  # queued head -> the resync merge the train pushed on its branch (a verdict ahead moved it)
        self.bootstrapped, self.candidates = set(), (None, [])  # heads tried by bootstrap; (tip, candidates) read

    def admit(self, port, entry):
        """Handle the oldest queued PR in verdict mode. True when it left the queue here (merged, refused, conflicted
        or requeued); False when it takes the tier2 fallback (the caller runs it as a batch of one)."""
        self.exact_head()
        self.renew(port)
        tip = self.workspace.tip(self.base_branch)
        with self.step(port, 'admit', tip) as measurement:
            self.workspace.fetch(entry.sha)
            if not self.owned(port, tip, entry):
                measurement.result = 'blocked'
                return True
            ok, value, how, expected = self.judge_verdict(port, entry, tip)
            if ok:
                merged = self.merge_admitted(port, entry, tip, value, how, expected)
                measurement.result = 'ok' if merged else 'blocked'
                return True
            measurement.result = 'blocked'
            print(f'train: #{entry.pr} not admitted on {tip}: {value}')
            if self.verdict_fallback == 'tier2':
                return False
            return self.resync(port, entry, tip, value)

    def bootstrap(self, port):
        """B2 (TRAIN-VERDICT-FIX): with the queue empty under verdict/requeue, resync one open PR that was ready
        before but whose head's latest gate judged an older base (train_queue.resync_candidate); its re-verdict's
        pr.ready queues it. True when one was taken, so drain reads the queue again. The candidates are read once per
        tip and each head is tried once per run."""
        if self.admit_mode != 'verdict' or self.verdict_fallback != 'requeue':
            return False
        tip = self.workspace.tip(self.base_branch)
        if self.candidates[0] != tip:
            self.candidates = tip, self.open_candidates(port, tip)
        for entry in self.candidates[1]:
            if entry.sha in self.bootstrapped:
                continue
            self.bootstrapped.add(entry.sha)
            self.renew(port)
            self.workspace.fetch(entry.sha)
            print(f'train: #{entry.pr} bootstrap: {entry.sha} has no live pr.ready and its last gate is not on {tip}')
            if self.owned(port, tip, entry):
                self.resync(port, entry, tip, 'bootstrap')
            return True
        return False

    def open_candidates(self, port, tip):
        found = []
        for number in port.open_changes(self.repo, self.base_branch):
            entry = train_queue.resync_candidate(port.read(self.repo, number), port.change(self.repo, number)['head'],
                                                 tip)
            if entry is not None:
                found.append(entry)
        return sorted(found, key=lambda entry: (entry.ready_at, entry.pr))

    def hand_back(self, port, entry, tip, why, files):
        """The PR goes back to its owner session on a textual conflict: pr.conflicted with the tip and its files."""
        port.emit('pr.conflicted', conflicted(self.subject(entry), tip, why, files))
        print(f'train: #{entry.pr} handed back to its owner ({TEXTUAL}: {", ".join(sorted(files))}): {why}')
        return True

    def resync(self, port, entry, tip, reason):
        """requeue: re-verdict the same head when it contains the tip and its cold verdict is a new event, else merge
        the tip into the head and push it; then ask the gate API for a cold verdict, with the verdicts ahead beside it
        (module docstring)."""
        if self.self_hosted.get(entry.sha, (True,))[0] is False:
            return self.self_host_red(port, entry, tip)
        if self.contains(tip, entry.sha) and self.new_input(port, entry, tip):
            print(f'train: #{entry.pr} re-verdict of the same head {entry.sha} on {tip} ({reason})')
            return self.judge_again(port, entry, tip, entry.sha, self.refresh_ahead(port, entry, tip))
        head, answer = self.refreshed(port, entry, tip)
        if head is None:
            return answer
        return self.judge_again(port, entry, tip, head, self.refresh_ahead(port, entry, tip))

    def refreshed(self, port, entry, tip):
        """Step 1 for one PR: (the pushed resync merge to judge, None), or (None, admit's answer) when there is none:
        True once a textual conflict went back to its owner, False for the tier-2 batch of one (unpushable)."""
        change, head = port.change(self.repo, entry.pr), self.pushed.get(entry.sha, entry.sha)
        branch, fork = change.get('head_ref'), change.get('head_repo') not in (None, self.repo)
        if not branch or fork:
            return None, self.unpushable(entry, f'the train cannot push to {change.get("head_repo")}:{branch}')
        commit, files, regenerated = self.workspace.combine_regenerated(head, tip, self.resync_message(entry, tip))
        if commit is None:
            return None, self.hand_back(port, entry, tip, f'the tip {tip} does not merge into the head', files)
        try:
            self.workspace.push(commit, branch)
        except Exception as error:  # noqa: BLE001 - the branch moved or refused: tier 2 or the forge pin decides
            return None, self.unpushable(entry, f'the resync merge could not be pushed to {branch} ({error})')
        self.pushed[entry.sha] = commit
        print(f'train: #{entry.pr} resynced: merged the tip {tip} into {head} as {commit} on {branch}'
              + (f' (regenerated: {", ".join(regenerated)})' if regenerated else ''))
        return commit, None

    def self_host_red(self, port, entry, tip):
        """The head's own toolchain is red on the head (D-079): a re-verdict brings the same foreign toolchain and the
        same red leg, so the PR goes back to its owner as a red verdict (pr.ejected, cause culprit), never a halt."""
        why = self.self_hosted[entry.sha][1]
        bid = train_queue.REVERDICT + entry.sha[:engine_role.setting('train.batch_id_chars')]
        output = getattr(self.self_host_leg, 'output', {}).get(entry.sha) or ''
        log = '\n'.join(part for part in (why, output[-engine_role.setting('train.tier2_log_chars'):]) if part)
        port.emit('pr.ejected', dict(self.subject(entry), batch_id=bid, stage='self-host', test=None, log=log or None,
                                     cause='culprit'))
        print(f'train: #{entry.pr} handed back to its owner: the head\'s own toolchain FAILED on {entry.sha} ({why})')
        return True

    def unpushable(self, entry, why):
        """False: the caller runs the PR as the tier-2 batch of one, which merges the pinned head with no push to its
        branch (D-078: not a conflict, the owner does nothing). A moved branch is then refused by the forge pin."""
        print(f'train: #{entry.pr} {why}; it takes the tier-2 batch of one')
        return False

    def new_input(self, port, entry, tip):
        """True when a cold verdict of the unchanged head on the tip is a new gate.passed event: its input_digest (the
        tip, the train's toolchain, the tip's gate) differs from the refused proof's, the v4 natural key. Only a
        refusal for warmth alone has the same digest; that head needs the merge commit's new sha (step 1)."""
        source = self.verified_source(port.adapter) if entry.evidence else None
        proof = self.evidence(port, source, entry) if source is not None else None
        try:
            digest = gate_digest.input_digest(self.workspace.tree(entry.sha), tip, PLAN,
                                              gate_proof.selection_digest(PLAN, None), self.reuse.toolchain_id(),
                                              self.reuse.gate_version())
        except ValueError:
            return True  # no digest to compare: the re-verdict's admission judges it (and halts if it cannot)
        return ((proof or {}).get('payload') or {}).get('input_digest') != digest

    def refresh_ahead(self, port, entry, tip):
        """D-076 (GATE-FAST): [(entry, head)] of the next queued PRs, up to train.reverdict_parallel - 1, whose verdict
        does not admit on the tip either, resynced now so their verdicts run beside this one. They stay speculative:
        a PR is admitted only from the queue, oldest first, as before. When the one
        ahead of them merges, their next verdict reuses by content (P-56) everything the merged PR did not touch."""
        ahead = []
        for other in self.ahead:
            if len(ahead) + 1 >= self.reverdict_parallel:
                break
            if other.pr == entry.pr or self.self_hosted.get(other.sha, (True,))[0] is False:
                continue
            self.workspace.fetch(other.sha)
            ok, value, _how, _expected = self.judge_verdict(port, other, tip)
            if ok:
                continue
            if self.contains(tip, other.sha) and self.new_input(port, other, tip):
                ahead.append((other, other.sha))
                continue
            head, _answer = self.refreshed(port, other, tip)
            if head is not None:
                ahead.append((other, head))
        return ahead

    def resync_message(self, entry, tip):
        return (f'Merge {self.base_branch} {tip} into #{entry.pr} (train resync)\n\n'
                f'The train merged the integration tip into the PR head so the gate API judges the combined tree\n'
                f'(scripts/gate-verdict --cold); no rebase, the owner session does nothing.\n\n'
                f'{RESYNC_TRAILER}: {tip}\nDecision: D-075\n')

    def judge_again(self, port, entry, tip, head, ahead=()):
        """Step 2: the cold verdict of `head`, with the speculative verdicts of `ahead` beside it (D-076). PASSED is
        admitted in this same pass (step 3); red hands it back."""
        self.renew(port)
        with self.step(port, 'reverdict', tip) as measurement:
            answers = self.run_verdicts([(entry.pr, head), *((other.pr, other_head) for other, other_head in ahead)])
            for (other, other_head), (other_code, other_output) in zip(ahead, answers[1:]):
                self.judged_ahead(port, other, other_head, other_code, other_output)
            code, output = answers[0]
            red = RED.findall(output) if code == 1 else []
            halting = [stage for stage, kind in red if kind in self.halt_classes]
            if code == 0:
                print(f'train: #{entry.pr} re-verdict PASSED on {head}; admitting it on that verdict')
            elif not red or halting:
                measurement.result = 'blocked'
                raise self.Halt(f're-verdict of #{entry.pr} on {head} did not judge the code (exit {code}'
                                f'{", red " + ", ".join(halting) if halting else ""}): nobody is blamed, the PR stays '
                                f'as it is; fix the machine or the rules and run the train again')
            else:
                measurement.result = 'fail'
        if code == 0:
            return self.admit_fresh(port, entry._replace(sha=head), tip)
        self.eject(port, entry, head, red, output)
        return True

    def run_verdicts(self, asked):
        """[(exit code or None, output)] of train.reverdict_command for each (pr, head), in order: side by side, at
        most train.reverdict_parallel at a time; each gate still holds its own slot (gate.slots) and worktree."""
        if len(asked) == 1:
            return [self.reverdict.run(*asked[0])]
        with ThreadPoolExecutor(max_workers=len(asked)) as pool:
            return list(pool.map(lambda item: self.reverdict.run(*item), asked))

    def judged_ahead(self, port, entry, head, code, output):
        """A speculative verdict: PASSED waits for its own turn in the queue, which admits it; a red of the code goes
        back to its owner like any red re-verdict; anything else leaves the PR queued (its own turn judges it again, never a halt)."""
        red = RED.findall(output) if code == 1 else []
        if code == 0:
            print(f'train: #{entry.pr} verdict PASSED ahead on {head}; it waits for its turn in the queue')
        elif red and not [stage for stage, kind in red if kind in self.halt_classes]:
            self.eject(port, entry, head, red, output)
        else:
            print(f'train: #{entry.pr} verdict ahead on {head} did not judge the code (exit {code}); it stays queued')

    def eject(self, port, entry, head, red, output):
        stage = red[0][0]
        bid = train_queue.REVERDICT + head[:engine_role.setting('train.batch_id_chars')]
        log = output[-engine_role.setting('train.tier2_log_chars'):] or None
        port.emit('pr.ejected', dict(self.subject(entry._replace(sha=head)), batch_id=bid, stage=stage, test=None,
                                     log=log, cause='culprit'))
        print(f'train: #{entry.pr} handed back to its owner: re-verdict FAILED on {head} '
              f'({", ".join(f"{name}: {kind}" for name, kind in red)})')
        for line in REASON.findall(output):
            print(f'train: #{entry.pr}   FAIL {line}')

    def admit_fresh(self, port, entry, tip):
        """Step 3: admit `entry.sha` on the gate.passed its re-verdict just published on the tip, read from the verified
        source, in this same pass. Never through the head's pr.ready: one of an unchanged sha has the refused one's
        event_id and the forge keeps the refused evidence (#805). A passed re-verdict that does not admit halts: the
        train's own verdict on the train's machine is refused, so the machine or the rules are wrong, never the PR."""
        source = self.verified_source(port.adapter)
        fresh = self.latest_verdict(port, source, entry, tip) if source is not None else None
        entry = entry._replace(evidence=fresh)
        ok, value, how, expected = self.judge_verdict(port, entry, tip)
        if not ok:
            raise self.Halt(f're-verdict of #{entry.pr} on {entry.sha} passed but does not admit ({value}): nobody is '
                            f'blamed, the PR stays as it is; fix the machine or the rules and run the train again')
        self.merge_admitted(port, entry, tip, value, how, expected)
        return True

    def latest_verdict(self, port, source, entry, tip):
        """The event_id of the latest gate.passed of `entry.sha` on `tip` in the verified source, or None."""
        reader = forge_events.ForgeEvents(source, port.clock, port.producer, port.correlation_id)
        found = [event['event_id'] for event in reader.read(self.repo, entry.pr, kinds=[train_admit.KIND])
                 if (event.get('payload') or {}).get('sha') == entry.sha
                 and (event.get('payload') or {}).get('base_sha') == tip]
        return found[-1] if found else None

    def evidence(self, port, source, entry):
        """The gate.passed envelope the entry's pr.ready names, read from the verified source, or None."""
        reader = forge_events.ForgeEvents(source, port.clock, port.producer, port.correlation_id)
        return next((event for event in reader.read(self.repo, entry.pr, kinds=[train_admit.KIND])
                     if event['event_id'] == entry.evidence), None)

    def judge_verdict(self, port, entry, tip):
        """(ok, input_digest or the refusal, 'strict' or 'shard', the tree the merge must have). A shard admission
        under shadow is measured and answered as a refusal."""
        try:
            source = self.verified_source(port.adapter)
            proof = self.evidence(port, source, entry) if source is not None else None
            toolchain, gate_version = self.reuse.toolchain_id(), self.reuse.gate_version()
            base = ((proof or {}).get('payload') or {}).get('base_sha')
            shard = self.shard_input(base, tip, entry) if base and base != tip and self.shard_admit != 'off' else None
            self_host = self.self_host_input(port, entry, tip) if base == tip and self.self_host == 'on' else None
            ok, value = train_admit.admissible(proof, tip, entry.sha, self.workspace.tree(entry.sha),
                                               self.contains(tip, entry.sha), toolchain, gate_version, PLAN,
                                               gate_proof.proof_version(train_admit.KIND), source is not None, shard,
                                               self_host, content=getattr(self, 'content_reuse', False))
        except engine_role.RoleHalt:
            raise  # the head leg renews the lease: a lost lock stops the train, it is not a refusal
        except Exception as error:  # noqa: BLE001 - an admission that cannot be judged is a refusal (fail closed)
            return False, f'the verdict cannot be judged ({type(error).__name__}: {error})', 'strict', None
        if shard is None:
            return ok, value, 'strict', self.workspace.tree(entry.sha) if ok else None
        self.shadow(port, tip, entry, base, ok, value)
        if not ok:
            return False, value, 'shard', None
        if self.shard_admit != 'on':
            return False, f'shard shadow: would admit on base {base} (train.shard_admit {self.shard_admit})', \
                'shard', None
        commit, files = self.workspace.combine(tip, entry.sha, f'train: shard check #{entry.pr} ({entry.sha})')
        if commit is None:
            return False, f'the head does not merge onto the tip ({", ".join(files)})', 'shard', None
        return True, value, 'shard', self.workspace.tree(commit)

    def self_host_input(self, port, entry, tip):
        """train_admit.SelfHost: the toolchain-set paths tip...head touches, and the head leg (run when asked)."""
        touched = [path for path in self.workspace.changed_files(tip, entry.sha)
                   if any(glob_match(path, glob) for glob in self.self_host_paths)]
        return train_admit.SelfHost(touched, lambda: self.head_leg(port, entry, tip))

    def head_leg(self, port, entry, tip):
        """(passed, why) of the head's own toolchain on the head, measured as train:self-host, once per head."""
        if entry.sha not in self.self_hosted:
            self.renew(port)
            with self.step(port, 'self-host', tip) as measurement:
                passed, why = self.self_host_leg.run(entry.sha)
                measurement.result = 'ok' if passed else 'fail'
            self.self_hosted[entry.sha] = passed, why
            print(f'train: #{entry.pr} self-host: the head\'s own toolchain {"PASSED" if passed else "FAILED"} on '
                  f'{entry.sha} ({why})')
        return self.self_hosted[entry.sha]

    def contains(self, ancestor, commit):
        return self.workspace.is_ancestor(ancestor, commit)

    def shard_input(self, base, tip, entry):
        """train_admit.Shard for a verdict on `base`: the ancestry, then disjoint() over the manifests at the tip."""
        self.workspace.fetch(base)
        in_head, in_tip = self.contains(base, entry.sha), self.contains(base, tip)
        if not (in_head and in_tip):
            return train_admit.Shard(in_head, in_tip, '')
        distance = self.workspace.count(base, tip, first_parent=True)
        manifests = train_ownership.UnitOwnership(self.workspace).manifests(tip)
        collision = train_admit.disjoint(manifests, self.workspace.changed_files(base, entry.sha),
                                         self.workspace.changed_files(base, tip), distance, self.shard_max_behind,
                                         self.shard_never)
        return train_admit.Shard(in_head, in_tip, collision)

    def shadow(self, port, tip, entry, base, ok, value):
        """One measured shard decision (would admit: ok; refused: blocked) and its line, whatever the mode acts on."""
        with self.step(port, 'shard-admit', tip) as measurement:
            measurement.result = 'ok' if ok else 'blocked'
        print(f'train: #{entry.pr} shard {self.shard_admit}: verdict base {base}, tip {tip}: '
              f'{"would admit" if ok else value}')

    def merge_admitted(self, port, entry, tip, digest, how, expected):
        """Merge one admitted PR (the pinned head), prove its tree and announce the new tip. False when the forge
        refused it (Train.refused); a tree other than `expected` halts the train."""
        bid = (SHARD if how == 'shard' else VERDICT) + digest[:engine_role.setting('train.batch_id_chars')]
        try:
            merge_sha = port.merge(self.repo, entry.pr, entry.sha)
        except Exception as error:  # the forge refused this change (head moved, not mergeable)
            self.refused(port, entry, tip, error)
            return False
        self.workspace.fetch(merge_sha)
        proved = self.workspace.tree(merge_sha) == expected
        port.emit('pr.merged', dict(self.subject(entry), merge_sha=merge_sha, batch_id=bid), repository=True)
        if not proved:
            raise self.Halt(f'tree proof failed: {merge_sha} does not have the tree {expected} the verdict of '
                            f'#{entry.pr} proved ({how})')
        if self.quarantine.open(port):
            self.quarantine.release(port, entry.pr, entry.lane_id, merge_sha,
                                    port.change(self.repo, entry.pr).get('body'))
        history, _complete = port.read_window(self.repo, None)
        port.emit('integration.advanced', dict(self.subject(sha=merge_sha), batch_id=bid, prs=[entry.pr],
                                               prs_since_release=prs_since_release(history) + 1))
        print(f'train: #{entry.pr} merged alone on its verdict ({how}) as {bid}: {merge_sha}')
        if self.publish_aggregates:
            self.keep_aggregates(port, merge_sha)
        return True
