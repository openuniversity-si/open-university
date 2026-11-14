"""Deliver a PR in one call: the gate on the exact head, the merge with --expect-head, the base refreshed and PR/s printed.

`scripts/deliver --pr N` runs from the checkout of the PR's head branch. It refuses when the local head is not the
pushed head (push first), runs `scripts/gate-dev --pr N` on it, merges with `origin pr merge N --expect-head N=<head>`
(a merge commit into the base), then checks out the base, fast-forwards it to the merge and prints the PR/s line of
`scripts/flow-metrics --prs 10`. It stops at the first step before the merge that fails and says which one; a fetch
that loses a ref lock race to another lane is tried again, and once Origin has merged the delivery exits 0, with a
warning when the refresh failed (F11, VAZÃO). One call instead of the five a
session made by hand for every delivery (SEMENTE cycle, 03/11). When the infrastructure's port is configured
(TOWER_PORT_URL and TOWER_PORT_TOKEN), every gate round also starts `scripts/gate-infra shadow` on the same head, beside
the box's gate and never waited on (GATE-INFRA 2, P5 F2: the box and the infrastructure judge the same heads).

`--branch B` delivers the pushed head of B from its own worktree (`.gate/deliver/pr-N`, detached at `<remote>/B`, the
checkout's toolchain linked in) and leaves the session's checkout alone: the session starts `deliver` in the background
and writes the next PR while the gate runs, since the gate judges the tree it runs in. The refresh is the fetch of the base;
no local branch is moved. The wrapper runs the base's own deliver for --branch (scripts/deliver).

The box batch (VAZÃO F36, D-297; docs/programs/vazao/design-trem.md §2): with delivery.batch `auto` a delivery of a
branch writes its entry to the box queue (box_queue.enqueue) before it asks for the box's lock. Once it holds the lock:
a result the leader of an earlier batch wrote for its head is its answer (merged: exit 0; ejected, conflicted or
refused: exit 1), with no gate; with two or more live deliveries waiting and the batch reading ready (F64: the box busy
>= 0.70 over the last hour and p <= 0.25, flow_metrics.measured_batch_reading) it leads one batch, `scripts/train run --box`
in the base's checkout with the lock passed down (box_queue.HELD_ENV), and the batch's line goes to the lock log; its
own PR, when the batch did not resolve it (no batch, or it waited after the culprit), then takes today's single path.
With delivery.batch `off` (the default, the one-key rollback) nothing of this runs.

After a merge, outside the box's lock, the quota ledger is refreshed (`scripts/usage --lanes --write`, F59; a failure
is a warning). After a merge (VAZÃO F60), outside the box's lock: a merge whose subject names a queue unit (`Fnn: ...` or `(Fnn)`)
gets its diary line, one `scripts/plan note` call per delivery (never a loop: batched writes race the gates for the
git-ref log), and one line in the local closed-rows record (QUEUE_CLOSED). `scripts/deliver --close-queue` applies the
record to the queue table of the checkout it runs in, so the coordinator commits the closed rows of many deliveries in
one change and parallel lanes never edit the table's adjacent rows (adjacent deletions conflict in a git merge).

A docs-only delivery (VAZÃO F62, D-301): with --branch, when the area plan of the head's diff against the base selects
no script test and no path is under scripts/, the delivery takes no box lock and joins no batch: the base merge, the
gate on the exact head and the merge with --expect-head run as below, with the same re-judgment when the base moves.
"""
import argparse
import contextlib
import fcntl
import json
import os
import re
import resource
import shutil
import tempfile
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

import box_queue  # noqa: E402
import config  # noqa: E402
import gate_areas  # noqa: E402
import gate_classify  # noqa: E402
import merge_train  # noqa: E402

ROUNDS = 3  # gates of one delivery while the base keeps moving under it
WINDOW = 10  # merges in the PR/s window printed after the merge (SEMENTE section 4)
FETCH_TRIES = 4  # fetches of one ref while another lane's fetch holds its lock (the lanes share one .git)
FETCH_PAUSE = 0.5  # seconds before the next try, times the try number
REFUSED = 2  # the exit of a delivery refused before its gate: nothing gated or merged
QUEUE = Path('docs/programs/vazao/fila.md')  # the queue whose rows a delivery closes (F60)
QUEUE_PROGRAM = 'vazao'
QUEUE_CLOSED = Path.home() / '.cache' / 'the-tower' / 'queue-closed.jsonl'  # one line per delivered unit
# one unit per title: `F57: ...`, `VAZÃO F58: ...`, `F57 PR 2: ...`, `(F51)`, `(VAZÃO F51)`, `(F62, D-301)`; a list of
# units (a queue batch: `(F60, F61 enter)`, `queue rows F62, F64-F71`) names no single delivered unit and matches nothing
UNIT = re.compile(r'^(?:VAZ[ÃA]O )?(F\d+)[:\s]|\((?:VAZ[ÃA]O )?(F\d+)(?:,\s*D-\d+)*\)')
MERGE_SHA = re.compile(r'Merge commit:\s*([0-9a-f]{7,40})')
PR_REF = re.compile(r'\(#(\d+)\)\s*$')  # the `(#N)` Origin ends a merge subject with
LOCK_RACE = re.compile(r"cannot lock ref|\.lock'?: File exists|unable to update local ref", re.IGNORECASE)


# FRONT-AUTH-ONCE (critério 3: the gate's p99 to 10 s): a `git ls-remote` of the base at the front took 1.9 to 2.6 s, of
# which ~2 s were git's own credential dance (an anonymous request, a 401, the helper: `origin auth token` and the helper
# itself, ~0.9 s, then the request again); with the credentials in a header it is one request, 0.34 to 0.58 s. They are
# asked once per process (git credential fill, whatever helper the machine has), ahead of the front (prefetch_auth), and
# go to git in its environment (GIT_CONFIG_*), never in argv; a failed call is tried again the old way
FORGE_AUTH = {}
NETWORK = (('git', 'ls-remote'), ('git', 'fetch'))


def prefetch_auth(remote, root, run=subprocess.run):
    """FRONT-AUTH-ONCE: the remote's credentials asked in a thread, for the calls to come; an https remote only."""
    import base64
    import threading

    def ask():
        try:
            url = run(['git', 'remote', 'get-url', remote], cwd=str(root), capture_output=True, text=True).stdout.strip()
            if not url.startswith('https://') or remote in FORGE_AUTH:
                return
            said = run(['git', 'credential', 'fill'], cwd=str(root), capture_output=True, text=True, timeout=30,
                       input=f'url={url}\n\n', env={**os.environ, 'GIT_TERMINAL_PROMPT': '0'})
            found = dict(line.split('=', 1) for line in (said.stdout or '').splitlines() if '=' in line)
            if said.returncode == 0 and found.get('username') and found.get('password'):
                basic = base64.b64encode(f"{found['username']}:{found['password']}".encode()).decode()
                FORGE_AUTH[remote] = {'GIT_CONFIG_COUNT': '2', 'GIT_CONFIG_KEY_0': 'credential.helper', 'GIT_CONFIG_VALUE_0': '',
                                      'GIT_CONFIG_KEY_1': 'http.extraHeader',
                                      'GIT_CONFIG_VALUE_1': f'Authorization: Basic {basic}'}
        except Exception:  # noqa: BLE001 - the calls go the old way
            pass
    thread = threading.Thread(target=ask, name='forge-auth', daemon=True)
    thread.start()
    return thread


def auth_env(argv):
    """FRONT-AUTH-ONCE: the environment of a network git call to a remote whose credentials were asked, else None."""
    if tuple(argv[:2]) not in NETWORK:
        return None
    remote = next((each for each in argv[2:] if not str(each).startswith('-')), None)
    found = FORGE_AUTH.get(remote)
    return {**os.environ, **found} if found else None


def output(run, argv, root):
    env = auth_env(argv)
    if env is not None:
        done = run(argv, cwd=str(root), capture_output=True, text=True, env=env)
        if done.returncode == 0:
            return done.returncode, (done.stdout or '').strip(), (done.stderr or '').strip()
    done = run(argv, cwd=str(root), capture_output=True, text=True)
    return done.returncode, (done.stdout or '').strip(), (done.stderr or '').strip()


def fetch(run, remote, ref, cwd):
    """(code, err) of `git fetch remote ref`, tried again while it loses a ref lock race: lanes are worktrees of one
    checkout and share its .git, so two deliveries fetching the base at once collide on `refs/remotes/<remote>/<ref>`
    (`cannot lock ref ... is at X but expected Y`, two lanes on 03/11). Any other failure is returned at once."""
    for attempt in range(1, FETCH_TRIES + 1):
        code, _, err = output(run, ['git', 'fetch', '--quiet', remote, ref], cwd)
        if code == 0 or not LOCK_RACE.search(err) or attempt == FETCH_TRIES:
            return code, err
        time.sleep(FETCH_PAUSE * attempt)
    return code, err


def reason(code, *texts):
    """What a failed command said: its stderr and stdout, both kept (Origin refuses a merge on either, and a conflict
    prints on stdout), else its exit code, so a refusal is never printed empty (03/11: 90-240 s lost each time)."""
    said = '\n'.join(text for text in texts if text)
    return said or f'exit {code}, no output'


def conflicts(run, tree, ours, theirs):
    """The paths that conflict when `theirs` merges into `ours`, from `git merge-tree --write-tree --name-only` (the tree
    id, then one conflicted path a line, then a blank line and the messages); [] when they merge clean or it cannot tell."""
    code, said, _ = output(run, ['git', 'merge-tree', '--write-tree', '--name-only', ours, theirs], tree)
    if code != 1:
        return []
    paths = []
    for line in said.splitlines()[1:]:
        if not line.strip():
            break
        paths.append(line.strip())
    return paths


def _conflict_text(paths):
    return f'conflicting paths: {", ".join(paths)}'


def deliver(pr, root=ROOT, run=subprocess.run, out=print, branch=None):
    said = []
    out = _recording(out, said)
    remote, base, cli = config.get('push-guard.remote'), config.get('train.base_branch'), config.get('origin-client.cli')
    home, tree = Path(root), Path(root)
    if run is subprocess.run:  # FRONT-AUTH-ONCE: the forge's credentials asked now, ahead of the front's ls-remote
        prefetch_auth(remote, home)
    if not base_ok(pr, base, cli, run, out, home):
        return REFUSED
    if branch:
        code, err = fetch(run, remote, branch, home)
        if code != 0:  # rev-parse would read the branch's older head and the gate would judge another commit
            out(f'deliver: fetching {branch} failed: {err[-300:]}; nothing gated or merged')
            return 2
        tree = home / '.gate' / 'deliver' / f'pr-{pr}'
        output(run, ['git', 'worktree', 'remove', '--force', str(tree)], home)
        _, head, _ = output(run, ['git', 'rev-parse', f'{remote}/{branch}'], home)
        code, _, err = output(run, ['git', 'worktree', 'add', '--quiet', '--detach', str(tree), head], home)
        if code != 0:
            out(f'deliver: no worktree for {branch} at {head[:12]}: {err[-300:]}')
            return 2
        link = tree / '.toolchain'
        if (home / '.toolchain').exists() and not link.exists():
            os.symlink(home / '.toolchain', link)
    else:
        _, branch, _ = output(run, ['git', 'rev-parse', '--abbrev-ref', 'HEAD'], home)
        _, head, _ = output(run, ['git', 'rev-parse', 'HEAD'], home)
    if config.get('delivery.judge') == 'infra':  # GATE-INFRA 3: the infrastructure judges and lands; the box is off the path
        code = _judge_on_infra(pr, home, tree, branch, head, remote, base, run, out, own_tree=tree != home)
        return _after(pr, code, said, home, tree, run, out)
    if tree != home and lockless(changed(run, remote, base, head, home)):
        out(f'deliver: #{pr} is docs-only (no script test, no scripts/** path): gated and merged outside the box lock (D-301)')
        code = _judge_and_merge(pr, home, tree, branch, head, remote, base, cli, run, out, own_tree=True)
        return _after(pr, code, said, home, tree, run, out)
    # F27: the box's lock spans the base merge, the gate and the merge: a delivery waiting for the box takes the base
    # after the one ahead has merged, so another lane on the box never moves the base under its gate (a re-judgment)
    batching = tree != home and config.get('delivery.batch') != 'off'  # F36: only a branch delivery can join a batch
    if batching:
        box_queue.enqueue(pr, branch, head)
    try:
        with box_gate(out, pr=pr) as row:
            code = _from_batch(pr, head, home, run, out, row) if batching else None
            if code is None:
                code = _judge_and_merge(pr, home, tree, branch, head, remote, base, cli, run, out, own_tree=tree != home)
    finally:
        if batching:
            box_queue.leave(pr)
    return _after(pr, code, said, home, tree, run, out)


def base_ok(pr, base, cli, run, out, home):
    """True when the PR targets `base` (train.base_branch). Origin's default base is main, frozen production (D-054):
    a PR opened on it (#203) is refused before the fetch, the gate or the merge, with the command that fixes it."""
    code, said, err = output(run, [cli, 'pr', 'view', str(pr), '--json', 'baseRef'], home)
    try:
        actual = json.loads(said)['baseRef'] if code == 0 else None
    except (ValueError, KeyError, TypeError):
        actual = None
    if actual == base:
        return True
    if actual is None:
        out(f'deliver: could not read the base of #{pr}: {(err or said)[-300:]}; nothing gated or merged')
    else:
        out(f'deliver: #{pr} targets {actual}, not {base}; nothing gated or merged. Fix: {cli} pr edit {pr} --base {base}')
    return False


def changed(run, remote, base, head, home):
    """The paths the head changes against its merge base with the fetched base ([] when git cannot say)."""
    code, text, _ = output(run, ['git', 'diff', '--name-only', f'{remote}/{base}...{head}'], home)
    return [line for line in text.splitlines() if line.strip()] if code == 0 else []


def lockless(paths):
    """F62 (D-301): a diff whose scoped area plan names an area, selects no script test and touches no scripts/** path.
    Anything else (no paths, an unmapped path, a plan that cannot be read) keeps the box lock."""
    if not paths or any(path.startswith('scripts/') for path in paths):
        return False
    try:
        plan = gate_areas.plan_for(paths)
    except Exception:  # noqa: BLE001 - a plan that cannot be read keeps the lock
        return False
    return plan['kind'] == 'scoped' and bool(plan['areas']) and 'script tests' not in plan['stages']


def _after(pr, code, said, home, tree, run, out):
    """What follows a delivery outside the box's lock: the diary, the PR/s line and the delivery tree."""
    if code == 0:  # F60: after the lock, like the report below
        diary(pr, said, home, run, out)
    if code == 0:  # F33: after the box's lock is released, so the next delivery does not wait for a report (#104: 12 s)
        _, metrics, _ = output(run, ['scripts/flow-metrics', '--prs', str(WINDOW)], home)
        out(next((line for line in metrics.splitlines() if 'PR/s' in line), 'deliver: no PR/s line'))
    if code == 0:  # F59: the quota ledger refreshes itself after each merge, outside the lock; best effort
        ledger(home, run, out)
    if tree != home and code == 0:
        output(run, ['git', 'worktree', 'remove', '--force', str(tree)], home)
    elif tree != home:  # the failure's logs live in the tree; the next deliver of this PR replaces it
        out(f'deliver: kept {tree} for its reports')
    return code


def ledger(home, run, out):
    """F59: refresh the quota ledger (`scripts/usage --lanes --write`, the newest subagents directory) so a merged PR has
    its row without a hand-run; a failure is a warning, since Origin has merged."""
    code, said, err = output(run, ['scripts/usage', '--lanes', '--write'], home)
    if code != 0:
        out(f'deliver: warning: merged, but the ledger refresh (scripts/usage --lanes --write) failed: {(err or said)[-300:]}')
    return code


def _recording(out, said):
    def write(line):
        said.append(line)
        out(line)
    return write


def diary(pr, said, home, run, out, closed=None):
    """F60: the merged unit's diary note (one `scripts/plan note`) and its closed-row record. The unit comes only from
    this PR's title: the subject of the merge commit Origin reported for it, never the base's tip (DX). A title that
    names no unit, or a subject that names another PR, writes neither; a failure is a warning, since Origin has merged."""
    sha = next((m.group(1) for line in said for m in [MERGE_SHA.search(line)] if m), None)
    if not sha:
        return None
    _, subject, _ = output(run, ['git', 'log', '-1', '--format=%s', sha], home)
    named = PR_REF.search(subject)
    if named and int(named.group(1)) != int(pr):
        out(f'deliver: warning: merge {sha[:12]} is #{named.group(1)}, not #{pr}; no diary note or closed row')
        return None
    found = UNIT.search(subject)
    if not found:
        return None
    unit = found.group(1) or found.group(2)
    code, _, err = output(run, ['scripts/plan', 'note', '--program', QUEUE_PROGRAM, '--from', unit, '--affects', unit,
                                '--pr', str(pr), '--kind', 'engine', '--evidence', sha,
                                f'{unit} delivered in #{pr} ({sha[:12]}); its queue row closes'], home)
    if code != 0:
        out(f'deliver: warning: merged, but the diary note for {unit} failed: {err[-300:]}')
    path = Path(closed or QUEUE_CLOSED)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('a') as handle:
            handle.write(json.dumps({'unit': unit, 'pr': pr, 'merge': sha}) + '\n')
    except OSError as error:
        out(f'deliver: warning: merged, but the closed row of {unit} was not recorded: {error}')
    out(f'deliver: {unit} noted in the diary and its queue row recorded closed (scripts/deliver --close-queue)')
    return unit


def close_queue(root=ROOT, closed=None, out=print):
    """F60: take the recorded delivered units' rows out of the queue table of `root`; returns the units taken out.
    Rows already gone are skipped, so applying the record twice changes nothing."""
    path = Path(closed or QUEUE_CLOSED)
    units = set()
    with contextlib.suppress(FileNotFoundError):
        for line in path.read_text().splitlines():
            with contextlib.suppress(ValueError, KeyError, TypeError):
                units.add(json.loads(line)['unit'])
    queue = Path(root) / QUEUE
    rows = queue.read_text().splitlines(keepends=True)
    gone = [row.split('|')[1].strip() for row in rows if row.startswith('| F') and row.split('|')[1].strip() in units]
    if gone:
        queue.write_text(''.join(row for row in rows if not (row.startswith('| F') and row.split('|')[1].strip() in units)))
    out(f"deliver: queue rows out: {' '.join(gone)}" if gone else 'deliver: no recorded row is still in the queue')
    return gone


def _answer(pr, found, out):
    """The exit code of a delivery a batch resolved, said in one line."""
    where = f" in batch {found.get('batch_id')}" if found.get('batch_id') else ''
    if found['outcome'] == 'merged':
        out(f"deliver: #{pr} merged{where} by the box leader (Merge commit: {found.get('merge_sha')})")
        return 0
    out(f"deliver: #{pr} {found['outcome']}{where} by the box leader: {found.get('detail') or '-'}; nothing more merged")
    return 1


def batch_reading():
    """F64 (D-297): flow-metrics' batch reading, read only when a batch could lead: ready when the box's busy share over
    the last hour reaches 0.70 and p <= 0.25 over the last train.batch_red_window merged PRs. A reading that fails is
    not ready (the single path), never a failed delivery."""
    try:
        import flow_metrics
        return flow_metrics.measured_batch_reading(lazy=True)
    except Exception as error:  # noqa: BLE001 - an unreadable meter keeps the single path
        return {'ready': False, 'why': f'the reading failed: {type(error).__name__}: {str(error)[:200]}'}


def _from_batch(pr, head, home, run, out, row):
    """F36, inside the box's lock: the code of a delivery a batch resolved (one before it, or the one it leads now), or
    None when its PR takes the single path. Leads with two or more live deliveries waiting (box_queue.entries)."""
    found = box_queue.result(pr, head)
    if found:
        return _answer(pr, found, out)
    waiting = box_queue.entries()
    if not waiting[1:]:  # a batch needs another live delivery beside this one
        return None
    reading = batch_reading()
    if not reading['ready']:  # F64, D-297: the batch leads only when the box is the constraint and p allows it
        out(f"deliver: {len(waiting)} deliveries wait for the box, but the batch is not ready ({reading['why']}); "
            f'#{pr} takes the single path (F64)')
        return None
    out(f'deliver: {len(waiting)} deliveries wait for the box; #{pr} leads one batch (scripts/train run --box)')
    env = dict(os.environ, **{box_queue.HELD_ENV: str(Path(os.path.expanduser(config.get('delivery.gate_lock_path'))))})
    done = run(['scripts/train', 'run', '--box'], cwd=str(home), capture_output=True, text=True, env=env)
    said = (done.stdout or '') + (done.stderr or '')
    for line in said.splitlines():
        if line.startswith('box: batch '):
            with contextlib.suppress(ValueError):
                row['batch'] = json.loads(line[len('box: batch '):])
    out('\n'.join(line for line in said.splitlines() if line.startswith(('box:', 'train: halted', 'train: died')))
        or f'deliver: the box batch said nothing (exit {done.returncode})')
    found = box_queue.result(pr, head)
    if found:
        return _answer(pr, found, out)
    out(f'deliver: the batch did not resolve #{pr}; it takes the single path')
    return None


def _merged_by_service(port, tree, branch, head, remote, base, run, out, sleep=time.sleep, clock=time.monotonic):
    """BRANCH-MERGE: the base merged into the branch and pushed by the live service with the forge's key (POST
    /v1/branch-merge); this tree then fetches the branch and moves to it by a fast-forward (a read, no merge or push of the
    lane's). (head, code), or None when the service did not do it (no route, a failure, no word in time): the lane merges."""
    import gate_infra
    try:
        asked = port.call('POST', '/v1/branch-merge', {'branch': branch, 'head': head, 'base': base})
        deadline = clock() + config.get('gate-infra.metadata_blind_wait_s')
        while True:
            said = port.call('GET', f"/v1/branch-merge/{asked['id']}")
            if said.get('state') not in ('asked', 'taken'):
                break
            if clock() >= deadline:
                out(f'deliver: the live service did not merge {base} into {branch} in time; the lane merges it')
                return None
            sleep(config.get('gate-infra.poll_last_s'))
    except gate_infra.Refused as error:
        if error.status != 404:
            out(f'deliver: the port refused the merge of {base} into {branch} ({error.status}); the lane merges it')
        return None
    outcome = said['state']
    if outcome == 'current':
        return head, 0
    if outcome == 'conflict':
        out(f"deliver: {branch} does not merge with {remote}/{base}: {_conflict_text(said.get('paths') or [])}; nothing merged")
        return head, 1
    if outcome == 'moved':
        out(f"deliver: {branch} moved to {str(said.get('tip'))[:12]} while it was merged; nothing merged")
        return head, 1
    if outcome != 'merged':
        out(f"deliver: the live service could not merge {base} into {branch} ({said.get('why', outcome)}); the lane merges it")
        return None
    merged = said['sha']
    code, _, err = output(run, ['git', 'fetch', '--quiet', remote, branch], tree)
    if code == 0:
        code, _, err = output(run, ['git', 'merge', '--quiet', '--ff-only', merged], tree)
    if code != 0:
        out(f'deliver: the service merged {base} into {branch} ({merged[:12]}) but this tree cannot follow it: {err[-300:]}')
        return head, 1
    parts = ', '.join(f'{name} {said[name]}' for name in ('fetch_s', 'combine_s', 'push_s') if said.get(name) is not None)
    reused = ', the premerge\'s commit' if said.get('reused') else ''
    out(f"deliver: the live service merged {remote}/{base} into {branch} ({merged[:12]}, {said.get('merge_s')} s"
        f"{': ' + parts if parts else ''}{reused}) so the gate judges what lands")
    return merged, 0


def _with_base(tree, branch, head, remote, base, run, out, port=None):
    """(head, 0) with the fetched base merged into the branch's head (a merge commit, pushed), or (head, code) when the
    base cannot come in. The gate then judges the combination the merge will land, not the head over an older base:
    the train that re-proved a batch on the tip (merge.max_behind_base) is stopped (programa VAZÃO, fase 1)."""
    # BASE-TIP-BY-LS-REMOTE: the base's tip by one round trip; the fetch (2.2 s, #654) only when the shared .git does not
    # already hold it (the lanes share a checkout: another delivery, the push or the pre-gate often fetched it seconds ago)
    code, said, _ = output(run, ['git', 'ls-remote', remote, f'refs/heads/{base}'], tree)
    tip = said.split()[0] if code == 0 and said.split() else None
    _, have, _ = output(run, ['git', 'rev-parse', '--verify', '--quiet', f'{remote}/{base}'], tree)
    if not tip or have.strip() != tip:
        code, err = fetch(run, remote, base, tree)
        if code != 0:  # an older base would let the gate judge a combination the merge does not land
            out(f'deliver: fetching {base} failed: {err[-300:]}; nothing merged')
            return head, 1
    code, _, _ = output(run, ['git', 'merge-base', '--is-ancestor', f'{remote}/{base}', 'HEAD'], tree)
    if code == 0:
        return head, 0
    if port is not None:  # BRANCH-MERGE: the live service merges and pushes, with the forge's key
        done = _merged_by_service(port, tree, branch, head, remote, base, run, out)
        if done is not None:
            return done
    code, said, err = output(run, ['git', 'merge', '--quiet', '--no-edit', '-m',
                                   f'Merge {remote}/{base} into {branch}', f'{remote}/{base}'], tree)
    if code != 0:
        _, unmerged, _ = output(run, ['git', 'diff', '--name-only', '--diff-filter=U'], tree)
        paths = unmerged.splitlines() or conflicts(run, tree, 'HEAD', f'{remote}/{base}')
        output(run, ['git', 'merge', '--abort'], tree)
        why = _conflict_text(paths) if paths else reason(code, err, said)[-300:]
        out(f'deliver: {branch} does not merge with {remote}/{base}: {why}; nothing merged')
        return head, 1
    _, merged, _ = output(run, ['git', 'rev-parse', 'HEAD'], tree)
    # F33: no pre-push hook on this push: it carries the base, already gated, and the branch, already checked at its own
    # pushes, and the gate judges this exact merged head next, inside the box's lock (#104: ~29 s for this push with it)
    code, _, err = output(run, ['git', 'push', '--quiet', '--no-verify', remote, f'HEAD:refs/heads/{branch}'], tree)
    if code != 0:
        out(f'deliver: the merge of {base} into {branch} could not be pushed: {err[-300:]}; nothing merged')
        return head, 1
    out(f'deliver: merged {remote}/{base} into {branch} ({merged[:12]}) so the gate judges what lands')
    return merged, 0


def children_cpu():
    """CPU-seconds (user + system) of this process's waited-for children so far: the gate, the base merge and the merge
    deliver runs under the lock, the same counters (cutime + cstime) gate_proof.cost's cpu_s reads (F71)."""
    used = resource.getrusage(resource.RUSAGE_CHILDREN)
    return used.ru_utime + used.ru_stime


def box_vcpus():
    """The CPUs the box gives this process (its affinity set, which a cpuset narrows), never less than 1."""
    try:
        return max(1, len(os.sched_getaffinity(0)))
    except (AttributeError, OSError):
        return max(1, os.cpu_count() or 1)


def _place(pr):
    """' (place N of M in the box queue)' for a queued PR, else ''; the queue folder never fails a wait."""
    try:
        found = box_queue.position(pr) if pr is not None else None
    except (OSError, ValueError, KeyError):
        found = None
    return f' (place {found[0]} of {found[1]} in the box queue)' if found else ''


@contextlib.contextmanager
def box_gate(out=print, path=None, clock=time.monotonic, pr=None, log=None, wall=time.time, cpu=children_cpu,
             vcpus=box_vcpus, sleep=time.sleep, every=60.0, poll=0.5):
    """Hold the box's gate lock (delivery.gate_lock_path) while a delivery judges and merges (VAZÃO F23, F27): the gate
    takes every CPU of the box, so two deliveries judging at once each take as long as both in a row and fail more under
    load; queued, each is judged at full speed, and the one waiting brings the base in only after the one ahead merged.
    Prints the wait when there was one, and appends {pr, waited_s, held_s, at, cpu_s, vcpus} to the box's lock log
    (delivery.gate_lock_log, F38) for scripts/flow-metrics --constraint; cpu_s is the CPU the hold's children used and
    vcpus the box's CPUs, so the log shows CPU-s per PR against the box's ceiling and the idle share of the hold (F71).
    While it waits it prints its place in the box queue on entering and a progress line every `every` s (F132), so a long
    wait reads as a queue and not as a hang. It yields a dict whose keys join that line (a leader puts its batch there, F36)."""
    lock = Path(os.path.expanduser(path or config.get('delivery.gate_lock_path')))
    lock.parent.mkdir(parents=True, exist_ok=True)
    waited = 0.0
    with open(lock, 'a') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            out(f'deliver: another gate holds the box ({lock}); waiting for it{_place(pr)}')
            started = clock()
            noted = started
            while True:
                try:
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    sleep(poll)
                    if clock() - noted >= every:
                        noted = clock()
                        out(f'deliver: still waiting for the box, {noted - started:.0f} s so far{_place(pr)}')
            waited = clock() - started
            out(f'deliver: the box is free after {waited:.0f} s')
        taken, extra, spent = clock(), {}, cpu()
        try:
            yield extra
        finally:
            held = clock() - taken
            fcntl.flock(handle, fcntl.LOCK_UN)
            if pr is not None:  # only a delivery is a line of the box's log: a test of the lock itself never is
                extra.setdefault('cpu_s', round(max(0.0, cpu() - spent), 1))
                extra.setdefault('vcpus', vcpus())
                _log_lock(log, pr, waited, held, wall(), extra)


def _log_lock(log, pr, waited, held, at, extra=None):
    """One line of the box's lock log; a log that cannot be written never fails the delivery."""
    try:
        path = Path(os.path.expanduser(log or config.get('delivery.gate_lock_log')))
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'a') as handle:
            row = dict(extra or {}, pr=pr, waited_s=round(waited, 1), held_s=round(held, 1), at=round(at))
            handle.write(json.dumps(row) + '\n')
    except (OSError, ValueError, KeyError):
        pass


def base_red(output):
    """F73: every red stage the gate names is class base, so the PR stays queued and the lane reworks nothing."""
    found = gate_classify.classes(output)
    return bool(found) and set(found.values()) == {gate_classify.BASE_CLASS}


SPAWN = subprocess.Popen  # the shadow of the gate starts beside it and is never waited on (GATE-INFRA 2, P5 F2)


def shadows(environ):
    """Where the shadow keeps its verdicts and its logs, and the box keeps its verdict beside them."""
    return Path(environ.get('XDG_CACHE_HOME') or Path.home() / '.cache') / 'the-tower' / 'gate-infra'


def keep_box(pr, head, code, said, seconds=None):
    """GATE-INFRA 4 (P5 F3): the box's verdict on a head the shadow also judges, kept beside the shadow's
    (box-<pr>-<head>.json next to pr-<pr>-<head>.json) so scripts/medir pairs them; never stops the delivery. With
    the seconds its gate took (MEDIR 5), which medir sets against the shadow's own for the same head."""
    verdict = {'pr': str(pr), 'head': head, 'verdict': 'green' if code == 0 else 'red',
               'red': sorted(gate_classify.classes(said)) if code else [],
               'at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
               **({'seconds': seconds} if seconds is not None else {})}
    try:
        import gate_infra  # the shadow's own writer, so the box's verdict and the shadow's keep one format
        gate_infra.kept_box(verdict)
    except OSError:
        return None
    return verdict


def start_shadow(pr, head, home, out, environ=None):
    """GATE-INFRA 2 (P5 F2, D-306): the infrastructure judges the same head in shadow beside the box's gate when the
    port is configured (TOWER_PORT_URL and TOWER_PORT_TOKEN), through scripts/gate-infra of the delivering checkout.
    It is never waited on, and nothing it says changes the delivery; its verdict is kept beside its log."""
    environ = os.environ if environ is None else environ
    if not environ.get('TOWER_PORT_URL') or not environ.get('TOWER_PORT_TOKEN'):
        return False
    logs = shadows(environ)
    try:
        logs.mkdir(parents=True, exist_ok=True)
        with open(logs / f'pr-{pr}.log', 'a', encoding='utf-8') as log:
            SPAWN([str(Path(home) / 'scripts' / 'gate-infra'), 'shadow', '--pr', str(pr), '--head', head], cwd=home,
                  stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    except OSError as error:
        out(f'deliver: the shadow of #{pr} did not start ({error}); the delivery goes on')
        return False
    out(f'deliver: the infrastructure judges #{pr} at {head} in shadow ({logs / f"pr-{pr}.log"})')
    return True


def _judge_and_merge(pr, home, tree, branch, head, remote, base, cli, run, out, own_tree):
    root = tree
    code, listed, err = output(run, ['git', 'ls-remote', remote, f'refs/heads/{branch}'], root)
    pushed = listed.split()[0] if code == 0 and listed else ''
    if pushed != head:
        out(f'deliver: {branch} at {head[:12]} is not the pushed head ({pushed[:12] or "none"}); push first {err}'.rstrip())
        return 2
    for _attempt in range(ROUNDS):
        if own_tree:
            head, code = _with_base(tree, branch, head, remote, base, run, out)
            if code:
                return code
        _, judged_base, _ = output(run, ['git', 'rev-parse', f'{remote}/{base}'], root)
        shadowed = start_shadow(pr, head, home, out)
        started = time.monotonic()
        code, gate, err = output(run, ['scripts/gate-dev', '--pr', str(pr)], root)
        if shadowed:  # GATE-INFRA 4: the box's verdict beside the shadow's, for the agreement P5 F3 asks
            keep_box(pr, head, code, gate + '\n' + err, seconds=time.monotonic() - started)
        if code != 0:
            out('\n'.join((gate + '\n' + err).strip().splitlines()[-15:]))
            for stage, kind in gate_classify.classes(gate + '\n' + err).items():
                out(f'deliver: class {kind} ({stage}): {gate_classify.ACTIONS[kind]}')
            if base_red(gate + '\n' + err):
                out(f'deliver: #{pr} stays queued: its red is the base\'s, not its own (F73); nothing merged')
                return 1
            out(f'deliver: the gate failed on {head[:12]}; nothing merged')
            return 1
        if not own_tree:  # the checkout's own head was judged; only a delivery that merged the base in checks it moved
            break
        code, err = fetch(run, remote, base, root)
        if code != 0:  # without the fetch the moved-base guard reads the old tip and cannot see the base move
            out(f'deliver: fetching {base} after the gate failed: {err[-300:]}; nothing merged')
            return 1
        _, tip, _ = output(run, ['git', 'rev-parse', f'{remote}/{base}'], root)
        if tip == judged_base:
            break
        out(f'deliver: {base} moved to {tip[:12]} during the gate; judging #{pr} again on it')
    else:
        out(f'deliver: {base} kept moving for {ROUNDS} gates; nothing merged')
        return 1
    box_check(head, time.monotonic() - started, out)
    merging = time.monotonic()
    code, merged, err = output(run, [cli, 'pr', 'merge', str(pr), '--expect-head', f'{pr}={head}'], root)
    took = time.monotonic() - merging
    if code != 0:
        why = reason(code, err, merged)[-400:]
        paths = conflicts(run, root, head, f'{remote}/{base}')
        out(f'deliver: merge of #{pr} at {head[:12]} refused: {why}' + (f'; {_conflict_text(paths)}' if paths else ''))
        return 1
    out(next((line.strip() for line in merged.splitlines() if 'Merge commit' in line), f'merged #{pr}'))
    out(f'deliver: origin merged #{pr} in {took:.3f} s')  # MEDIR 1 (P6 F1): the merge through Origin, per delivery
    return _refreshed(home, remote, base, run, out, own_tree)


def train_port():
    """The port of the merge train, or None when the train is off (delivery.train) or there is no port to keep it."""
    if not config.get('delivery.train'):
        return None
    import gate_infra
    try:
        return gate_infra.port_from_env()
    except RuntimeError:
        return None  # land() says so in its own words


def _front_gate(tr, pr, tree, remote, base, run, out, judged, branch=None):
    """The hook between the checks and the landing (gate_infra.land front=): a red entry leaves the train at once; a
    green one waits for the front, then keeps its verdict if the base the front moved does not reach it, else raises
    merge_train.Stale to merge the base and be judged again. BASE-MOVED-SWAP: a verdict that stands on a base that moved
    answers that base's tip, the parent the merge will have, for the landing's announcement (gate_infra.land)."""
    import gate_infra

    def front(ok, red, _seconds):
        if not ok:
            with contextlib.suppress(OSError, gate_infra.Refused):
                tr.end('left', f"red: {', '.join(red)[:200]}")
            return
        began = time.monotonic()  # LANDING-PARTS: where the front's seconds go, in the delivery's own log
        # FRONT-AT-ONCE (critério 3): the renewal reads the train's state; an entry that is the front already does not
        # ask again by the long poll (0.7 to 4.4 s more per landing, #659 to #665, one at a time with no one ahead)
        renewal = tr.renew('checks decided')
        renewed = time.monotonic()
        try:
            if not (isinstance(renewal, dict) and renewal.get('state') == 'front'):
                tr.until_front()
        except (OSError, gate_infra.Refused) as error:  # fail open: the train went away under it
            out(f'deliver: the merge train stopped answering ({error}); #{pr} lands as before')
            return
        fronted = time.monotonic()
        # READY-BESIDE-BASE (critério 3): the successors' readiness (GET /v1/deploy/status and its beats, 0.5 to 1.0 s) is
        # read while the base's tip is (0.4 to 0.6 s): neither depends on the other. A base that moved under the PR still
        # raises Stale below; the reading is then dropped
        import threading
        readied = threading.Thread(target=lambda: tr.ready(branch, config.get('delivery.successor_wait_s'),
                                                           config.get('delivery.successor_poll_s')),
                                   name='ready-beside-base', daemon=True)
        readied.start()
        # BASE-TIP-BY-LS-REMOTE: the base's tip by one round trip; the fetch only when it moved (the diff needs it)
        code, said, _ = output(run, ['git', 'ls-remote', remote, f'refs/heads/{base}'], tree)
        tip = said.split()[0] if code == 0 and said.split() else None
        if tip != judged['base']:
            code, err = fetch(run, remote, base, tree)
            if code != 0:
                raise RuntimeError(f'fetching {base} before landing #{pr}: {err[-300:]}')
            _, tip, _ = output(run, ['git', 'rev-parse', f'{remote}/{base}'], tree)
        tipped = time.monotonic()
        if tip == judged['base']:
            readied.join()
            crashed(tr, pr)
            out(f'deliver: #{pr} at the front: renew {renewed - began:.1f} s, front {fronted - renewed:.1f} s, '
                f'base {tipped - fronted:.1f} s, ready {time.monotonic() - tipped:.1f} s')
            return
        _, listed, _ = output(run, ['git', 'diff', '--name-only', judged['base'], tip], tree)
        why = merge_train.stale(listed.split(), tr.files)
        if why:
            raise merge_train.Stale(tip, why)
        out(f'deliver: {base} moved to {tip[:12]} but not under #{pr}: its verdict stands, no new merge or judgment')
        readied.join()
        crashed(tr, pr)
        return tip
    return front


def crashed(tr, pr):
    """SUCCESSOR-CRASH-RED: the code that would land does not start a role of the engine (merge_train.Train.ready: its
    successor gave up): the entry leaves the train and the delivery stops before the landing; nothing merges."""
    if not getattr(tr, 'gave_up', None):
        return
    roles = ', '.join(tr.gave_up)
    import gate_infra
    with contextlib.suppress(OSError, gate_infra.Refused):
        tr.end('left', f'the successor of {roles} on its code gave up at its start')
    raise merge_train.Left(f'#{pr}: its code does not start the {roles} (its successor ended more than 3 times at its '
                           f'start: platform.deploy.successor failed); fix it and deliver again')


def box_check(head, seconds, out):
    """EMERGENCY-EXIT-CHECK (docs/operations/aws.md, the emergency exit): the box's green verdict is published as tower/gate
    on the head before the merge, as the infrastructure's judge publishes its own (D-313). The forge's ruleset requires
    that check, and only the infrastructure's judge published it: with the engine stopped a fix judged by the box was
    refused at the merge (the rehearsal of 11/11: `Required status checks are missing`). gate_status.check_hooks' rules:
    nothing when gate.check_run_enabled is off; a publish that fails is logged and the merge is tried all the same."""
    import gate_status
    hooks = gate_status.check_hooks(head, log=out, mode='box')
    if hooks:
        hooks[1](True, [], seconds)


def _judge_on_infra(pr, home, tree, branch, head, remote, base, run, out, own_tree):
    """GATE-INFRA 3 (P5 F4; delivery.judge infra): the base merged into the branch as on the box, then the
    infrastructure judges the head and lands it with the expected head (gate_infra.land); the box's gate and lock are
    off the path. Green is a merge the forge made; red or moved merges nothing; late cancels the landing.
    TRAIN-FRONT-FIRST: the delivery joins the base's merge train first; only the front lands (scripts/lib/merge_train.py)."""
    import gate_infra
    port = train_port()
    if own_tree:
        head, code = _with_base(tree, branch, head, remote, base, run, out, port=port)
        if code:
            return code
    _, base_sha, _ = output(run, ['git', 'rev-parse', f'{remote}/{base}'], tree)
    tr = judged = front = None
    if port is not None:
        _, listed, _ = output(run, ['git', 'diff', '--name-only', f'{remote}/{base}...{head}'], tree)
        tr = merge_train.Train(port, base, pr, head, listed.split(), rounds=config.get('delivery.train_rounds'), out=out,
                               lease_s=config.get('delivery.train_lease_s'))
        try:
            tr.join()
        except (OSError, gate_infra.Refused) as error:  # FAIL OPEN: a port without the train (404 before its deploy), or unreachable
            out(f'deliver: no merge train ({error}); #{pr} lands as before')
            tr = None
        else:
            judged = {'base': base_sha}
            front = _front_gate(tr, pr, tree, remote, base, run, out, judged, branch)
    landed = False
    try:
        for _round in range(ROUNDS):
            try:
                if tr:
                    tr.renew('checks started')
                # TRAIN-LEASE-IN-JUDGMENT: the judgment's own progress renews the train's lease
                verdict, cancelled = gate_infra.land(pr, head, base_sha, branch, base, root=tree, port=port, front=front,
                                                     progress=tr.progress if tr else None)
            except merge_train.Stale as stale:
                out(f'deliver: #{pr} is the front but {stale.why}; merging {base} and judging again')
                head, code = _with_base(tree, branch, head, remote, base, run, out, port=port)
                if code:
                    return code
                _, base_sha, _ = output(run, ['git', 'rev-parse', f'{remote}/{base}'], tree)
                judged['base'] = base_sha
                tr.moved(head)  # TRAIN-HEAD-FOLLOWS: the train's entry names the head now judged
                continue
            except merge_train.Left as error:
                out(f'deliver: {error}; nothing merged')
                return 1
            except (RuntimeError, OSError, gate_infra.Refused) as error:
                out(f'deliver: the infrastructure did not judge #{pr}: {error}; nothing merged')
                return REFUSED
            break
        else:
            out(f'deliver: {base} kept moving under the front for {ROUNDS} judgments; nothing merged')
            return 1
        if verdict['verdict'] == 'green':
            landed = True
            if tr:
                tr.end('landed')
            out(f"Merge commit: {(verdict['landing'].get('result') or {}).get('merge_sha')}")
            out(f"deliver: the infrastructure judged and landed #{pr} in {verdict['seconds']:.1f} s "
                f"({verdict['checks']} check(s), {verdict['from_cache']} from the cache)")
            return _refreshed(home, remote, base, run, out, own_tree)
        if verdict['verdict'] == 'late':
            out(f'deliver: #{pr} had no verdict in time; its landing was cancelled ({cancelled}); nothing merged')
            return 1
        why = ', '.join(verdict['red']) or verdict['landing'].get('error') or verdict['verdict']
        out(f"deliver: the infrastructure judged #{pr} {verdict['verdict']} ({why}); nothing merged")
        return 1
    finally:
        if tr and not landed:
            try:
                tr.end('left', 'the delivery ended without landing')  # a no-op when it left already (red)
            except (OSError, gate_infra.Refused) as error:
                out(f'deliver: warning: #{pr} could not leave the train: {error}; `scripts/deliver --queue` shows it')


def _refreshed(home, remote, base, run, out, own_tree):
    """After a merge: the base fetched into the checkout and moved where it is checked out here; never a failure."""
    # Origin has merged: the delivery succeeded and exits 0; a refresh that fails is a warning, never a failure
    code, err = fetch(run, remote, base, home)
    if code != 0:
        out(f'deliver: warning: merged, but fetching {base} failed (the local {remote}/{base} is behind): {err[-300:]}')
    # from its own worktree the fetched base is the refresh: the checkouts that hold the base branch move it themselves
    # F101: a base another worktree holds cannot be checked out here; that checkout moves it itself, no false warning
    steps = [] if own_tree or code != 0 or _held_elsewhere(run, home, base) else [
        ['git', 'checkout', '--quiet', base], ['git', 'merge', '--quiet', '--ff-only', f'{remote}/{base}']]
    for argv in steps:
        code, _, err = output(run, argv, home)
        if code != 0:
            out(f'deliver: warning: merged, but `{" ".join(argv)}` failed: {err[-300:]}')
            break
    return 0


def _held_elsewhere(run, home, base):
    """True when `base` is checked out in a worktree other than `home` (git refuses a second checkout of it)."""
    code, listed, _ = output(run, ['git', 'worktree', 'list', '--porcelain'], home)
    if code != 0:
        return False
    path = ''
    for line in listed.splitlines():
        if line.startswith('worktree '):
            path = line[len('worktree '):]
        elif line == f'branch refs/heads/{base}' and Path(path).resolve() != Path(home).resolve():
            return True
    return False


TRAILERS = re.compile(r'^(Plan|Co-Authored-By|Claude-Session|Signed-off-by):', re.IGNORECASE)
FIT_REVIEW = 'Fit-Review: not reviewed (Daniel 2026-10-25: no review step)'  # AGENTS.md, D-055


def pr_body(commits, footer=''):
    """(title, body) of a PR made from its commits [(subject, body)], oldest first: the first commit's subject and
    prose, the plan from the `Plan:` trailers (item N is the first commit that names N), then the trailers."""
    items, prose = {}, []
    for subject, body in commits:
        for number in re.findall(r'^Plan:\s*(\d+)', body, re.MULTILINE):
            items.setdefault(int(number), subject)
    if commits:
        prose = [line for line in commits[0][1].strip().splitlines() if not TRAILERS.match(line)]
    plan = '\n'.join(f'- [ ] {number}. {items[number]}' for number in sorted(items))
    body = '\n'.join(prose).strip() + f'\n\n## Plano de commits\n{plan}\n\nPremises: none\n{FIT_REVIEW}\n'
    return (commits[0][0] if commits else ''), body + (f'\n{footer.strip()}\n' if footer.strip() else '')


def body_problems(body_file, root=ROOT, run=subprocess.run):
    """The FAIL lines of `scripts/structure-check --pr-body FILE`, so a PR is never opened with a body the gate would
    refuse (lane 4, D-236; the guard lane-ship carried until F9)."""
    _, said, _ = output(run, [str(Path(root) / 'scripts' / 'structure-check'), '--pr-body', str(body_file)], root)
    return [line for line in said.splitlines() if line.startswith('FAIL')]


def open_pr(branch, root=ROOT, run=subprocess.run, out=print, footer='', create=True):
    """The number of the open PR of `branch`, opened from its commits when there is none (`deliver --open`); with
    create=False (F101: `--branch B` alone) only found, and None with a message when there is none."""
    remote, base, cli = config.get('push-guard.remote'), config.get('train.base_branch'), config.get('origin-client.cli')
    output(run, ['git', 'fetch', '--quiet', remote, base, branch], root)
    found = None
    for state in ('open', 'draft'):  # `-s open` hides drafts (F92)
        code, listed, _ = output(run, [cli, 'pr', 'list', '-H', branch, '-s', state], root)
        found = re.search(r'^#(\d+)\s', listed, re.MULTILINE) if code == 0 else None
        if found:
            break
    if found:
        return int(found.group(1))
    if not create:
        out(f'deliver: {branch} has no open PR; open it (`origin pr create`) or pass --open')
        return None
    _, log, _ = output(run, ['git', 'log', '--reverse', '--no-merges', '--format=%s%x1f%b%x1e',
                             f'{remote}/{base}..{remote}/{branch}'], root)
    commits = [tuple(row.strip('\n').split('\x1f', 1)) for row in log.split('\x1e') if '\x1f' in row]
    title, body = pr_body(commits, footer)
    if not title:
        out(f'deliver: {branch} has no commit over {base}; nothing to open')
        return None
    with tempfile.NamedTemporaryFile('w', suffix='.md', delete=False) as handle:
        handle.write(body)
    try:
        problems = body_problems(handle.name, root, run)
        if problems:
            out(f'deliver: the body made for {branch} would be refused; nothing opened')
            for line in problems:
                out(line)
            return None
        code, created, err = output(run, [cli, 'pr', 'create', '-t', title, '-F', handle.name, '-H', branch, '-B', base],
                                    root)
    finally:
        os.unlink(handle.name)
    found = re.search(r'#(\d+)', created) if code == 0 else None
    if not found:
        out(f'deliver: could not open a PR for {branch}: {(err or created)[-300:]}')
        return None
    out(f'deliver: opened #{found.group(1)} for {branch}')
    return int(found.group(1))


def cli_on_path(environ=None):
    """F81: append the first origin-client.cli_dirs entry holding the Origin CLI to PATH when the CLI is off it, so
    the `origin` calls below (and the gate's) find it without the lane exporting PATH. Returns the CLI found or None."""
    environ = os.environ if environ is None else environ
    cli = config.get('origin-client.cli')
    if shutil.which(cli, path=environ.get('PATH')):
        return cli
    for folder in config.get('origin-client.cli_dirs'):
        candidate = Path(folder).expanduser() / cli
        if candidate.is_file() and os.access(candidate, os.X_OK):
            environ['PATH'] = os.pathsep.join(filter(None, (environ.get('PATH', ''), str(candidate.parent))))
            return str(candidate)
    return None


def switches(environ=None):
    """GATE-INFRA 12: a branch delivery runs the base's own deliver from .gate/deliver/base (scripts/deliver), and that
    worktree's file store is its own: on 04/11 delivery.judge infra, set in the checkout, never reached it. The wrapper
    names the invoking checkout in DELIVER_CONFIG_ROOT, and this process reads that checkout's change store. The base's
    registry still gives every default, and the gate's own processes keep their head's store (D-069 item 5)."""
    root = (os.environ if environ is None else environ).get('DELIVER_CONFIG_ROOT')
    return config.use_store_of(root) if root else contextlib.nullcontext()


def main(argv=None):
    with switches():
        return _main(argv)


def _main(argv=None):
    parser = argparse.ArgumentParser(prog='scripts/deliver', description=__doc__.splitlines()[0])
    parser.add_argument('--pr', type=int)
    parser.add_argument('--branch', help="deliver this branch's pushed head from its own worktree")
    parser.add_argument('--open', action='store_true', help='open the PR from the branch commits when it has none')
    parser.add_argument('--footer', default='', help='text appended to the body of a PR --open makes')
    parser.add_argument('--close-queue', action='store_true',
                        help="take the delivered units' rows (the closed-rows record) out of the queue table here")
    parser.add_argument('--queue', action='store_true', help="show the merge train: every base's queue in order, front first")
    parser.add_argument('--queue-drop', type=int, metavar='PR',
                        help='take a stuck entry (a delivery that died) out of the train: it leaves, an event')
    parser.add_argument('--wait', action='store_true',
                        help='block until the PR merges or is ejected, in this one call (F79: what a delivery does; '
                             'the flag says so for a caller that would otherwise poll)')
    parser.add_argument('--verbose', action='store_true',
                        help='print every line as it comes (default F79: the merge and PR/s lines on green, '
                             'everything on red, the full log on disk)')
    args = parser.parse_args(argv)
    if args.close_queue:
        close_queue()
        return 0
    if args.queue or args.queue_drop:
        return show_queue(args.queue_drop)
    if args.pr is None and not args.branch:
        parser.error('--pr is required unless --branch B names the branch (its open PR is found; --open also makes one)')
    cli_on_path()
    pr = args.pr or open_pr(args.branch, footer=args.footer, create=args.open)
    if pr is None:
        return 2
    if args.verbose:
        return deliver(pr, branch=args.branch)
    return quiet_deliver(pr, args.branch)


def show_queue(drop=None, port=None, out=print):
    """scripts/deliver --queue: the merge train as the port keeps it; --queue-drop PR takes a stuck entry out first."""
    import gate_infra
    try:
        port = port or gate_infra.port_from_env()
        if drop is not None:
            state = port.call('GET', '/v1/train')
            for base, entries in state['queues'].items():
                if any(entry['pr'] == str(drop) for entry in entries):
                    port.call('POST', '/v1/train/end', {'base': base, 'pr': str(drop), 'ended': 'left',
                                                        'reason': 'dropped by hand (deliver --queue-drop)'})
                    out(f'deliver: #{drop} left the {base} train')
        for line in merge_train.render(port.call('GET', '/v1/train')):
            out(line)
    except (RuntimeError, OSError, gate_infra.Refused) as error:
        out(f'deliver: no merge train to show: {error}')
        return 1
    return 0


GREEN_LINES = ('merged', 'Merge commit', 'PR/s', 'warning', 'queue row')


def quiet_deliver(pr, branch, log_dir=None, show=print):
    """F79: deliver with the full output in a log file. A merge prints its merge and PR/s lines (and warnings) and the
    log path; any other end prints every line, so the failure is whole, and the log path."""
    lines = []
    folder = Path(log_dir or Path.home() / '.cache' / 'the-tower' / 'deliver')
    try:
        folder.mkdir(parents=True, exist_ok=True)
        log = folder / f'pr-{pr}.log'
    except OSError:
        log = None
    code = deliver(pr, branch=branch, out=lines.append)
    if log:
        with contextlib.suppress(OSError):
            log.write_text('\n'.join(lines) + '\n')
    chosen = [line for line in lines if any(key in line for key in GREEN_LINES)] if code == 0 else lines
    for line in chosen or lines[-1:]:
        show(line)
    if log:
        show(f'deliver: full log {log}')
    return code


if __name__ == '__main__':
    sys.exit(main())
