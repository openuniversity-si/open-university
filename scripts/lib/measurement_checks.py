"""The gate's "measurement checks" stage (D-322): the measurement checks, run by the gate, not by the structure check.

The structure check (planning, layer 1) imports nothing of measurement (layer 5): the checks that judge the measures' own
data run here, as an always-run stage after it, the way the production guard and the gate maps do (D-054, D-322):
  absolute baseline  the absolute exception list (every unit's census record) only shrinks, per area and value (D-063, D-064 a);
  census             each unit's census record: shape, digest chain, fold, owner, append-only (CENSO-NO-MANIFESTO);
  shared literals    a value of two or more census areas is born in the common catalog (D-064 c);
  budgets            the performance budgets' entries and baseline, never loosened without a decision (D-069 item 14, D-025).
And the PR body's part, which the gate's `pr metadata` stage runs beside structure-check --metadata:
  effort             the `## Cheapest useful effort` block of the PR body (EFFORT-STEP, D-069 items 4, 8, 9).

`python3 measurement_checks.py check [--base B] [--root R]` and `body (--pr-body FILE | --pr N) [--base B] [--sha S]
[--observation FILE] [--root R]` print FAIL/WARN lines and a summary, and exit 1 on an error.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys

import budget_check
import census
import config
import effort

ABSOLUTE_BASELINE = 'scripts/lib/absolute-literals-baseline'  # D-064 (a): where scripts/generate census renders an area
SHARED_LITERALS = 'scripts/lib/shared-literals.json'
TRIVIAL_LITERALS = frozenset({'number "0"', 'number "1"', 'boolean "true"', 'string ""'})  # D-063: the remainder domain


def baseline_files(root, base=None):
    """The absolute exception list, {path: {value: count}}: every unit's census record and, until migrated, the old
    per-area files (scripts/lib/census.py, CENSO-NO-MANIFESTO), in the checkout or in `base`; None if it holds none."""
    try:
        return census.entries(root, census.BASELINE, base) or None
    except census.CensusError:
        return None


def check_absolute_baseline(root, base=None):
    """D-063, D-064 (a): the absolute exception list only shrinks, per census area and value. Against the base, no
    area allows a value more times in all its files together; a literal may move with its file inside its area, and a
    value removed from one area does not pay for the same value added to another."""
    after = baseline_files(root)
    before = baseline_files(root, base) if base else None
    if after is None or before is None:
        return []

    def totals(files):
        counts = {}
        for path, values in files.items():
            for value, count in values.items():
                key = (census.area(path), value)
                counts[key] = counts.get(key, 0) + count
        return counts

    before, after = totals(before), totals(after)
    return [f'{ABSOLUTE_BASELINE}/{area}.json: {value} allowed {before.get((area, value), 0)} times in {base}, {count} here; '
            f'the list only shrinks per area (D-063, D-064 a): read the value from a catalog'
            for (area, value), count in sorted(after.items()) if count > before.get((area, value), 0)]


def shared_values(files):
    """Each non-trivial listed value present in two or more census areas, with its areas."""
    areas = {}
    for path, values in files.items():
        for value in values:
            areas.setdefault(value, set()).add(census.area(path))
    return {value: sorted(found) for value, found in areas.items() if len(found) > 1 and value not in TRIVIAL_LITERALS}


def check_shared_literals(root, base=None):
    """D-064 (c): a value present in two or more areas is born in the common catalog (a catalog entry of the census).
    The census list (equal to the census, D-063) shows every literal still written in a production file; one in 2+ areas fails
    unless the registered list names it with a documented reason. The registered list only shrinks against the base;
    an entry that no longer spans 2+ areas is a warning, so a front that fixes a value need not edit the list (D-064 a)."""
    files = baseline_files(root)
    if files is None:
        return [], []
    shared = shared_values(files)
    listed = Path(root) / SHARED_LITERALS
    data = json.loads(listed.read_text()) if listed.is_file() else {'reasons': {}, 'values': {}}
    reasons, registered = data.get('reasons', {}), data.get('values', {})
    errors = [f'{SHARED_LITERALS}: {value} names the unknown reason "{reason}"'
              for value, reason in sorted(registered.items()) if reason not in reasons]
    errors += [f'{value} is written in {len(areas)} areas ({", ".join(areas)}) and is not in the common catalog: '
               f'a value of 2+ areas is born in a common catalog (scripts/census add --catalog; D-064 c)'
               for value, areas in sorted(shared.items()) if value not in registered]
    if base:
        shown = subprocess.run(['git', '-C', str(root), 'show', f'{base}:{SHARED_LITERALS}'], capture_output=True, text=True)
        before = json.loads(shown.stdout).get('values', {}) if shown.returncode == 0 else None
        if before is not None:
            errors += [f'{SHARED_LITERALS}: {value} is not registered in {base}; the list only shrinks (D-064 c): '
                       'put the value in the common catalog' for value in sorted(registered) if value not in before]
    warnings = [f'{SHARED_LITERALS}: {value} no longer spans 2+ areas; integration drops it (D-064 c)'
                for value in sorted(registered) if value not in shared]
    return errors, warnings


def check(root, base=None):
    """The tree's measurement checks: (errors, warnings)."""
    errors = check_absolute_baseline(root, base)
    errors += census.check(root, base)  # CENSO-NO-MANIFESTO: each unit's record, written only by scripts/census
    shared_errors, warnings = check_shared_literals(root, base)
    errors += shared_errors
    budget_errors, budget_warnings = budget_check.check(root, base)  # D-069 item 14, D-025
    return errors + list(budget_errors), warnings + list(budget_warnings)


def fetched_pr(root, number, sha=None, observation=None):
    """The PR as the structure check's `pr metadata` reads it (structure.gated_fetch, planning, a lower layer), judged on
    the gated sha (GX-14); with an observation, what the live service read (PR-OBSERVATION). Imported only here, so the
    tree's check and a body file never load it."""
    import structure
    return structure.gated_fetch(root, number, sha, observation=observation)


def body(root, text, base=None, created=None):
    """The PR body's measurement refusals: the effort block (EFFORT-STEP, D-069 items 4, 8, 9, D-025)."""
    return effort.body_errors(text, root, base=base, created=created)


def default_root():
    found = subprocess.run(['git', 'rev-parse', '--show-toplevel'], capture_output=True, text=True)
    return Path(found.stdout.strip()) if found.returncode == 0 else Path(__file__).resolve().parents[2]


def main(argv=None, fetch=fetched_pr):
    parser = argparse.ArgumentParser(prog='measurement_checks.py', description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest='command', required=True)
    tree = commands.add_parser('check', help='the tree: absolute baseline, census, shared literals, budgets')
    tree.add_argument('--base')
    tree.add_argument('--root', type=Path)
    pr = commands.add_parser('body', help='the PR body: the effort block (the gate runs it in `pr metadata`)')
    source = pr.add_mutually_exclusive_group()
    source.add_argument('--pr-body', type=Path, help='a PR body file')
    source.add_argument('--pr', type=int, help='this PR over the forge, judged on --sha or the gated head')
    pr.add_argument('--base')
    pr.add_argument('--sha')
    pr.add_argument('--observation', type=Path, help='--pr: judge what the live service read of the PR (PR-OBSERVATION)')
    pr.add_argument('--root', type=Path)
    args = parser.parse_args(argv)
    root = (args.root or default_root()).resolve()
    warnings = []
    with config.reading():
        if args.command == 'check':
            errors, warnings = check(root, args.base)
            scope = f'against {args.base}' if args.base else 'no base'
        elif args.pr_body:
            errors, scope = body(root, args.pr_body.read_text()), 'PR body file'
        elif args.pr:
            scope = f'PR #{args.pr}'
            try:
                seen = json.loads(args.observation.read_text()) if args.observation else None
                fetched = fetch(root, args.pr, args.sha, observation=seen)
            except (RuntimeError, OSError, KeyError) as error:  # fail closed: the body was not judged
                errors = [f'measurement: PR #{args.pr} not readable ({error})']
            else:
                errors = body(root, fetched.get('body', ''), base=(fetched.get('base') or {}).get('merge_base'),
                              created=fetched.get('created_at'))
        else:
            errors, scope = [], 'no PR'  # the gate's `pr metadata` without --pr judges nothing
    for line in errors:
        print('FAIL ' + line)
    for line in warnings:
        print('WARN ' + line)
    print(f'measurement checks ({args.command}, {scope}): {len(errors)} error(s), {len(warnings)} warning(s)')
    return 1 if errors else 0


if __name__ == '__main__':
    sys.exit(main())
