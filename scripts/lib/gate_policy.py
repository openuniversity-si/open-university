"""Shared gate plans. Path-to-stage rules live in gate-areas.json (ADR-33/34)."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
from delivery import subject_root
from gate_areas import plan_for, full_plan
import gate_carry
import gate_select
import forge_events
import config

ROOT = Path(__file__).resolve().parents[2]
# GATE-VERDICT-API (D-070): cheap stages first, `pr metadata` (about 5 s, the most frequent red) at the top. This is the
# declared and displayed order (--list, --explain, status rows); gate-local starts the seven together (GK1, no early stop).
PREREQUISITES = ['pr metadata', 'no GitHub Actions workflows', 'secret scan (tree)', 'structure check',
                 'generated drift', 'schema compat', 'secret scan (history)']  # GX-15: pr metadata is launched by gate-hooks/prereq.sh
# OU-DECOUPLE F5 (D-113): the engine gate runs only engine stages. Open University's web and database stages (install,
# suites, lint, typecheck, builds, performance, browsers, the per-PR database stages, the DB gate and the factory bench) left
# with it; the names stay, so a reader of the plans keeps its API. The dev plan adds the script tests its areas select.
DEVELOPMENT = []
FULL_ONLY = ['shellcheck', 'script tests']
BROWSER = []
FULL_STAGES = PREREQUISITES + DEVELOPMENT + FULL_ONLY + BROWSER
# Tier 3 (D-065 (5)): the full battery on an integration tip; nothing of it is kept for the release any more.
TIER3_STAGES = PREREQUISITES + DEVELOPMENT + FULL_ONLY + BROWSER
DEV_STAGES = PREREQUISITES + DEVELOPMENT
# The per-PR database gate (ADR-34) was Open University's; no engine path asks for it.
DB_STAGES = []
PLANS = {'dev': DEV_STAGES, 'noite': FULL_STAGES, 'full': FULL_STAGES, 'tier3': TIER3_STAGES}


POLICY_VERSION = '7.0.0'


def select_dev_plan(paths, base, head, root=ROOT):
    """Area plan for one diff. An invalid identity keeps the full battery; an unmapped path is the always stages, refused
    by the structure check (D-106)."""
    identity = isinstance(paths, (list, tuple)) and bool(base) and bool(head)
    paths = [str(path) for path in (paths or [])]
    if not identity:
        plan = full_plan(paths, 'invalid diff identity; full battery')
    else:
        plan = plan_for(paths)
    plan.update(base=base or '', head=head or '', policyVersion=POLICY_VERSION)
    return plan


def changed_paths(root, base, head):
    if not base or not head:
        raise RuntimeError('Missing diff identity; full battery required')
    return subprocess.check_output(['git', '-C', str(root), 'diff', '--no-renames', '--name-only', '-z',
                                    base + '...' + head], stderr=subprocess.DEVNULL).decode().strip('\0').split('\0')


def selection_for(paths, root):
    """GS1: the units the diff affects (gate_select). Anything it cannot decide, including a checkout whose
    registry predates the gate.* selection entries (KeyError), is the full battery: the selection never aborts a classification."""
    try:
        return gate_select.select(paths, root)
    except (OSError, subprocess.CalledProcessError, ValueError, KeyError):
        return gate_select.full('the selection could not be computed', paths)


def carry_plan(full, decision, head, root=ROOT):
    """GX-20 (P-42, D-B6): (delta plan, carried stages) for a carry decision of gate_carry, or None for a normal gate.
    The delta plan runs; every gate stage of the base...head plan it does not run is carried from the earlier proof,
    which must have passed each of them."""
    delta = select_dev_plan(decision['delta_files'], decision['from']['sha'], head, root)
    owned = set(DEV_STAGES) | {'script tests'}
    wanted = [stage for stage in full['stages'] if stage in owned]
    if delta['kind'] != 'scoped' or not set(wanted) <= set(decision['passed_stages']) | set(delta['stages']):
        return None
    carried = [stage for stage in wanted if stage not in delta['stages']]
    delta.update(carry={'from': decision['from'], 'delta_files': decision['delta_files'], 'stages': carried})
    return delta, carried


def identity(pr, repo=None):
    """Read the live PR identity through the selected forge (also used by gate-local)."""
    port = forge_events.ForgeEvents(forge_events.adapter_from_config(), forge_events.clock_from_config(),
                                    'gate-policy', f'pr-{pr}', consumer='scripts/lib/gate_policy.py')
    return port.change(repo or config.get('forge-events.repo'), int(pr))


@config.reading()
def classify_pr(pr, head, root=ROOT, repo=None, base=None, logs=None):
    if base is None:
        info = identity(pr, repo)
        if not info.get('base') or not info.get('head'):
            raise RuntimeError('gh: exit 0 (invalid-fields); missing PR diff identity')
        if info['head'] != head:
            raise RuntimeError('PR head changed while classifying; rerun on the new head')
        base = info['base']
    subprocess.run(['git', '-C', str(root), 'fetch', '-q', 'origin', base, head], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    paths = changed_paths(root, base, head)
    dev_plan = select_dev_plan(paths, base, head, root)
    selection = selection_for(paths, root)
    decision = gate_carry.load_decision()
    same = bool(decision) and (decision.get('sha'), decision.get('base')) == (head, base)
    carry = carry_plan(dev_plan, decision, head, root) if same else None
    if decision and carry is None:
        why = 'the earlier proof does not cover the base...head plan' if same else 'the decision is for another head or base'
        print(f'carry: normal gate ({why})', file=sys.stderr)
    if carry:
        dev_plan, carried = carry
        selection = selection_for(decision['delta_files'], root)
        if logs is not None:
            gate_carry.record(logs, decision, carried)
        print(f'carry: {len(carried)} stage(s) carried from {decision["from"]["sha"]}: {", ".join(carried)}', file=sys.stderr)
    # OU-DECOUPLE F5 (D-113): the database classification (`db`, `paths`) left with Open University's DB gate.
    return {'head': head, 'base': base, 'devPlan': dev_plan, 'selection': selection}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    p = sub.add_parser('classify'); p.add_argument('--pr', required=True); p.add_argument('--sha', required=True)
    p.add_argument('--base', help='base from this invocation’s fresh PR view (never a pass record)')
    p.add_argument('--repo'); p.add_argument('--output', type=Path)
    p = sub.add_parser('identity'); p.add_argument('--pr', required=True); p.add_argument('--repo')
    p.add_argument('--head-only', action='store_true')
    p = sub.add_parser('plan'); p.add_argument('mode', choices=list(PLANS))
    args = parser.parse_args()
    if args.action == 'identity':
        try:
            info = identity(args.pr, args.repo)
            print(info['head'] if args.head_only else f"{info['head']}\t{info['base']}")
        except (RuntimeError, KeyError) as error:
            print(str(error), file=sys.stderr); sys.exit(1)
    elif args.action == 'plan':
        print(json.dumps({'mode': args.mode, 'stages': PLANS[args.mode]}, indent=2))
    else:
        try:
            result = classify_pr(args.pr, args.sha, root=subject_root(), repo=args.repo, base=args.base,
                                 logs=args.output.parent if args.output else None)
            if args.output: args.output.write_text(json.dumps(result, indent=2))
            print(result['devPlan']['kind'])
        except RuntimeError as error:
            parser.exit(1, str(error) + '\nCannot classify actual PR diff; full battery required\n')
        except (OSError, subprocess.CalledProcessError, KeyError, ValueError):
            parser.exit(1, 'Cannot classify actual PR diff; full battery required\n')
