"""The fast local check (LR1, D-069): a registry of checks, run before a push by `scripts/commit-check --local`.

Checks are data: config key local-checks.checks lists {id, owner, budget_ms, handler, stage, enabled}. A handler is a name
of HANDLERS or a `module:function`; it takes a Context and returns a list of refusals (strings), or raises Skip(reason).
Other tooling adds a check (a lessons kind=check) by appending an entry; nothing here changes.

  stage local   runs here, and its cost is measured with the injected monotonic clock;
  stage gate    not run here (the gate runs it); a check over its budget is moved there.
A check whose measured cost exceeds its budget_ms is reported `over_budget`, the runner says it MOVES TO THE GATE and
records it in the state file (local-checks.state_file, next to the git directory); the next runs read it as stage gate.
The registry entry is never deleted or edited. The total cost over local-checks.total_budget_ms is reported too.
A check that cannot run (missing tool, no PR body, no base, handler error) is `skipped` with a reason and never blocks;
only a real finding exits 1. Four tree modules of structure-check run here on their own (F-15): config_check,
literal_census and vendor_check against the base, unit_check on the tree; their warnings are not refusals.
"""
import datetime
import importlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
ZERO = re.compile(r'^0+$')


class Skip(Exception):
    """The check cannot run here; the reason is reported and the push is not blocked."""


class Context:
    """What a handler may use: the checkout, the PR body (or None), the pushed refs, the clock."""

    def __init__(self, root, body=None, refs=None, clock=time.monotonic, today=None):
        self.root, self.body, self.refs, self.clock = Path(root), body, refs, clock
        self.today = today or datetime.date.today()
        self._changed = None

    def git(self, *args):
        return subprocess.run(['git', '-C', str(self.root), *args], capture_output=True, text=True)

    def base(self):
        """The ref pushed work is measured against: the branch's upstream, else origin/<integration branch>."""
        up = self.git('rev-parse', '--abbrev-ref', '--symbolic-full-name', '@{upstream}')
        if up.returncode == 0:
            return up.stdout.strip()
        ref = 'origin/' + config.get('train.base_branch')
        return ref if self.git('rev-parse', '--verify', '--quiet', ref).returncode == 0 else None

    def changed(self):
        """Files changed in the pushed range (or against the base) plus uncommitted ones; deleted files are left out."""
        if self._changed is None:
            names = set()
            spans = []
            for _, local, _, remote in self.refs or []:
                if not ZERO.match(local):
                    spans.append(f'{remote}..{local}' if not ZERO.match(remote) else None)
            if not spans:
                spans = [None]
            base = self.base()
            for span in spans:
                span = span or (f'{base}...HEAD' if base else None)
                if span:
                    done = self.git('diff', '--name-only', '--diff-filter=d', span)
                    names |= set(done.stdout.split()) if done.returncode == 0 else set()
            status = self.git('status', '--porcelain', '--untracked-files=all')
            names |= {line[3:].split(' -> ')[-1].strip('"') for line in status.stdout.splitlines() if 'D' not in line[:2]}
            self._changed = sorted(name for name in names if (self.root / name).is_file())
        return self._changed


def parse_refs(text):
    """Pre-push stdin lines: <local ref> <local sha> <remote ref> <remote sha>."""
    refs = []
    for line in (text or '').splitlines():
        parts = line.split()
        if len(parts) == 4:
            refs.append(tuple(parts))
    return refs


def one_push_per_commit(ctx):
    """D-022: a push brings at most one commit of the branch that the remote lacks (first parent, merges excluded)."""
    refs = ctx.refs
    if not refs:
        base = ctx.base()
        if not base:
            raise Skip('no upstream and no origin/<integration branch> to count against')
        refs = [('HEAD', 'HEAD', 'HEAD', base)]
    errors = []
    for _, local, remote_ref, remote in refs:
        if ZERO.match(local):
            continue
        exclude = ctx.base() if ZERO.match(remote) else remote
        if exclude is None:
            raise Skip('new branch and no integration branch to count against')
        # a new branch counts what neither the base nor any other remote ref holds: a branch stacked on a pushed,
        # unmerged one sends only its own commit (FLUXO-AMPLO F1.1, D-142)
        held = ['--not', '--remotes'] if ZERO.match(remote) else []
        done = ctx.git('rev-list', '--first-parent', '--no-merges', local, '^' + exclude, *held)
        if done.returncode != 0:
            raise Skip(f'cannot list commits {exclude}..{local}')
        shas = done.stdout.split()
        if len(shas) > 1:
            errors.append(f'push: {len(shas)} commits of the branch would be pushed at once ({", ".join(s[:7] for s in shas)}); '
                          'push each commit as it is done (D-022); fix: scripts/replay-branch <pr>')
    return errors


def no_history_rewrite(ctx):
    """FP1 (D-022): merge commits only. A push whose remote sha is not an ancestor of the pushed sha rewrites history
    (a force push after a rebase or amend); new branches and deletions are not judged."""
    errors = []
    for _, local, remote_ref, remote in ctx.refs or []:
        if ZERO.match(local) or ZERO.match(remote):
            continue
        done = ctx.git('merge-base', '--is-ancestor', remote, local)
        if done.returncode == 1:
            errors.append(f'force-push: {remote_ref} would move from {remote[:7]} to {local[:7]}, which does not contain it '
                          '(a rebase, amend or reset); pushed history is never rewritten: bring the base in with '
                          '`git merge`, or replay the PR on a new branch with scripts/replay-branch <pr>')
        elif done.returncode != 0:
            raise Skip(f'remote commit {remote[:7]} is not in this checkout')
    return errors


def gate_change_cites_decision(ctx):
    """D-025: a change to the gate cites an approved D-NNN in the PR body."""
    import commit_check
    files = ctx.changed()
    errors = commit_check.gate_errors(ctx.body or '', files, commit_check.decisions(ctx.root))
    if errors and ctx.body is None:
        raise Skip('the change touches the gate but no PR body is given (--body-file or the body_env file)')
    return errors


def _gitleaks(ctx):
    found = shutil.which('gitleaks')
    local = ctx.root / '.toolchain/bin/gitleaks'
    return found or (str(local) if local.is_file() else None)


def secret_scan_diff(ctx):
    """gitleaks on the changed files only, copied to a temp tree like gate-runner.sh secret_tree; values are redacted."""
    tool = _gitleaks(ctx)
    if not tool:
        raise Skip('gitleaks is not installed (bash scripts/cloud/setup.sh)')
    files = ctx.changed()
    if not files:
        return []
    with tempfile.TemporaryDirectory() as tmp:
        scan, report = Path(tmp) / 'tree', Path(tmp) / 'report.json'
        for name in files:
            target = scan / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ctx.root / name, target)
        cfg = ctx.root / config.get('local-checks.gitleaks_config')
        command = [tool, 'dir', '--redact', '--no-banner', '--report-format', 'json', '--report-path', str(report)]
        if cfg.is_file():
            command += ['--config', str(cfg)]
        try:
            done = subprocess.run(command + ['.'], cwd=scan, capture_output=True, text=True,
                                  timeout=config.get('local-checks.gitleaks_timeout_s'))
        except subprocess.TimeoutExpired:
            raise Skip('gitleaks timed out')
        if done.returncode == 0:
            return []
        try:
            hits = json.loads(report.read_text())
        except (OSError, ValueError):
            raise Skip(f'gitleaks failed (exit {done.returncode})')
    return [f'secret: {hit.get("File", "?")}:{hit.get("StartLine", "?")} matches {hit.get("RuleID", "?")} (value redacted)'
            for hit in hits[:10]]


def no_registered_literals(ctx):
    """D-068: a changed engine file spells no registered parameter as a literal (the rules of structure-check)."""
    import config_check
    root = ctx.root
    params = config._load(root if (root / 'config/registry').is_dir() else ROOT)  # a bare fixture repo uses the engine's registry
    names = config_check.Names(params)
    changed = set(ctx.changed())
    errors = []
    for path, kind in config_check.engine_files(root):
        if path not in changed:
            continue
        text = (root / path).read_text(encoding='utf-8', errors='replace')
        hits = (config_check.python_findings(path, text, names, params) if kind == '.py'
                else config_check.text_findings(path, text, names, shell=kind == '.sh'))
        for line, identifier, name, found in hits:
            if found == 'fallback':
                errors.append(f'literal: {path}:{line} an inline fallback after reading {name}; the registry value is the only value')
            elif f'{path}:{identifier}' not in (params[name].get('x-literal-sites') or []):
                errors.append(f'literal: {path}:{line} {identifier} spells the registered parameter {name}; read it with config.get')
    return errors


def structure_fast(ctx):
    """The cheap sub-checks of structure-check, called directly (the whole check takes 20-34 s)."""
    import commit_check
    import postmortem_check
    import premises
    import structure
    root = ctx.root
    errors = structure.check_decisions(root, ctx.today)[0]
    errors += structure.check_links(root)[0]
    errors += postmortem_check.check(root)
    errors += premises.check_register(root)[0]
    if ctx.body is not None:
        errors += commit_check.plan_errors(ctx.body)
    return errors


DECISION_RECORDS = 'docs/domain/decisions/'  # decision_table.RECORDS, as a path prefix
DECISION_TABLE = 'docs/domain/DECISIONS.md'  # decision_table.TABLE


def decision_table_in_step(ctx):
    """D-217: a push that changes a decision record or the table keeps the table in step with the records
    (decision_table.drift): a record with no matching row (fix: scripts/decision-table --write), an id written twice or
    by hand, an id the base's register had and this one lost. A push that touches neither is not judged, so a base that
    already drifts never refuses an unrelated push."""
    import decision_table
    if not any(name.startswith(DECISION_RECORDS) or name == DECISION_TABLE for name in ctx.changed()):
        return []
    try:
        records = decision_table.load(ctx.root)
    except ValueError as error:
        return [f'decision record {error}']
    base = ctx.base()
    before = decision_table.previous_table(base, ctx.root) if base else None
    return [f'decision table: {line}' for line in decision_table.drift(ctx.root, records, before)]


GIT_PATHS = ('GIT_DIR', 'GIT_INDEX_FILE', 'GIT_WORK_TREE')  # what a git hook exports to the processes it starts


def other_repository(root):
    """The git variable that points at another repository than root, or None. A hook of another checkout (push_guard's
    post-commit push of a test fixture) exports them, and every `git -C root` of a module would then read that one."""
    clean = {key: value for key, value in os.environ.items() if key not in GIT_PATHS}
    done = subprocess.run(['git', '-C', str(root), 'rev-parse', '--absolute-git-dir', '--show-toplevel'],
                          capture_output=True, text=True, env=clean)
    if done.returncode != 0:
        return None
    own = [Path(line).resolve() for line in done.stdout.split()]
    for name in GIT_PATHS:
        value = os.environ.get(name)
        if value and not any(path == mine or mine in path.parents for path in [Path(value).resolve()] for mine in own):
            return name
    return None


def _structure_module(name, base=False):
    """A structure-check module as a check: its errors are refusals, its warnings are not; without a base a
    base-relative module is skipped, and so is every one run under a git variable of another repository."""
    def handler(ctx):
        foreign = other_repository(ctx.root)
        if foreign:
            raise Skip(f'{foreign} names another repository (a hook of another checkout)')
        args = [ctx.root]
        if base:
            ref = ctx.base()
            if ref is None:
                raise Skip('no base to diff against')
            args.append(ref)
        found = importlib.import_module(name).check(*args)
        return list(found[0] if isinstance(found, tuple) else found)
    handler.__doc__ = f'structure-check {name}, called directly.'
    return handler


structure_config_check = _structure_module('config_check', base=True)
structure_literal_census = _structure_module('literal_census', base=True)
structure_vendor = _structure_module('vendor_check', base=True)
structure_unit_check = _structure_module('unit_check')


HANDLERS = {
    'one_push_per_commit': one_push_per_commit,
    'no_history_rewrite': no_history_rewrite,
    'gate_change_cites_decision': gate_change_cites_decision,
    'secret_scan_diff': secret_scan_diff,
    'no_registered_literals': no_registered_literals,
    'structure_fast': structure_fast,
    'structure_config_check': structure_config_check,
    'structure_literal_census': structure_literal_census,
    'structure_vendor': structure_vendor,
    'structure_unit_check': structure_unit_check,
    'decision_table': decision_table_in_step,
}


def resolve(name):
    if name in HANDLERS:
        return HANDLERS[name]
    if ':' in name:
        module, _, function = name.partition(':')
        return getattr(importlib.import_module(module), function)
    raise Skip(f'no handler named {name}')


def state_path(root):
    done = subprocess.run(['git', '-C', str(root), 'rev-parse', '--git-path', config.get('local-checks.state_file')],
                          capture_output=True, text=True)
    if done.returncode != 0:
        return None
    path = Path(done.stdout.strip())
    return path if path.is_absolute() else Path(root) / path


def load_moved(path):
    try:
        return dict(json.loads(path.read_text()).get('moved', {})) if path else {}
    except (OSError, ValueError, AttributeError):
        return {}


def save_moved(path, moved):
    if path:
        try:
            path.write_text(json.dumps({'moved': moved}, indent=2, sort_keys=True) + '\n')
        except OSError:
            pass


LOCK_OF = {'one_push_per_commit': 'commit-plan', 'literal_census': 'literals', 'structure_literal_census': 'literals'}  # a check whose refusals the exception regime may lift (D-260)


def _lift_of(check_id, errors):
    lock = LOCK_OF.get(check_id)
    if not lock or not errors:
        return errors
    import commit_check  # not at import: commit_check is reached from structure, which imports this module
    return commit_check.lift(errors, lock)


def run(ctx, entries=None, total_limit=None, state=None):
    """Run the enabled local checks. Returns {results, errors, total_ms, total_over, moved}; each result is
    {id, owner, status ok|failed|skipped|over_budget|gate|disabled, cost_ms, budget_ms, reason, errors}."""
    entries = config.get('local-checks.checks') if entries is None else entries
    total_limit = config.get('local-checks.total_budget_ms') if total_limit is None else total_limit
    state = state_path(ctx.root) if state is None else state
    moved = load_moved(state)
    results, errors, total, newly = [], [], 0.0, {}
    for entry in entries:
        result = {'id': entry['id'], 'owner': entry['owner'], 'budget_ms': entry['budget_ms'], 'cost_ms': 0.0,
                  'reason': '', 'errors': []}
        if not entry['enabled']:
            result['status'] = 'disabled'
        elif entry['stage'] == 'gate' or entry['id'] in moved:
            result['status'] = 'gate'
        else:
            started = ctx.clock()
            try:
                result['errors'] = _lift_of(entry['id'], list(resolve(entry['handler'])(ctx)))
                result['status'] = 'failed' if result['errors'] else 'ok'
            except Skip as skip:
                result['status'], result['reason'] = 'skipped', str(skip)
            except Exception as error:  # a broken handler never blocks a push
                result['status'], result['reason'] = 'skipped', f'handler error: {type(error).__name__}: {error}'
            result['cost_ms'] = round((ctx.clock() - started) * 1000, 1)
            total += result['cost_ms']
            if result['cost_ms'] > entry['budget_ms']:
                result['over_budget'] = True
                newly[entry['id']] = {'cost_ms': result['cost_ms'], 'budget_ms': entry['budget_ms']}
            errors += result['errors']
        results.append(result)
    if newly:
        moved.update(newly)
        save_moved(state, moved)
    return {'results': results, 'errors': errors, 'total_ms': round(total, 1), 'total_over': total > total_limit,
            'total_limit_ms': total_limit, 'moved': newly}


def report(outcome, out=print):
    for result in outcome['results']:
        status = 'over_budget' if result.get('over_budget') else result['status']
        note = f' ({result["reason"]})' if result['reason'] else ''
        out(f'local-check {result["id"]}: {status} {result["cost_ms"]:.0f} ms of {result["budget_ms"]} ms{note}')
        for line in result['errors']:
            out('FAIL ' + line)
        if result.get('over_budget'):
            out(f'WARN {result["id"]} is over its budget and MOVES TO THE GATE: the next local runs skip it '
                f'({result["owner"]} owns it; the registry entry is unchanged)')
    if outcome['total_over']:
        out(f'WARN local checks took {outcome["total_ms"]:.0f} ms, over the total budget of {outcome["total_limit_ms"]} ms')
    out(f'local-checks: {len(outcome["errors"])} refusal(s), {outcome["total_ms"]:.0f} ms')


def main(root, body_file=None, stdin_refs=False, stdin=None, only=None):
    """Entry of commit_check --local. Exit 1 only for a real finding; `only` runs the one check of that id (1, a refusal, when no check
    has it), so a caller can put one check on the commit path (lane 1's request, D-236)."""
    entries = None
    if only is not None:
        entries = [entry for entry in config.get('local-checks.checks') if entry['id'] == only]
        if not entries:
            print(f'local-checks: no check named {only}; the registry names {", ".join(e["id"] for e in config.get("local-checks.checks"))}')
            return 1
    body = None
    path = body_file or os.environ.get(config.get('local-checks.body_env'))
    if path:
        try:
            body = Path(path).read_text()
        except OSError:
            body = None
    refs = parse_refs((stdin or sys.stdin).read()) if stdin_refs else None
    outcome = run(Context(root, body=body, refs=refs), entries=entries)
    report(outcome)
    return 1 if outcome['errors'] else 0
