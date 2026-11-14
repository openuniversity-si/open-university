"""Commit discipline of a PR (D-022, enforced by D-025).

scripts/commit-check --pr N [--sha S] reads the PR through the GitHub REST client the tail uses, judged on the gated
commit S (structure-check passes its checkout's HEAD), and refuses:
  plan       the body has no D-022 commit plan checklist (at least one item; no maximum unless the registry sets one, D-307);
  fixup      a commit only fixes the previous commit of the same PR (every commit must be green on its own);
  push       one push brought several commits of the PR at the same instant (push them one by one; the
             .githooks push each commit alone, and scripts/replay-branch N is the remedy of a batched push);
  force-push the PR head ref has force_push activity: pushed history was rewritten (merge commits only; FP1). Branch
             protection is unavailable, so the gate refuses it; scripts/replay-branch N builds a new branch;
  rebase     the head is behind its base by more than the registry allows and no PR commit merges the base (a rebased
             or never-updated branch; limit 0 while merge.tier1_requires_base_merge is on, else merge.max_behind_base):
             bring the base in with `git merge <push-guard.remote>/<base>`, a merge commit, never a rebase (FP1);
  gate       the PR changes the gate without citing an approved D-NNN of docs/domain/DECISIONS.md;
  decision   a PR comment waits on an owner decision and no later comment records a "Decision:" line
             (DECIDE, THEN REPORT, Daniel 2026-10-26 21:29; scripts/lib/decision_wait.py). Only comments created up to
             the gated head's push are judged (GX-14): a comment during the gate does not change its verdict.
--fixture FILE checks the same shape from JSON (tests, no network). Exit 1 on a refusal.
--local runs the fast registry-driven local checks (scripts/lib/local_checks.py, LR1): one push per commit, the gate cites a
decision, a diff secret scan, no registered literal, the cheap structure checks. --body-file gives the PR body, --stdin-refs
reads the pre-push lines (.githooks/pre-push). A check over its budget moves to the gate; one that cannot run is skipped.
"""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys

import config
import decision_wait

try:
    import regime  # the exception regime (D-260, lane 4); until it lands every lock acts as it does today
except ImportError:
    regime = None

ROOT = Path(__file__).resolve().parents[2]
REPO = config.get('forge-events.repo')  # the forge's slug for this repository (ORIGIN-FINISH: Origin's)
PLAN_ITEM = re.compile(r'^\s*[-*] \[[ xX]\] \d+\.\s+\S', re.M)
PLAN_MIN, PLAN_MAX = config.get('budgets.pr_commits_min'), config.get('budgets.pr_commits_max')
FIXUP_PREFIX = re.compile(r'^(fixup|squash|amend)! ')
FIXUP_SUBJECT = re.compile(r'^(fix|fixes|fixed|fixup)\b.*\b(tests?|ids?|lint|typos?|types?|build|imports?|snapshots?)\b', re.I)
GATE_FILE = re.compile(r'^scripts/(gate-[^/]+|lib/gate[^/]*|structure-check|lib/structure\.py|commit-check|lib/commit_check\.py)$')
DECISION = re.compile(r'\bD-\d{3}\b')


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
        own = len(commit.get('parents', [])) < 2
        if own and FIXUP_PREFIX.match(subject):
            errors.append(f'fixup: {commit["sha"][:7]} "{subject}" is a fix-up commit; fold it into the commit it fixes')
        elif (own and previous is not None and FIXUP_SUBJECT.match(subject)
              and commit.get('files') and set(commit['files']) <= set(previous.get('files') or [])):
            errors.append(f'fixup: {commit["sha"][:7]} "{subject}" only fixes {previous["sha"][:7]}; '
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
    return len(merged) >= 2 and before in merged[1:] and brought == {after, merged[0]}


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
            shas = ', '.join(commit['sha'][:7] for commit in listed)
            errors.append(f'push: {brought} commits pushed at the same instant ({push.get("timestamp", "?")}: {shas}); '
                          f'push each commit as it is done (D-022); fix: scripts/replay-branch {number or "<pr>"}')
    return errors


def force_push_errors(force_pushes, branch=None, number=None):
    """Merge commits only: a force push on the PR head ref rewrote pushed history, which no repair on the same branch undoes.
    The remedy is a new branch, scripts/replay-branch (X1)."""
    return [f'force-push: {branch or "the head ref"} was force-pushed at {push.get("timestamp", "?")} '
            f'({(push.get("before") or "?")[:7]} -> {(push.get("after") or "?")[:7]}); pushed history is never rewritten '
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
            f'({behind} behind, limit {limit}; merge base {merge_base[:7]}); bring the base in with '
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
    return [f'gate: the PR changes the gate ({", ".join(touched[:4])}{" ..." if len(touched) > 4 else ""}) '
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
            + decision_wait.errors(decision_wait.before(pr.get('comments', []), gated_push_time(pr)), pr.get('number')))


def git(root, *args):
    """stdout of a git command in root, else None (no checkout, unknown commit, shallow history)."""
    if root is None:
        return None
    done = subprocess.run(['git', '-C', str(root), *args], capture_output=True, text=True)
    return done.stdout if done.returncode == 0 else None


def local_files(root, shas):
    """{sha: files changed against its first parent} for every sha from one git log, else None."""
    if not shas:
        return {}
    out = git(root, 'log', '--no-walk=unsorted', '--diff-merges=first-parent', '--name-only', '--format=%x00%H', *shas)
    if out is None:
        return None
    files = {}
    for record in out.split('\0')[1:]:
        sha, _, names = record.partition('\n')
        files[sha.strip()] = [name for name in names.splitlines() if name.strip()]
    return files if set(shas) <= set(files) else None


def gated_commits(page, gated):
    """PLAN-COMMIT-ORDER: the commits of the PR's page the gated sha reaches through its parents, oldest first, whatever
    the page's order. Origin lists a PR's commits newest first, and the page cut at the gated sha's index (an oldest-first
    reading) kept the gated commit alone: a head that is the live service's merge of the base (#678, #690) had its own
    commits out of the plan's count ('item 1 not ticked'), and so had every earlier commit of a PR of several."""
    by = {item['sha']: item for item in page}
    reached, todo = set(), [gated]
    while todo:
        sha = todo.pop()
        if sha in by and sha not in reached:
            reached.add(sha)
            todo.extend(by[sha].get('parents') or [])
    ordered, placed = [], set()

    def place(sha):  # parents first: oldest first, as local_commits answers
        stack = [(sha, False)]
        while stack:
            current, ready = stack.pop()
            if current in placed or current not in reached:
                continue
            if ready:
                placed.add(current)
                ordered.append(current)
                continue
            stack.append((current, True))
            stack.extend((parent, False) for parent in reversed(by[current].get('parents') or []))
    for item in reversed(page) if page and page[0]['sha'] == gated else page:
        place(item['sha'])
    return [{'sha': sha, 'message': by[sha]['message'], 'parents': list(by[sha].get('parents', []))} for sha in ordered]


def local_commits(root, merge_base, sha):
    """The commits of merge_base..sha, oldest first, with message and parents, when the gated sha is not on the page."""
    out = git(root, 'log', '--reverse', '--topo-order', '--format=%x00%H%x01%P%x01%B', f'{merge_base}..{sha}') if merge_base else None
    if out is None:
        return None
    commits = []
    for record in out.split('\0')[1:]:
        head, _, rest = record.partition('\x01')
        parents, _, message = rest.partition('\x01')
        commits.append({'sha': head.strip(), 'message': message.strip('\n'), 'parents': parents.split()})
    return commits


def fetch(number, sha=None, root=None, head=None, observation=None):
    """The PR's body, commits (with files), changed files, branch pushes, force pushes, comments and the head's standing
    against its base through the forge port, judged on the gated sha (GX-14): sha, else the live head. A push while the gate
    runs does not move what it judges. Commit and PR file names come from the local checkout (root) when it holds the
    gated sha, so a PR costs six calls whatever its size; without it they fall back to one forge call per commit.
    head is a checkout's HEAD (structure-check in the gate's checkout): it is the gated sha when it is a PR commit."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import forge_events
    # PR-OBSERVATION: with an observation, what the live service read with the forge's key; else the forge, live
    adapter = forge_events.adapter_of_observation(observation) if observation else forge_events.adapter_from_config()
    port = forge_events.ForgeEvents(adapter, forge_events.clock_from_config(),
                                    'commit-check', f'pr-{number}', consumer='scripts/lib/commit_check.py')
    from concurrent.futures import ThreadPoolExecutor
    # Independent reads belong to the same gated snapshot, but need not pay six network round trips in series.
    with ThreadPoolExecutor() as reads:
        pending_pull = reads.submit(lambda: port.pull(REPO, number))
        pending_page = reads.submit(lambda: port.change_commits(REPO, number))
        pending_comments = reads.submit(lambda: port.comments(REPO, number))
        pull = pending_pull.result()
        pending_pushes = reads.submit(lambda: port.pushes(REPO, pull['head_ref']))
        pending_forced = reads.submit(lambda: port.force_pushes(REPO, pull['head_ref']))
        page = pending_page.result()
        live = pull['head_sha']
        shas = [item['sha'] for item in page]
        gated = sha or (head if head in shas else live)
        base = pull['base_ref']
        pending_compare = reads.submit(lambda: port.compare(REPO, base, gated))
        compare = pending_compare.result()
        pushes, forced, comments = pending_pushes.result(), pending_forced.result(), pending_comments.result()
    merge_base = compare['merge_base']
    if gated in shas:
        commits = gated_commits(page, gated)
    else:
        commits = local_commits(root, merge_base, gated)
        if commits is None:
            raise RuntimeError(f'gated sha {gated} is neither on the PR commits page nor in the checkout {root}')
    names = local_files(root, [commit['sha'] for commit in commits])
    for commit in commits:
        if names is not None:
            commit['files'] = names[commit['sha']]
        else:
            commit['files'] = [entry['filename'] for entry in port.commit_files(REPO, commit['sha'])]
    diff = git(root, 'diff', '--name-only', merge_base, gated) if merge_base and merge_base != gated else None
    if diff is not None:
        files = sorted(name for name in diff.splitlines() if name.strip())
    else:  # no local tree, or a head the base already contains (a merged PR): the PR's own file list
        files = [entry['filename'] for entry in port.change_files(REPO, number)]
    return {'number': number, 'body': pull.get('body') or '', 'branch': pull['head_ref'], 'commits': commits,
            'created_at': pull.get('created_at'), 'draft': bool(pull.get('draft')),  # D-083: plan completeness when ready
            'files': files, 'comments': [{'body': item['body'], 'created_at': item['created_at']}
                                       for item in comments], 'gated': {'sha': gated, 'live': live},
            'pushes': [{'before': p.get('before'), 'after': p.get('after'), 'timestamp': p.get('timestamp')} for p in pushes],
            'force_pushes': [{'before': p.get('before'), 'after': p.get('after'), 'timestamp': p.get('timestamp')} for p in forced],
            'base': {'ref': base, 'behind_by': compare.get('behind_by'), 'merge_base': merge_base}}


def main(argv=None):
    parser = argparse.ArgumentParser(prog='scripts/commit-check', description=__doc__.splitlines()[0])
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--local', action='store_true', help='the fast local checks of local-checks.checks (no network)')
    source.add_argument('--pr', type=int, help='PR number, read through the forge port')
    parser.add_argument('--sha', help='--pr: the gated commit to judge (default: the live PR head)')
    source.add_argument('--fixture', type=Path, help='JSON with body, commits, files, pushes, force_pushes, base and comments (tests)')
    parser.add_argument('--root', type=Path, default=ROOT, help='checkout whose DECISIONS.md is cited (--local: the checkout checked)')
    parser.add_argument('--body-file', type=Path, help='--local: file with the PR body')
    parser.add_argument('--stdin-refs', action='store_true', help='--local: read the pre-push lines from stdin')
    parser.add_argument('--only', metavar='NAME', help='--local: run only the local check of that id (D-236)')
    args = parser.parse_args(argv)
    if args.local:
        import local_checks  # not at import: local_checks reaches structure, which imports this module
        return local_checks.main(args.root.resolve(), args.body_file, args.stdin_refs, only=args.only)
    try:
        pr = json.loads(args.fixture.read_text()) if args.fixture else fetch(args.pr, args.sha, args.root.resolve())
    except RuntimeError as error:
        print(f'FAIL commit-check: {error}')
        return 1
    errors = check(pr, decisions(args.root.resolve()))
    for line in errors:
        print('FAIL ' + line)
    print(f'commit-check: {len(pr.get("commits", []))} commit(s); {len(errors)} refusal(s)')
    return 1 if errors else 0


if __name__ == '__main__':
    sys.exit(main())
