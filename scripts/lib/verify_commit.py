"""The verifier thread's gate (the migration to GitHub, 14/11/2026): judge one exact commit and publish the verdict as its
commit status `tower/gate` on GitHub, the check the merge queue of `main` requires.

    scripts/verify-commit --sha <commit> --base <base commit> [--repo owner/name] [--no-post]

The commit must be the checkout's HEAD (the verifier checks out what it judges: a pull request's head, or the merge
queue's `gh-readonly-queue/main/...` commit, which is main plus the pull requests ahead of it). The plan is the gate's
own (scripts/gate-check plan checks: the stages and only the script tests whose covers the diff base...HEAD touches);
every stage of it runs, and the tests run in one `gate-check tests` batch. The status is `pending` while it runs, then `success` or `failure` with what was red. No
GitHub Actions and no runner of its own: the verifier is a Claude Code thread, the session that publishes is the one
that ran the checks. Standard library, the registry's scripts/lib/config.py (GATE-ISOLATED) and the `gh` CLI (the
session's GitHub credential) only.

VERDICT-REUSE (docs/process/gate-github-speed.md): `--record DIR` writes a green verdict's key under DIR and names it in
$GITHUB_OUTPUT (`verdict=tower-gate-green-<key>`), for the job to keep as an artifact of that name; `--reuse` lets the
tests' green verdict recorded under the same key stand, and still runs every stage. The key is the sha256 of the judged
commit's tree, its parents, the base, the plan's stages and tests and the hosted runner's image: the same tree is the
same verifier, gate and toolchain pins (all tracked), the same parents make the history below the commit the same, and
the stages, which also read the commit itself (its message), run again. Only a run of this repository on one of the
commit's parents counts, never a fork's; any error of the lookup is a miss, and the tests run.

PR-METADATA-GITHUB (D-329): the `pr metadata` stage reads the pull request from GitHub with `gh api` (its body, commits,
the branch's pushes and force pushes from the repository activity, its comments and its head against its base), not
from Origin, and judges it with gate_discipline.pr_errors: the commit plan, fix-ups, one commit per push, force pushes, a
head behind its base without a merge of it, a gate change citing no decision, an owner wait (decision_wait, D-325), the
plan completeness and the lanes. The pull request is the event's (GITHUB_EVENT_PATH), else the number in the merge
queue's branch name (gh-readonly-queue/<base>/pr-<n>-<sha>), else --pr; it is judged on the head the event names, else
its live head (the queue commit is not a commit of the pull request). A pull request or merge queue event that names
none, and any read error, is red (fail closed); a local run that names none judges nothing.
"""
import hashlib
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse

ROOT = Path(__file__).resolve().parent.parent.parent
CONTEXT = 'tower/gate'
TAIL = 6000  # VERIFY-TAIL: the characters of a red stage's or test batch's output the verifier prints (the job log)
SKIPPED = ()  # D-329: no stage of the plan is skipped; `pr metadata` reads the GitHub pull request (PR-METADATA-GITHUB)
METADATA = 'pr metadata'
QUEUE_BRANCH = re.compile(r'(?:^|refs/heads/)gh-readonly-queue/[^/]+/pr-(\d+)-[0-9a-f]+$')  # the merge queue's branch
PULL_REF = re.compile(r'^refs/pull/(\d+)/(?:merge|head)$')
PR_EVENTS = ('pull_request', 'pull_request_target', 'merge_group')  # an event that always names a pull request
VERDICT = 'tower-gate-green-'  # VERDICT-REUSE: the artifact name of a recorded green verdict, its key after it
KEY_VERSION = 1  # VERDICT-REUSE: a change to what the key covers bumps it, so no older record matches
RUNNER = ('RUNNER_OS', 'RUNNER_ARCH', 'ImageOS', 'ImageVersion')  # the hosted runner's image, part of the key
WORKERS = 'GATE_TEST_WORKERS'  # GATE-ISOLATED: the batch's workers (gate_test_cache.WORKERS_ENV)
PARTS = ('main', 'shard1', 'alone')  # GATE-PARTS: the jobs of one tower/gate, side by side (tower-gate.yml's matrix)
WALL_MIN_S = 5.0  # GATE-WALLS: every test of the batch at least this long is named with its wall (not only the slowest)
SLOWEST = 3  # GATE-PACE: the tests of a batch its pace line names, the slowest first (their walls in the batch)
STAGES_S = 15.0
# GATE-PER-WORKER (18/11/2026): what each part's batch runs at once, the load a part's share is weighed by: main keeps one
# worker for its stages beside the batch (GATE-PACE), shard1 has the runner's four. Constants, not the machine's CPUs:
# every job of one run must split alike. #217's gate: main's three deploy parts 54.7-60.7 s, shard1's three 48.2-49.8 s.
PART_WORKERS = {'main': 3, 'shard1': 4, 'alone': 4}  # GATE-PARTS: what main's stages weigh in the split (#130's commit: main 41 s, shard1 24 s with none)
# GATE-ALONE-SHARE (REQ-gate-60s, 19/11/2026): alone ran its two timing-bound tests (~15 s) and then sat idle while main and
# shard1 ran a wide plan's seven ~40 s deploy tests on seven workers (~70 s gates); it now takes a share of the others
# after its own, on its runner's four workers. GATE-SPLIT-BY-WORKER: each test goes to the least loaded of the eleven
# workers (the batch runs longest first, so that is its wall), not to the part lighter on average: by the average, a part
# took two ~25 s tests on one worker while another part's worker sat idle.
# GATE-PER-RUNNER (REQ-gate-60s, 19/11/2026): by the worker alone, #279's queue gate put four deploy-slow parts on alone's
# four workers and four on shard1's while main sat at 30 s; four at once on GitHub's 4-vCPU runner took 1.3-1.9x their
# hints (40-55 s, alone 71 s). A part's wall is now also its runner's load over RUNNER_LOAD (main's stages counted), and
# each test goes to the part it ends earliest on: the heavy tests spread 3/3/2.
RUNNER_LOAD = 3.0  # GATE-PER-RUNNER: the test-seconds a runner does per second (shard1: four deploy-slow, 126 s of hints in 44 s)


def costs():
    """GATE-PARTS: {test: seconds} of the committed cost hints (gate.test_costs_file); {} when absent."""
    import config
    try:
        return json.loads((ROOT / config.get('gate.test_costs_file')).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def split(tests, named, hints):
    """GATE-PARTS: the planned tests of each part. alone: the timing-bound ones (named) first; then the others, longest
    first (by the cost hints, ties by name), each to the part it ends earliest on (GATE-PER-RUNNER; ties main, shard1,
    alone): the later of its least loaded worker's end (GATE-SPLIT-BY-WORKER) and its runner's load over RUNNER_LOAD,
    main's STAGES_S in its load and its floor, alone's after its timing-bound tests (GATE-ALONE-SHARE), so every job
    computes the same split."""
    parts = {'main': [], 'shard1': [], 'alone': [test for test in tests if test in named]}
    known = sorted(float(value) for value in hints.values() if value)
    usual = known[len(known) // 2] if known else 1.0  # a test with no hint weighs the median hint, never nothing

    def weight(test):
        return float(hints.get(test) or usual)
    # alone's timing-bound tests hold its whole runner before its share starts; main's stages run beside its batch on the
    # CPU it keeps, so they weigh on its runner's load, not on its workers
    before = {'main': 0.0, 'shard1': 0.0, 'alone': sum(map(weight, parts['alone']))}
    load = {'main': STAGES_S, 'shard1': 0.0, 'alone': 0.0}
    workers = {part: [0.0] * PART_WORKERS[part] for part in PARTS}

    def wall(part, seconds):  # GATE-PER-RUNNER: the part's wall with this test, by its runner and by its workers (main's
        # stages, one after another, hold it STAGES_S at least)
        return before[part] + max(STAGES_S if part == 'main' else 0.0, (load[part] + seconds) / RUNNER_LOAD,
                                  min(workers[part]) + seconds)
    for test in sorted((test for test in tests if test not in named), key=lambda test: (-weight(test), test)):
        seconds = weight(test)
        part = min(PARTS, key=lambda part: (wall(part, seconds), PARTS.index(part)))
        parts[part].append(test)
        load[part] += seconds
        slot = workers[part]
        slot[slot.index(min(slot))] += seconds
    return parts


def isolated_tests():
    """GATE-ISOLATED: the timing-bound tests run apart from the batch (the registry's gate.isolated_tests)."""
    import config  # scripts/lib, beside this file
    return list(config.get('gate.isolated_tests') or [])


def run(args, cwd=ROOT, env=None):
    done = subprocess.run(args, cwd=cwd, capture_output=True, text=True, env=env)
    return done.returncode, (done.stdout or '') + (done.stderr or '')


def plan(base, run=run):
    """The gate's plan of base...HEAD: {stages, tests, ...}."""
    with tempfile.TemporaryDirectory() as tmp:
        answer = Path(tmp) / 'plan.json'
        code, said = run(['scripts/gate-check', 'plan', 'checks', '--base', base],
                         env={**os.environ, 'TOWER_ANSWER_FILE': str(answer)})
        if code != 0 or not answer.is_file():
            raise RuntimeError(f'no plan: {said.strip()[-300:]}')
        return json.loads(answer.read_text())['plan']


def identity(run=run):
    """VERDICT-REUSE: (tree, parents) of HEAD."""
    code, tree = run(['git', 'rev-parse', 'HEAD^{tree}'])
    listed, line = run(['git', 'rev-list', '--parents', '-n', '1', 'HEAD'])
    if code != 0 or listed != 0 or not tree.strip() or not line.split():
        raise RuntimeError('no tree or parents for HEAD')
    return tree.strip(), line.split()[1:]


def verdict_key(base, planned, run=run, environ=None):
    """VERDICT-REUSE: (key, what it covers) of the verdict on HEAD judged against base with this plan."""
    environ = os.environ if environ is None else environ
    tree, parents = identity(run)
    body = {'version': KEY_VERSION, 'tree': tree, 'parents': parents, 'base': base,
            'stages': sorted(stage for stage in planned.get('stages') or [] if stage not in SKIPPED),
            'tests': sorted(planned.get('tests') or []), 'runner': {name: environ.get(name, '') for name in RUNNER}}
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest(), body


def recorded(repo, key, parents, run=run, parts=None):
    """VERDICT-REUSE: the id of a run of this repository on one of HEAD's parents that kept a green verdict under key,
    else None. A fork's run (its head in another repository), an expired record, another name or any error is None.
    GATE-PARTS: with parts, the run must have kept the verdict of every part named (`<name>-<part>`), all in that one
    run; a part asks for its own alone (GATE-PARTS-REUSE)."""
    names = [VERDICT + key] if not parts else [f'{VERDICT}{key}-{part}' for part in parts]
    runs = None
    for name in names:
        code, said = run(['gh', 'api', f'repos/{repo}/actions/artifacts?name={name}&per_page=100'])
        if code != 0:
            return None
        try:
            artifacts = json.loads(said).get('artifacts') or []
        except (ValueError, AttributeError):
            return None
        found = set()
        for each in artifacts:
            made = each.get('workflow_run') or {}
            if (each.get('name') == name and each.get('expired') is False and made.get('repository_id') is not None
                    and made.get('head_repository_id') == made.get('repository_id') and made.get('head_sha') in parents):
                found.add(made.get('id'))
        runs = found if runs is None else runs & found
        if not runs:
            return None
    return min(runs) if runs else None


def reuser(repo, base, run=run, environ=None, parts=None):
    """VERDICT-REUSE: judge's `reuse`: the plan -> the run whose green verdict of the tests stands, or None."""
    def reuse(planned):
        try:
            key, body = verdict_key(base, planned, run, environ)
            return recorded(repo, key, body['parents'], run, parts)
        except Exception:  # noqa: BLE001 - a lookup that fails is a miss: the tests run
            return None
    return reuse


def judge(base, run=run, clock=time.monotonic, tails=None, alone=None, every=False, reuse=None, isolated=isolated_tests,
          cpus=os.cpu_count, part=None, hints=costs, paces=None, metadata=None, stages_only=False, strict_alone=False):
    """(green, red names, the plan, seconds): every stage of the plan but SKIPPED, then its tests in one batch.
    VERIFY-TAIL: tails, when given, receives (name, the end of its output) for each red stage and each test still red.
    VERIFY-ALONE (the engine's FULL-RUN-ALONE): a test red in the batch runs again alone, and that verdict is its own; a
    hosted runner's 4 vCPUs starve the timing-bound ones beside the rest (infra-intask-standby: 110 s and red in the
    batch of PR #3, 10 s and green alone). alone, when given, receives the tests that were green only alone.
    FULL-SUITE-MAIN: every=True judges every script test of the checkout, not the diff's (the safety net after a merge).
    VERDICT-REUSE: reuse, when given, maps the plan to the run whose green verdict of these tests stands (planned's
    `reused`), else None and the tests run; the stages always run.
    GATE-ISOLATED (the Torre, 16/11/2026): the planned tests that isolated() names run one after another by
    themselves, at the same time as the batch of the others, which runs with one worker fewer; one still red runs once
    more alone after the batch, like a test red in the batch. infra-intask-standby beside a 4-worker batch was red and
    its rerun alone made the gate 98-146 s (32 of 150 runs); beside a 3-worker batch it passed in 14 s and the batch of
    a service change's 27 other tests took 42 s.
    GATE-PARTS (the Torre, 16/11/2026): part, when given, is this job's share of the plan, the others judged by the other
    jobs of the same tower/gate: main the stages and a share of the tests, shard1 another, alone the timing-bound tests
    by themselves on a runner of their own and then a share of the others (split(), GATE-ALONE-SHARE). planned['part']
    names it and planned['judged'] its checks; the plan, and the verdict's key, stay the whole plan's.
    GATE-PACE (the Torre's AWS review, 16/11/2026): in the main part the stages run one after another in a thread beside
    the batch, which keeps one worker fewer for them, instead of before it: on the hosted runner they were ~35 of main's
    57 s (#146's queue commit: main 57 s, shard1 22 s with more of the tests), and the queue gate waits for its slowest
    part. paces, when given, receives (name, seconds) of each stage and of the batch, for the job log to name the pace.
    PINNED-ON-GITHUB (D-070, D-335): stages_only runs the plan's stages and none of its tests: the job that judges a
    gate change with the base's gate (gate_pin.py overlay); the head's tests are the parts' to run."""
    began = clock()
    planned = plan(base, run)
    red = []
    tails = [] if tails is None else tails
    alone = [] if alone is None else alone
    shares = split(planned.get('tests') or [], set(isolated()), hints()) if part else None
    if part:
        planned['part'] = part
    paces = [] if paces is None else paces
    staged_red, staged_tails = [], []

    def stages():
        for stage in (planned.get('stages') or []) if part in (None, 'main') else []:
            if stage in SKIPPED:
                continue
            at = clock()
            if stage == METADATA:  # PR-METADATA-GITHUB: the GitHub pull request, not gate-check (D-329)
                code, said = (metadata or pr_metadata)()
            else:
                code, said = run(['scripts/gate-check', 'stage', stage, '--base', base])
            paces.append((stage, clock() - at))
            if code != 0:
                staged_red.append(stage)
                # a secret scan's output may quote what it found: the public job log never carries it
                staged_tails.append((stage, 'its output is not printed (a secret scan): run it locally'
                                     if stage.startswith('secret') else said[-TAIL:]))
    staging = threading.Thread(target=stages, name='verify-stages', daemon=True) if part == 'main' else None
    if staging:
        staging.start()
    else:
        stages()
    if stages_only:
        planned['judged'] = len([stage for stage in planned.get('stages') or [] if stage not in SKIPPED])
        planned['flakes'] = []
        planned['flake_rate'] = 0.0
        red[:0], tails[:0] = staged_red, staged_tails
        return not red, red, planned, clock() - began
    tests = planned.get('tests') or []
    judged_tests = 0
    if every:
        tests = sorted(path.relative_to(ROOT).as_posix() for path in (ROOT / 'scripts' / 'tests').glob('*.test.sh'))
        planned['tests'] = tests
    reused = reuse(planned) if tests and reuse is not None else None
    if reused is not None:
        planned['reused'] = reused
    elif tests:
        named = set(isolated())
        apart = [test for test in tests if test in named]
        batch = [test for test in tests if test not in named]
        if part:  # GATE-PARTS: this job's share; the timing-bound tests have a runner of their own, so no worker is kept
            apart = [test for test in shares[part] if test in named]
            batch = [test for test in shares[part] if test not in named]
        judged_tests = len(apart) + len(batch)
        verdicts = {}

        def by_themselves():
            for test in apart:
                verdicts[test] = run(['scripts/gate-check', 'test', test])
        beside = threading.Thread(target=by_themselves, name='verify-isolated', daemon=True) if apart else None
        if beside:
            beside.start()
            if part:  # GATE-ALONE-SHARE: alone's timing-bound tests by themselves first, then its share on the whole runner
                beside.join()
        failed = []
        with tempfile.TemporaryDirectory() as tmp:
            if batch:
                answer = Path(tmp) / 'tests.json'
                env = {**os.environ, 'TOWER_ANSWER_FILE': str(answer)}
                if (apart and not part) or staging:  # GATE-ISOLATED, GATE-PACE: one CPU of the runner is the isolated tests' or the stages'
                    env[WORKERS] = str(max(1, int(os.environ.get(WORKERS) or cpus() or 1) - 1))
                at = clock()
                code, out = run(['scripts/gate-check', 'tests', ','.join(batch)], env=env)
                spent_s = clock() - at
                answered = json.loads(answer.read_text()) if answer.is_file() else {}
                said, took = answered.get('tests', {}), answered.get('seconds') or {}
                slowest = sorted(((float(spent), test) for test, spent in took.items()), reverse=True)[:SLOWEST]
                named_slowest = ', '.join(f'{Path(test).name.removesuffix(".test.sh")} {spent:.1f} s' for spent, test in slowest)
                paces.append(('the batch of tests' + (f' ({named_slowest})' if slowest else ''), spent_s))
                planned['walls'] = {test: float(spent) for test, spent in took.items()}  # GATE-WALLS
                failed = [test for test in batch if said.get(test) != 'PASS']
                if code != 0 and not failed:
                    red.append('script tests')
                    tails.append(('script tests', out[-TAIL:]))
            if beside:
                beside.join()
            failed += [test for test in apart if verdicts.get(test, (1, ''))[0] != 0]
            for test in failed:
                again, said_alone = run(['scripts/gate-check', 'test', test])
                if again == 0:
                    alone.append(test)
                    if strict_alone:
                        red.append(f'{test} (flake)')
                        tails.append((f'{test} (flake)', 'failed in batch and passed alone (--strict-alone, D-355)\n'))
                else:
                    red.append(test)
                    tails.append((f'{test} (alone)', said_alone[-TAIL:]))
    if staging:
        staging.join()
    planned['flakes'] = list(alone)
    planned['flake_rate'] = (len(alone) / judged_tests) if judged_tests else 0.0
    red[:0], tails[:0] = staged_red, staged_tails  # the stages' first, as when they ran before the tests
    if part:
        planned['judged'] = ((len([stage for stage in planned.get('stages') or [] if stage not in SKIPPED])
                              if part == 'main' else 0) + len(shares[part]))
    return not red, red, planned, clock() - began


def pull_request(environ=None, given=None):
    """PR-METADATA-GITHUB: (number, head sha or None, must) of the pull request this run judges: --pr (given), else the
    event's pull request (GITHUB_EVENT_PATH: its number and head), else the number in the merge queue's branch name
    (merge_group.head_ref, GITHUB_REF), else a refs/pull/<n>/ ref. must: the event always names one (PR_EVENTS)."""
    environ = os.environ if environ is None else environ
    must = environ.get('GITHUB_EVENT_NAME') in PR_EVENTS
    if given:
        return int(given), None, must
    event = {}
    if environ.get('GITHUB_EVENT_PATH'):
        try:
            event = json.loads(Path(environ['GITHUB_EVENT_PATH']).read_text(encoding='utf-8')) or {}
        except (OSError, ValueError):
            event = {}
    pull = event.get('pull_request') if isinstance(event.get('pull_request'), dict) else {}
    if pull.get('number'):
        return int(pull['number']), (pull.get('head') or {}).get('sha'), must
    for ref in ((event.get('merge_group') or {}).get('head_ref'), environ.get('GITHUB_REF'), environ.get('GITHUB_HEAD_REF')):
        found = QUEUE_BRANCH.search(ref or '') or PULL_REF.match(ref or '')
        if found:
            return int(found.group(1)), None, must
    return None, None, must


def gh_json(run, path, lines=None):
    """`gh api` of path as JSON; with lines (a jq filter) it reads every page and answers the list of its lines' values."""
    args = ['gh', 'api', path] if lines is None else ['gh', 'api', '--paginate', path, '--jq', lines]
    code, said = run(args)
    if code != 0:
        raise RuntimeError(f'gh api {path}: {(said.strip().splitlines() or [""])[-1]}')  # gh says why on its last line
    try:
        return json.loads(said) if lines is None else [json.loads(line) for line in said.splitlines() if line.strip()]
    except ValueError as error:
        raise RuntimeError(f'gh api {path}: not JSON ({error})') from None


def github_pr(repo, number, head=None, run=run, root=ROOT):
    """PR-METADATA-GITHUB: the pull request in the shape forge_pr.fetch answers (what commit_check judges), read from
    GitHub and judged on head (the event's), else on its live head. Commit and PR file names come from the checkout
    when it holds the commits, else from GitHub."""
    import forge_pr  # scripts/lib, beside this file
    pull = gh_json(run, f'repos/{repo}/pulls/{number}')
    branch, base, live = pull['head']['ref'], pull['base']['ref'], pull['head']['sha']
    gated = head or live
    page = gh_json(run, f'repos/{repo}/pulls/{number}/commits?per_page=100',
                   '.[] | {sha, message: .commit.message, parents: [.parents[].sha]}')
    ref = urllib.parse.quote(f'refs/heads/{branch}', safe='')
    pushes = gh_json(run, f'repos/{repo}/activity?ref={ref}&activity_type=push&per_page=100',
                     '.[] | {before, after, timestamp}')
    forced = gh_json(run, f'repos/{repo}/activity?ref={ref}&activity_type=force_push&per_page=100',
                     '.[] | {before, after, timestamp}')
    comments = gh_json(run, f'repos/{repo}/issues/{number}/comments?per_page=100', '.[] | {body, created_at}')
    compare = gh_json(run, f'repos/{repo}/compare/{urllib.parse.quote(base, safe="")}...{gated}')
    merge_base = (compare.get('merge_base_commit') or {}).get('sha')
    if gated in {item['sha'] for item in page}:
        commits = forge_pr.gated_commits(page, gated)
    else:
        commits = forge_pr.local_commits(root, merge_base, gated)
        if commits is None:
            raise RuntimeError(f'head {gated} is neither on the pull request\'s commits nor in the checkout')
    names = forge_pr.local_files(root, [commit['sha'] for commit in commits])
    for commit in commits:
        commit['files'] = (names[commit['sha']] if names is not None
                           else gh_json(run, f'repos/{repo}/commits/{commit["sha"]}', '.files[].filename'))
    diff = forge_pr.git(root, 'diff', '--name-only', merge_base, gated) if merge_base and merge_base != gated else None
    files = (sorted(name for name in diff.splitlines() if name.strip()) if diff is not None
             else gh_json(run, f'repos/{repo}/pulls/{number}/files?per_page=100', '.[].filename'))
    moves = ('before', 'after', 'timestamp')
    return {'number': number, 'body': pull.get('body') or '', 'branch': branch, 'commits': commits,
            'created_at': pull.get('created_at'), 'draft': bool(pull.get('draft')), 'files': files,
            'comments': [{'body': item.get('body') or '', 'created_at': item.get('created_at')} for item in comments],
            'gated': {'sha': gated, 'live': live},
            'pushes': [{key: push.get(key) for key in moves} for push in pushes],
            'force_pushes': [{key: push.get(key) for key in moves} for push in forced],
            'base': {'ref': base, 'behind_by': compare.get('behind_by'), 'merge_base': merge_base}}


def pr_metadata(repo=None, number=None, head=None, must=False, run=run, root=ROOT, judge_pr=None):
    """PR-METADATA-GITHUB (D-329): (code, output) of the `pr metadata` stage on the GitHub pull request: the refusals
    and warnings of gate_discipline.pr_errors (judge_pr), one per line. No pull request: red when the event must name one,
    else nothing judged. A read error is red and never lifted (commit-check's blind read)."""
    if number is None:
        if must:
            return 1, 'FAIL pr metadata: the event names no pull request (no pull_request, no merge queue branch)\n'
        return 0, 'pr metadata: no pull request named: nothing judged\n'
    if judge_pr is None:
        import gate_discipline  # scripts/lib, beside this file: the gate's own PR discipline (D-322)
        judge_pr = gate_discipline.pr_errors
    try:
        pr = github_pr(repo, number, head, run, root)
    except (RuntimeError, KeyError, TypeError, AttributeError) as error:
        return 1, f'FAIL commit-check: PR #{number} not readable on GitHub ({error})\n'
    errors, warnings = judge_pr(pr, root)
    said = [f'FAIL {line}' for line in errors] + [f'WARN {line}' for line in warnings]
    said.append(f'pr metadata: PR #{number} at {pr["gated"]["sha"]}: {len(pr["commits"])} commit(s); '
                f'{len(errors)} refusal(s)')
    return (1 if errors else 0), '\n'.join(said) + '\n'


def post(repo, sha, state, description, run=run):
    """The commit status, through the session's `gh` (repository-scoped)."""
    code, said = run(['gh', 'api', '-X', 'POST', f'repos/{repo}/statuses/{sha}', '-f', f'state={state}',
                      '-f', f'context={CONTEXT}', '-f', f'description={description[:140]}'])
    if code != 0:
        raise RuntimeError(f'status not posted: {said.strip()[-300:]}')


def repo_of(run=run):
    code, url = run(['git', 'remote', 'get-url', 'origin'])
    url = url.strip().removesuffix('.git')
    if code != 0 or 'github.com/' not in url:
        raise RuntimeError('origin is not a GitHub repository: pass --repo')
    return url.split('github.com/', 1)[1]


def flake_entry(sha, base, planned, part=None, strict_alone=False):
    """D-355: structured VERIFY-ALONE flake telemetry record for one verify-commit run (compatible with
    config/validation/runs/flakes.json, D-351 operational weaknesses and D-353 trust indicator 3)."""
    flakes = list(planned.get('flakes') or [])
    return {
        'sha': sha,
        'base': base,
        'part': part,
        'flaked': bool(flakes),
        'alone': flakes,
        'flakes': flakes,
        'flake_count': len(flakes),
        'flake_rate': float(planned.get('flake_rate') or 0.0),
        'strict_alone': bool(strict_alone),
        'at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
    }


def record(directory, base, planned, sha, run=run, environ=None):
    """VERDICT-REUSE: the green verdict's key and what it covers in DIR/verdict.json, its name in $GITHUB_OUTPUT.
    GATE-PARTS: a part's verdict is kept as `<name>-<part>`; a reuse asks for every part's."""
    environ = os.environ if environ is None else environ
    key, body = verdict_key(base, {**planned, 'part': None}, run, environ)
    if planned.get('part'):
        key, body = f"{key}-{planned['part']}", {**body, 'part': planned['part']}
    directory.mkdir(parents=True, exist_ok=True)
    payload = {'key': key, 'sha': sha, **body, 'flakes': list(planned.get('flakes') or []),
               'flake_rate': float(planned.get('flake_rate') or 0.0)}
    (directory / 'verdict.json').write_text(json.dumps(payload, indent=2, sort_keys=True) + '\n')
    if environ.get('GITHUB_OUTPUT'):
        with open(environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as output:
            output.write(f'verdict={VERDICT}{key}\n')
    return VERDICT + key


def gate_mode(environ):
    """D-335: name this checkout in $OU_CONFIG_REGISTRY_ONLY, so the config layer of every stage and test the verifier
    runs reads registry defaults only, never the checkout's .tower/config (a head's forced add of an override)."""
    import config
    environ[config.REGISTRY_ONLY_ENV] = str(ROOT)
    return environ


def main(argv=None, run=run, environ=None):
    parser = argparse.ArgumentParser(prog='verify-commit', description=__doc__.splitlines()[0])
    parser.add_argument('--sha', required=True)
    parser.add_argument('--base', required=True)
    parser.add_argument('--repo')
    parser.add_argument('--pr', type=int, help='PR-METADATA-GITHUB: the pull request `pr metadata` judges (default: the '
                        'event\'s, or the merge queue branch\'s)')
    parser.add_argument('--no-post', action='store_true', help='judge and print; publish nothing')
    parser.add_argument('--all', action='store_true', help='every script test, not only the diff\'s (FULL-SUITE-MAIN)')
    parser.add_argument('--reuse', action='store_true',
                        help='VERDICT-REUSE: the tests\' green verdict recorded under the same key stands; the stages run')
    parser.add_argument('--part', choices=PARTS,
                        help='GATE-PARTS: judge this job\'s share of the plan; the other parts are other jobs')
    parser.add_argument('--record', type=Path, metavar='DIR',
                        help='VERDICT-REUSE: on green, write the verdict\'s key under DIR and name it in $GITHUB_OUTPUT')
    parser.add_argument('--stages-only', action='store_true',
                        help='PINNED-ON-GITHUB: the plan\'s stages only, no test (the pinned job of a gate change)')
    parser.add_argument('--flake-log', type=Path, metavar='FILE',
                        help='D-355: append a structured JSONL VERIFY-ALONE flake telemetry record to FILE')
    parser.add_argument('--strict-alone', action='store_true',
                        help='D-355: fail the run when any test fails in batch and passes alone (VERIFY-ALONE)')
    args = parser.parse_args(argv)
    if args.stages_only and (args.part or args.all or args.reuse or args.record or args.strict_alone):
        parser.error('--stages-only judges the stages alone: no --part, --all, --reuse, --record or --strict-alone')
    code, head = run(['git', 'rev-parse', 'HEAD'])
    if code != 0 or head.strip() != args.sha:
        print(f'verify-commit: HEAD is {head.strip()[:12]}, not {args.sha[:12]}: check out the commit it judges',
              file=sys.stderr)
        return 2
    repo = args.repo or repo_of(run)
    if not args.no_post:
        post(repo, args.sha, 'pending', 'the verifier is judging this commit', run)
    try:
        tails, alone = [], []
        # GATE-PARTS-REUSE (16/11): each part looks up its own share's verdict only; a part's key holds its job's runner
        # image, and the three jobs of one run may land on different images (#142: alone's key differed from main's and
        # shard1's), so asking one run for all three under one key was a miss even for an exact duplicate
        reuse = reuser(repo, args.base, run, environ, (args.part,) if args.part else None) if args.reuse else None
        paces = []
        number, head, must = pull_request(environ, args.pr)  # PR-METADATA-GITHUB (D-329)
        metadata = lambda: pr_metadata(repo, number, head, must, run)  # noqa: E731 - run in the stages' thread
        green, red, planned, seconds = judge(args.base, run, tails=tails, alone=alone, every=args.all, reuse=reuse,
                                             part=args.part, paces=paces, metadata=metadata,
                                             stages_only=args.stages_only, strict_alone=args.strict_alone)
    except Exception as error:  # noqa: BLE001 - a verifier that could not judge says so on the commit
        if not args.no_post:
            post(repo, args.sha, 'error', f'not judged: {error}', run)
        print(f'verify-commit: not judged: {error}', file=sys.stderr)
        return 1
    checks = len([stage for stage in planned.get('stages') or [] if stage not in SKIPPED]) + len(planned.get('tests') or [])
    if 'judged' in planned:  # GATE-PARTS: this job's share of them
        checks = planned['judged']
    description = ((f'{args.part}: ' if args.part else 'stages: ' if args.stages_only else '') + f'green: {checks} check(s) in {seconds:.0f} s' + (f', {len(alone)} green only alone' if alone else '')
                   + (f', tests green in run {planned["reused"]}' if 'reused' in planned else '')
                   if green else f'red: {", ".join(red)}'[:140])
    if not args.no_post:
        post(repo, args.sha, 'success' if green else 'failure', description, run)
    print(f'verify-commit: {args.sha[:12]} {description}')
    if 'reused' in planned:  # VERDICT-REUSE: said, so the job log names the run that judged the tests
        print(f'verify-commit: the tests\' green verdict of run {planned["reused"]} stands (the same tree, parents, base, '
              'plan and runner image); the stages ran')
    if green and args.record:
        try:
            print(f'verify-commit: recorded {record(args.record, args.base, planned, args.sha, run, environ)}')
        except Exception as error:  # noqa: BLE001 - no record only costs the merge queue's run its reuse
            print(f'verify-commit: no record: {error}', file=sys.stderr)
    walls = sorted(((spent, test) for test, spent in (planned.get('walls') or {}).items() if spent >= WALL_MIN_S), reverse=True)
    if walls:  # GATE-WALLS (the Torre, 18/11/2026): a test slow on the runner alone (infra-aws: 56 s here, 4 s locally) is seen
        print('verify-commit: walls: ' + ', '.join(f'{Path(test).name.removesuffix(".test.sh")} {spent:.1f} s'
                                                   for spent, test in walls))
    if paces:  # GATE-PACE: what the part's time went to, the slowest first
        print('verify-commit: pace: ' + ', '.join(f'{name} {spent:.1f} s' for name, spent in
                                                  sorted(paces, key=lambda pair: -pair[1])))
    if alone:  # VERIFY-ALONE: said, so a test that needs the machine to itself is seen, not hidden
        print(f'verify-commit: red in the batch and green alone: {", ".join(alone)}')
    if alone or args.flake_log:  # D-355: structured VERIFY-ALONE flake telemetry
        entry = flake_entry(args.sha, args.base, planned, part=args.part, strict_alone=args.strict_alone)
        encoded = json.dumps(entry, sort_keys=True)
        print(f'verify-commit: flake-metric {encoded}')
        if args.flake_log:
            args.flake_log.parent.mkdir(parents=True, exist_ok=True)
            with open(args.flake_log, 'a', encoding='utf-8') as handle:
                handle.write(encoded + '\n')
    for name, tail in tails:  # VERIFY-TAIL: what failed, where the verifier runs (a hosted job keeps no other log)
        print(f'--- verify-commit: the end of the output of {name} ---\n{tail.rstrip()}', file=sys.stderr)
    return 0 if green else 1


if __name__ == '__main__':
    gate_mode(os.environ)
    sys.exit(main())
