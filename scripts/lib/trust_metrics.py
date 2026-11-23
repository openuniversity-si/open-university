"""External trust numbers and scope-calibrated autonomy ladder (D-353, C8): `scripts/model trust`.

Reads the proposed or active autonomy ladder from config/governance/autonomy-ladder.json against
contracts/model/autonomy.v1.json, computes eight external, non-self-reported trust indicators from
git history and repository/CI/production artifacts, and evaluates scope-calibrated autonomy levels
(A, B, C) with automatic demotion circuit breakers.

Every numeric threshold, window, percentile and path classification rule lives as data in
config/governance/autonomy-ladder.json; this module carries no hardcoded policy thresholds.
While the ladder's state is `proposed`, the effective autonomy level remains `none` even if every
indicator were green: explicit owner approval is required to activate promotion.
"""
import argparse
import json
import math
import re
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

import json_schema

CONTRACT_PATH = 'contracts/model/autonomy.v1.json'
LADDER_PATH = 'config/governance/autonomy-ladder.json'
MARK = '\x1e'
FIELD = '\x1f'
PR_NUMBER = re.compile(r'#([0-9]+)')
MERGE_BRANCH = re.compile(r'^Merge pull request #[0-9]+ from [^/]+/(\S+)')
FIXES_PR = re.compile(r'^Fixes-PR:\s*#?([0-9]+)', re.MULTILINE | re.IGNORECASE)
REVERT_SUBJECT = re.compile(r'^Revert\b', re.IGNORECASE)
FRONT_MATTER = re.compile(r'^---\n(.*?)\n---\n', re.DOTALL)
FROM_LINE = re.compile(r'^\s*FROM\s+(?:--[^\s]+\s+)*([^\s]+)(?:\s+AS\s+([^\s]+))?', re.IGNORECASE)
PIPE_SHELL = re.compile(r'\b(?:curl|wget)\b[^\n|]*\|\s*(?:[A-Z_][A-Z0-9_]*=\S+\s+)*(?:ba|da|z)?sh\b')
NO_AUDIT = re.compile(r'--no-audit\b')
ORDER = (
    'main_integrity',
    'change_failure_rework',
    'first_pass_yield',
    'independent_audit',
    'human_override_rate',
    'signal_to_overhead',
    'production_health_and_cost',
    'security_posture',
)


class TrustError(ValueError):
    """Raised when the autonomy ladder contract or configuration cannot be loaded."""


def _read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError) as error:
        raise TrustError(f'{path}: {error}') from None


def _read_optional_json(path):
    target = Path(path)
    if not target.is_file():
        return None
    try:
        return json.loads(target.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return None


def _git(root, *args, stdin=None):
    try:
        done = subprocess.run(['git', '-C', str(root), *args], input=stdin, capture_output=True, text=True, check=False)
    except OSError:
        return ''
    return done.stdout if done.returncode == 0 else ''


def _git_returncode(root, *args):
    try:
        return subprocess.run(['git', '-C', str(root), *args], capture_output=True, text=True, check=False).returncode
    except OSError:
        return -1


def _parse_iso(stamp):
    if not stamp or not isinstance(stamp, str):
        return None
    try:
        return datetime.fromisoformat(stamp.replace('Z', '+00:00'))
    except ValueError:
        return None


def _parse_day(value):
    if not value:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    try:
        return date.fromisoformat(str(value)[:len('YYYY-MM-DD')])
    except ValueError:
        return None


def _today(today):
    if today is None:
        return datetime.now(timezone.utc).date()
    parsed = _parse_day(today)
    if parsed is None:
        raise TrustError(f'invalid date: {today}')
    return parsed


def _round_metric(value, digits):
    return None if value is None else round(value, digits)


def _percentile(values, pct, scale):
    """Nearest-rank percentile for sorted or unsorted numeric values."""
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil((pct / scale) * len(ordered)) - 1))
    return ordered[index]


def load_ladder(root=ROOT):
    """Load and validate config/governance/autonomy-ladder.json against contracts/model/autonomy.v1.json."""
    root = Path(root)
    schema = _read_json(root / CONTRACT_PATH)
    ladder = _read_json(root / LADDER_PATH)
    errors = [f'{CONTRACT_PATH}: {err}' for err in json_schema.check_schema(schema)]
    errors += [f'{LADDER_PATH}: {err}' for err in json_schema.validate(schema, ladder)]
    if not errors:
        errors += _check_consistency(ladder)
    return ladder, errors


def _check_consistency(ladder):
    errors = []
    indicators = ladder['indicators']
    numbers = [item['number'] for item in indicators.values()]
    if len(set(numbers)) != len(numbers):
        errors.append(f'{LADDER_PATH}: duplicate indicator numbers')
    seen_levels = set()
    for item in ladder['levels']:
        tier = item['level']
        if tier in seen_levels:
            errors.append(f'{LADDER_PATH}: duplicate level {tier}')
        seen_levels.add(tier)
        prereq = item.get('prerequisite_level')
        if prereq is not None and prereq not in seen_levels:
            errors.append(f'{LADDER_PATH}: level {tier} prerequisite {prereq} must appear before it')
        for ind in item['required_indicators']:
            if ind not in indicators:
                errors.append(f'{LADDER_PATH}: level {tier} names unknown indicator {ind}')
    for breaker in ladder['circuit_breakers']:
        if breaker['indicator'] not in indicators:
            errors.append(f'{LADDER_PATH}: circuit breaker {breaker["id"]} names unknown indicator {breaker["indicator"]}')
    return errors


def first_parent_merges(root, limit):
    """First-parent merge commits newest first: [{sha, parents, timestamp, subject, body, pr, branch, files}]."""
    fmt = f'{MARK}%H{FIELD}%P{FIELD}%ct{FIELD}%s{FIELD}%b{FIELD}'
    out = _git(root, 'log', '--first-parent', '--merges', '-m', f'-n{limit}', f'--format={fmt}', '--numstat')
    merges = []
    for chunk in out.split(MARK)[1:]:
        parts = chunk.split(FIELD)
        if len(parts) < len(('sha', 'parents', 'ct', 's', 'b', 'stat')):
            continue
        sha, parent_str, ct_str, subject, body, stat, *_ = parts
        files = []
        for line in stat.splitlines():
            cols = line.split('\t')
            if len(cols) == len(('added', 'deleted', 'path')) and cols[-1]:
                files.append(cols[-1])
        pr_match = PR_NUMBER.search(subject)
        branch_match = MERGE_BRANCH.match(subject)
        try:
            ts = int(ct_str.strip())
        except ValueError:
            ts = 0
        merges.append({
            'sha': sha.strip(),
            'parents': parent_str.split(),
            'timestamp': ts,
            'subject': subject.strip(),
            'body': body.strip(),
            'pr': int(pr_match.group(1)) if pr_match else None,
            'branch': branch_match.group(1) if branch_match else None,
            'files': sorted(set(files)),
        })
    return merges


def _parse_front_matter(text):
    match = FRONT_MATTER.match(text)
    if not match:
        return {}
    fields = {}
    for line in match.group(1).splitlines():
        if ':' in line:
            key, _, value = line.partition(':')
            fields[key.strip()] = value.strip()
    return fields


DECISION_REF = re.compile(r'\bD-[0-9]+\b')
INDEPENDENT_AUTHORITIES = ('owner', 'independent')
EXPLICIT_AUTHORITIES = ('owner', 'independent', 'session', 'self')


def read_decision_authorities(root, ladder):
    """Map D-NNN -> {status, authority, source} from docs/domain/decisions/D-*.md (aligned with D-360)."""
    defaults = ladder['defaults']
    session_markers = [m.casefold() for m in defaults['session_authority_markers']]
    owner_markers = [m.casefold() for m in defaults['owner_authority_markers']]
    folder = Path(root) / ladder['indicators']['security_posture']['sources']['decisions_dir']
    records = {}
    superseded = set()
    if not folder.is_dir():
        return records
    for path in sorted(folder.glob('D-*.md')):
        text = path.read_text(encoding='utf-8', errors='replace')
        fields = _parse_front_matter(text)
        ident = fields.get('number', path.stem)
        raw_status = fields.get('status', 'accepted').strip().lower()
        status = 'accepted' if raw_status == 'recorded' else raw_status
        author = fields.get('author', '').strip().casefold()
        approver = fields.get('approver', '').strip().casefold()
        explicit = fields.get('authority', '').strip().lower()
        folded = text.casefold()
        if status == 'proposed':
            authority = 'proposed'
        elif author and approver and author == approver:
            authority = 'self'
        elif explicit in EXPLICIT_AUTHORITIES:
            authority = explicit
        elif author and approver:
            authority = 'independent'
        elif any(marker in folded for marker in session_markers):
            authority = 'session'
        elif any(marker in folded for marker in owner_markers):
            authority = 'owner'
        else:
            authority = 'unknown'
        if status == 'accepted':
            superseded.update(DECISION_REF.findall(fields.get('supersedes', '')))
        records[ident] = {'status': status, 'authority': authority, 'source': path.relative_to(root).as_posix()}
    for ident in superseded:
        if ident in records:
            records[ident]['status'] = 'superseded'
    return records


def _sort_runs_chronologically(runs, key):
    indexed = list(enumerate(runs))
    has_times = all(_parse_iso(item.get(key)) is not None for _, item in indexed)
    if has_times:
        indexed.sort(key=lambda pair: (_parse_iso(pair[1][key]), -pair[0]))
        return [item for _, item in indexed]
    return list(reversed(runs))


def measure_main_integrity(root, ladder, merges=None):
    """Indicator 1: post-merge full-suite pass rate and merges landed while main was red."""
    spec = ladder['indicators']['main_integrity']
    target = spec['target']
    digits = len(ladder['defaults']['diagnostic_percentiles'])
    data = _read_optional_json(Path(root) / spec['sources']['verdicts'])
    runs = data.get('runs') if isinstance(data, dict) and isinstance(data.get('runs'), list) else []
    if not runs:
        return {
            'number': spec['number'],
            'name': spec['name'],
            'state': 'unmeasured',
            'pass_rate': None,
            'passes': 0,
            'failures': 0,
            'total_runs': 0,
            'max_consecutive_failures': 0,
            'merges_while_red': 0,
            'red_streak_seconds': 0,
            'snapshot_at': data.get('at') if isinstance(data, dict) else None,
            'merges_since_snapshot': None,
            'target': target,
            'reason': 'no full-suite runs recorded',
        }
    ordered = _sort_runs_chronologically(runs, 'completed')
    passes = sum(1 for item in ordered if item.get('conclusion') == 'success')
    failures = len(ordered) - passes
    pass_rate = passes / len(ordered)
    max_streak, cur_streak, merges_while_red = 0, 0, 0
    streak_start, max_red_seconds = None, 0
    for item in ordered:
        ok = item.get('conclusion') == 'success'
        completed = _parse_iso(item.get('completed'))
        if ok:
            cur_streak = 0
            streak_start = None
        else:
            if cur_streak > 0:
                merges_while_red += 1
            else:
                streak_start = completed
            cur_streak += 1
            max_streak = max(max_streak, cur_streak)
            if streak_start is not None and completed is not None:
                max_red_seconds = max(max_red_seconds, int((completed - streak_start).total_seconds()))
    merges_since = None
    if merges:
        newest_sha = ordered[-1].get('sha')
        for index, merge in enumerate(merges):
            if merge['sha'] == newest_sha:
                merges_since = index
                break
    met = pass_rate >= target['min_pass_rate'] and merges_while_red <= target['max_merges_while_red'] and failures == 0
    return {
        'number': spec['number'],
        'name': spec['name'],
        'state': 'met' if met else 'not-met',
        'pass_rate': _round_metric(pass_rate, digits),
        'passes': passes,
        'failures': failures,
        'total_runs': len(ordered),
        'max_consecutive_failures': max_streak,
        'merges_while_red': merges_while_red,
        'red_streak_seconds': max_red_seconds,
        'snapshot_at': data.get('at'),
        'merges_since_snapshot': merges_since,
        'target': target,
    }


def _rework_within_window(root, merges, window):
    """Share of first-parent merges whose added non-blank lines are removed within `window` later merges."""
    if not merges:
        return 0, 0, None
    chronological = list(reversed(merges))
    shas = [item['sha'] for item in chronological]
    out = _git(root, 'log', '--no-walk=unsorted', '--first-parent', '-m', '-p', '-U0', '--no-color',
               f'--format={MARK}%H', '--stdin', stdin='\n'.join(shas))
    by_sha = {}
    for chunk in out.split(MARK)[1:]:
        sha, _, patch = chunk.partition('\n')
        added, removed, path = set(), [], None
        for line in patch.splitlines():
            if line.startswith('+++ '):
                path = line[len('+++ '):].removeprefix('b/')
            elif line.startswith(('--- ', 'diff ', '@@')):
                continue
            elif line.startswith('+') and line[1:].strip():
                added.add((path, line[1:]))
            elif line.startswith('-') and line[1:].strip():
                removed.append((path, line[1:]))
        by_sha[sha.strip()] = (added, removed)
    latest, hits = {}, set()
    for index, sha in enumerate(shas):
        added, removed = by_sha.get(sha, (set(), []))
        for key in removed:
            earlier = latest.get(key)
            if earlier is not None and 0 < index - earlier <= window:
                hits.add(earlier)
        for key in added:
            latest[key] = index
    return len(hits), len(shas), len(hits) / len(shas)


def measure_change_failure_rework(root, ladder, merges=None):
    """Indicator 2: external post-merge failure rate (CFR) plus diagnostic 5-PR line rework."""
    spec = ladder['indicators']['change_failure_rework']
    target = spec['target']
    defaults = ladder['defaults']
    digits = len(defaults['diagnostic_percentiles'])
    if merges is None:
        merges = first_parent_merges(root, defaults['max_window_merges'])
    if not merges:
        return {
            'number': spec['number'],
            'name': spec['name'],
            'state': 'unmeasured',
            'escape_rate': None,
            'escapes_total': 0,
            'escapes_by_source': {'reverts': 0, 'errata': 0, 'full_suite_regressions': 0, 'deploy_failures': 0, 'fixes_pr': 0},
            'rework_rate': None,
            'reworked_prs': 0,
            'window_prs': 0,
            'target': target,
            'reason': 'no merged pull requests in git history',
        }
    reverts, errata_hits, suite_regressions, deploy_failures, fixes_pr = set(), set(), set(), set(), set()

    for merge in merges:
        if REVERT_SUBJECT.search(merge['subject']):
            reverts.add(f'sha:{merge["sha"]}')
        for pr_num in FIXES_PR.findall(merge['body']):
            fixes_pr.add(f'pr:{pr_num}')
    # Also inspect non-merge commit subjects/bodies inside the merge window in one git call.
    oldest_parents = merges[-1]['parents']
    span = f'{oldest_parents[0]}..{merges[0]["sha"]}' if oldest_parents else merges[0]['sha']
    commit_log = _git(root, 'log', '--no-merges', f'--format={MARK}%H{FIELD}%s{FIELD}%b', span)
    for chunk in commit_log.split(MARK)[1:]:
        parts = chunk.split(FIELD)
        if len(parts) < len(('sha', 's', 'b')):
            continue
        c_sha, c_subj, c_body, *_ = parts
        c_sha, c_subj = c_sha.strip(), c_subj.strip()
        if REVERT_SUBJECT.search(c_subj):
            reverts.add(f'commit:{c_sha}')
        for pr_num in FIXES_PR.findall(c_body):
            fixes_pr.add(f'pr:{pr_num}')

    errata_data = _read_optional_json(Path(root) / spec['sources']['errata'])
    for idx, entry in enumerate((errata_data or {}).get('errata') or []):
        ref = entry.get('change') or entry.get('commit') or entry.get('sha') or f'entry:{idx}'
        errata_hits.add(f'erratum:{ref}')

    verdicts_data = _read_optional_json(Path(root) / spec['sources']['verdicts'])
    runs = (verdicts_data or {}).get('runs') or []
    ordered_runs = _sort_runs_chronologically(runs, 'completed') if runs else []
    prev_ok = True
    for run in ordered_runs:
        ok = run.get('conclusion') == 'success'
        if not ok and prev_ok:
            sha = run.get('sha') or str(run.get('id', ''))
            suite_regressions.add(f'suite:{sha}')
        prev_ok = ok

    deploy_data = _read_optional_json(Path(root) / spec['sources']['deploy_live'])
    for run in (deploy_data or {}).get('runs') or []:
        if run.get('conclusion') != 'success' or 'rollback' in str(run.get('event', '')).lower():
            deploy_failures.add(f'deploy:{run.get("id", "unknown")}')

    all_escapes = reverts | errata_hits | suite_regressions | deploy_failures | fixes_pr
    escape_rate = len(all_escapes) / len(merges)
    reworked_count, window_prs, rework_rate = _rework_within_window(root, merges, defaults['rework_window_prs'])
    met = escape_rate <= target['max_escape_rate']
    return {
        'number': spec['number'],
        'name': spec['name'],
        'state': 'met' if met else 'not-met',
        'escape_rate': _round_metric(escape_rate, digits),
        'escapes_total': len(all_escapes),
        'escapes_by_source': {
            'reverts': len(reverts),
            'errata': len(errata_hits),
            'full_suite_regressions': len(suite_regressions),
            'deploy_failures': len(deploy_failures),
            'fixes_pr': len(fixes_pr),
        },
        'rework_rate': _round_metric(rework_rate, digits),
        'reworked_prs': reworked_count,
        'window_prs': window_prs,
        'target': target,
    }


def measure_first_pass_yield(root, ladder):
    """Indicator 3: PR first-pass gate yield plus external flake rate (never silent green if unwired)."""
    spec = ladder['indicators']['first_pass_yield']
    target = spec['target']
    digits = len(ladder['defaults']['diagnostic_percentiles'])
    slo_data = _read_optional_json(Path(root) / spec['sources']['slo'])
    verdicts = (slo_data or {}).get('verdicts') if isinstance(slo_data, dict) else None
    verdicts = verdicts if isinstance(verdicts, list) else []

    flake_data = _read_optional_json(Path(root) / spec['sources']['flakes'])
    flake_wired, flake_events, flake_total, flake_rate = False, None, 0, None
    if isinstance(flake_data, dict):
        if isinstance(flake_data.get('runs'), list) and flake_data['runs']:
            flake_wired = True
            flake_total = len(flake_data['runs'])
            flake_events = sum(1 for item in flake_data['runs'] if item.get('flaked') or item.get('alone'))
            flake_rate = flake_events / flake_total
        elif isinstance(flake_data.get('total_runs'), int) and flake_data['total_runs'] > 0:
            flake_wired = True
            flake_total = flake_data['total_runs']
            flake_events = int(flake_data.get('flake_runs', 0))
            flake_rate = flake_events / flake_total

    if not verdicts:
        return {
            'number': spec['number'],
            'name': spec['name'],
            'state': 'unmeasured',
            'first_pass_rate': None,
            'pr_first_attempt_rate': None,
            'passed_runs': 0,
            'failed_runs': 0,
            'total_runs': 0,
            'flake_source_wired': flake_wired,
            'flake_events': flake_events,
            'flake_rate': _round_metric(flake_rate, digits),
            'snapshot_at': (slo_data or {}).get('at'),
            'target': target,
            'reason': 'no PR gate verdict runs recorded',
        }

    passed = sum(1 for item in verdicts if item.get('passed') is True)
    total = len(verdicts)
    failed = total - passed
    first_pass_rate = passed / total

    by_pr = {}
    for item in verdicts:
        pr = item.get('pr')
        if pr is None:
            continue
        stamp = _parse_iso(item.get('at')) or datetime.min.replace(tzinfo=timezone.utc)
        if pr not in by_pr or stamp < by_pr[pr][0]:
            by_pr[pr] = (stamp, item.get('passed') is True)
    pr_rate = (sum(1 for _, ok in by_pr.values() if ok) / len(by_pr)) if by_pr else first_pass_rate

    if first_pass_rate < target['min_first_pass_rate'] or pr_rate < target['min_first_pass_rate']:
        state = 'not-met'
    elif not flake_wired:
        state = 'unmeasured'
    elif flake_rate > target['max_flake_rate']:
        state = 'not-met'
    else:
        state = 'met'
    return {
        'number': spec['number'],
        'name': spec['name'],
        'state': state,
        'first_pass_rate': _round_metric(first_pass_rate, digits),
        'pr_first_attempt_rate': _round_metric(pr_rate, digits),
        'passed_runs': passed,
        'failed_runs': failed,
        'total_runs': total,
        'flake_source_wired': flake_wired,
        'flake_events': flake_events,
        'flake_total_runs': flake_total,
        'flake_rate': _round_metric(flake_rate, digits),
        'snapshot_at': slo_data.get('at'),
        'target': target,
    }


def _is_independent_record(record):
    reviewer = str(record.get('reviewer') or '').strip()
    author = str(record.get('author') or '').strip()
    if not reviewer:
        return False
    if author and reviewer.casefold() == author.casefold():
        return False
    return record.get('independent', True) is not False


def measure_independent_audit(root, ladder):
    """Indicator 4: independent PR audit agreement, excluding self-reviewed samples."""
    spec = ladder['indicators']['independent_audit']
    target = spec['target']
    digits = len(ladder['defaults']['diagnostic_percentiles'])
    root = Path(root)
    audited_prs, clean_prs, critical_high, gaming, self_excluded = 0, 0, 0, 0, 0

    audits_dir = root / spec['sources']['audits_dir']
    if audits_dir.is_dir():
        for path in sorted(audits_dir.glob('*.json')):
            record = _read_optional_json(path)
            if not isinstance(record, dict):
                continue
            if not _is_independent_record(record):
                self_excluded += 1
                continue
            if isinstance(record.get('prs'), list):
                for pr in record['prs']:
                    audited_prs += 1
                    findings = int(pr.get('critical_high_findings', 0))
                    pr_gaming = int(pr.get('gaming_cases', 0))
                    critical_high += findings
                    gaming += pr_gaming
                    if pr.get('clean') is True and findings == 0 and pr_gaming == 0:
                        clean_prs += 1
            elif isinstance(record.get('audited_prs'), int):
                audited_prs += record['audited_prs']
                clean_prs += int(record.get('clean_prs', 0))
                critical_high += int(record.get('critical_high_findings', 0))
                gaming += int(record.get('gaming_cases', 0))

    for path in sorted(root.glob(spec['sources']['retro_glob'])):
        record = _read_optional_json(path)
        if not isinstance(record, dict):
            continue
        if not _is_independent_record(record):
            self_excluded += 1
            continue
        for pr in record.get('prs') or []:
            audited_prs += 1
            findings = int(pr.get('critical_high_findings', 0))
            pr_gaming = int(pr.get('gaming_cases', 0))
            critical_high += findings
            gaming += pr_gaming
            if pr.get('clean', not pr.get('cheaper', False)) and findings == 0 and pr_gaming == 0:
                clean_prs += 1

    if audited_prs == 0:
        return {
            'number': spec['number'],
            'name': spec['name'],
            'state': 'unmeasured',
            'clean_approval_rate': None,
            'audited_prs': 0,
            'clean_prs': 0,
            'critical_high_findings': 0,
            'gaming_cases': 0,
            'self_reviewed_samples_excluded': self_excluded,
            'target': target,
            'reason': 'no independently reviewed audit samples recorded',
        }
    rate = clean_prs / audited_prs
    met = (rate >= target['min_clean_approval_rate']
           and critical_high <= target['max_critical_high_findings']
           and gaming <= target['max_gaming_cases'])
    return {
        'number': spec['number'],
        'name': spec['name'],
        'state': 'met' if met else 'not-met',
        'clean_approval_rate': _round_metric(rate, digits),
        'audited_prs': audited_prs,
        'clean_prs': clean_prs,
        'critical_high_findings': critical_high,
        'gaming_cases': gaming,
        'self_reviewed_samples_excluded': self_excluded,
        'target': target,
    }


def measure_human_override_rate(root, ladder, total_merges=0):
    """Indicator 5: owner corrective interventions outside gitignored local directories."""
    spec = ladder['indicators']['human_override_rate']
    target = spec['target']
    defaults = ladder['defaults']
    digits = len(defaults['diagnostic_percentiles'])
    root = Path(root)
    legacy_rel = spec['sources']['legacy_incidents_dir']
    legacy_exists = (root / legacy_rel).is_dir()
    legacy_ignored = _git_returncode(root, 'check-ignore', '-q', legacy_rel) == 0
    if not legacy_ignored and (root / '.gitignore').is_file():
        gitignore = (root / '.gitignore').read_text(encoding='utf-8', errors='replace')
        parent_dir = Path(legacy_rel).parent.as_posix()
        legacy_ignored = f'/{parent_dir}/' in gitignore or f'{parent_dir}/' in gitignore

    overrides_path = root / spec['sources']['overrides']
    data = _read_optional_json(overrides_path)
    if not isinstance(data, dict) or not isinstance(data.get('overrides'), list):
        return {
            'number': spec['number'],
            'name': spec['name'],
            'state': 'unmeasured',
            'source_wired': False,
            'legacy_source_gitignored': legacy_ignored,
            'legacy_dir_exists': legacy_exists,
            'overrides': None,
            'lock_violations': None,
            'overrides_per_50_prs': None,
            'window_prs': total_merges,
            'target': target,
            'reason': 'no tracked external override log; legacy docs/operations/incidents is gitignored and absent'
            if legacy_ignored and not legacy_exists else 'no tracked external override log recorded',
        }
    entries = data['overrides']
    count = len(entries)
    lock_violations = sum(1 for item in entries if item.get('lock_violation'))
    prs = int(data.get('window_prs') or total_merges or 0)
    per_norm = (count * defaults['override_normalization_prs'] / prs) if prs > 0 else None
    met = count <= target['max_overrides'] and lock_violations <= target['max_lock_violations']
    return {
        'number': spec['number'],
        'name': spec['name'],
        'state': 'met' if met else 'not-met',
        'source_wired': True,
        'legacy_source_gitignored': legacy_ignored,
        'legacy_dir_exists': legacy_exists,
        'overrides': count,
        'lock_violations': lock_violations,
        'overrides_per_50_prs': _round_metric(per_norm, digits),
        'window_prs': prs,
        'snapshot_at': data.get('at'),
        'target': target,
    }


def _classify_merge(files, defaults):
    product_prefixes = tuple(defaults['product_prefixes'])
    capacity_prefixes = tuple(defaults['capacity_prefixes'])
    meta_prefixes = tuple(defaults['meta_governance_prefixes'])
    meta_files = set(defaults['meta_governance_files'])
    touches_product = any(path.startswith(product_prefixes) for path in files)
    touches_meta = any(path.startswith(meta_prefixes) or path in meta_files for path in files)
    touches_capacity = any(path.startswith(capacity_prefixes) and not (path.startswith(meta_prefixes) or path in meta_files)
                           for path in files)
    return touches_product, touches_capacity, touches_meta


def measure_signal_to_overhead(root, ladder, merges=None):
    """Indicator 6 (C8): product/capacity work share vs. meta-governance overhead and PR-split detection."""
    spec = ladder['indicators']['signal_to_overhead']
    target = spec['target']
    defaults = ladder['defaults']
    digits = len(defaults['diagnostic_percentiles'])
    if merges is None:
        merges = first_parent_merges(root, defaults['max_window_merges'])
    has_value_threshold = 'min_value_share' in target
    has_meta_threshold = 'max_meta_governance_share' in target
    work_mix_diagnostic_only = not has_value_threshold and not has_meta_threshold
    if not merges:
        return {
            'number': spec['number'],
            'name': spec['name'],
            'state': 'unmeasured',
            'total_merges': 0,
            'product_merges': 0,
            'capacity_merges': 0,
            'value_merges': 0,
            'meta_governance_merges': 0,
            'other_merges': 0,
            'product_share': None,
            'capacity_share': None,
            'value_share': None,
            'meta_governance_share': None,
            'work_mix_diagnostic_only': work_mix_diagnostic_only,
            'sequential_same_scope_splits': 0,
            'split_pairs': [],
            'target': target,
            'reason': 'no merged pull requests in git history',
        }

    product_n, capacity_n, value_n, meta_n, other_n = 0, 0, 0, 0, 0
    for merge in merges:
        touches_product, touches_capacity, touches_meta = _classify_merge(merge['files'], defaults)
        if touches_product:
            product_n += 1
        if touches_capacity:
            capacity_n += 1
        if touches_meta:
            meta_n += 1
        if touches_product or (touches_capacity and not touches_meta):
            value_n += 1
        elif not touches_meta:
            other_n += 1

    # Detect consecutive PRs merged within split_window_seconds that split identical file sets or
    # land sequential single-file / overlapping commits from the exact same branch.
    chronological = list(reversed(merges))
    split_window = defaults['split_window_seconds']
    split_pairs = []
    for index in range(1, len(chronological)):
        prev, curr = chronological[index - 1], chronological[index]
        gap = abs(curr['timestamp'] - prev['timestamp'])
        if gap > split_window or not prev['files'] or not curr['files']:
            continue
        prev_set, curr_set = set(prev['files']), set(curr['files'])
        same_files = prev_set == curr_set
        same_branch = bool(prev['branch'] and curr['branch'] and prev['branch'] == curr['branch'])
        subset_same_branch = same_branch and (prev_set <= curr_set or curr_set <= prev_set)
        if same_files or subset_same_branch:
            split_pairs.append({
                'first_pr': prev['pr'],
                'second_pr': curr['pr'],
                'first_sha': prev['sha'],
                'second_sha': curr['sha'],
                'gap_seconds': gap,
                'reason': 'identical_files' if same_files else 'same_branch_subset_scope',
            })

    total = len(merges)
    product_share = product_n / total
    capacity_share = capacity_n / total
    value_share = value_n / total
    meta_share = meta_n / total
    value_ok = (not has_value_threshold) or (value_share >= target['min_value_share'])
    meta_ok = (not has_meta_threshold) or (meta_share <= target['max_meta_governance_share'])
    splits_ok = ('max_sequential_same_scope_splits' not in target
                 or len(split_pairs) <= target['max_sequential_same_scope_splits'])
    met = value_ok and meta_ok and splits_ok
    return {
        'number': spec['number'],
        'name': spec['name'],
        'state': 'met' if met else 'not-met',
        'total_merges': total,
        'product_merges': product_n,
        'capacity_merges': capacity_n,
        'value_merges': value_n,
        'meta_governance_merges': meta_n,
        'other_merges': other_n,
        'product_share': _round_metric(product_share, digits),
        'capacity_share': _round_metric(capacity_share, digits),
        'value_share': _round_metric(value_share, digits),
        'meta_governance_share': _round_metric(meta_share, digits),
        'work_mix_diagnostic_only': work_mix_diagnostic_only,
        'sequential_same_scope_splits': len(split_pairs),
        'split_pairs': split_pairs,
        'target': target,
    }


def measure_production_health_and_cost(root, ladder):
    """Indicator 7: deploy latency (p100 + diagnostic p50/p95/p99 and swap/reload), canary, and gross AWS spend."""
    spec = ladder['indicators']['production_health_and_cost']
    target = spec['target']
    defaults = ladder['defaults']
    digits = len(defaults['diagnostic_percentiles'])
    root = Path(root)

    deploy_data = _read_optional_json(root / spec['sources']['deploy_live'])
    deploy_runs = (deploy_data or {}).get('runs') if isinstance(deploy_data, dict) else None
    deploy_runs = deploy_runs if isinstance(deploy_runs, list) else []
    seconds = [float(item['seconds']) for item in deploy_runs if isinstance(item.get('seconds'), (int, float))]
    pcts = defaults['diagnostic_percentiles']
    scale = max(pcts)
    percentiles = {f'p{pct}_s': _round_metric(_percentile(seconds, pct, scale), digits) for pct in pcts}
    p100 = _percentile(seconds, scale, scale)
    by_event = {}
    from_counts = {}
    newest_run_at = None
    for item in deploy_runs:
        event = str(item.get('event') or 'unknown')
        bucket = by_event.setdefault(event, [])
        if isinstance(item.get('seconds'), (int, float)):
            bucket.append(float(item['seconds']))
        clock = str(item.get('from') or 'unknown')
        from_counts[clock] = from_counts.get(clock, 0) + 1
        started = _parse_iso(item.get('started'))
        if started is not None and (newest_run_at is None or started > newest_run_at):
            newest_run_at = started
    event_summary = {
        event: {'count': len(vals), 'max_s': _round_metric(max(vals), digits) if vals else None}
        for event, vals in sorted(by_event.items())
    }

    canary_data = _read_optional_json(root / spec['sources']['canary'])
    canary_runs = (canary_data or {}).get('runs') if isinstance(canary_data, dict) else None
    canary_wired = isinstance(canary_runs, list) and len(canary_runs) > 0
    canary_pass_rate = None
    if canary_wired:
        canary_passes = sum(1 for item in canary_runs if item.get('conclusion') == 'success' or item.get('passed') is True)
        canary_pass_rate = canary_passes / len(canary_runs)

    spend_data = _read_optional_json(root / spec['sources']['aws_spend'])
    aws_usd = None
    gross_verified = False
    if isinstance(spend_data, dict) and isinstance(spend_data.get('usd'), (int, float)):
        aws_usd = float(spend_data['usd'])
        source_text = str(spend_data.get('source') or '').casefold()
        mentions_exclusion = 'credit' in source_text and 'exclud' in source_text
        if spend_data.get('credits_excluded') is True or (mentions_exclusion and aws_usd > 0):
            gross_verified = True

    if not deploy_runs and not canary_wired and aws_usd is None:
        return {
            'number': spec['number'],
            'name': spec['name'],
            'state': 'unmeasured',
            'deploy_percentiles': percentiles,
            'deploy_p100_s': None,
            'deploy_by_event': event_summary,
            'deploy_clocks': from_counts,
            'deploy_newest_run_at': None,
            'canary_wired': False,
            'canary_pass_rate': None,
            'aws_monthly_usd': None,
            'gross_spend_verified': False,
            'target': target,
            'reason': 'no production deploy, canary or AWS spend snapshots recorded',
        }

    deploy_ok = p100 is not None and p100 <= target['max_deploy_p100_s']
    canary_ok = canary_wired and canary_pass_rate is not None and canary_pass_rate >= target['min_canary_pass_rate']
    spend_ok = (aws_usd is not None and aws_usd >= 0 and aws_usd <= target['max_aws_monthly_usd']
                and (gross_verified or not target.get('require_gross_aws_spend')))
    met = deploy_ok and canary_ok and spend_ok
    return {
        'number': spec['number'],
        'name': spec['name'],
        'state': 'met' if met else 'not-met',
        'deploy_percentiles': percentiles,
        'deploy_p100_s': _round_metric(p100, digits),
        'deploy_by_event': event_summary,
        'deploy_clocks': from_counts,
        'deploy_newest_run_at': newest_run_at.isoformat().replace('+00:00', 'Z') if newest_run_at else None,
        'deploy_snapshot_at': (deploy_data or {}).get('at'),
        'canary_wired': canary_wired,
        'canary_pass_rate': _round_metric(canary_pass_rate, digits),
        'aws_monthly_usd': aws_usd,
        'gross_spend_verified': gross_verified,
        'target': target,
    }


def _scan_dockerfiles(root, ladder):
    """Find tracked Dockerfiles and report unpinned FROM, --no-audit, and curl/wget | sh issues."""
    root = Path(root)
    names = set(ladder['defaults']['dockerfile_names'])
    listed = _git(root, 'ls-files').splitlines()
    if listed:
        candidates = [root / path for path in listed if Path(path).name in names and (root / path).is_file()]
    else:
        candidates = [path for path in sorted(root.rglob('*')) if path.is_file() and path.name in names]
    issues = []
    for path in sorted(candidates):
        rel = path.relative_to(root).as_posix()
        stages = {'scratch'}
        for lineno, raw in enumerate(path.read_text(encoding='utf-8', errors='replace').splitlines(), 1):
            stripped = raw.strip()
            if not stripped or stripped.startswith('#'):
                continue
            from_match = FROM_LINE.match(raw)
            if from_match:
                image, alias = from_match.groups()
                if alias:
                    stages.add(alias.lower())
                if image.lower() not in stages and '@sha256:' not in image:
                    issues.append({'file': rel, 'line': lineno, 'kind': 'unpinned_from', 'detail': image})
            if NO_AUDIT.search(raw):
                issues.append({'file': rel, 'line': lineno, 'kind': 'no_audit', 'detail': '--no-audit'})
            if PIPE_SHELL.search(raw):
                issues.append({'file': rel, 'line': lineno, 'kind': 'pipe_to_shell', 'detail': 'curl/wget piped to shell'})
    return issues


def _audited_ecosystems(advisories_data):
    if not isinstance(advisories_data, dict):
        return []
    if isinstance(advisories_data.get('ecosystems'), list):
        return sorted({str(item).lower() for item in advisories_data['ecosystems']})
    found = set()
    for path in (advisories_data.get('lockfiles') or {}):
        lower = path.lower()
        if 'pnpm-lock' in lower or 'package-lock' in lower or 'yarn.lock' in lower:
            found.add('npm')
        if 'requirements' in lower or 'poetry.lock' in lower or 'uv.lock' in lower:
            found.add('pypi')
        if 'dockerfile' in lower:
            found.add('docker')
    return sorted(found)


def measure_security_posture(root, ladder):
    """Indicator 8: vulnerabilities, open threats, unapproved TAIL exemptions, Dockerfile hygiene, audit coverage."""
    spec = ladder['indicators']['security_posture']
    target = spec['target']
    defaults = ladder['defaults']
    high_sevs = {sev.casefold() for sev in defaults['high_severities']}
    root = Path(root)

    advisories_data = _read_optional_json(root / spec['sources']['advisories'])
    advisories = (advisories_data or {}).get('advisories') if isinstance(advisories_data, dict) else []
    open_adv = [
        item for item in (advisories or [])
        if str(item.get('severity') or '').casefold() in high_sevs and item.get('state', 'affecting') == 'affecting'
    ]
    audited = _audited_ecosystems(advisories_data)
    missing_ecosystems = [eco for eco in defaults['expected_ecosystems'] if eco not in audited]

    open_vulns = []
    vulns_dir = root / spec['sources']['vulns_dir']
    if vulns_dir.is_dir():
        for path in sorted(vulns_dir.glob('VULN-*.json')):
            body = _read_optional_json(path)
            if isinstance(body, dict) and not body.get('fixed') and body.get('state') != 'fixed':
                open_vulns.append(body.get('id', path.stem))

    open_threats = []
    threats_dir = root / spec['sources']['threats_dir']
    if threats_dir.is_dir():
        for path in sorted(threats_dir.glob('THREAT-*.json')):
            body = _read_optional_json(path)
            if not isinstance(body, dict):
                continue
            for finding in (body.get('review') or {}).get('findings') or []:
                if finding.get('disposition') == 'open':
                    open_threats.append({'threat': body.get('id', path.stem), 'about': finding.get('about', 'unknown')})

    decisions = read_decision_authorities(root, ladder)
    unapproved_tailorings = []
    active_tailorings = 0
    tailoring_dir = root / spec['sources']['tailoring_dir']
    if tailoring_dir.is_dir():
        for path in sorted(tailoring_dir.glob('TAIL-*.json')):
            body = _read_optional_json(path)
            if not isinstance(body, dict) or body.get('state') != 'active':
                continue
            active_tailorings += 1
            auth_id = body.get('authorized_by')
            dec = decisions.get(auth_id)
            if dec is None or dec['status'] != 'accepted' or dec['authority'] not in INDEPENDENT_AUTHORITIES:
                unapproved_tailorings.append({
                    'id': body.get('id', path.stem),
                    'scope': body.get('scope'),
                    'authorized_by': auth_id,
                    'decision_status': dec['status'] if dec else 'missing',
                    'authority': dec['authority'] if dec else 'missing',
                })

    dockerfile_issues = _scan_dockerfiles(root, ladder)
    eco_ok = not target.get('require_multi_ecosystem_audit') or not missing_ecosystems
    met = (len(open_adv) <= target['max_open_critical_high_advisories']
           and len(open_vulns) <= target['max_open_vulns']
           and len(open_threats) <= target['max_open_threat_findings']
           and len(unapproved_tailorings) <= target['max_unapproved_tailorings']
           and len(dockerfile_issues) <= target['max_dockerfile_issues']
           and eco_ok)
    return {
        'number': spec['number'],
        'name': spec['name'],
        'state': 'met' if met else 'not-met',
        'open_critical_high_advisories': len(open_adv),
        'audited_ecosystems': audited,
        'missing_ecosystems': missing_ecosystems,
        'open_vulns': open_vulns,
        'open_threat_findings': open_threats,
        'active_tailorings': active_tailorings,
        'unapproved_tailorings': unapproved_tailorings,
        'dockerfile_issues': dockerfile_issues,
        'target': target,
    }


def _consecutive_history_days(history, required_indicators, today_date):
    """Count consecutive calendar days ending at the newest qualifying entry (within 1 day of today)."""
    if not history:
        return 0
    by_day = {}
    for entry in history:
        day = _parse_day(entry.get('date'))
        if day is not None:
            by_day[day] = entry
    if not by_day:
        return 0
    days = sorted(by_day, reverse=True)
    if (today_date - days[0]).days > 1 or days[0] > today_date:
        return 0
    required = set(required_indicators)
    streak = 0
    expected = days[0]
    for day in days:
        if day != expected:
            break
        entry = by_day[day]
        if entry.get('circuit_breakers_tripped'):
            break
        if not required.issubset(set(entry.get('indicators_met') or [])):
            break
        streak += 1
        expected = day - timedelta(days=1)
    return streak


def _extra_guards_ok(level, indicators):
    guards = level.get('extra_guards') or {}
    if not guards:
        return True
    if 'max_overrides_per_50_prs' in guards:
        rate = indicators['human_override_rate'].get('overrides_per_50_prs')
        if rate is None or rate > guards['max_overrides_per_50_prs']:
            return False
    if ('max_gaming_cases' in guards
            and indicators['independent_audit'].get('gaming_cases', 0) > guards['max_gaming_cases']):
        return False
    return not ('max_sequential_same_scope_splits' in guards
                and indicators['signal_to_overhead'].get('sequential_same_scope_splits', 0)
                > guards['max_sequential_same_scope_splits'])


def evaluate_ladder(ladder, indicators, today=None):
    """Evaluate circuit breakers, per-level promotion eligibility, and effective autonomy level."""
    today_date = _today(today)
    tripped = []
    for breaker in ladder['circuit_breakers']:
        ind_key = breaker['indicator']
        ind = indicators[ind_key]
        if ind['state'] != 'met':
            tripped.append({
                'id': breaker['id'],
                'indicator': ind_key,
                'state': ind['state'],
                'action': breaker['action'],
                'reason': breaker['reason'],
            })

    history = ladder.get('history') or []
    levels_status = []
    eligible_set = set()
    eligible_level = 'none'
    for level in ladder['levels']:
        tier = level['level']
        prereq = level.get('prerequisite_level')
        required = level['required_indicators']
        missing = [key for key in required if indicators[key]['state'] != 'met']
        extra_ok = _extra_guards_ok(level, indicators)
        prereq_ok = prereq is None or prereq in eligible_set
        days_qualified = 0 if (tripped or missing or not extra_ok) else _consecutive_history_days(history, required, today_date)
        eligible = (not tripped and not missing and extra_ok and prereq_ok
                    and days_qualified >= level['promotion_days'])
        if eligible:
            eligible_set.add(tier)
            eligible_level = tier
        levels_status.append({
            'level': tier,
            'name': level['name'],
            'status': 'eligible' if eligible else 'locked',
            'prerequisite_level': prereq,
            'prerequisite_met': prereq_ok,
            'days_qualified': days_qualified,
            'days_required': level['promotion_days'],
            'missing_indicators': missing,
            'extra_guards_met': extra_ok,
        })

    proposal_pending = ladder['state'] != 'active'
    effective_level = 'none' if proposal_pending else eligible_level
    return {
        'id': ladder['id'],
        'state': ladder['state'],
        'decision': ladder['decision'],
        'owner': ladder['owner'],
        'proposal_pending_owner': proposal_pending,
        'circuit_breakers_tripped': tripped,
        'demoted': bool(tripped),
        'eligible_level': eligible_level,
        'effective_level': effective_level,
        'levels': levels_status,
        'always_owner_locked': [item['id'] for item in ladder['always_owner_locked']],
        'independent_approval_locked': [item['id'] for item in ladder.get('independent_approval_locked') or []],
    }


def measure(root=ROOT, today=None):
    """Compute all eight external trust indicators and evaluate the autonomy ladder for `root`."""
    root = Path(root)
    ladder, errors = load_ladder(root)
    if errors:
        return {'errors': errors, 'indicators': {}, 'ladder': None}
    merges = first_parent_merges(root, ladder['defaults']['max_window_merges'])
    indicators = {
        'main_integrity': measure_main_integrity(root, ladder, merges=merges),
        'change_failure_rework': measure_change_failure_rework(root, ladder, merges=merges),
        'first_pass_yield': measure_first_pass_yield(root, ladder),
        'independent_audit': measure_independent_audit(root, ladder),
        'human_override_rate': measure_human_override_rate(root, ladder, total_merges=len(merges)),
        'signal_to_overhead': measure_signal_to_overhead(root, ladder, merges=merges),
        'production_health_and_cost': measure_production_health_and_cost(root, ladder),
        'security_posture': measure_security_posture(root, ladder),
    }
    evaluation = evaluate_ladder(ladder, indicators, today=today)
    met_count = sum(1 for item in indicators.values() if item['state'] == 'met')
    return {
        'errors': [],
        'as_of': _today(today).isoformat(),
        'met_count': met_count,
        'indicator_count': len(indicators),
        'indicators': indicators,
        'ladder': evaluation,
    }


def _fmt_pct(value):
    return 'unmeasured' if value is None else f'{value:.1%}'


def _indicator_detail(key, item):
    if key == 'main_integrity':
        return (f'pass {_fmt_pct(item["pass_rate"])} ({item["passes"]}/{item["total_runs"]}), '
                f'max streak {item["max_consecutive_failures"]}, merges while red {item["merges_while_red"]}')
    if key == 'change_failure_rework':
        return (f'escapes {_fmt_pct(item["escape_rate"])} ({item["escapes_total"]}/{item["window_prs"]}), '
                f'rework {_fmt_pct(item["rework_rate"])} ({item["reworked_prs"]}/{item["window_prs"]})')
    if key == 'first_pass_yield':
        flake = _fmt_pct(item['flake_rate']) if item['flake_source_wired'] else 'unwired'
        return f'first-pass {_fmt_pct(item["first_pass_rate"])} ({item["passed_runs"]}/{item["total_runs"]}), flake {flake}'
    if key == 'independent_audit':
        return (f'clean {_fmt_pct(item["clean_approval_rate"])} ({item["clean_prs"]}/{item["audited_prs"]}), '
                f'self-reviewed excluded {item["self_reviewed_samples_excluded"]}')
    if key == 'human_override_rate':
        if not item['source_wired']:
            return f'unwired (legacy gitignored={item["legacy_source_gitignored"]}, exists={item["legacy_dir_exists"]})'
        return f'overrides {item["overrides"]}, lock violations {item["lock_violations"]}'
    if key == 'signal_to_overhead':
        mode = ' (diagnostic only)' if item.get('work_mix_diagnostic_only') else ''
        return (f'product {_fmt_pct(item["product_share"])}, value {_fmt_pct(item["value_share"])}, '
                f'meta-governance {_fmt_pct(item["meta_governance_share"])}{mode}, '
                f'splits {item["sequential_same_scope_splits"]}')
    if key == 'production_health_and_cost':
        p = item['deploy_percentiles']
        canary = _fmt_pct(item['canary_pass_rate']) if item['canary_wired'] else 'unwired'
        gross = 'verified' if item['gross_spend_verified'] else 'unverified-credits'
        return (f'deploy p100={item["deploy_p100_s"]} s (p50={p.get("p50_s")}, p95={p.get("p95_s")}), '
                f'canary {canary}, aws ${item["aws_monthly_usd"]} ({gross})')
    return (f'adv {item["open_critical_high_advisories"]}, vulns {len(item["open_vulns"])}, '
            f'open threats {len(item["open_threat_findings"])}, unapproved TAIL {len(item["unapproved_tailorings"])}, '
            f'dockerfile issues {len(item["dockerfile_issues"])}, missing eco {len(item["missing_ecosystems"])}')


def summary(result):
    """Human-readable summary of the eight external trust indicators and autonomy ladder."""
    if result.get('errors'):
        return '\n'.join(f'ERROR {line}' for line in result['errors'])
    ladder = result['ladder']
    lines = [
        (f'trust ({ladder["id"]}, state={ladder["state"]}, decision={ladder["decision"]}, owner={ladder["owner"]}): '
         f'{result["met_count"]} of {result["indicator_count"]} external indicator(s) met'),
        f'autonomy: eligible={ladder["eligible_level"]}, effective={ladder["effective_level"]}'
        + (' (proposal pending owner approval)' if ladder['proposal_pending_owner'] else ''),
    ]
    if ladder['circuit_breakers_tripped']:
        tripped = ', '.join(f'{item["id"]} ({item["indicator"]}={item["state"]})' for item in ladder['circuit_breakers_tripped'])
        lines.append(f'circuit breakers tripped: {tripped}')
    else:
        lines.append('circuit breakers tripped: none')
    for key in ORDER:
        item = result['indicators'][key]
        tag = item['state'].upper()
        lines.append(f'  {item["number"]}. [{tag}] {key}: {_indicator_detail(key, item)}')
    lines.append('levels:')
    for lvl in ladder['levels']:
        missing = ', '.join(lvl['missing_indicators']) if lvl['missing_indicators'] else 'none'
        lines.append(f'  Level {lvl["level"]} ({lvl["status"]}): {lvl["days_qualified"]}/{lvl["days_required"]} day(s); '
                     f'missing: {missing}')
    lines.append(f'always owner-locked ({len(ladder["always_owner_locked"])}): {", ".join(ladder["always_owner_locked"])}')
    if ladder.get('independent_approval_locked'):
        ind = ladder['independent_approval_locked']
        lines.append(f'independent approval required ({len(ind)}): {", ".join(ind)}')
    return '\n'.join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(prog='scripts/model trust', description=__doc__.splitlines()[0])
    parser.add_argument('--root', type=Path, default=ROOT, help='repository root to inspect')
    parser.add_argument('--today', help='override UTC date (YYYY-MM-DD) for deterministic runs')
    parser.add_argument('--check', action='store_true', help='validate autonomy ladder contract and config only')
    parser.add_argument('--json', dest='json_out', help='write structured JSON output to PATH (or - for stdout)')
    args = parser.parse_args(argv)
    try:
        if args.check:
            ladder, errors = load_ladder(args.root)
            for err in errors:
                print(f'ERROR {err}')
            print(f'trust check: {ladder["id"]} ({ladder["state"]}), {len(errors)} error(s)')
            return 1 if errors else 0
        result = measure(args.root, today=args.today)
        if args.json_out:
            payload = json.dumps(result, indent=1) + '\n'
            if args.json_out == '-':
                sys.stdout.write(payload)
            else:
                Path(args.json_out).write_text(payload, encoding='utf-8')
        else:
            print(summary(result))
        return 1 if result['errors'] else 0
    except TrustError as error:
        print(f'trust: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
