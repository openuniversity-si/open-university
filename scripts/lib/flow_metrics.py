"""Integrated commits per day and their guards (FLUXO-AMPLO, D-137), and merged pull requests per second (`--prs N`, SEMENTE): `scripts/flow-metrics`.

An INTEGRATED commit is a non-merge commit that reached the base branch through a merged pull request (the first-parent
merge is the envelope, never counted). RAW is that number per BRT day of landing (the merge's day). A commit is COUNTED only when nothing below
removes it; every guard counts operations (commits and hunks), never a time window:
  empty       its diff changes nothing once whitespace is ignored (a commit of nothing: not VALID work);
  fixup       its subject starts with `fixup!`, `squash!` or `Revert` (it undoes or patches another commit: rework);
  split       it touches exactly the same files as the commit right before it in the same pull request, with the same
              `Plan:` trailer (one unit of work cut in two: the pair counts once);
  docsonly    every file it changes is under docs/ (counted; a guard ratio against padding a plan with prose commits)
  tangled     it touches more than one area of the repository (docs, unit manifests, config and tests that accompany code are not areas) (not COHESIVE; counted, but reported as a guard ratio
              so the ratio, not a size threshold, is what a phase has to keep).
Guards are ratios of the raw count: empty, fixup, split and tangled commits, plus plan-linked (the commit's pull request
carries a `Plan:` trailer on it). Output: text table, or JSON with --json. The area of a path is its top directory (one
level deeper under a product root), enough to tell one concern from several without a registry. `--admit BASE..HEAD` asks
the same questions of a range before it is pushed.
"""
import argparse
import collections
import contextlib
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import statistics
import subprocess
import sys
import time

try:
    import regime  # the exception regime (D-260, lane 4); until it lands the count guards act as they do today
except ImportError:
    regime = None

ROOT = Path(__file__).resolve().parent.parent.parent
MARK = '\x1e'
FIELD = '\x1f'
PRODUCT_ROOTS = ('apps', 'packages', 'services')
DOCS = re.compile(r'^docs/')
COMPANION = re.compile(r'(^docs/|^units/|^config/|^CODEOWNERS$|(^|/)tests?/|\.test\.|^README)')
LANE = re.compile(r'^Merge pull request #\d+ from [^/]+/')
PLAN = re.compile(r'^Plan:\s*(\S+)', re.MULTILINE)
GATE_FIX = re.compile(r'^Gate-fix:\s*\S', re.MULTILINE)
UNDO = ('fixup!', 'squash!', 'Revert')
SINCE = '2026-10-24 00:00'
DAY_S = datetime.timedelta(days=1).total_seconds()
HOUR_S = datetime.timedelta(hours=1).total_seconds()
ZONE = 'America/Sao_Paulo'
LADDER_STEP_1 = 1000 / DAY_S  # SEMENTE section 3: step 1 is 1,000 merged pull requests per day, x10 per step
LADDER_FACTOR = 10
GUARD_WINDOW = 5  # merged PRs after a PR in which a rewrite of its lines counts as its rework (--guards)
CACHE_TTL_S = 60  # F91: how long a window's gate runs, read from the forge, are reused by the next call (lanes and the coordinator call --constraint several times)
GATE_RUNS_WINDOW = 10  # merged PRs whose gate runs --guards reads when neither --gate-runs nor --prs names a window
FREE_MARGIN = 0.5  # SEMENTE section 4: the engine's infrastructure uses at most half of each free-plan daily limit
QUOTA_WINDOW = 10  # merged lanes whose quota per PR --guards reads from the ledger when --quota names no window (F59)
PR_NUMBER = re.compile(r'^Merge pull request #(\d+)\b|\(#(\d+)\)\s*$')


def git(root, *args, zone=ZONE, stdin=None):
    env = dict(os.environ, TZ=zone)
    out = subprocess.run(['git', '-C', str(root), *args], capture_output=True, text=True, env=env, input=stdin)
    if out.returncode:
        raise SystemExit(f'flow-metrics: git {args[0]} failed: {out.stderr.strip()}')
    return out.stdout


def area(path):
    """The concern a path belongs to: its top directory, and for a product root (`apps/<name>`) the one below it. A script
    and its library under scripts/ are one area, not two."""
    parts = path.split('/')
    return '/'.join(parts[:1 + (parts[0] in PRODUCT_ROOTS)])


def parse_commits(log):
    """The commits of a `log -w --numstat` with MARK/FIELD formatting: [{sha, day, subject, plan, files}]."""
    commits = []
    for chunk in log.split(MARK)[1:]:
        head, _, stat = chunk.partition('\n\n\n')
        sha, day, at, subject, *rest = head.split(FIELD) + ['']
        body = rest[0]
        files = []
        for line in stat.splitlines():
            added, _, rest = line.partition('\t')
            deleted, _, path = rest.partition('\t')
            if path and (added, deleted) != ('0', '0'):
                files.append(path)
        found = PLAN.search(body)
        commits.append({'sha': sha, 'day': day, 'at': int(at), 'subject': subject, 'plan': found.group(1) if found else None,
                        'files': sorted(files), 'gate_fix': bool(GATE_FIX.search(body))})
    return commits


def envelopes(root, base, since, zone):
    """[(landing day, merge epoch seconds, lane, [commit shas oldest first])] of the first-parent merges after `since`.
    The lane is the head branch the merge subject names (`Merge pull request #n from owner/branch`)."""
    rows = git(root, 'log', base, '--first-parent', '--merges', f'--since={since}', '--date=format-local:%Y-%m-%d',
               f'--format=%H %P{FIELD}%ct{FIELD}%cd{FIELD}%s', zone=zone).split('\n')
    found = []
    for row in rows:
        head, _, rest = row.partition(FIELD)
        merged_at, _, rest = rest.partition(FIELD)
        landed, _, subject = rest.partition(FIELD)
        merge, *parents = head.split() or ['']
        if len(parents) > 1:
            shas = git(root, 'rev-list', '--reverse', '--no-merges', f'{parents[0]}..{parents[1]}', zone=zone).split()
            found.append((landed, int(merged_at), LANE.sub('', subject), shas))
    return found


def commit_facts(root, shas, zone):
    """Facts of each sha (whitespace ignored in the numstat), in the given order."""
    if not shas:
        return []
    fmt = f'{MARK}%H{FIELD}%cd{FIELD}%ct{FIELD}%s{FIELD}%b\n\n'
    log = git(root, 'log', '-w', '--no-walk=unsorted', '--date=format-local:%Y-%m-%d', f'--format={fmt}', '--numstat',
              '--stdin', zone=zone, stdin='\n'.join(shas))
    return parse_commits(log)


_LIFTED = {}


def guards_lifted():
    """True when the exception regime lifts the count guards (split, rework); asked once per process (D-260)."""
    if 'count-guards' not in _LIFTED:
        _LIFTED['count-guards'] = regime is not None and bool(regime.lifted('count-guards'))
    return _LIFTED['count-guards']


def uncounted(labels):
    """A commit is not counted when it is empty, or (unless the regime lifts the count guards) a fixup or a split."""
    guards = {'empty'} if guards_lifted() else {'empty', 'fixup', 'split'}
    return bool(guards & set(labels))


def classify(envelope):
    """The verdicts of one envelope's commits, in order: {sha: [labels]}; counted = no 'empty', 'fixup' or 'split'."""
    verdicts = {}
    previous = None
    for commit in envelope:
        labels = []
        if not commit['files']:
            labels.append('empty')
        if commit['subject'].startswith(UNDO):
            labels.append('fixup')
        same = previous and commit['files'] and commit['files'] == previous['files'] and commit['plan'] == previous['plan']
        if same and not commit.get('gate_fix'):
            labels.append('split')
        if len({area(path) for path in commit['files'] if not COMPANION.search(path)}) > 1:
            labels.append('tangled')
        if commit['files'] and all(DOCS.match(path) for path in commit['files']):
            labels.append('docsonly')
        verdicts[commit['sha']] = labels
        previous = commit
    return verdicts


def merged_envelopes(root, base, since, zone):
    """[(landing day, merge epoch seconds, lane, facts of its commits)] for every merged pull request after `since`."""
    parts = envelopes(root, base, since, zone)
    unique = list(dict.fromkeys(sha for _landed, _at, _lane, shas in parts for sha in shas))
    by_sha = {commit['sha']: commit for commit in commit_facts(root, unique, zone)}  # one git process, not one per pull request
    return [(landed, merged_at, lane, [by_sha[sha] for sha in shas if sha in by_sha]) for landed, merged_at, lane, shas in parts]


def measure(root, base, since, zone=ZONE, merged=None):
    days = collections.OrderedDict()
    for landed, _merged_at, _lane, facts in merged if merged is not None else merged_envelopes(root, base, since, zone):
        verdicts = classify(facts)
        planned = any(commit['plan'] for commit in facts)
        for commit in facts:
            labels = verdicts[commit['sha']]
            day = days.setdefault(landed, collections.Counter())
            day['raw'] += 1
            day['plan_linked'] += 1 if planned else 0
            for label in labels:
                day[label] += 1
            if not uncounted(labels):
                day['counted'] += 1
    return collections.OrderedDict(sorted(days.items()))


def rolling(merged, now, span):
    """Raw and counted integrated commits landed in the `span` seconds before `now` (epoch seconds): the lane-day of
    a sub-phase, which a calendar day cuts in two. The window only chooses which merges are read; what counts is the
    same rule as everywhere (D-137)."""
    total = collections.Counter()
    for _landed, merged_at, _lane, facts in merged:
        if now - span <= merged_at <= now:
            verdicts = classify(facts)
            total['raw'] += len(facts)
            total['counted'] += sum(1 for commit in facts if not uncounted(verdicts[commit['sha']]))
    return {'raw': total['raw'], 'counted': total['counted']}


def pr_rate(merged, now, count):
    """Merged pull requests per second over the last `count` merges (SEMENTE section 4): the window runs from the oldest
    of those merges to `now`, so the idle time since the last merge counts against the rate (a stop lowers it). `step`
    is the highest ladder step whose target the rate reaches (0 when none), `next` the target of the step above it."""
    times = sorted((merged_at for _landed, merged_at, _lane, _facts in merged if merged_at <= now), reverse=True)[:count]
    window = now - times[-1] if times else 0
    rate = len(times) / window if window > 0 else 0.0
    step = 0
    while rate >= LADDER_STEP_1 * LADDER_FACTOR ** step:
        step += 1
    return {'prs': len(times), 'window_s': window, 'rate': rate, 'step': step,
            'next': LADDER_STEP_1 * LADDER_FACTOR ** step}


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
    # train.size_for_red's rule, stated here since engine-flow does not import engine-train (D-067): the first row whose
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


def render_batch_reading(reading):
    """The `batch:` line of --constraint (F64): ready or not and why, p, and the projected ceiling with k."""
    busy = f"box busy {reading['busy']:.0%} {'>=' if reading['busy'] >= BOX_BOUND else '<'} {BOX_BOUND:.0%}"
    p = (f"p {reading['p']:.3f} {'<=' if reading['p'] <= READY_RED else '>'} {READY_RED} over {reading['prs']} PRs"
         if reading['p'] is not None else f"p unread ({reading['unread']})")
    if reading['single_per_h']:
        ceiling = (f"projected ceiling {reading['single_per_h']:.0f}/h x {reading['k']}/{reading['ratio']:.1f} "
                   f"~ {reading['ceiling_per_h']:.0f}/h with k {reading['k']}")
    else:
        ceiling = f"k {reading['k']}, no delivery logged for a ceiling"
    return f"batch: {'ready' if reading['ready'] else 'not ready'} ({busy}, {p}); {ceiling}"


def closed_hours(merged, now, hours, zone=ZONE):
    """Merged pull requests per minute in each of the last `hours` closed clock hours of `zone`, newest first
    (Daniel 03/11 04:13 BRT: PR/min per closed hour is the number he follows). The hour still running is not counted."""
    import zoneinfo
    tz = zoneinfo.ZoneInfo(zone)
    top = datetime.datetime.fromtimestamp(now, tz).replace(minute=0, second=0, microsecond=0)
    rows = []
    for back in range(1, hours + 1):
        start, end = top - datetime.timedelta(hours=back), top - datetime.timedelta(hours=back - 1)
        count = sum(1 for _landed, at, _lane, _facts in merged if start.timestamp() <= at < end.timestamp())
        rows.append({'hour': start.strftime('%Y-%m-%d %H:00'), 'prs': count, 'per_minute': count / 60})
    return rows


def hourly(merged, now, hours):
    """Counted integrated commits per hour for the last `hours` hours, newest first: element 0 is the hour that ends at
    `now`, element 1 the hour before it. The rate per hour is the number a lane is steered by (Daniel, 31/10 18:5x BRT:
    the hourly rate matters more than the 24 h one); the rule that counts is the same as everywhere (D-137)."""
    buckets = [0] * hours
    for _landed, merged_at, _lane, facts in merged:
        ago = int((now - merged_at) // HOUR_S)
        if 0 <= ago < hours and now >= merged_at:
            verdicts = classify(facts)
            buckets[ago] += sum(1 for commit in facts if not uncounted(verdicts[commit['sha']]))
    return buckets


def family(lane):
    """The lane a head branch belongs to: `lane2` for a `...-lane2-...` branch, else `lane1` (the session that started the
    programme). A branch name is the only record of who wrote a PR; the convention is the lane's own (its prompt names it)."""
    return 'lane2' if '-lane2-' in lane or lane.endswith('-lane2') else 'lane1'


def hourly_by_lane(merged, now, hours):
    """{lane: counted commits per hour, newest first} for the last `hours` hours, by `family` of the head branch."""
    def lane_of(row):
        _landed, _at, branch, _facts = row
        return family(branch)

    return {lane: hourly([row for row in merged if lane_of(row) == lane], now, hours) for lane in sorted({lane_of(row) for row in merged})}


def cycles(merged):
    """Per landing day, the medians in seconds over its pull requests: `wait` (last commit to merge), `authoring` per
    commit ((last commit - first commit) / commits), the number of pull requests and of lanes (distinct head branches). Operations are counted, time only
    describes the flow's cycle; no guard reads it."""
    per_day = collections.OrderedDict()
    for landed, merged_at, lane, facts in sorted(merged, key=lambda row: row[0]):
        if not facts:
            continue
        first, last = min(c['at'] for c in facts), max(c['at'] for c in facts)
        row = per_day.setdefault(landed, {'wait': [], 'authoring': [], 'lanes': set()})
        row['lanes'].add(lane)
        row['wait'].append(max(merged_at - last, 0))
        row['authoring'].append((last - first) / len(facts))
    return collections.OrderedDict((day, {'prs': len(row['wait']), 'lanes': len(row['lanes']), 'wait_s': statistics.median(row['wait']),
                                          'authoring_s': statistics.median(row['authoring'])})
                                   for day, row in per_day.items())


def parse_changes(log):
    """[{sha, added: {(file, text)}, removed: [(file, text)]}] of a `log -p -U0` with MARK-prefixed shas, in log order.
    Blank lines are not content and never match."""
    commits = []
    for chunk in log.split(MARK)[1:]:
        sha, _, patch = chunk.partition('\n')
        added, removed, path = set(), [], None
        for line in patch.splitlines():
            if line.startswith('+++ '):
                path = line[len('+++ '):].removeprefix('b/')
            elif line.startswith('--- ') or line.startswith('diff ') or line.startswith('@@'):
                continue
            elif line[:1] == '+' and line[1:].strip():
                added.add((path, line[1:]))
            elif line[:1] == '-' and line[1:].strip():
                removed.append((path, line[1:]))
        commits.append({'sha': sha.strip(), 'added': added, 'removed': removed})
    return commits


def rewritten(changes, window):
    """The shas of commits whose added lines one of the next `window` commits (in integration order) removed: the
    durability guard in operations, no clock. A commit is listed once, however many lines were rewritten."""
    latest = {}
    found = []
    for position, commit in enumerate(changes):
        for key in commit['removed']:
            earlier = latest.get(key)
            if earlier is not None and position - earlier[0] <= window and earlier[1] not in found:
                found.append(earlier[1])
        for key in commit['added']:
            latest[key] = (position, commit['sha'])
    return found


def reworked_prs(changes, owner, window):
    """The PRs (by index, oldest first) one of whose added lines a later PR within `window` merged PRs removed: the
    rework guard of SEMENTE section 4 at the level it names (a PR corrected or reverted by another), no clock."""
    latest, found = {}, []
    for commit in changes:
        pr = owner[commit['sha']]
        for key in commit['removed']:
            earlier = latest.get(key)
            if earlier is not None and 0 < pr - earlier <= window and earlier not in found:
                found.append(earlier)
        for key in commit['added']:
            latest[key] = pr
    return found


def pr_rework(root, base, since, window, zone=ZONE):
    """Share of the merged PRs since `since` whose lines a later PR within `window` merged PRs rewrote."""
    parts = list(reversed(envelopes(root, base, since, zone)))
    owner = {sha: index for index, (_day, _at, _lane, shas) in enumerate(parts) for sha in shas}
    shas = [sha for _day, _at, _lane, shas in parts for sha in shas]
    if not shas:
        return {'window': window, 'prs': 0, 'reworked': 0, 'share': 0}
    out = git(root, 'log', '--no-walk=unsorted', '--no-merges', '-p', '-U0', '--no-color',
              f'--format={MARK}%H', '--stdin', zone=zone, stdin='\n'.join(shas))
    hits = reworked_prs(parse_changes(out), owner, window)
    return {'window': window, 'prs': len(parts), 'reworked': len(hits), 'share': len(hits) / len(parts)}


def incidents(root):
    """{open, undecided}: incident records still open, and those whose Case, Class or Design is still undecided (the
    SEMENTE section 4 guard "incidentes abertos sem causa raiz")."""
    found = {'open': 0, 'undecided': 0}
    for path in sorted((Path(root) / 'docs' / 'operations' / 'incidents').glob('I-*.md')):
        text = path.read_text()
        if re.search(r'^status: open$', text, re.M):
            found['open'] += 1
            found['undecided'] += 1 if '(to be decided)' in text else 0
    return found


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


def render_cpu(cpu):
    """F71: one line of the box's CPU per delivery against its ceiling, and the idle share of the holds."""
    ceiling = f"{cpu['ceiling_per_h']:.0f} deliveries/h" if cpu['ceiling_per_h'] else 'no CPU spent'
    idle = f"{cpu['idle']:.0%}" if cpu['idle'] is not None else 'unknown'
    return (f"box CPU: {cpu['cpu_per_delivery_s']:.0f} CPU-s per delivery ({cpu['deliveries']} with cpu_s) against "
            f"{cpu['vcpus']} vCPU ({cpu['ceiling_cpu_s_h']} CPU-s/h, ceiling {ceiling}); hold idle {idle}")


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


def render_batches(row):
    """The line of `batch_log`, or None when the log has no batch."""
    if not row or not row['batches']:
        return None
    per = f"{row['runs_per_resolved']:.2f}" if row['runs_per_resolved'] is not None else '-'
    batch = f"{row['held_per_batch_s']:.0f} s" if row['held_per_batch_s'] is not None else '-'
    single = f"{row['held_per_single_s']:.0f} s" if row['held_per_single_s'] is not None else '-'
    return (f"batches on the box (last {row['batches']}): {row['green']} green, {row['runs']} tier-2 runs for "
            f"{row['resolved']} resolved PRs ({per} per PR; off at 1.00), held {batch} per batch, {single} per single "
            'delivery')


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


def rows_read(document, limit):
    """The free-plan guard (VAZÃO F34, SEMENTE section 4): the control plane's storage rows read (its `rows_read`
    metric, per UTC day, hour and the hour before) against the Free plan's `limit` a day. It warns at FREE_MARGIN of
    the limit, or when the previous hour's pace over a day would reach it. {'error'} when the meter is absent."""
    found = {labels.get('window'): (labels, value)
             for labels, value in ((document or {}).get('metrics') or {}).get('rows_read') or []}
    if 'day' not in found:
        return {'error': 'the control plane exposes no rows_read: its Worker predates F34'}
    day, today = found['day']
    hour, this_hour = found.get('hour', ({}, 0))
    previous, previous_hour = found.get('previous_hour', ({}, 0))
    threshold = limit * FREE_MARGIN
    pace = previous_hour * round(DAY_S / HOUR_S)
    warning = None
    if today >= threshold:
        warning = 'over half the daily limit'
    elif pace >= threshold:
        warning = "the previous hour's pace reaches half the daily limit"
    since = day.get('since') or ''
    return {'day': day.get('at'), 'today': today, 'hour': hour.get('at'), 'this_hour': this_hour,
            'previous_hour': previous_hour, 'pace': pace, 'limit': limit, 'threshold': threshold,
            'share': today / limit if limit else 0.0, 'warning': warning,
            'partial_since': since if since[:10] == day.get('at') and not since.endswith('T00') else None}


def measured_rows_read(read=None, limit=None):
    """`rows_read` of the control plane's public GET /status; {'error'} when it cannot be read (down, the quota spent,
    no network), so the other guards still print."""
    try:
        if limit is None:
            import config
            limit = config.get('service.free_rows_read_day')
        if read is None:
            import service_status
            read = service_status.Sources(ROOT).control
        return rows_read(read(), limit)
    except Exception as error:  # noqa: BLE001 - a measure that cannot be read is reported, never a crash of the guards
        return {'error': f'{type(error).__name__}: {str(error)[:200]}'}


def render_rows_read(row):
    """The guard's one line."""
    if 'error' in row:
        return f"rows read on the control plane: not measured ({row['error']})"
    since = f", metered since {row['partial_since']}" if row['partial_since'] else ''
    verdict = f"WARNING: {row['warning']}" if row['warning'] else 'ok'
    return (f"rows read on the control plane today (UTC {row['day']}{since}): {row['today']:,} of {row['limit']:,} "
            f"({row['share']:.1%}); this hour {row['this_hour']:,}, previous hour {row['previous_hour']:,} "
            f"({row['pace']:,} a day at that pace); guard at half the limit ({row['threshold']:,.0f}): {verdict}")


def durability(root, base, since, window, zone=ZONE):
    """Share of the integrated commits since `since` rewritten within `window` later integrated commits."""
    shas = [sha for _day, _at, _lane, shas in reversed(envelopes(root, base, since, zone)) for sha in shas]
    if not shas:
        return {'window': window, 'rewritten': 0, 'share': 0}
    out = git(root, 'log', '--no-walk=unsorted', '--no-merges', '-p', '-U0', '--no-color',
              f'--format={MARK}%H', '--stdin', zone=zone, stdin='\n'.join(shas))
    hits = rewritten(parse_changes(out), window)
    return {'window': window, 'rewritten': len(hits), 'share': len(hits) / len(shas)}


def admit(root, rev_range, zone=ZONE):
    """The verdicts of the commits of `rev_range` (oldest first), as they would be counted once integrated: [(sha,
    subject, labels)], labels as in `classify` (empty, fixup, split, tangled); a commit counts unless it is empty, fixup
    or split. The admission-time form of the guards (D-137, D-144): the same rule, asked before the push."""
    shas = git(root, 'rev-list', '--reverse', '--no-merges', rev_range, zone=zone).split()
    facts = commit_facts(root, shas, zone)
    verdicts = classify(facts)
    out = git(root, 'log', '--no-walk=unsorted', '--no-merges', '-p', '-U0', '--no-color', f'--format={MARK}%H', '--stdin', zone=zone,
              stdin='\n'.join(shas))
    again = set(rewritten(parse_changes(out), len(shas)))  # D-243: a later commit of the range removes its lines
    return [(commit['sha'], commit['subject'], verdicts[commit['sha']] + (['rework'] if commit['sha'] in again else []))
            for commit in facts]


def refused(rows):
    """The rows an admission would not count."""
    return [row for row in rows if uncounted(row[-1])]


def rework(root, base, since, zone=ZONE):
    """Share of the integrated commits whose added lines a LATER commit of the same pull request removed: one unit of
    work cut in pieces, or written twice before it landed (D-243). Unlike `durability` it needs no window: the envelope is
    the window. A guard ratio like the others; the commit still counts."""
    parts = envelopes(root, base, since, zone)
    shas = [sha for _day, _at, _lane, group in parts for sha in group]
    if not shas:
        return {'rewritten': 0, 'share': 0}
    out = git(root, 'log', '--no-walk=unsorted', '--no-merges', '-p', '-U0', '--no-color', f'--format={MARK}%H', '--stdin',
              zone=zone, stdin='\n'.join(shas))
    by_sha = {change['sha']: change for change in parse_changes(out)}
    hits = []
    for _day, _at, _lane, group in parts:
        changes = [by_sha[sha] for sha in group if sha in by_sha]
        hits.extend(rewritten(changes, len(changes)))
    return {'rewritten': len(hits), 'share': len(hits) / len(shas)}


def ratios(days):
    total = collections.Counter()
    for counts in days.values():
        total.update(counts)
    raw = total['raw'] or 1
    return {name: total[name] / raw for name in ('empty', 'fixup', 'split', 'tangled', 'docsonly', 'plan_linked')}


def report(days):
    total = collections.Counter()
    for counts in days.values():
        total.update(counts)
    names = ('raw', 'counted', 'empty', 'fixup', 'split', 'tangled', 'docsonly', 'plan_linked')
    return {'days': days, 'total': {name: total[name] for name in names}, 'guards': ratios(days)}


def read_ledger(path):
    """The rows of the quota ledger (flow.lanes_ledger, written by scripts/usage --lanes --write); a broken line is skipped."""
    path = Path(path).expanduser()
    rows = []
    for line in path.read_text().splitlines() if path.exists() else []:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def quota(rows, last):
    """The cost of a merged PR over the last `last` merged PRs of the ledger (F59): the weighted tokens, wall seconds and
    tool calls of its lane rows summed per PR, their medians and the weighted mean, and the coordinators' share: each
    coordinator row's weighted tokens per PR for every PR of the window merged in its span."""
    lanes = collections.defaultdict(lambda: {'weighted': 0, 'wall_s': 0, 'tool_calls': 0, 'end': ''})
    for row in rows:
        if row.get('role') == 'lane' and row.get('merged') and row.get('pr'):
            cost = lanes[row['pr']]
            cost['weighted'] += (row.get('tokens') or {}).get('weighted', 0)
            cost['wall_s'] += row.get('wall_s', 0)
            cost['tool_calls'] += row.get('tool_calls', 0)
            cost['end'] = max(cost['end'], row.get('end') or '')
    window = sorted(lanes, key=lambda pr: lanes[pr]['end'], reverse=True)[:last]
    if not window:
        return {'prs': []}
    coordinator = sum(row.get('weighted_per_pr') or 0 for row in rows if row.get('role') == 'coordinator'
                      for pr in row.get('prs') or [] if pr in window)
    spent = sum(lanes[pr]['weighted'] for pr in window)
    pick = lambda field: [lanes[pr][field] for pr in window]  # noqa: E731
    return {'prs': window, 'weighted_median': statistics.median(pick('weighted')), 'weighted_mean': spent / len(window),
            'wall_median_s': statistics.median(pick('wall_s')), 'tool_calls_median': statistics.median(pick('tool_calls')),
            'coordinator': coordinator, 'coordinator_share': coordinator / (spent + coordinator) if spent + coordinator else 0}


def render_quota(row):
    """One line: the cost of a merged PR over the window, or why it is not measured."""
    prs = row['prs']
    if not prs:
        return 'quota per merged PR: not measured (no merged lane in the ledger; scripts/usage --lanes DIR --write fills it)'
    return (f"quota per merged PR over the last {len(prs)} merged lanes (#{min(prs)} to #{max(prs)}): weighted tokens median "
            f"{row['weighted_median']:.0f}, mean {row['weighted_mean']:.0f}; wall median {row['wall_median_s']:.0f} s; tool calls "
            f"median {row['tool_calls_median']:.0f}; coordinator {row['coordinator']:.0f} weighted "
            f"({row['coordinator_share']:.0%} of lane plus coordinator)")


def render_gate_runs(row):
    """One line per measure of `gate_runs`, each naming its window."""
    prs = row['prs']
    window = f"last {len(prs)} merged PRs" + (f" (merged #{prs[-1]} to #{prs[0]})" if prs else '')
    if 'error' in row:
        return [f"gate runs on the {window}: not measured ({row['error']})"]
    batched = row.get('batched') or []
    return [f"red gate runs on the {window}: {row['red']:g} of {row['runs']:g} (p {row['p']:.3f})",
            f"gate runs per merged PR on the {window}: {row['n_r']:.2f} (n_r, over the {len(row['measured'])} with a "
            "recorded verdict" + (f", {len(batched)} judged in a batch at 1/k run each" if batched else '')
            + "); none recorded: " + (' '.join(f'#{pr}' for pr in row['unrecorded']) or '-')
            + '; another forge\'s number: ' + (' '.join(f'#{pr}' for pr in row['foreign']) or '-'),
            f"gate runs judging again because the base moved on the {window}: {row['rejudged']} of {row['runs']}; "
            f"carried verdicts: {row['carried']}"]


def render(data):
    lines = ['day         raw  counted  empty  fixup  split  tangled']
    for day, counts in data['days'].items():
        lines.append(f"{day}  {counts['raw']:>4}  {counts['counted']:>7}  {counts['empty']:>5}  {counts['fixup']:>5}  "
                     f"{counts['split']:>5}  {counts['tangled']:>7}")
    total = data['total']
    lines.append(f"total       {total.get('raw', 0):>4}  {total.get('counted', 0):>7}")
    for day, cycle in data.get('cycles', {}).items():
        lines.append(f"{day}  prs {cycle['prs']:>3}  lanes {cycle['lanes']:>3}  wait_s {cycle['wait_s']:.0f}  authoring_s/commit {cycle['authoring_s']:.0f}")
    if 'rework' in data:
        lines.append(f"rewritten by a later commit of the same pull request: {data['rework']['rewritten']} ({data['rework']['share']:.3f})")
    for lane, counts in data.get('lanes', {}).items():
        lines.append(f"{lane} counted per hour, newest first: " + ' '.join(str(count) for count in counts))
    if 'hourly' in data:
        lines.append('counted per hour, newest first: ' + ' '.join(str(count) for count in data['hourly']))
    if 'prs' in data:
        prs = data['prs']
        lines.append(f"last {prs['prs']} merges in {prs['window_s']:.0f} s: {prs['rate']:.4f} PR/s, ladder step "
                     f"{prs['step']} reached, next target {prs['next']:.4f} PR/s")
    for row in data.get('closed_hours', []):
        lines.append(f"{row['hour']}  {row['prs']:>3} PRs  {row['per_minute']:.3f} PR/min")
    if 'constraint' in data:
        c = data['constraint']
        per_pr = f"{c['per_pr_s']:.0f} s per merged PR" if c['per_pr_s'] else 'no merge'
        held = f"{c['held_per_delivery_s']:.0f} s held per delivery" if c['held_per_delivery_s'] else 'no delivery logged'
        suites = f"{c['held_per_suite_s']:.0f} s held per suite" if c.get('held_per_suite_s') else 'no suite logged'
        lines.append(f"constraint (last {c['hours']} h): {c['constraint']}; {c['merged']} merged, {per_pr}; box busy "
                     f"{c['busy']:.0%} ({c['deliveries']} deliveries, {held}; {c.get('suites', 0)} suites, {suites}; "
                     f"{c['waits']} waited, longest "
                     f"{c['wait_max_s']:.0f} s); {c['queue_rows']} rows in the queue")
        if c.get('cpu'):
            lines.append(render_cpu(c['cpu']))
        if c.get('slots'):
            lines.append(f"--changed suites off the box: {c['slots']} slot holds, {c['held_per_slot_s']:.0f} s held per "
                         f"suite, {c['slot_waits']} waited, longest {c['slot_wait_max_s']:.0f} s")
        if render_batches(c.get('batches')):
            lines.append(render_batches(c['batches']))
    if 'batch_reading' in data:
        lines.append(render_batch_reading(data['batch_reading']))
    if 'rolling' in data:
        lines.append(f"last 24 h: {data['rolling']['raw']} raw, {data['rolling']['counted']} counted")
    if 'pr_rework' in data:
        rework_row = data['pr_rework']
        lines.append(f"PRs rewritten by one of the next {rework_row['window']} PRs: {rework_row['reworked']} of {rework_row['prs']} "
                     f"({rework_row['share']:.3f})")
    if 'gate_runs' in data:
        lines.extend(render_gate_runs(data['gate_runs']))
    if 'constraint' not in data and render_batches(data.get('batches')):
        lines.append(render_batches(data['batches']))
    if 'rows_read' in data:
        lines.append(render_rows_read(data['rows_read']))
    if 'quota' in data:
        lines.append(render_quota(data['quota']))
    if 'incidents' in data:
        lines.append(f"incidents open: {data['incidents']['open']}, without a root cause: {data['incidents']['undecided']}")
    if 'durability' in data:
        lines.append(f"rewritten within the next {data['durability']['window']} integrated commits: {data['durability']['rewritten']} ({data['durability']['share']:.3f})")
    lines.append('guards (share of raw): ' + ', '.join(f'{name} {value:.3f}' for name, value in data['guards'].items()))
    return '\n'.join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--base', default='origin/mod/roadmap-integration')
    parser.add_argument('--since', default=SINCE)
    parser.add_argument('--tz', default=ZONE)
    parser.add_argument('--json', action='store_true')
    parser.add_argument('--rework', action='store_true', help='share of commits rewritten by a later commit of the same pull request')
    parser.add_argument('--durability', type=int, metavar='K', help='share of commits rewritten by the next K integrated commits')
    parser.add_argument('--admit', metavar='RANGE', help='verdicts of the commits of a range (base..head); exit 1 if one would not count')
    parser.add_argument('--lanes', type=int, metavar='N', help='counted commits per hour of each lane for the last N hours, newest first')
    parser.add_argument('--hourly', type=int, metavar='N', help='counted commits per hour for the last N hours, newest first')
    parser.add_argument('--prs', type=int, metavar='N', help='merged pull requests per second over the last N merges and the ladder step it reaches')
    parser.add_argument('--closed-hours', type=int, metavar='N', help='merged pull requests per minute in each of the last N closed hours, newest first')
    parser.add_argument('--pr-rework', type=int, metavar='K', help='share of merged PRs a later PR within the next K merged PRs rewrote')
    parser.add_argument('--guards', action='store_true', help='the SEMENTE section 4 guards: PR rework (K=5), incidents open without a '
                        'root cause, the red-gate share p and gate runs per merged PR n_r (read from the forge event port), and the '
                        'control plane\'s rows read today against the free plan (F34)')
    parser.add_argument('--gate-runs', type=int, metavar='N', help='window of --guards gate runs: the last N merged PRs '
                        f'(default: --prs N, else {GATE_RUNS_WINDOW})')
    parser.add_argument('--constraint', type=float, nargs='?', const=1.0, metavar='HOURS',
                        help='the current constraint over the last HOURS (default 1): box busy share from the lock log, '
                             'merges, waits and the queue rows (F38); the batch reading, ready when busy >= 0.70 and '
                             'p <= 0.25, and its projected ceiling with k (F64, D-297)')
    parser.add_argument('--quota', type=int, metavar='N', help='weighted tokens, wall time and tool calls per merged PR over the '
                        f'last N merged lanes of the quota ledger (flow.lanes_ledger; --guards reads {QUOTA_WINDOW}) (F59)')
    parser.add_argument('--rolling', action='store_true', help='counted commits landed in the last 24 hours (a lane-day)')
    parser.add_argument('--cycles', action='store_true', help='also the wait and authoring medians per day')
    args = parser.parse_args(argv)
    if args.admit:
        rows = admit(ROOT, args.admit, args.tz)
        for sha, subject, labels in rows:
            print(f"{sha}  {','.join(labels) or 'counts'}  {subject}")
        return 1 if refused(rows) else 0
    merged = merged_envelopes(ROOT, args.base, args.since, args.tz)
    data = report(measure(ROOT, args.base, args.since, args.tz, merged))
    if args.lanes:
        data['lanes'] = hourly_by_lane(merged, time.time(), args.lanes)
    if args.hourly:
        data['hourly'] = hourly(merged, time.time(), args.hourly)
    if args.prs:
        data['prs'] = pr_rate(merged, time.time(), args.prs)
    if args.closed_hours:
        data['closed_hours'] = closed_hours(merged, time.time(), args.closed_hours, args.tz)
    if args.constraint:
        import config
        data['constraint'] = constraint(merged, time.time(), args.constraint, config.get('delivery.gate_lock_log'),
                                        ROOT / 'docs' / 'programs' / 'vazao' / 'fila.md')
        data['batch_reading'] = measured_batch_reading(data['constraint'], base=args.base, since=args.since, zone=args.tz)
    if args.rolling:
        data['rolling'] = rolling(merged, time.time(), DAY_S)
    if args.cycles:
        data['cycles'] = cycles(merged)
    if args.rework:
        data['rework'] = rework(ROOT, args.base, args.since, args.tz)
    if args.guards:
        data['pr_rework'] = pr_rework(ROOT, args.base, args.since, args.pr_rework or GUARD_WINDOW, args.tz)
        data['incidents'] = incidents(ROOT)
        import config
        data['batches'] = batch_log(lock_rows(config.get('delivery.gate_lock_log')))
        data['gate_runs'] = measured_gate_runs(ROOT, args.base, args.since, args.gate_runs or args.prs or GATE_RUNS_WINDOW,
                                               args.tz, sizes=data['batches']['sizes'])
        data['rows_read'] = measured_rows_read()
    if args.guards or args.quota:
        import config
        data['quota'] = quota(read_ledger(config.get('flow.lanes_ledger')), args.quota or QUOTA_WINDOW)
    if args.pr_rework:
        data['pr_rework'] = pr_rework(ROOT, args.base, args.since, args.pr_rework, args.tz)
    if args.durability:
        data['durability'] = durability(ROOT, args.base, args.since, args.durability, args.tz)
    print(json.dumps(data, indent=1) if args.json else render(data))
    return 0


if __name__ == '__main__':
    sys.exit(main())
