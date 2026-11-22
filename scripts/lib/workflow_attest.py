"""Deterministic workflow attestation, Andon main-health guard, and proposal validator (PR W, C6, C7, D-087).

Subcommands (`scripts/workflow-attest`):
  main-health        Andon stop-the-line check (C6): evaluates base's full-suite check runs and open
                     `main-red-andon` issues; non-`fix-main` PRs fail closed while main is red.
  verify             External GitHub App attestation check (C7, THREAT-gate): verifies base..head changed no
                     workflow/action/ruleset file (and no .github/ file from a fork) and that 100% of required
                     check runs passed on the exact head SHA (D-337).
  validate-proposed  Static security & parity audit of services/runner/github/proposed/ before owner install (D-087).

Stdlib only, pure and forge-agnostic (reads JSON payloads or local git only; never invokes vendor CLIs or APIs).
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
PROPOSED_DIR = 'services/runner/github/proposed'
STAGED_GATE = 'services/runner/github/tower-gate.yml'
LIVE_RULESET = '.github/rulesets/main.json'

FULL_SUITE_CHECK = 'full-suite'
ANDON_LABEL = 'main-red-andon'
FIX_MAIN_LABEL = 'fix-main'
ATTESTED_CONTEXT = 'tower/gate-attested'
DEFAULT_REQUIRED_CHECKS = (
    'gate part (main)',
    'gate part (shard1)',
    'gate part (alone)',
    'gate pinned to the base',
    'main-health',
    'tower/gate',
)

SHA40 = re.compile(r'^[0-9a-f]{40}$')
USES = re.compile(r'^\s*(?:-\s+)?uses:\s*(?P<action>[^@\s]+)@(?P<ref>\S+)')
IMAGE = re.compile(r'^\s*image:\s*(?P<ref>[^\s#]+)')
PIPE_SHELL = re.compile(r'\b(?:curl|wget)\b[^|\n]*\|\s*(?:[^\n]*\s)?(?:ba|da|z)?sh\b')
FORBIDDEN_ACTIONS_API = re.compile(r'/actions/(?:runs|workflows|jobs)\b')
PR_TRIGGER = re.compile(r'^\s+pull_request:\s*(?:#.*)?$', re.MULTILINE)
PR_TARGET_TRIGGER = re.compile(r'^\s+pull_request_target:\s*(?:#.*)?$', re.MULTILINE)
WORKFLOW_RUN_TRIGGER = re.compile(r'^\s+workflow_run:\s*(?:#.*)?$', re.MULTILINE)
PERMISSIONS_TOP = re.compile(r'^permissions:\s*', re.MULTILINE)
WRITE_ALL = re.compile(r'^permissions:\s*write-all\b', re.MULTILINE)
CONTENTS_WRITE = re.compile(r'^\s+contents:\s*write\b', re.MULTILINE)
UNTRUSTED_CHECKOUT = re.compile(r'ref:\s*\$\{\{\s*github\.event\.workflow_run\.head_(?:sha|branch)')


def _normalize_check_runs(payload):
    if isinstance(payload, dict):
        items = payload.get('check_runs')
        return list(items) if isinstance(items, list) else []
    if isinstance(payload, list):
        return list(payload)
    return []


def _newest_completed(check_runs, name):
    completed = [
        item for item in check_runs
        if isinstance(item, dict)
        and item.get('name') == name
        and item.get('status') == 'completed'
        and item.get('conclusion') not in ('cancelled', 'skipped')
    ]
    if not completed:
        return None
    return max(completed, key=lambda item: (str(item.get('completed_at') or ''), int(item.get('id') or 0)))


def _issue_has_label(issue, label):
    labels = issue.get('labels')
    if not isinstance(labels, list):
        return False
    for entry in labels:
        name = entry.get('name') if isinstance(entry, dict) else entry
        if name == label:
            return True
    return False


def evaluate_main_health(
    check_runs,
    andon_issues,
    pr_labels=(),
    full_suite_name=FULL_SUITE_CHECK,
    andon_label=ANDON_LABEL,
    fix_label=FIX_MAIN_LABEL,
):
    """Evaluate Andon stop-the-line state for main (C6). Non-fix-main PRs fail closed while main is red."""
    runs = _normalize_check_runs(check_runs)
    issues = list(andon_issues) if isinstance(andon_issues, list) else []
    reasons = []

    open_andon = [
        issue for issue in issues
        if isinstance(issue, dict)
        and 'pull_request' not in issue
        and issue.get('state', 'open') == 'open'
        and (not issue.get('labels') or _issue_has_label(issue, andon_label))
    ]
    if open_andon:
        numbers = ', '.join(f'#{item.get("number", "?")}' for item in open_andon)
        reasons.append(f'open {andon_label} issue(s) on main ({numbers})')

    newest = _newest_completed(runs, full_suite_name)
    if newest is not None and newest.get('conclusion') != 'success':
        reasons.append(f'latest completed {full_suite_name} on base is {newest.get("conclusion")!r}')

    if not reasons:
        return {
            'ok': True,
            'main_red': False,
            'override': False,
            'findings': [],
            'summary': 'main-health ok: main is green (no open Andon issue, base full-suite green)',
        }

    normalized_labels = {str(label).strip() for label in pr_labels if str(label).strip()}
    if fix_label in normalized_labels:
        return {
            'ok': True,
            'main_red': True,
            'override': True,
            'findings': [],
            'reasons': reasons,
            'summary': f'main-health ok ({fix_label} override): main is red ({"; ".join(reasons)})',
        }

    return {
        'ok': False,
        'main_red': True,
        'override': False,
        'findings': reasons,
        'summary': (
            f'main-health RED (Andon stop-the-line, C6): {"; ".join(reasons)}; '
            f'only PRs carrying label {fix_label} may advance until {full_suite_name} is green on main'
        ),
    }


def changed_paths(root, base, head):
    """Return sorted repository-relative files changed between base and head via local git."""
    done = subprocess.run(
        ['git', '-C', str(root), 'diff', '--name-only', '--no-renames', f'{base}..{head}'],
        capture_output=True,
        text=True,
        check=False,
    )
    if done.returncode != 0:
        raise RuntimeError(f'git diff {base}..{head} failed: {(done.stderr or done.stdout).strip()}')
    return sorted(line.strip() for line in done.stdout.splitlines() if line.strip())


def evaluate_attestation(
    head_sha,
    base_sha,
    paths,
    check_runs,
    required_checks=DEFAULT_REQUIRED_CHECKS,
    head_repo='',
    base_repo='',
    expected_app_id=None,
):
    """Fail-closed attestation check closing THREAT-gate (C7): refuses workflow/ruleset edits, fork .github/ edits,
    and any missing or non-success required check on the exact head SHA."""
    findings = []
    if not SHA40.match(str(head_sha or '')):
        findings.append(f'invalid head SHA {head_sha!r}')
    if not SHA40.match(str(base_sha or '')):
        findings.append(f'invalid base SHA {base_sha!r}')

    is_fork = bool(head_repo and base_repo and head_repo.casefold() != base_repo.casefold())
    for raw_path in sorted(set(paths or ())):
        path = str(raw_path)
        while path.startswith('./'):
            path = path.removeprefix('./')
        if path.startswith(('.github/workflows/', '.github/actions/')):
            findings.append(f'workflow-changed: {path} (cannot auto-attest modified Actions files; owner install D-087)')
        elif path.startswith('.github/rulesets/'):
            findings.append(f'ruleset-changed: {path} (cannot auto-attest ruleset edits; owner applies directly)')
        elif is_fork and (path == '.github' or path.startswith('.github/')):
            findings.append(f'fork-github-change: {path} (fork PR touching .github/ refused under THREAT-gate)')

    runs = _normalize_check_runs(check_runs)
    verified = []
    for name in required_checks:
        newest = _newest_completed(runs, name)
        if newest is None:
            findings.append(f'check-missing: required check {name!r} has no completed run on head')
            continue
        run_head = newest.get('head_sha')
        if run_head and run_head != head_sha:
            findings.append(f'check-head-mismatch: {name!r} judged {run_head}, expected {head_sha}')
            continue
        if expected_app_id is not None:
            app_id = (newest.get('app') or {}).get('id')
            if app_id != expected_app_id:
                findings.append(f'check-wrong-app: {name!r} reported by app {app_id!r}, expected {expected_app_id!r}')
                continue
        if newest.get('conclusion') != 'success':
            findings.append(f'check-not-green: {name!r} concluded {newest.get("conclusion")!r}')
            continue
        verified.append(name)

    return {
        'attested': not findings,
        'head': head_sha,
        'base': base_sha,
        'fork': is_fork,
        'verified_checks': verified,
        'findings': findings,
    }


def extract_cache_step(text):
    """Extract the CACHE-PGDATA actions/cache step up to the toolchain step, or None when absent."""
    marker = '      - uses: actions/cache@'
    end_marker = '      - name: toolchain'
    if marker not in text or end_marker not in text:
        return None
    start = text.index(marker)
    try:
        end = text.index(end_marker, start)
    except ValueError:
        return None
    return text[start:end]


def audit_workflow_text(name, text, tower_gate_text=None):
    """Static security and hygiene audit of one proposed workflow file."""
    findings = []
    if PR_TARGET_TRIGGER.search(text):
        findings.append(f'{name}: pull_request_target is forbidden (pwn-request risk)')
    if not PERMISSIONS_TOP.search(text):
        findings.append(f'{name}: missing explicit top-level permissions:')
    if WRITE_ALL.search(text):
        findings.append(f'{name}: permissions: write-all is forbidden')
    if PR_TRIGGER.search(text) and CONTENTS_WRITE.search(text):
        findings.append(f'{name}: pull_request workflow must not grant contents: write')
    if PIPE_SHELL.search(text):
        findings.append(f'{name}: curl/wget piped to shell is forbidden')
    if FORBIDDEN_ACTIONS_API.search(text):
        findings.append(f'{name}: calls forbidden GitHub Actions API endpoint')

    for line in text.splitlines():
        used = USES.match(line)
        if used and not used.group('action').startswith('./'):
            action, ref = used.group('action'), used.group('ref')
            if not SHA40.match(ref):
                findings.append(f'{name}: action {action}@{ref} must be pinned by 40-char commit SHA')
        image = IMAGE.match(line)
        if image:
            ref = image.group('ref').strip('"\'')
            if '@sha256:' not in ref:
                findings.append(f'{name}: container image {ref} must be pinned by @sha256: digest')

    if name == 'full-suite.yml':
        if tower_gate_text is not None:
            gate_cache = extract_cache_step(tower_gate_text)
            suite_cache = extract_cache_step(text)
            if not suite_cache or suite_cache != gate_cache:
                findings.append(f'{name}: CACHE-PGDATA step differs from {STAGED_GATE}')
        for required_token in ('main-red-andon', 'refresh-snapshots', 'TOWER_SNAPSHOT_TOKEN'):
            if required_token not in text:
                findings.append(f'{name}: missing required Andon/snapshot token {required_token!r}')

    if name == 'tower-gate.yml':
        for required_token in ('main-health', 'scripts/workflow-attest', 'gate pinned to the base', 'tower/gate'):
            if required_token not in text:
                findings.append(f'{name}: missing required gate/Andon token {required_token!r}')

    if name == 'tower-gate-attest.yml':
        if not WORKFLOW_RUN_TRIGGER.search(text):
            findings.append(f'{name}: must trigger via workflow_run on main')
        if PR_TRIGGER.search(text):
            findings.append(f'{name}: attester must not run on untrusted pull_request trigger')
        if UNTRUSTED_CHECKOUT.search(text):
            findings.append(f'{name}: attester must never check out untrusted PR head code')
        if 'scripts/workflow-attest' not in text:
            findings.append(f'{name}: must invoke scripts/workflow-attest')

    if name == 'site-canary.yml':
        if 'scripts/site-canary' not in text:
            findings.append(f'{name}: must invoke scripts/site-canary')
        if 'TOWER_DEPLOY_DOORBELL_TOKEN' in text:
            findings.append(f'{name}: canary workflow must not access deploy doorbell secrets')
        if 'site-canary-red' not in text:
            findings.append(f'{name}: missing deduplicated alert label site-canary-red')

    return findings


def _live_actions_app_id(root):
    path = Path(root) / LIVE_RULESET
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding='utf-8'))
    for rule in data.get('rules', []):
        if rule.get('type') == 'required_status_checks':
            for item in (rule.get('parameters') or {}).get('required_status_checks', []):
                if item.get('context') == 'tower/gate' and isinstance(item.get('integration_id'), int):
                    return item['integration_id']
    return None


def audit_ruleset_data(data, actions_app_id=None):
    """Audit proposed ruleset-main.json closing THREAT-gate (C7)."""
    findings = []
    if not isinstance(data, dict):
        return ['ruleset-main.json: root must be a JSON object']
    if data.get('enforcement') != 'active':
        findings.append('ruleset-main.json: enforcement must be "active"')
    rules = {rule.get('type'): rule.get('parameters') or {} for rule in data.get('rules', []) if isinstance(rule, dict)}
    for needed in ('deletion', 'non_fast_forward', 'required_status_checks', 'merge_queue'):
        if needed not in rules:
            findings.append(f'ruleset-main.json: missing required rule {needed!r}')
    queue = rules.get('merge_queue') or {}
    if queue.get('merge_method') != 'MERGE':
        findings.append('ruleset-main.json: merge_queue.merge_method must be MERGE')
    if queue.get('grouping_strategy') != 'ALLGREEN':
        findings.append('ruleset-main.json: merge_queue.grouping_strategy must be ALLGREEN')

    checks = (rules.get('required_status_checks') or {}).get('required_status_checks') or []
    by_context = {item.get('context'): item.get('integration_id') for item in checks if isinstance(item, dict)}
    if ATTESTED_CONTEXT not in by_context:
        findings.append(f'ruleset-main.json: missing required check {ATTESTED_CONTEXT!r}')
    else:
        app_id = by_context[ATTESTED_CONTEXT]
        if app_id in (None, ''):
            findings.append(f'ruleset-main.json: {ATTESTED_CONTEXT!r} must specify external GitHub App integration_id')
        elif actions_app_id is not None and app_id == actions_app_id:
            findings.append(
                f'ruleset-main.json: {ATTESTED_CONTEXT!r} must not use GitHub Actions integration_id {actions_app_id}'
            )
    return findings


def validate_proposed(root=ROOT):
    """Validate every file in services/runner/github/proposed/."""
    root = Path(root)
    folder = root / PROPOSED_DIR
    if not folder.is_dir():
        return {'ok': True, 'workflows': [], 'ruleset': None, 'findings': []}

    gate_path = root / STAGED_GATE
    tower_gate_text = gate_path.read_text(encoding='utf-8') if gate_path.is_file() else None
    workflows = sorted(folder.glob('*.yml'))
    findings = []
    for path in workflows:
        findings += audit_workflow_text(path.name, path.read_text(encoding='utf-8'), tower_gate_text=tower_gate_text)

    ruleset_path = folder / 'ruleset-main.json'
    ruleset_checked = None
    if ruleset_path.is_file():
        ruleset_checked = ruleset_path.relative_to(root).as_posix()
        try:
            data = json.loads(ruleset_path.read_text(encoding='utf-8'))
        except ValueError as error:
            findings.append(f'ruleset-main.json: invalid JSON ({error})')
        else:
            findings += audit_ruleset_data(data, actions_app_id=_live_actions_app_id(root))

    return {
        'ok': not findings,
        'workflows': [path.name for path in workflows],
        'ruleset': ruleset_checked,
        'findings': findings,
    }


def _read_json_arg(path_str):
    if path_str == '-':
        return json.load(sys.stdin)
    return json.loads(Path(path_str).read_text(encoding='utf-8'))


def main(argv=None):
    parser = argparse.ArgumentParser(prog='scripts/workflow-attest', description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest='command', required=True)

    health = sub.add_parser('main-health', help='evaluate Andon stop-the-line state on main (C6)')
    health.add_argument('--checks', required=True, help='JSON file of base full-suite check runs (or - for stdin)')
    health.add_argument('--issues', required=True, help='JSON file of open main-red-andon issues')
    health.add_argument('--label', action='append', default=[], help='label on the current PR (repeatable)')
    health.add_argument('--json', action='store_true', dest='as_json')

    verify = sub.add_parser('verify', help='fail-closed verifier for external App attestation (C7)')
    verify.add_argument('--base', required=True, help='base commit SHA (40 hex)')
    verify.add_argument('--head', required=True, help='head commit SHA (40 hex)')
    verify.add_argument('--checks', required=True, help='JSON file of head check runs (or - for stdin)')
    verify.add_argument('--files', help='JSON list of changed paths (defaults to git diff base..head)')
    verify.add_argument('--root', default=str(ROOT), help='git checkout root when --files is omitted')
    verify.add_argument('--required', action='append', dest='required_checks', help='required check name (repeatable)')
    verify.add_argument('--head-repo', default='', help='PR head repository owner/name')
    verify.add_argument('--base-repo', default='', help='PR base repository owner/name')
    verify.add_argument('--expected-app-id', type=int, default=None, help='optional expected app.id on check runs')
    verify.add_argument('--json', action='store_true', dest='as_json')

    proposed = sub.add_parser('validate-proposed', help='audit services/runner/github/proposed/ (D-087)')
    proposed.add_argument('--root', default=str(ROOT))
    proposed.add_argument('--json', action='store_true', dest='as_json')

    args = parser.parse_args(argv)
    if args.command == 'main-health':
        verdict = evaluate_main_health(_read_json_arg(args.checks), _read_json_arg(args.issues), pr_labels=args.label)
        print(json.dumps(verdict, indent=1, sort_keys=True) if args.as_json else verdict['summary'])
        return 0 if verdict['ok'] else 1

    if args.command == 'verify':
        paths = _read_json_arg(args.files) if args.files else changed_paths(args.root, args.base, args.head)
        verdict = evaluate_attestation(
            args.head,
            args.base,
            paths,
            _read_json_arg(args.checks),
            required_checks=tuple(args.required_checks) if args.required_checks else DEFAULT_REQUIRED_CHECKS,
            head_repo=args.head_repo,
            base_repo=args.base_repo,
            expected_app_id=args.expected_app_id,
        )
        if args.as_json:
            print(json.dumps(verdict, indent=1, sort_keys=True))
        elif verdict['attested']:
            print(f'workflow-attest ok: {args.head} verified {len(verdict["verified_checks"])} check(s)')
        else:
            print(f'workflow-attest RED: {args.head} ({len(verdict["findings"])} finding(s))')
            for line in verdict['findings']:
                print(f'  - {line}')
        return 0 if verdict['attested'] else 1

    report = validate_proposed(args.root)
    if args.as_json:
        print(json.dumps(report, indent=1, sort_keys=True))
    elif report['ok']:
        print(f'validate-proposed ok: {len(report["workflows"])} workflow(s)' + (
            f', {report["ruleset"]}' if report['ruleset'] else ''
        ))
    else:
        print(f'validate-proposed RED: {len(report["findings"])} finding(s)')
        for line in report['findings']:
            print(f'  - {line}')
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
