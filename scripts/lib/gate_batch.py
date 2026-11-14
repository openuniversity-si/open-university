"""Batch mode for the gate (GS1, lever 4): gate the union of several PRs' changes once, with per-PR attribution.

The merge train gates a batch of PRs on their combined head. Gating each PR alone repeats the same work; gating the
union once costs one gate, and when it is red the attribution says which PRs the failures implicate, so the train ejects
those and keeps the rest.

  merge_union(root, base, shas)    the combined commit (each PR merged into the running tip without touching a branch) and
                                   the PRs that conflicted with the tip, with the files; a conflicting PR is left out
  plan(root, base, shas)           the union gate plan: the area plan and the per-unit selection of the union of the
                                   included PRs' paths, each PR's own selection and the paths more than one PR changes
  attribute(plan, failures, ...)   which PRs a red run implicates: a failure is blamed on the PRs whose change can reach it
                                   (they touched its file, or a unit its unit requires, or their selection was full), and
                                   a failure that cannot be placed (a stage with no failing test, a path the map does not
                                   know) implicates every PR, so the train never merges a PR a failure may belong to

scripts/gate-batch [--base REF] <ref>...  (also scripts/gate-dev --batch <ref>...) runs gate-local --dev on the combined
commit with the union plan and prints the attribution as JSON; exit 0 only when every PR is clear.

Tier 2 of the train (GX-30, train.tier2_command): `scripts/gate-batch --tier 2 <combined>` gates the train's own combined
commit (or a bisection prefix of it) with the union plan of the members it names in GATE_BATCH_BASE and
GATE_BATCH_MEMBERS. plan(..., head=) checks that commit has exactly the union's tree and gates that sha, so the train's
flake and tree proofs keep keying on the commit it built; a batch of documentation no script test covers runs no
script-test stage.
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

import config
import gate_failures
import gate_policy
import gate_select
import units
import merge_composition

ROOT = Path(__file__).resolve().parents[2]
TIERS = ('2',)  # --tier: only the train's tier 2 gates a given combined commit (train.tier2_command)


class BatchError(ValueError):
    pass


def git(root, *args, check=True, input=None):
    return subprocess.run(['git', '-C', str(root), *args], capture_output=True, text=True, check=check, input=input)


def resolve(root, ref):
    done = git(root, 'rev-parse', '--verify', '--quiet', f'{ref}^{{commit}}', check=False)
    if done.returncode != 0:
        raise BatchError(f'{ref} is not a commit')
    return done.stdout.strip()


def tree(root, commit):
    return git(root, 'rev-parse', '--verify', f'{commit}^{{tree}}').stdout.strip()


def changed(root, base, sha):
    out = git(root, 'diff', '--no-renames', '--name-only', '-z', f'{base}...{sha}').stdout
    return sorted(path for path in out.split('\0') if path)


def merge_union(root, base, shas):
    """(combined commit, included shas, conflicts [{sha, files}]). Branches and the index are never touched."""
    tip, included, conflicts = base, [], []
    for sha in shas:
        def run(*args, **kwargs):
            return git(root, *args, **kwargs)

        def failure(command, done):
            return BatchError(f'git {command} failed for {sha}: {done.stderr.strip()[:200]}')

        lines, files = merge_composition.merge_tree(run, tip, sha, failure)
        if files:
            conflicts.append({'sha': sha, 'files': files})
            continue
        tip = merge_composition.merge_commit(run, lines[0], tip, sha, f'gate batch: {sha}')
        included.append(sha)
    return tip, included, conflicts


def plan(root, base, shas, head=None):
    """The union gate plan. `shas` are the PR heads in train order; a conflicting PR is reported and left out. `head` is
    a combined commit already built by the caller (the train): it must hold every PR and have the union's tree, and it
    is the commit the plan gates. The registry is read as it stands when the plan starts (config.reading): one stat
    of it for the whole plan, not one per value read."""
    with config.reading():
        return _plan(root, base, shas, head)


def _plan(root, base, shas, head):
    limit = config.get('gate.batch_max_prs')
    if not shas:
        raise BatchError('a batch needs at least one PR')
    if len(shas) > limit:
        raise BatchError(f'a batch holds at most {limit} PRs (gate.batch_max_prs)')
    if len(set(shas)) != len(shas):
        raise BatchError('a PR appears twice in the batch')
    base = resolve(root, base)
    head_union, included, conflicts = merge_union(root, base, shas)
    head = head_union if head is None else given_head(root, head, head_union, conflicts)
    paths = {sha: changed(root, base, sha) for sha in shas}
    union = sorted({path for sha in included for path in paths[sha]})
    seen, overlap = {}, set()
    for sha in included:
        for path in paths[sha]:
            if path in seen and seen[path] != sha:
                overlap.add(path)
            seen.setdefault(path, sha)
    return {
        'base': base, 'head': head, 'included': included, 'conflicts': conflicts, 'overlap': sorted(overlap),
        'prs': [{'sha': sha, 'paths': paths[sha], 'selection': gate_select.select(paths[sha], root)} for sha in shas],
        'devPlan': gate_policy.select_dev_plan(union, base, head, root) if included else None,
        'selection': gate_select.select(union, root) if included else None,
    }


def given_head(root, head, union, conflicts):
    """The caller's combined commit, once it is proven to be the union: no member conflicts and the same tree."""
    head = resolve(root, head)
    if conflicts:
        raise BatchError(f'{head} cannot be the union: {", ".join(c["sha"] for c in conflicts)} conflict(s) with the base')
    if tree(root, head) != tree(root, union):
        raise BatchError(f'{head} does not have the tree of its members merged on the base')
    return head


def file_of(identity, files):
    """The repository path a failing test id names, or None: `scripts/tests/x.test.sh`, `|label| <path> > case`.
    OU-DECOUPLE F5 (D-113): a path relative to Open University's web package is no longer resolved."""
    for token in identity.split(' > ', 1)[0].split():
        if token in files:
            return token
    return None


def attribute(batch, failures, stage_failures=(), files=None, root=ROOT):
    """Which PRs a run implicates. `failures` are gate_failures items; `stage_failures` the names of failed stages."""
    files = set(gate_select.tracked(root) if files is None else files)
    blame = {pr['sha']: [] for pr in batch['prs']}
    unplaced = []
    for failure in failures:
        path = file_of(failure['id'], files)
        owner = units.unit_of(path, root) if path else None
        placed = []
        for pr in batch['prs']:
            if pr['sha'] not in batch['included']:
                continue
            selection = pr['selection']
            if selection['kind'] != 'scoped':
                placed.append(pr['sha'])  # a full-battery change can reach anything
            elif path and path in pr['paths']:
                placed.append(pr['sha'])
            elif owner and owner in selection['affected']:
                placed.append(pr['sha'])
        if not path or not owner or not placed:
            unplaced.append(failure['id'])
            placed = [pr['sha'] for pr in batch['prs'] if pr['sha'] in batch['included']]
        for sha in placed:
            blame[sha].append(failure['id'])
    for name in stage_failures:
        unplaced.append(name)
        for sha in batch['included']:
            blame[sha].append(name)
    result = {sha: sorted(set(ids)) for sha, ids in blame.items()}
    return {'verdict': 'fail' if any(result[sha] for sha in batch['included']) else 'pass',
            'prs': {pr['sha']: {'implicated': result[pr['sha']],
                                'clear': pr['sha'] in batch['included'] and not result[pr['sha']],
                                'conflict': next((c['files'] for c in batch['conflicts'] if c['sha'] == pr['sha']), None)}
                    for pr in batch['prs']},
            'unplaced': sorted(set(unplaced))}


def main(argv):
    parser = argparse.ArgumentParser(prog='gate_batch', description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest='command', required=True)
    planned = commands.add_parser('plan')
    planned.add_argument('--base', default=None)
    planned.add_argument('--head', default=None, help='a combined commit already built (the train): gate that sha')
    planned.add_argument('--tier', choices=TIERS, default=None, help='the train\'s tier 2: needs --base and --head')
    planned.add_argument('--tier-extra', default=None, help=argparse.SUPPRESS)  # scripts/gate-batch: a word too many
    planned.add_argument('--root', default=str(ROOT))
    planned.add_argument('--output', required=True)
    planned.add_argument('refs', nargs='+')
    judged = commands.add_parser('attribute')
    judged.add_argument('--plan', required=True)
    judged.add_argument('--reports', required=True)
    judged.add_argument('--root', default=str(ROOT))
    args = parser.parse_args(argv[1:])
    try:
        if args.command == 'plan':
            if args.tier_extra:
                raise BatchError(f'--tier takes one combined commit, not {args.tier_extra} too')
            if args.tier and not (args.base and args.head):
                raise BatchError(f'--tier {args.tier} needs the base and the combined commit (GATE_BATCH_BASE, <combined>)')
            base = args.base or config.get('gate.batch_base_ref')
            shas = [resolve(args.root, ref) for ref in args.refs]
            result = plan(args.root, base, shas, args.head)
            Path(args.output).write_text(json.dumps(result, indent=2))
            print(result['head'])
            return 0
        batch = json.loads(Path(args.plan).read_text())
        reports = Path(args.reports)
        stages = json.loads((reports / 'stages.json').read_text()) if (reports / 'stages.json').is_file() else {'stages': []}
        found, _total = gate_failures.failing(reports)
        parsed = {item['stage'] for item in found}
        stage_failures = [s['name'] for s in stages['stages'] if s['result'] == 'FAIL' and s['name'] not in parsed]
        verdict = attribute(batch, found, stage_failures, root=args.root)
        print(json.dumps(verdict, indent=2))
        return 0 if verdict['verdict'] == 'pass' and not batch['conflicts'] else 1
    except (BatchError, subprocess.CalledProcessError, OSError, ValueError) as error:
        print(f'gate-batch: {error}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv))
