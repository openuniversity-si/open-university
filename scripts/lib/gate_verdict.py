#!/usr/bin/env python3
"""The gate as an API (GATE-API, D-070): give it a head, it runs the tests and returns the result, passed or failed.

Daniel, 28/10 20:22: "o Gate é uma API que roda os testes e devolve os resultados, seja positivo ou negativo." Passing
or failing is the same call; the answer is the payload.

  scripts/gate-verdict --head <sha> [--base <sha>] [--pr <n>] [--no-run] [--cold] [--json]

The exit contract, in one place: this table and docs/padrao/v5/gate-verdict.md, which test_gate_verdict reads both.

| Exit | Verdict | Printed |
|---|---|---|
| 0 | PASSED | `verdict PASSED <head> <base> <digest>` |
| 1 | FAILED | `verdict FAILED <head> <base> <digest>`, then `red <stage>: <class>` for each red stage |
| 4 | UNOBSERVABLE | `verdict UNOBSERVABLE <head> <reason>` |
| 64 | usage | the usage error, on stderr |

4 is gate.verdict_unobservable_exit_code and 64 is EX_USAGE. UNOBSERVABLE means the gate could not run or its input
could not be read: it is never a result about the code. An API that cannot read its own registry exits EX_SOFTWARE,
never 0 or 1. `--json` prints the same answer as one object. stdout holds only the answer; the gate's own output and
the API's notes go to stderr.

How a call is answered (every step fails closed to UNOBSERVABLE):
  1. The input: the head commit, fetched; with --pr the PR, read with gate.verdict_read_attempts tries
     (gate.verdict_read_backoff_s, doubling), whose head must be the asked head; the base tip the pinned gate judges
     against (gate_pin.resolve's rule: the PR's base branch, else gate.batch_base_ref). --base names the base to
     answer about; a run always judges the tip, so a base that is not the tip is answered from a record or not at all.
  2. The binding (--pr): the gate's own input_digest (gate_digest: head tree, base, plan dev, selection, toolchain id,
     gate version), made by the tooling that will judge it (gate_pin.ensure's tool root, its gate_proof.py bind), so
     the record's key is the one the run binds (audit F2). A bare head is run as `gate-local --dev --sha`, which hands
     its proof hook no base: the gate binds nothing, the digest is printed `unbound` and the answer is never recorded.
  3. With --pr, the PR metadata check, live and publishing nothing (structure-check --metadata): P-42, it always
     reruns and is never recorded. Red is answered FAILED at once, without starting the gate, with the red stages of a
     record of the rest when there is one.
  4. The record (tier 1 only): a --pr call whose tier (gate_tier: the tier of the gate run it is made from, else
     tier 1) is in gate-tier.cacheable_tiers reads and writes records through the storage port under
     gate.verdict_store_dir, one per head and input_digest. Tier 2 and 3 never do (D-065 (5), D-070 (b), P-43).
     A record answers within gate.verdict_ttl_s; a malformed, foreign, expired or future one is a miss. --no-run
     answers a record or UNOBSERVABLE: it never starts the gate and never invents a pass.
  5. The run: scripts/gate-local --dev (--pr N, else --sha <head>) with its own GATE_REPORT_DIR. The answer is read
     from the report (audit F3): PASSED needs exit 0 and a PASS report of the head, FAILED exit 1, a FAIL report and
     no abort; an abort, a missing or contradicting report, or a gate that cannot start is UNOBSERVABLE. The base the
     pin printed (`gate: pinned to <sha>`) is the measured one; a moved base is bound again. A pass is recorded when
     its .pass record carries the same input_digest; a failure only when a red stage outside
     gate.verdict_live_stages has a class in gate.verdict_recorded_classes (an env failure is not a function of the
     input, audit F6).
  6. --cold (D-075, TRAIN-VERDICT; meaning amended by D-076): a verdict with no result of another tree. The record is
     never read (it is keyed by head, not by content), the gate always runs, with a fresh build cache
     (GATE_BUILD_CACHE_DIR) and no carry-over (COLD_ENV, which gate-hooks/plan.sh reads). Script tests and stages reuse
     a PASS only under their content key (the files they read, the attested toolchain, the judging runner; P-56): the
     per-test store stays and the stage markers live in gate.content_stage_cache_dir (GATE_STAGE_CACHE_DIR). Its
     gate.passed says cache_mode content and has no carried_from, which train_admit.admissible requires. With
     gate.content_cache_enabled off (the rollback) the per-test and stage stores are fresh too and nothing is reused.
     --cold with --no-run is a usage error.

Not gate_verdicts.py, which lists the event versions of a published verdict for its readers: this module answers.
"""
import argparse
import contextlib
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time

from adapters import storage
import config
import gate_classify
import gate_pin
import gate_report
import gate_tier

ROOT = Path(__file__).resolve().parent.parent.parent  # the checkout of this tooling: the record root
PASSED, FAILED, UNOBSERVABLE, USAGE = 'PASSED', 'FAILED', 'UNOBSERVABLE', 'usage'
PLAN = 'dev'  # the gate-local mode the API runs: gate-dev's per-PR plan
METADATA = 'pr metadata'  # the gate's PR-metadata stage (gate-hooks/prereq.sh)
RED_FIELDS = ('stage', 'class')
MISSING, SKIPPED = 'missing', 'skipped'  # an expected stage that never ran, or that a failed dependency skipped
RECORD_VERSION = 1
UNBOUND = 'unbound'  # the digest of a bare head: `gate-local --sha` hands its proof hook no base, so nothing binds it
HEX = re.compile(r'[0-9a-f]{7,40}')
PINNED = re.compile(r'^gate: pinned to ([0-9a-f]{40})$', re.M)  # gate_pin.run's first line
REASON_SEPARATOR = '\n'  # Answer.reason of a FAILED verdict: one FAIL line per line, printed as `reason <line>`
FAIL_LINE = re.compile(r'^FAIL (.+)$', re.M)
UNREADABLE = re.compile(r'^commit-check: PR #\d+ not readable')  # structure.metadata_part: the PR could not be read
STAMP = '%Y%m%dT%H%M%S'  # gate-local's report directory stamp
COLD_ENV = 'OU_GATE_COLD'  # set to 1 for a --cold run: gate-hooks/plan.sh then decides no carry-over


def setting(name):
    return config.get(name, ROOT)


def exits():
    """{verdict: exit code}: the contract of the docstring."""
    return {PASSED: 0, FAILED: 1, UNOBSERVABLE: setting('gate.verdict_unobservable_exit_code'), USAGE: os.EX_USAGE}


class Unobservable(Exception):
    """The gate could not run or its input could not be read: never a result about the code."""


class Answer:
    """One answer of the API: the verdict about (head, base, digest), or why there is none."""

    def __init__(self, verdict, head, base='', digest='', reason='', red=(), report='', recorded_at=None, tier=None,
                 pr=None, cold=False):
        self.cold = cold
        self.verdict, self.head, self.base, self.digest, self.reason = verdict, head, base, digest, reason
        self.red = [list(item) for item in red]
        self.report, self.recorded_at, self.tier, self.pr = report, recorded_at, tier, pr

    @property
    def code(self):
        return exits()[self.verdict]

    def lines(self):
        if self.verdict == UNOBSERVABLE:
            return [f'verdict {UNOBSERVABLE} {self.head} {self.reason}']
        return ([f'verdict {self.verdict} {self.head} {self.base} {self.digest}']
                + [f'red {stage}: {kind}' for stage, kind in self.red]
                + [f'reason {line}' for line in self.reason.split(REASON_SEPARATOR) if line])

    def payload(self, code=None):
        return {'verdict': self.verdict, 'exit': self.code if code is None else code, 'head': self.head,
                'base': self.base or None,
                'digest': self.digest or None, 'reason': self.reason or None, 'red': red_records(self.red),
                'report': self.report or None, 'recorded': self.recorded_at is not None,
                'recorded_at': iso(self.recorded_at) if self.recorded_at is not None else None, 'tier': self.tier,
                'pr': self.pr, 'cold': self.cold}


def red_records(red):
    return [dict(zip(RED_FIELDS, item)) for item in red]


def iso(seconds):
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat()


def last_line(text):
    lines = [line for line in (text or '').strip().splitlines() if line.strip()]
    return lines[-1].strip() if lines else 'no output'


# --- what the API calls outside itself (Seams replaces any of them in a test) -----------------------------------------
def judging_tool(root, base):
    """(tool root, held lock or None) of the tooling that judges base: the pinned base worktree (gate_pin.ensure, reused
    by the run), else this checkout when the pin is off (gate-pin.enabled=false, the rollback)."""
    if not setting('gate-pin.enabled'):
        return Path(root), None
    return gate_pin.ensure(root, base)


def bind(root, tool, head, base):
    """The gate's binding of (head, base) for the dev plan, made by the judging tooling's gate_proof.py bind."""
    done = subprocess.run([sys.executable, str(Path(tool) / 'scripts/lib/gate_proof.py'), 'bind',
                           '--src-root', str(root), '--tool-root', str(tool), '--sha', head, '--base', base,
                           '--plan', PLAN], capture_output=True, text=True)
    if done.returncode != 0:
        raise Unobservable(f'the input cannot be bound ({last_line(done.stderr or done.stdout)})')
    try:
        binding = json.loads(done.stdout.splitlines()[0])
    except (IndexError, ValueError):
        raise Unobservable(f'the input cannot be bound (no binding in "{last_line(done.stdout)}")') from None
    if (binding.get('sha'), binding.get('base_sha')) != (head, base) or not binding.get('input_digest'):
        raise Unobservable(f'the input cannot be bound (bound {binding.get("sha")} on {binding.get("base_sha")})')
    return binding


def metadata(root, tool, head, base, pr):
    """(exit code, output) of the PR metadata check as the gate runs it (gate-hooks/prereq.sh), on a checkout of head,
    judged by the tool root, publishing nothing."""
    checkout, throwaway = gate_pin.head_tooling(root, head)
    try:
        done = subprocess.run([str(Path(tool) / 'scripts/structure-check'), '--metadata', '--base', base,
                               '--pr', str(pr), '--no-publish'], cwd=checkout, capture_output=True, text=True)
        # D-322: the PR body's measurement part (the effort block), which the structure check no longer imports
        body = subprocess.run([sys.executable, str(Path(tool) / 'scripts/lib/measurement_checks.py'), 'body', '--base', base,
                               '--pr', str(pr)], cwd=checkout, capture_output=True, text=True)
    finally:
        gate_pin.drop(root, throwaway)
    return max(done.returncode, body.returncode), done.stdout + done.stderr + body.stdout + body.stderr


def gate(root, head, pr, logs):
    """(exit code, stdout) of scripts/gate-local --dev for the head (with --pr, the PR's head), its report in logs. Its
    stdout is passed on to stderr line by line, so the caller's stdout holds only the answer."""
    command = [str(Path(root) / 'scripts/gate-local'), f'--{PLAN}', *(['--pr', str(pr)] if pr else ['--sha', head])]
    try:
        child = subprocess.Popen(command, cwd=root, env={**os.environ, 'GATE_REPORT_DIR': str(logs)},
                                 stdout=subprocess.PIPE, text=True)
    except OSError as error:
        raise Unobservable(f'the gate could not start ({error})') from None
    seen = []
    for line in child.stdout:
        sys.stderr.write(line)
        sys.stderr.flush()
        seen.append(line)
    return child.wait(), ''.join(seen)


class Seams:
    """What the API calls outside itself. A test passes replacements by name."""

    def __init__(self, **replaced):
        self.fetch = gate_pin.fetch_commit  # (root, sha) -> full sha, fetched from origin when absent
        self.identity = gate_pin.pr_identity  # (root, pr) -> (head, reported base, base ref)
        self.tip = gate_pin.base_tip  # (root, ref) -> the fetched tip of origin's branch ref
        self.batch_tip = gate_pin.batch_base  # (root) -> the fetched tip of gate.batch_base_ref
        self.tool = judging_tool
        self.bind = bind
        self.metadata = metadata
        self.gate = gate
        self.now = time.time
        self.sleep = time.sleep
        for name, value in replaced.items():
            if not hasattr(self, name):
                raise TypeError(f'no seam named {name}')
            setattr(self, name, value)


# --- the record (tier 1) ----------------------------------------------------------------------------------------------
def records(root):
    return storage.open_store(Path(root) / setting('gate.verdict_store_dir'))


def record_key(head, digest):
    return f'{head}/{digest}'


def digest_of(binding):
    """The input_digest of a binding; UNBOUND for a bare head, which the gate itself binds to no base."""
    return binding['input_digest'] if binding else UNBOUND


def well_formed(red):
    """A list of {stage, class} records whose values are non-empty strings."""
    return isinstance(red, list) and all(
        isinstance(item, dict) and sorted(item) == sorted(RED_FIELDS)
        and all(isinstance(item[name], str) and item[name] for name in RED_FIELDS) for item in red)


def load(root, head, base, digest, now):
    """The recorded answer of exactly this input, or None: absent, malformed, foreign, expired and future are misses."""
    blob = records(root).get(record_key(head, digest))
    if blob is None:
        return None
    try:
        record = json.loads(blob)
        verdict, red, at = record['verdict'], record['red'], record['recorded_at']
        same = ((record['version'], record['head'], record['base'], record['input_digest'])
                == (RECORD_VERSION, head, base, digest))
    except (ValueError, KeyError, TypeError):
        return None
    shaped = (well_formed(red) and isinstance(at, int) and not isinstance(at, bool)
              and ((verdict == PASSED and not red) or (verdict == FAILED and bool(red))))
    if not (same and shaped and 0 <= int(now) - at <= setting('gate.verdict_ttl_s')):
        return None
    return Answer(verdict, head, base, digest, red=[[item[name] for name in RED_FIELDS] for item in red],
                  report=record.get('report') or '', recorded_at=at)


def recorded_red(red):
    """The red stages a record keeps: never a live stage (P-42)."""
    live = setting('gate.verdict_live_stages')
    return [item for item in red if item[0] not in live]


def worth_recording(answer):
    """A pass, or a failure with a red stage whose class is a function of the input (audit F6)."""
    if answer.verdict == PASSED:
        return True
    kinds = setting('gate.verdict_recorded_classes')
    return answer.verdict == FAILED and any(kind in kinds for _, kind in recorded_red(answer.red))


def save(root, answer, binding, now):
    record = {'version': RECORD_VERSION, 'head': answer.head, 'base': answer.base, 'input_digest': answer.digest,
              'toolchain_id': binding.get('toolchain_id'), 'gate_version': binding.get('gate_version'),
              'verdict': answer.verdict, 'red': red_records(recorded_red(answer.red)), 'report': answer.report,
              'recorded_at': int(now)}
    records(root).put(record_key(answer.head, answer.digest), json.dumps(record, sort_keys=True).encode())


# --- reading a run ----------------------------------------------------------------------------------------------------
def record_dir(root):
    """gate-local's record directory (GATE_RECORD_DIR, else <root>/.gate/records): the .pass records and reports."""
    return Path(os.environ.get('GATE_RECORD_DIR') or Path(root) / '.gate/records')


def report_dir(root, head, now):
    """A new report directory of this run, named like gate-local's own (reports/<head>/dev-<stamp>-<unique>): two calls
    in one second never share one."""
    parent = record_dir(root) / 'reports' / head
    parent.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=f'{PLAN}-{datetime.fromtimestamp(now).strftime(STAMP)}-', dir=parent))


def pass_extras(root, head):
    """The key=value lines of the gate's .pass record of head (gate-local), {} when there is none."""
    path = record_dir(root) / f'{head}.{PLAN}.pass'
    try:
        text = path.read_text()
    except OSError:
        return {}
    return dict(line.split('=', 1) for line in text.splitlines() if '=' in line)


def red_stages(report, logs):
    """[stage, class] of each stage that did not pass, classified like the gate (gate_classify on its log), then each
    stage a failed dependency skipped and each expected stage that never ran."""
    red = [[stage['name'], gate_classify.classify(stage['name'], gate_report.stage_log(logs, stage['name']))]
           for stage in report.get('stages', []) if stage.get('result') != 'PASS']
    named = {stage for stage, _ in red}
    red += [[item.get('name'), SKIPPED] for item in report.get('skippedStages', []) if item.get('name') not in named]
    named |= {stage for stage, _ in red}
    red += [[name, MISSING] for name in report.get('missingStages', []) if name not in named]
    return red


def fail_lines(text):
    """The distinct FAIL lines of a check's output, in order: the cause a red stage names (B3, TRAIN-VERDICT-FIX)."""
    return list(dict.fromkeys(FAIL_LINE.findall(text or '')))


def said(output):
    found = FAIL_LINE.findall(output or '')
    return f': {found[-1]}' if found else ''


def judge(head, code, logs, output):
    """(verdict, red, the FAIL lines of the red stages' logs) of a finished run, read from its report (audit F3);
    Unobservable when the run did not judge."""
    logs = Path(logs)
    try:
        report = json.loads((logs / 'stages.json').read_text())
    except (OSError, ValueError):
        report = None
    report = report if isinstance(report, dict) else None
    if (logs / gate_report.ABORT_MARKER).is_file() or (report or {}).get('aborted'):
        try:
            stage = json.loads((logs / gate_report.ABORT_MARKER).read_text())['stage']
        except (OSError, ValueError, KeyError, TypeError):
            stage = ((report or {}).get('aborted') or {}).get('stage', 'gate driver')
        raise Unobservable(f'the gate could not run: {stage}: {last_line(gate_report.stage_log(logs, stage))}')
    if report is None:
        raise Unobservable(f'the gate exited {code} with no readable report{said(output)}')
    if report.get('sha') != head:
        raise Unobservable(f'the gate judged {report.get("sha")}, not the asked head')
    result = report.get('result')
    if code == 0 and result == 'PASS':
        return PASSED, [], []
    if code == 1 and result == 'FAIL':
        red = red_stages(report, logs)
        if red:
            return FAILED, red, [line for stage, _ in red for line in fail_lines(gate_report.stage_log(logs, stage))]
        raise Unobservable('the gate failed without naming a stage')
    raise Unobservable(f'the gate exited {code} with a {result} report')


def live_red(code, output, pr):
    """(the red PR-metadata stage, its FAIL lines), None when green; Unobservable when the check did not judge or
    could not read the PR."""
    if code == 0:
        return None
    errors = FAIL_LINE.findall(output or '')
    if code == 1 and errors and all(UNREADABLE.match(error) for error in errors):
        raise Unobservable(f'PR #{pr} cannot be read by the metadata check ({errors[-1]})')
    if code == 1 and errors:
        return [METADATA, gate_classify.classify(METADATA, output)], fail_lines(output)
    raise Unobservable(f'the PR metadata check exited {code}{said(output)}')


# --- the call ---------------------------------------------------------------------------------------------------------
def call_tier(pr, head):
    """The tier of this call (audit F4): the tier of the gate run it is made from (OU_GATE_TIER bound to this tooling),
    else the tier gate_tier.derive gives the run it would start (--pr: per PR; a bare head: the batch)."""
    explicit = gate_tier.explicit()
    return explicit if explicit is not None else gate_tier.derive(pr, head, False)


def read_pr(root, pr, seams):
    """(head, base ref) of PR <pr>, with gate.verdict_read_attempts tries, the wait doubling from
    gate.verdict_read_backoff_s; Unobservable when it stays unreadable."""
    attempts, delay, error = setting('gate.verdict_read_attempts'), setting('gate.verdict_read_backoff_s'), None
    for attempt in range(attempts):
        try:
            head, _, ref = seams.identity(root, pr)
            return head, ref
        except gate_pin.PinError as failed:
            error = failed
        if attempt + 1 < attempts:
            seams.sleep(delay)
            delay += delay
    raise Unobservable(f'PR #{pr} cannot be read ({error}; {attempts} tries)')


def answer(head, base=None, pr=None, no_run=False, root=ROOT, seams=None, cold=False):
    """The answer about head (see the module docstring); never raises Unobservable."""
    seams = seams or Seams()
    found = Answer(UNOBSERVABLE, head, pr=pr, cold=cold)
    try:
        found.head = seams.fetch(root, head)
        found.tier = call_tier(pr, found.head)
        return decide(found, base, no_run, root, seams)
    except Unobservable as error:
        found.reason = str(error)
    except gate_pin.PinError as error:
        found.reason = f'the input cannot be read ({error})'
    return found


def decide(found, asked_base, no_run, root, seams):
    head, pr, tier = found.head, found.pr, found.tier
    if pr:
        current, ref = read_pr(root, pr, seams)
        if current != head:
            raise Unobservable(f'PR #{pr} head is {current}, not the asked head')
        tip = seams.tip(root, ref)
    else:
        tip = seams.batch_tip(root)
    base = found.base = seams.fetch(root, asked_base) if asked_base else tip
    binding, live = bound(root, head, base, seams, pr) if pr else (None, None)
    found.digest = digest_of(binding)
    allowed = bool(pr) and tier in setting('gate-tier.cacheable_tiers')
    recorded = load(root, head, base, found.digest, seams.now()) if allowed and not found.cold else None
    if live:
        (stage, errors), failed = live, recorded is not None and recorded.verdict == FAILED
        rest, said_before = (recorded.red, recorded.reason) if failed else ([], '')
        reason = REASON_SEPARATOR.join(item for item in [*errors, said_before] if item)
        return Answer(FAILED, head, base, found.digest, reason=reason, red=[stage, *rest], tier=tier, pr=pr,
                      cold=found.cold)
    if recorded is not None:
        recorded.tier, recorded.pr = tier, pr
        return recorded
    if no_run:
        raise Unobservable('no recorded result for this input (--no-run)' if allowed else
                           f'tier {tier} never reads the box-local store (D-065 (5), --no-run)' if pr else
                           'a head without --pr is never recorded: the gate binds it to no base (--no-run)')
    if base != tip:
        raise Unobservable(f'a run judges the base tip {tip}, not {base}')
    return run(found, binding, allowed, root, seams)


def bound(root, head, base, seams, pr=None):
    """(binding, the red metadata stage or None) of (head, base), both from the tooling that judges base; the
    metadata check runs only for a PR. The pinned worktree's lock is held only meanwhile."""
    tool, held = seams.tool(root, base)
    try:
        binding = seams.bind(root, tool, head, base)
        return binding, live_red(*seams.metadata(root, tool, head, base, pr), pr) if pr else None
    finally:
        if held is not None:
            held.close()


def run(found, binding, allowed, root, seams):
    head, base, pr = found.head, found.base, found.pr
    logs = report_dir(root, head, seams.now())
    try:
        with cold_caches(found.cold):
            code, output = seams.gate(root, head, pr, logs)
        verdict, red, errors = judge(head, code, logs, output)
    finally:
        with contextlib.suppress(OSError):
            logs.rmdir()  # only an empty one: a gate that wrote nothing leaves no report directory behind
    extras = pass_extras(root, head) if verdict == PASSED else {}
    measured = next(iter(PINNED.findall(output)), None) or extras.get('base_sha')
    recordable = allowed and measured is not None
    if measured is not None and measured != base:
        print(f'gate-verdict: the base moved to {measured} before the run; answered for it', file=sys.stderr)
        binding, base = bound(root, head, measured, seams)[0] if binding else None, measured
    result = Answer(verdict, head, base, digest_of(binding), reason=REASON_SEPARATOR.join(errors), red=red,
                    report=str(logs), tier=found.tier, pr=pr, cold=found.cold)
    if recordable and verdict == PASSED and extras.get('input_digest') != result.digest:
        print(f'gate-verdict: the gate recorded input_digest {extras.get("input_digest")}, not {result.digest}: '
              'not recorded', file=sys.stderr)
        recordable = False
    if recordable and worth_recording(result):
        save(root, result, binding, seams.now())
    return result


@contextlib.contextmanager
def cold_caches(cold):
    """For a --cold run, the gate's environment with a fresh build cache and no carry-over, removed after. Script tests
    and stages reuse only results recorded under their content key (D-076): the per-test store stays, and the stage
    markers live in gate.content_stage_cache_dir (GATE_STAGE_CACHE_DIR), apart from the fresh build cache."""
    if not cold:
        yield
        return
    saved = {name: os.environ.get(name) for name in ('GATE_BUILD_CACHE_DIR', 'GATE_STAGE_CACHE_DIR', 'GATE_TEST_CACHE_DIR',
                                                    COLD_ENV)}
    with tempfile.TemporaryDirectory(prefix='gate-verdict-cold-') as cache:
        os.environ.update(GATE_BUILD_CACHE_DIR=cache, **{COLD_ENV: '1'})
        if setting('gate.content_cache_enabled'):
            os.environ['GATE_STAGE_CACHE_DIR'] = os.path.expanduser(setting('gate.content_stage_cache_dir'))
        else:  # the rollback: nothing is reused, as before D-076
            os.environ.update(GATE_STAGE_CACHE_DIR=cache, GATE_TEST_CACHE_DIR=os.path.join(cache, 'test-cache'))
        try:
            yield
        finally:
            for name, value in saved.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value


# --- the command ------------------------------------------------------------------------------------------------------
class Parser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        print(f'{self.prog}: error: {message}', file=sys.stderr)
        raise SystemExit(os.EX_USAGE)


def sha_argument(value):
    if not HEX.fullmatch(value or ''):
        raise argparse.ArgumentTypeError(f'{value!r} is not a commit sha (7 to 40 lowercase hex digits)')
    return value


def pr_argument(value):
    if not value.isdigit() or int(value) < 1:
        raise argparse.ArgumentTypeError(f'{value!r} is not a PR number')
    return int(value)


def parser():
    found = Parser(prog='scripts/gate-verdict', description=__doc__.splitlines()[0])
    found.add_argument('--head', required=True, type=sha_argument, help='the commit to judge')
    found.add_argument('--base', type=sha_argument, help='the base to answer about (default: the tip the gate judges)')
    found.add_argument('--pr', type=pr_argument, help='the PR whose head this is: tier 1, with its metadata check')
    found.add_argument('--no-run', action='store_true', help='answer only what is recorded; never start the gate')
    found.add_argument('--cold', action='store_true',
                       help='never read a record; run with fresh caches and no carry-over (a verdict the train admits)')
    found.add_argument('--json', action='store_true', help='print the answer as one JSON object')
    return found


def emit(found, as_json, code=None):
    if as_json:
        print(json.dumps(found.payload(code), sort_keys=True))
    else:
        print('\n'.join(found.lines()))
    sys.stdout.flush()
    if found.report:
        print(f'gate-verdict: report {found.report}', file=sys.stderr)
    if found.recorded_at is not None:
        print(f'gate-verdict: recorded {iso(found.recorded_at)}; the gate did not run', file=sys.stderr)


def unobservable_code():
    try:
        return exits()[UNOBSERVABLE]
    except Exception:  # noqa: BLE001 - without its registry the API still never exits 0 or 1
        return os.EX_SOFTWARE


def main(argv=None, seams=None, root=ROOT):
    args = parser().parse_args(argv)
    if args.cold and args.no_run:
        parser().error('--cold always runs the gate; it cannot be combined with --no-run')
    try:
        found = answer(args.head, args.base, args.pr, args.no_run, root, seams, args.cold)
        code = found.code
    except Exception as error:  # noqa: BLE001 - exit 1 means FAILED only: a fault of the API itself is UNOBSERVABLE
        found = Answer(UNOBSERVABLE, args.head, reason=f'the API failed ({type(error).__name__}: {error})', pr=args.pr)
        code = unobservable_code()
    emit(found, args.json, code)
    return code


if __name__ == '__main__':
    sys.exit(main())
