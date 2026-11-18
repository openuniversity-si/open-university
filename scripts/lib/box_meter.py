"""The box's meter (F38, F64, VAZÃO F24; D-297, D-322): what delivery reads to steer a batch, from the data it owns.

The box's busy share comes from its gate lock log (delivery.gate_lock_log, written by deliver.box_gate and the suites),
and the gate's red share p over the last merged PRs from the verdict events on each PR's channel (forge_events) and the
first-parent merges of the base (git). deliver.batch_reading and train.observed_red read it inside the box's lock;
flow-metrics (measurement) re-exports it for --constraint and --guards, so the one rule is read the same way above and
below (D-322: a unit depends only on its own or a lower layer).

  constraint(merged, now, hours, log, queue)   the box's busy share, waits, batches and CPU over the last `hours`
  batch_reading(found, gate, sizes_by_red, cap) F64: ready when the box is busy and p allows a batch
  measured_batch_reading(lazy=...)             batch_reading from the lock log and the forge (deliver)
  measured_gate_runs(root, base, since, count)  gate_runs of the last `count` merged PRs (train, flow-metrics)
"""
import collections
import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time

ROOT = Path(__file__).resolve().parent.parent.parent

FIELD = '\x1f'
SINCE = '2026-10-24 00:00'
ZONE = 'America/Sao_Paulo'
CACHE_TTL_S = 60  # F91: how long a window's gate runs, read from the forge, are reused by the next call (lanes and the coordinator call --constraint several times)
PR_NUMBER = re.compile(r'^Merge pull request #(\d+)\b|\(#(\d+)\)\s*$')


def git(root, *args, zone=ZONE, stdin=None):
    env = dict(os.environ, TZ=zone)
    out = subprocess.run(['git', '-C', str(root), *args], capture_output=True, text=True, env=env, input=stdin)
    if out.returncode:
        raise SystemExit(f'flow-metrics: git {args[0]} failed: {out.stderr.strip()}')
    return out.stdout


BATCH_PREFIX = 'b-'  # train.batch_id: a tier-2 batch's id (v- strict verdict and s- shard ids rest on the PR's own gate)
BATCH_WINDOW = 10  # batches of the lock log whose runs per resolved PR --guards and --constraint read (design-trem.md §5)
BOX_BOUND = 0.7  # the box's busy share from which it is the constraint (Kingman: above it the wait grows fast; toc.md 6.4)
SUPPLY_PER_LANE = 2  # free queue rows per gating lane below which the supply of units is the constraint (toc.md 6.4)


def box_cpu(deliveries):
    """F71: the CPU the deliveries of the lock log spent, from the rows that carry cpu_s and vcpus (deliver.box_gate;
    older rows have neither and are left out). cpu_per_delivery_s is the CPU-s one delivery costs, ceiling_cpu_s_h the
    box's CPU-s per hour (vcpus x 3600) and ceiling_per_h the deliveries an hour that fill it; idle is the share of the
    holds' CPU capacity (held_s x vcpus) nobody used: the hold waiting on the network, git and GitHub, not on the CPU."""
    rows = [row for row in deliveries if isinstance(row.get('cpu_s'), (int, float)) and row.get('vcpus')]
    if not rows:
        return None
    cpu = sum(row['cpu_s'] for row in rows)
    capacity = sum(row['held_s'] * row['vcpus'] for row in rows)
    vcpus = max(row['vcpus'] for row in rows)
    per = cpu / len(rows)
    return {'deliveries': len(rows), 'cpu_per_delivery_s': per, 'vcpus': vcpus, 'ceiling_cpu_s_h': vcpus * 3600,
            'ceiling_per_h': vcpus * 3600 / per if per else None,
            'idle': 1 - cpu / capacity if capacity else None}


def constraint(merged, now, hours, log, queue, lanes=3):
    """F38: the current constraint, measured over the last `hours`. The box's busy share is the seconds deliveries and
    whole suites (F58: rows of kind `suite`, written by scripts/test-suite) held its gate lock (the lock log) over the
    window, each kind counted apart; when it reaches BOX_BOUND the box is the constraint, else the PRs are not arriving
    fast enough: the supply of ready units and the lanes' authoring (upstream of the box). F65: a --changed suite's
    slot holds (kind `suite_slot`) are not the box's: they are reported apart and stay out of its busy share and waits."""
    window = hours * 3600
    every = [row for row in lock_rows(log) if not is_slot(row)]
    within = [row for row in lock_rows(log) if now - window <= row['at'] <= now]
    rows = [row for row in within if not is_slot(row)]
    slots = [row for row in within if is_slot(row)]
    slot_waits = [row['waited_s'] for row in slots if row['waited_s'] > 0]
    suites = [row for row in rows if is_suite(row)]
    deliveries = [row for row in rows if not is_suite(row)]
    held = sum(row['held_s'] for row in rows)
    held_deliveries = sum(row['held_s'] for row in deliveries)
    held_suites = held - held_deliveries
    waited = [row['waited_s'] for row in rows if row['waited_s'] > 0]
    landed = [merged_at for _landed, merged_at, _lane, _facts in merged if now - window <= merged_at <= now]
    free = 0
    try:
        table = Path(queue).read_text().split('## Unidades', 1)[1].split('\n## ', 1)[0]
        free = sum(1 for line in table.splitlines() if re.match(r'^\| F\d+ \|', line))
    except (OSError, IndexError):
        pass
    busy = held / window if window else 0.0
    return {'hours': hours, 'merged': len(landed), 'per_pr_s': window / len(landed) if landed else None,
            'deliveries': len(deliveries), 'busy': busy,
            'held_per_delivery_s': held_deliveries / len(deliveries) if deliveries else None,
            'suites': len(suites), 'held_per_suite_s': held_suites / len(suites) if suites else None,
            'waits': len(waited), 'wait_max_s': max(waited) if waited else 0.0, 'queue_rows': free,
            'slots': len(slots), 'held_per_slot_s': sum(row['held_s'] for row in slots) / len(slots) if slots else None,
            'slot_waits': len(slot_waits), 'slot_wait_max_s': max(slot_waits) if slot_waits else 0.0,
            'batches': batch_log(every), 'cpu': box_cpu(deliveries),
            'constraint': ('box (the serial gate)' if busy >= BOX_BOUND
                           else 'supply of ready units' if free < SUPPLY_PER_LANE * lanes
                           else 'lane authoring (units are ready; PRs are not arriving)')}


READY_RED = 0.25  # D-297, design-trem.md §5: the gate's red share p at or under which a batch on the box pays
BATCH_HOLD = 1.3  # a batch round's lock time over a single delivery's until the lock log measures one (F64 row: ~1.3x)


def batch_reading(found, gate, sizes_by_red, cap):
    """F64 (D-297, design-trem.md §5): `ready` when the box's busy share in `found` (constraint) reaches BOX_BOUND and
    the gate's red share p in `gate` (gate_runs over the last train.batch_red_window merged PRs) is at most READY_RED,
    else `why` names the first condition that fails. k is the train's k_max for p (train.batch_size_by_red, capped by
    train.batch_size); the projected ceiling is the serial one (3600 s over the seconds held per delivery) times k over
    the batch's hold ratio (held per batch over held per single delivery in the lock log, else BATCH_HOLD)."""
    p = None if 'error' in gate or not gate.get('runs') else gate['p']
    batches = found.get('batches') or {}
    ratio = (batches['held_per_batch_s'] / batches['held_per_single_s']
             if batches.get('held_per_batch_s') and batches.get('held_per_single_s') else BATCH_HOLD)
    single = 3600 / found['held_per_delivery_s'] if found.get('held_per_delivery_s') else None
    # train.size_for_red's rule, stated here since engine-delivery does not import engine-train (D-067): the first row whose
    # red_max p does not pass, capped by train.batch_size; 1 (no batch) past the last row or with p unread
    k = next((min(row['size'], cap) for row in sizes_by_red if p is not None and p <= row['red_max']), 1)
    unread = None if p is not None else gate.get('error') or 'no gate run measured'
    why = (f"box busy {found['busy']:.0%} < {BOX_BOUND:.0%}" if found['busy'] < BOX_BOUND
           else f'p unread: {unread}' if p is None
           else f'p {p:.3f} > {READY_RED}' if p > READY_RED else None)
    return {'ready': why is None, 'why': why, 'busy': found['busy'], 'p': p, 'unread': unread, 'prs': len(gate.get('prs') or ()),
            'k': k, 'ratio': ratio, 'single_per_h': single, 'ceiling_per_h': single * k / ratio if single else None}


def measured_batch_reading(found=None, hours=1.0, now=None, base=None, since=SINCE, zone=ZONE, lazy=False):
    """batch_reading from the box's lock log over the last `hours` and p read from the forge; with `lazy` (deliver,
    inside the box's lock) p is not read while the box is not busy, since the reading cannot be ready then."""
    import config
    if found is None:
        found = constraint([], now or time.time(), hours, config.get('delivery.gate_lock_log'),
                           ROOT / 'docs' / 'programs' / 'vazao' / 'fila.md')
    if lazy and found['busy'] < BOX_BOUND:
        gate = {'error': 'not read'}
    else:
        gate = measured_gate_runs(ROOT, base or f"origin/{config.get('train.base_branch')}", since,
                                  config.get('train.batch_red_window'), zone, sizes=found['batches']['sizes'])
    return batch_reading(found, gate, config.get('train.batch_size_by_red'), config.get('train.batch_size'))


def merged_prs(root, base, since, count, zone=ZONE):
    """[(number, merge sha)] of the last `count` pull requests merged into `base` since `since`, newest first, read from
    the first-parent merge subjects (`Merge pull request #n from ...`, or `... (#n)`, the Origin form)."""
    rows = git(root, 'log', base, '--first-parent', '--merges', f'--since={since}', f'--format=%H{FIELD}%s', zone=zone)
    found, seen = [], set()
    for row in rows.splitlines():
        sha, _, subject = row.partition(FIELD)
        match = PR_NUMBER.search(subject)
        number = int(match.group(1) or match.group(2)) if match else None
        if number is not None and number not in seen:
            seen.add(number)
            found.append((number, sha))
    return found[:count]


def is_suite(row):
    """F58: a lock-log row a whole suite (scripts/test-suite) wrote, not a delivery."""
    return row.get('kind') == 'suite'


def is_slot(row):
    """F65: a lock-log row of a --changed suite's slot (gate.changed_suite_slots), not a hold of the box lock."""
    return row.get('kind') == 'suite_slot'


def lock_rows(log):
    """Every row of the box's lock log (F38), oldest first; a missing log reads as no rows and a broken line is skipped."""
    try:
        lines = Path(os.path.expanduser(log)).read_text().splitlines()
    except OSError:
        return []
    rows = []
    for line in lines:
        try:
            row = json.loads(line)
            float(row['at']), float(row['held_s']), float(row['waited_s'])
        except (ValueError, KeyError, TypeError):
            continue
        rows.append(row)
    return rows


def batch_log(rows, last=BATCH_WINDOW):
    """F36: the last `last` batches of the lock log (rows with a `batch` {id, prs, runs, merged, ejected, conflicted,
    refused}, written by the leader that ran it) against the single deliveries of the same log:
      runs_per_resolved  tier-2 runs over the PRs the batches resolved (merged, ejected, conflicted or refused); the
                         batch stops paying at 1.0 (design-trem.md §5 turns delivery.batch off there);
      green              batches every member of which merged with one run;
      held_per_batch_s / held_per_single_s  the lock time of a batch against that of a delivery alone."""
    batches = [row for row in rows if isinstance(row.get('batch'), dict)][-last:]
    singles = [row for row in rows if not isinstance(row.get('batch'), dict) and not is_suite(row)]
    runs = sum(row['batch'].get('runs', 0) for row in batches)
    resolved = sum(len(row['batch'].get(kind) or ()) for row in batches
                   for kind in ('merged', 'ejected', 'conflicted', 'refused'))
    green = sum(1 for row in batches if row['batch'].get('runs') == 1 and row['batch'].get('prs')
                and list(row['batch'].get('merged') or ()) == list(row['batch']['prs']))
    return {'batches': len(batches), 'green': green, 'runs': runs, 'resolved': resolved,
            'runs_per_resolved': runs / resolved if resolved else None,
            'held_per_batch_s': sum(row['held_s'] for row in batches) / len(batches) if batches else None,
            'held_per_single_s': sum(row['held_s'] for row in singles) / len(singles) if singles else None,
            'sizes': {row['batch'].get('id'): len(row['batch'].get('prs') or ()) for row in batches}}


@contextlib.contextmanager
def pinned_tip(port):
    """F91: within the block, every git-ref log under `port` is fetched once. A read of one PR's channel fetched the
    log's tip again (3 git calls, ~0.8 s on the box) although the parse is already kept per tip; a window of PRs read
    in one batch needs the tip once. Nothing is written, so a tip that moves during the block is read at the next call."""
    adapter = getattr(port, 'adapter', None)
    logs = [adapter, getattr(adapter, 'main', None), *(getattr(adapter, '_logs', lambda: [])())]
    refs = {id(log.refs): log.refs for log in logs if getattr(log, 'refs', None) is not None}
    held = {}
    for key, found in refs.items():
        original, memo = found.read, {}

        def read(name, original=original, memo=memo):
            if name not in memo:
                memo[name] = original(name)
            return memo[name]
        held[key] = (found, original)
        found.read = read
    try:
        yield
    finally:
        for found, original in held.values():
            found.read = original


def cache_file():
    """Where a window's gate runs are kept between calls: shared by every worktree of the machine."""
    return Path(os.environ.get('FLOW_METRICS_CACHE') or Path.home() / '.cache' / 'the-tower' / 'flow-metrics.json')


def cached(path, key, compute, ttl=CACHE_TTL_S, now=None):
    """F91: `compute()` once per `key` per `ttl` seconds, kept in the JSON file `path`. A result with an 'error' is never
    kept (a forge that could not be read is asked again); a file that cannot be read or written costs the reuse only."""
    now = time.time() if now is None else now
    try:
        held = json.loads(Path(path).read_text())
        if held['key'] == key and 0 <= now - held['at'] < ttl:
            return held['value']
    except (OSError, ValueError, KeyError, TypeError):
        pass
    value = compute()
    if not (isinstance(value, dict) and value.get('error')):
        try:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            temp = Path(f'{path}.{os.getpid()}')
            temp.write_text(json.dumps({'key': key, 'at': now, 'value': value}))
            os.replace(temp, path)
        except OSError:
            pass
    return value


def read_verdicts(port, repo, prs):
    """{pr: [gate.passed, gate.failed, pr.merged and pr.ejected envelopes in log order]}: one read of each PR's channel,
    never the repository channel, so the cost is the window's PR count (the control plane allows 600 requests a
    minute)."""
    import gate_verdicts
    kinds = (*gate_verdicts.TYPES, 'pr.merged', 'pr.ejected')
    with pinned_tip(port):
        return {pr: [event for event in port.read(repo, pr, kinds=kinds)
                     if event.get('type') in ('pr.merged', 'pr.ejected') or gate_verdicts.is_verdict(event)] for pr in prs}


def batch_of(event):
    """The tier-2 batch id a pr.merged or pr.ejected names, or None (a PR merged on its own gate)."""
    if event.get('type') not in ('pr.merged', 'pr.ejected'):
        return None
    found = (event.get('payload') or {}).get('batch_id')
    return found if isinstance(found, str) and found.startswith(BATCH_PREFIX) else None


def gate_runs(events, merges, sizes=None):
    """The gate's cost per merged PR over the window `merges` ([(pr, merge sha)]; VAZÃO F24, toc section 6): every
    published verdict on a PR's channel is one gate run.
      p          the share of runs that came back red (gate.failed);
      n_r        runs per merged PR, over the PRs with a recorded verdict (`measured`); the PRs without one (merged
                 before the event log, or by hand) are listed in `unrecorded`, never counted as zero runs;
      rejudged   runs that followed a green verdict of the same PR on another base (`scripts/deliver` judging again
                 because the base moved during the gate);
      carried    verdicts carried from an earlier run (no suite ran);
      foreign    PRs whose channel records another merge commit: the number belongs to another forge's PR (GitHub
                 numbers before the Origin cut-over), so its events are not this merge's;
      batched    PRs judged in a tier-2 batch on the box (F36): each batch a PR took part in (its pr.merged or
                 pr.ejected names the batch id) is 1/k of a run, k the batch's size (`sizes`, from the lock log, else
                 the window's PRs that name the batch), red when the PR left it as the culprit (pr.ejected)."""
    runs = red = rejudged = carried = 0
    unrecorded, foreign, measured, batched = [], [], [], []
    members = collections.Counter(bid for pr, _sha in merges
                                  for bid in {batch_of(event) for event in events.get(pr) or []} if bid)
    for pr, sha in merges:
        found = events.get(pr) or []
        landed = {event['payload'].get('merge_sha') for event in found if event.get('type') == 'pr.merged'}
        if landed and sha not in landed:
            foreign.append(pr)
            continue
        verdicts = [event for event in found if event.get('type') not in ('pr.merged', 'pr.ejected')]
        shares = {}
        for event in found:
            bid = batch_of(event)
            if bid:
                culprit = event['type'] == 'pr.ejected' and (event.get('payload') or {}).get('cause') == 'culprit'
                shares[bid] = shares.get(bid, False) or culprit
        for bid, culprit in shares.items():
            share = 1 / max((sizes or {}).get(bid) or members[bid], 1)
            runs += share
            red += share if culprit else 0
        if shares:
            batched.append(pr)
        (measured if verdicts or shares else unrecorded).append(pr)
        previous = None
        for event in verdicts:
            payload = event.get('payload') or {}
            runs += 1
            red += event.get('type') == 'gate.failed'
            carried += bool(payload.get('carried_from'))
            before = (previous or {}).get('payload') or {}
            if (previous and previous.get('type') == 'gate.passed' and before.get('base_sha') and payload.get('base_sha')
                    and before['base_sha'] != payload['base_sha']):
                rejudged += 1
            previous = event
    return {'prs': [pr for pr, _sha in merges], 'measured': measured, 'runs': runs, 'red': red,
            'p': red / runs if runs else 0.0, 'n_r': runs / len(measured) if measured else 0.0, 'rejudged': rejudged,
            'carried': carried, 'unrecorded': unrecorded, 'foreign': foreign, 'batched': batched}


def measured_gate_runs(root, base, since, count, zone=ZONE, port=None, repo=None, sizes=None):
    """`gate_runs` of the last `count` merged PRs, read from the forge event port; {'prs', 'error'} when it cannot be
    read (no credential, no network), so the other guards still print. `sizes` is {batch id: members} from the lock
    log."""
    merges = merged_prs(root, base, since, count, zone)
    if port is not None:
        return read_gate_runs(merges, port, repo, sizes)
    # the real forge: the window's result is reused for CACHE_TTL_S (an injected port is always read)
    key = hashlib.sha1(json.dumps([merges, sizes, repo], sort_keys=True, default=str).encode()).hexdigest()
    return cached(cache_file(), key, lambda: read_gate_runs(merges, None, repo, sizes))


def read_gate_runs(merges, port, repo, sizes):
    try:
        if port is None:
            import forge_events
            port = forge_events.ForgeEvents(forge_events.adapter_from_config(), forge_events.clock_from_config(),
                                            'flow-metrics', 'flow-metrics')
        if repo is None:
            import config
            repo = config.get('forge-events.repo')
        return gate_runs(read_verdicts(port, repo, [pr for pr, _sha in merges]), merges, sizes)
    except Exception as error:  # noqa: BLE001 - a measure that cannot be read is reported, never a crash of the guards
        return {'prs': [pr for pr, _sha in merges], 'error': f'{type(error).__name__}: {str(error)[:200]}'}
