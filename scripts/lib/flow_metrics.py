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
import datetime
import json
from pathlib import Path
import re
import statistics
import sys
import time

try:
    import regime  # the exception regime (D-260, lane 4); until it lands the count guards act as they do today
except ImportError:
    regime = None

# The box's meter is delivery's (D-322): the batch reading and the gate runs of the merged PRs live beside the lock
# log and the verdict events they read (box_meter); flow-metrics reports them under the same names.
from box_meter import (  # noqa: E402,F401
    BATCH_HOLD, BATCH_PREFIX, BATCH_WINDOW, BOX_BOUND, CACHE_TTL_S, FIELD, PR_NUMBER, READY_RED, SINCE,
    SUPPLY_PER_LANE, ZONE, batch_log, batch_of, batch_reading, box_cpu, cache_file, cached, constraint, gate_runs,
    git, is_slot, is_suite, lock_rows, measured_batch_reading, measured_gate_runs, merged_prs, pinned_tip,
    read_gate_runs, read_verdicts)

ROOT = Path(__file__).resolve().parent.parent.parent
MARK = '\x1e'
PRODUCT_ROOTS = ('apps', 'packages', 'services')
DOCS = re.compile(r'^docs/')
COMPANION = re.compile(r'(^docs/|^units/|^config/|^CODEOWNERS$|(^|/)tests?/|\.test\.|^README)')
LANE = re.compile(r'^Merge pull request #\d+ from [^/]+/')
PLAN = re.compile(r'^Plan:\s*(\S+)', re.MULTILINE)
GATE_FIX = re.compile(r'^Gate-fix:\s*\S', re.MULTILINE)
UNDO = ('fixup!', 'squash!', 'Revert')
DAY_S = datetime.timedelta(days=1).total_seconds()
HOUR_S = datetime.timedelta(hours=1).total_seconds()
LADDER_STEP_1 = 1000 / DAY_S  # SEMENTE section 3: step 1 is 1,000 merged pull requests per day, x10 per step
LADDER_FACTOR = 10
GUARD_WINDOW = 5  # merged PRs after a PR in which a rewrite of its lines counts as its rework (--guards)
GATE_RUNS_WINDOW = 10  # merged PRs whose gate runs --guards reads when neither --gate-runs nor --prs names a window
QUOTA_WINDOW = 10  # merged lanes whose quota per PR --guards reads from the ledger when --quota names no window (F59)


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


def render_cpu(cpu):
    """F71: one line of the box's CPU per delivery against its ceiling, and the idle share of the holds."""
    ceiling = f"{cpu['ceiling_per_h']:.0f} deliveries/h" if cpu['ceiling_per_h'] else 'no CPU spent'
    idle = f"{cpu['idle']:.0%}" if cpu['idle'] is not None else 'unknown'
    return (f"box CPU: {cpu['cpu_per_delivery_s']:.0f} CPU-s per delivery ({cpu['deliveries']} with cpu_s) against "
            f"{cpu['vcpus']} vCPU ({cpu['ceiling_cpu_s_h']} CPU-s/h, ceiling {ceiling}); hold idle {idle}")


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
