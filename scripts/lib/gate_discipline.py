"""The PR discipline the gate judges (D-022, D-025, D-329): the rules of a PR's commits, body and comments.

The gate's `pr metadata` stage (scripts/lib/verify_commit.py, tower/gate) judges a pull request with pr_errors(): the
commit plan, fix-ups, one commit per push, force pushes, a head behind its base without a merge of it, a gate change
citing no decision, an owner wait (decision_wait), the plan completeness and the lanes. They live in the gate layer so
the gate reads no delivery module (D-322); scripts/commit-check (scripts/lib/commit_check.py, delivery) re-exports
them for its callers and its command line.
"""
import re
import sys

import config
import decision_wait

try:
    import regime  # the exception regime (D-260, lane 4); until it lands every lock acts as it does today
except ImportError:
    regime = None

import plan_tick
from gate_pin import GATE_FILE

PLAN_ITEM = re.compile(r'^\s*[-*] \[[ xX]\] \d+\.\s+\S', re.M)
PLAN_MIN, PLAN_MAX = config.get('budgets.pr_commits_min'), config.get('budgets.pr_commits_max')
FIXUP_PREFIX = re.compile(r'^(fixup|squash|amend)! ')
FIXUP_SUBJECT = re.compile(r'^(fix|fixes|fixed|fixup)\b.*\b(tests?|ids?|lint|typos?|types?|build|imports?|snapshots?)\b', re.I)
DECISION = re.compile(r'\bD-\d{3}\b')
SHA = config.get('gate.pr_sha_chars')  # the characters of a sha a refusal prints


def plan_errors(body):
    """D-022: a commit plan checklist of numbered items, at least PLAN_MIN of them; D-307: no maximum while
    budgets.pr_commits_max is 0, its default, so a PR is split by its content and never by a counter."""
    items = len(PLAN_ITEM.findall(body or ''))
    if items >= PLAN_MIN and (not PLAN_MAX or items <= PLAN_MAX):
        return []
    bound = f'at least {PLAN_MIN}' if not PLAN_MAX else f'{PLAN_MIN}-{PLAN_MAX}'
    return [f'plan: the PR body needs a D-022 commit plan checklist of {bound} items ("- [ ] 1. ..."); found {items}']


def fixup_errors(commits):
    """A commit that only fixes the commit before it, by prefix or by a "fix test/ids" subject on its files only."""
    errors, previous = [], None
    for commit in commits:
        subject = commit['message'].splitlines()[0] if commit['message'] else ''
        own = not commit.get('parents', [])[1:]  # one parent or none: not a merge
        if own and FIXUP_PREFIX.match(subject):
            errors.append(f'fixup: {commit["sha"][:SHA]} "{subject}" is a fix-up commit; fold it into the commit it fixes')
        elif (own and previous is not None and FIXUP_SUBJECT.match(subject)
              and commit.get('files') and set(commit['files']) <= set(previous.get('files') or [])):
            errors.append(f'fixup: {commit["sha"][:SHA]} "{subject}" only fixes {previous["sha"][:SHA]}; '
                          'every commit must be green on its own')
        if own:
            previous = commit
    return errors


def reach(parents, sha):
    """The PR commits sha reaches through parents (itself included); commits outside the PR stop the walk."""
    seen, stack = set(), [sha]
    while stack:
        current = stack.pop()
        if current in parents and current not in seen:
            seen.add(current)
            stack.extend(parents[current])
    return seen


def carried_by_merge(parents, brought, before, after):
    """True when a push brought a merge of the branch's published head (before, a non-first parent of after) and the one
    commit it carries (after's first parent), nothing else: a commit made under a head another checkout moved
    (scripts/deliver pushes its merge of the base) can never go out alone, and the push guard sends it with that merge
    (VAZÃO F30). The pre-push count (local_checks.one_push_per_commit, merges excluded) counts that push as one commit."""
    merged = parents.get(after) or []
    return before in merged[1:] and brought == {after, merged[0]}


def push_errors(commits, pushes, number=None):
    """Each push may bring at most one commit of the PR. Pushes without a known before/after are not judged.
    What a push brought: the PR commits its after reaches and its before does not, when the PR's parents form one graph
    (every commit reached from the last); else, as the forge lists them, the commits between before and after. A list in
    date order puts a commit made under a moved head before the merge another checkout pushed (VAZÃO F30), so the order
    alone would charge that merge's push with it. A merge of the branch's published head may carry the one commit made
    under it (carried_by_merge). The refusal names the remedy, scripts/replay-branch (X1): pushed history is never
    rewritten."""
    order = {commit['sha']: index for index, commit in enumerate(commits)}
    parents = {commit['sha']: list(commit.get('parents') or []) for commit in commits}
    graph = bool(commits) and reach(parents, commits[-1]['sha']) == set(parents)
    errors = []
    for push in pushes:
        after = order.get(push.get('after'))
        if after is None:
            continue
        before = order.get(push.get('before'), -1)
        if graph:
            brought = reach(parents, push['after']) - reach(parents, push.get('before'))
            if len(brought) > 1 and carried_by_merge(parents, brought, push.get('before'), push['after']):
                continue
            listed = [commit for commit in commits if commit['sha'] in brought]
        else:
            listed = commits[before + 1:after + 1]
        brought = len(listed)
        if brought > 1:
            shas = ', '.join(commit['sha'][:SHA] for commit in listed)
            errors.append(f'push: {brought} commits pushed at the same instant ({push.get("timestamp", "?")}: {shas}); '
                          f'push each commit as it is done (D-022); fix: scripts/replay-branch {number or "<pr>"}')
    return errors


def force_push_errors(force_pushes, branch=None, number=None):
    """Merge commits only: a force push on the PR head ref rewrote pushed history, which no repair on the same branch undoes.
    The remedy is a new branch, scripts/replay-branch (X1)."""
    return [f'force-push: {branch or "the head ref"} was force-pushed at {push.get("timestamp", "?")} '
            f'({(push.get("before") or "?")[:SHA]} -> {(push.get("after") or "?")[:SHA]}); pushed history is never rewritten '
            f'(merge commits only, no rebase or amend); fix: scripts/replay-branch {number or "<pr>"} replays the PR on a new branch'
            for push in force_pushes]


def rebase_errors(base, commits, branch=None):
    """A head behind its base must carry a merge commit of the base: a PR commit whose non-first parent is the merge
    base of base...head (what `git merge <remote>/<base>` leaves). An unknown compare is not judged, nor a head the base
    already contains (the merge base is the head: a merged PR).

    The rule is the registry's (GX-22, config/registry/merge.json): with the P-G3 switch merge.tier1_requires_base_merge
    on (default, today's rule) the limit without a merge of the base is 0; off, a head at most merge.max_behind_base
    behind passes, since the train re-proves the batch on the tip. Merge commits only either way (FP1). The refusal
    names "N behind, limit M", the verdict line merge_behind.limit_line prints for merge-phase."""
    behind, merge_base = (base or {}).get('behind_by'), (base or {}).get('merge_base')
    if not behind or not merge_base or (commits and commits[-1]['sha'] == merge_base):
        return []
    if any(merge_base in commit.get('parents', [])[1:] for commit in commits):
        return []
    limit = 0 if config.get('merge.tier1_requires_base_merge') else config.get('merge.max_behind_base')
    if behind <= limit:
        return []
    name = base.get('ref') or '<base>'
    return [f'rebase: {branch or "the head"} is {behind} commit(s) behind {name} and no commit of the PR merges it '
            f'({behind} behind, limit {limit}; merge base {merge_base[:SHA]}); bring the base in with '
            f'`git merge {config.get("push-guard.remote")}/{name}` (a merge commit), never a rebase or force push']


def decisions(root):
    path = root / 'docs/domain/DECISIONS.md'
    text = path.read_text() if path.is_file() else ''
    return {match.group(1) for match in re.finditer(r'^\| (D-\d{3}) \|', text, re.M)}


def gate_errors(body, files, known):
    """A change to the gate cites a D-NNN recorded in DECISIONS.md."""
    touched = sorted(name for name in files if GATE_FILE.match(name))
    if not touched:
        return []
    cited = set(DECISION.findall(body or '')) & known
    if cited:
        return []
    listed = config.get('gate.pr_gate_files_listed')
    return [f'gate: the PR changes the gate ({", ".join(touched[:listed])}{" ..." if len(touched) > listed else ""}) '
            'without citing an approved D-NNN of docs/domain/DECISIONS.md in its body']


def gated_push_time(pr):
    """When the gated head reached GitHub: pr.gated.pushed_at, else the latest push whose after is the gated sha."""
    gated = pr.get('gated') or {}
    if gated.get('pushed_at'):
        return gated['pushed_at']
    times = [push.get('timestamp') for push in pr.get('pushes', []) if gated.get('sha') and push.get('after') == gated['sha']]
    return max((time for time in times if time), default=None)


def lifted(lock):
    """True when the exception regime lifts this lock (D-260). Without the regime module nothing is lifted."""
    return regime is not None and bool(regime.lifted(lock))


def lift(errors, lock):
    """The refusals of one lock: a lifted lock warns, names itself and refuses nothing (D-260)."""
    if not errors or not lifted(lock):
        return errors
    for line in errors:
        print(f'WARN lock {lock} lifted by the exception regime: {line}', file=sys.stderr)
    return []


def check(pr, known):
    commits = pr.get('commits', [])
    files = pr.get('files') or sorted({name for commit in commits for name in commit.get('files') or []})
    return (lift(plan_errors(pr.get('body', '')), 'commit-plan') + lift(fixup_errors(commits), 'commit-plan')
            + lift(push_errors(commits, pr.get('pushes', []), pr.get('number')), 'commit-plan')
            + force_push_errors(pr.get('force_pushes', []), pr.get('branch'), pr.get('number'))
            + rebase_errors(pr.get('base'), commits, pr.get('branch')) + gate_errors(pr.get('body', ''), files, known)
            + decision_wait.errors(decision_wait.before(pr.get('comments', []), gated_push_time(pr)), pr.get('number'),
                                   body=pr.get('body', '')))  # I-c16f2b7c: the body waits on the owner too


def plan_completeness_errors(body, commits):
    """GX-21: errors naming the plan items of the body that no real commit ticks. commits: [{message, files}]. A body
    without items is plan_errors' to refuse; an empty commit ticks nothing (plan_tick.ticked_by_commits)."""
    missing = plan_tick.unticked(body, commits)
    if not missing:
        return []
    numbers = ', '.join(str(number) for number in missing)
    return [f'plan: item(s) {numbers} not ticked by a commit that changes a file (an empty commit ticks nothing); fix: edit the '
            f'PR body so the plan lists what the commits deliver, or add a REAL commit with the "Plan: N" trailer, never an empty one']


def plan_verdict(body, commits, draft):
    """D-083: (errors, warnings) of the plan completeness of a PR head. A draft's head is judged on what its commits
    delivered: an item not yet ticked is a warning, so a serial PR can be green on every commit while its plan is still a
    plan; a PR marked ready is refused as GX-21 says. pr.ready waits for every item either way (pr_ready, D-065 V4)."""
    missing = plan_completeness_errors(body, commits)
    if not draft:
        return missing, []
    return [], [f'{line} [draft PR: refused once it is marked ready; pr.ready waits for every item (D-083)]'
                for line in missing]


def lane_errors(root, merge_base, files):
    """GX-21: errors when the files touch the units of several lanes (the lane is undecidable and the train would refuse
    it), listing each unit with its lane. A change touching no unit, or only shared paths, has no lane and is fine; the
    rule is train_ownership's lanes(), the one lane_of() reads (LANE-OWN)."""
    import git_objects  # not at import: the pre-push path never judges lanes
    import train_ownership
    tree = git_objects.Tree(root, timeout=config.get('train.git_timeout_s'))
    touched = train_ownership.UnitOwnership(tree).lanes(merge_base, files, 'HEAD')  # D-112
    if len(set(touched.values())) <= 1:
        return []
    listed = ', '.join(f'{unit} ({lane})' for unit, lane in sorted(touched.items()))
    return [f'lane undecidable: the change touches units of several lanes: {listed}; split it into one PR per lane']


def pr_errors(pr, root):
    """(errors, warnings) of a PR as the gate's `pr metadata` stage judges its commits (D-322: these left the structure
    check, a lower layer): the discipline of check(), the plan completeness of plan_verdict() and the lanes of
    lane_errors() on the merge base. The plan and lane refusals stay under the `structure` lock they were born in."""
    errors = check(pr, decisions(root))
    plan, warnings = plan_verdict(pr.get('body', ''), pr.get('commits', []), pr.get('draft', False))
    merge_base = (pr.get('base') or {}).get('merge_base')
    lanes = lane_errors(root, merge_base, pr.get('files') or []) if merge_base else []
    return errors + lift(plan + lanes, 'structure'), warnings
