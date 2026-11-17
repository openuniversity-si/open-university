"""A pull request as the gate judges it, read through the forge port on the gated sha (GX-14).

fetch(number, sha, root, head, observation) answers the PR's body, commits (with files), changed files, branch pushes,
force pushes, comments and the head's standing against its base: the one reading the commit discipline
(commit_check, delivery) and the structure check's PR metadata (structure, planning) both judge, so it lives under both,
in the events layer (D-322). It reads; it judges nothing. git, local_files, gated_commits and local_commits are its
helpers (commit_check re-exports them).
"""
from pathlib import Path
import subprocess
import sys

import config

REPO = config.get('forge-events.repo')  # the forge's slug for this repository (ORIGIN-FINISH: Origin's)


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
                                    'commit-check', f'pr-{number}', consumer='scripts/lib/forge_pr.py')
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

