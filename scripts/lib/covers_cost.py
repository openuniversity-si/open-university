"""Expected script-test cost per PR, from the covers (D-167): `scripts/covers-cost --since DATE`.

Replays the merged PRs since DATE (first-parent merge commits of the base), selects the script tests each one's diff
would have run, and prints, per test, its miss rate and its share of the expected cost per PR (miss rate times its cost
in scripts/tests/costs.json, the cold cost on a container-class box). The sum is the number D-149 used: what a PR pays
when no proof is attested, and the one to cut before the real gate can be fast. With --paths PATTERN it also prints
which of the test's covers patterns the diffs met, so a broad pattern shows up by its count.
"""
import argparse
import collections
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

import config  # noqa: E402
import gate_script_tests  # noqa: E402
from gate_areas import glob_match  # noqa: E402


def git(*args):
    return subprocess.run(['git', '-C', str(ROOT), *args], capture_output=True, text=True, check=True).stdout.split()


def merged_diffs(since, base):
    """One path list per PR merged into `base` since `since` (a git date)."""
    diffs = []
    for merge in git('log', '--first-parent', '--merges', f'--since={since}', '--format=%H', base):
        paths = git('diff', '--name-only', f'{merge}^1', merge)
        if paths:
            diffs.append(paths)
    return diffs


def measure(diffs, mapping, costs, plan_for=None):
    """({test: PRs that select it}, PR count, expected cold seconds per PR, PRs whose gate skips the script tests).

    F41: the gate decides from its area plan (gate_areas.plan_for) whether the script-test stage runs at all; a PR whose
    plan leaves it out pays no test, and a full plan pays the whole suite. Only a plan that runs the stage selects by
    the covers, as the gate does."""
    if plan_for is None:
        import gate_areas
        plan_for = gate_areas.plan_for
    hits, skipped = collections.Counter(), 0
    for paths in diffs:
        plan = plan_for(paths)
        if 'script tests' not in (plan.get('stages') or []):
            skipped += 1
            continue
        if plan.get('kind') == 'full':
            hits.update(mapping['scripts'])
            continue
        hits.update(gate_script_tests.select(paths, mapping)[0])
    total = sum(costs.get(test, 0) * count for test, count in hits.items())
    return hits, len(diffs), total / len(diffs) if diffs else 0, skipped


def script_of(name, mapping):
    """The mapped script for `name`, given as the script path or as the bare test name (`covers-cost`); None if unknown."""
    wanted = name if name.startswith('scripts/') else f'scripts/tests/{name}.test.sh'
    return next((item['script'] for item in mapping['tests'] if item['script'] == wanted), None)


def patterns_met(diffs, mapping, test):
    """{covers pattern of `test`: PRs whose diff meets it}, the broad ones first."""
    covers = next(item['covers'] for item in mapping['tests'] if item['script'] == script_of(test, mapping))
    met = collections.Counter()
    for paths in diffs:
        expanded = gate_script_tests.by_readers(paths)
        met.update({pattern for path in expanded for pattern in covers if glob_match(path, pattern)})
    return met


def report(hits, count, expected, costs, skipped=0):
    lines = [f'{count} PRs, expected cold script-test cost per PR {expected:.1f} s; '
             f'{skipped} PRs whose gate plan runs no script test']
    for test, seen in sorted(hits.items(), key=lambda item: -item[1] * costs.get(item[0], 0)):
        cost = costs.get(test, 0)
        lines.append(f'{test}  miss {seen / count:.2f}  cost {cost:.1f} s  share {seen / count * cost:.1f} s')
    return lines


def main(argv=None):
    parser = argparse.ArgumentParser(prog='scripts/covers-cost', description=__doc__)
    parser.add_argument('--since', required=True, help='git date, e.g. 2026-10-28')
    parser.add_argument('--base', default=f'{config.get("train.git_remote")}/{config.get("train.base_branch")}')
    parser.add_argument('--paths', default='', help='a script test: print the covers patterns its PRs met')
    args = parser.parse_args(argv)
    mapping = gate_script_tests.load()
    if args.paths and script_of(args.paths, mapping) is None:
        print(f'covers-cost: --paths {args.paths}: no script test of that name (use covers-cost or '
              f'scripts/tests/covers-cost.test.sh)', file=sys.stderr)
        return 1
    costs = json.loads((ROOT / 'scripts' / 'tests' / 'costs.json').read_text())
    diffs = merged_diffs(args.since, args.base)
    if not diffs:
        print('no merged PR in the window', file=sys.stderr)
        return 1
    hits, count, expected, skipped = measure(diffs, mapping, costs)
    print('\n'.join(report(hits, count, expected, costs, skipped)))
    if args.paths:
        for pattern, seen in patterns_met(diffs, mapping, args.paths).most_common():
            print(f'  {script_of(args.paths, mapping)} covers {pattern}: {seen} PRs')
    return 0


if __name__ == '__main__':
    sys.exit(main())
