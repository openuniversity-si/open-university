"""GX-26 (D-070, P-46): say what a dev gate WOULD do (`explain`) and why a red one failed (`why`). Runs no stage, writes nothing.

  gate_explain.py explain --pr N [--root R] [--head SHA --base SHA]
      the plan, the selection, the stages carried from an earlier proof, the script tests and which of them a cache
      marker already covers, the expected wall, the completeness of the plan and the preflight result. It reads the
      same code the gate does (gate_policy, gate_carry, gate_script_tests, gate_test_cache, preflight); with --head and
      --base it makes no GitHub call.
  gate_explain.py why <report dir> | --latest [--root R]
      the first failing stage or test, its class (gate_classify), the log path and the base status.

"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

import config  # noqa: E402
import preflight  # noqa: E402

CONSUMER = 'scripts/lib/gate_explain.py'  # this module's demand on the forge port


def sha(value):
    return value[:config.get('gate.status_sha_chars', ROOT)]


def clip(text):
    return str(text).strip()[:config.get('gate.explain_clip_chars', ROOT)]


def forge_port(pr):
    """The forge port identity reads the change through (ORIGIN-FINISH): the configured adapter, this consumer."""
    import forge_events  # --head and --base make no forge call and never load the port
    return forge_events.ForgeEvents(forge_events.adapter_from_config(), forge_events.clock_from_config(),
                                    'gate-explain', f'pr-{pr}', consumer=CONSUMER)


def identity(pr, root, head=None, base=None, port=None):
    """(head, base) of the PR: the arguments, else the same change gate-local reads through the forge port."""
    if head and base:
        return head, base
    try:
        change = (port or forge_port(pr)).change(config.get('forge-events.repo', ROOT), int(pr))
    except (RuntimeError, OSError, ValueError, KeyError) as error:  # the port's, its adapter's and config's errors
        raise RuntimeError(f'cannot read PR #{pr}: {clip(error) or type(error).__name__}') from None
    found = change if isinstance(change, dict) else {}
    if not (found.get('head') and found.get('base')):
        raise RuntimeError(f'cannot read PR #{pr}: the forge returned no head and base')
    return found['head'], found['base']


def binding_for(root, head, base):
    """The proof binding of a run on this head (what gate-hooks/proof.sh exports), or None when it cannot be built."""
    import gate_proof
    started = ROOT / 'scripts/lib/gate_proof.py'
    bound = subprocess.run([sys.executable, str(started), 'bind', '--src-root', str(root), '--tool-root', str(ROOT),
                            '--sha', head, '--base', base, '--plan', 'dev', '--batch-file', '', '--started-ms', '0',
                            '--pid', str(os.getpid())], capture_output=True, text=True)
    if bound.returncode:
        return None
    try:
        found = json.loads(bound.stdout.split('\n', 1)[0])
    except ValueError:
        return None
    return found if isinstance(found, dict) and gate_proof else None


def carry_for(pr, root, head, base, full):
    """(delta plan, carried stages, reason) from gate_carry, exactly as the plan hook and classify_pr decide it."""
    import gate_carry
    import gate_policy
    try:
        enabled, areas = gate_carry.settings()
        binding = binding_for(root, head, base)
        if not enabled or not binding:
            return None, [], 'normal gate (carry off or no proof binding)'
        decision = gate_carry.decide(gate_carry.read_events(pr), binding, root, enabled, areas)
    except Exception as error:  # noqa: BLE001 - the explanation never fails: a carry that cannot be decided is a normal gate
        return None, [], f'normal gate (cannot decide: {clip(error)})'
    if not decision['carry']:
        return None, [], f'normal gate ({decision["reason"]})'
    carried = gate_policy.carry_plan(full, decision, head, root)
    if carried is None:
        return None, [], 'normal gate (the earlier proof does not cover the base...head plan)'
    plan, stages = carried
    return plan, stages, f'{decision["reason"]}; from {sha(decision["from"]["sha"])}'


def cache_predictions(scripts, root):
    """{script: 'hit' | 'miss' | 'run'} from the markers the gate itself would read."""
    import gate_script_tests
    import gate_test_cache
    mapping = gate_script_tests.load(root)
    location = gate_test_cache.store_location()
    hashes, out = {}, {}
    for script in scripts:
        key = gate_test_cache.key(script, root, mapping, hashes=hashes)
        out[script] = 'run (no key)' if not key else ('hit' if gate_test_cache.lookup(location, key) else 'miss')
    return out


def explain(pr, root, head=None, base=None):
    import gate_policy
    import gate_script_tests
    import preflight
    head, base = identity(pr, root, head, base)
    paths = [path for path in gate_policy.changed_paths(root, base, head) if path]
    full = gate_policy.select_dev_plan(paths, base, head, root)
    plan, carried, carry_reason = carry_for(pr, root, head, base, full)
    running = plan or full
    owned = set(gate_policy.DEV_STAGES) | {'script tests'}
    stages = [stage for stage in running['stages'] if stage in owned]
    selection = gate_policy.selection_for(plan['carry']['delta_files'] if plan else paths, root)
    lines = [f'gate-dev --explain: PR #{pr} head {sha(head)} base {sha(base)} ({len(paths)} changed path(s)); nothing is run',
             f'plan: {full["kind"]} ({full.get("reason", "")})',
             f'carried: {len(carried)} stage(s) ({carry_reason})' + (': ' + ', '.join(carried) if carried else ''),
             f'runs: {len(stages)} stage(s): ' + (', '.join(stages) or 'none'),
             f'selection: {selection.get("kind", "full")} ({selection.get("reason", "")})']
    if 'script tests' in stages:
        chosen, why = gate_script_tests.select_plan(running)
        predicted = cache_predictions(chosen, root)
        hits = sorted(script for script, state in predicted.items() if state == 'hit')
        lines.append(f'script tests: {len(chosen)} selected ({why}); predicted cache hits: {len(hits)} of {len(chosen)}')
    else:
        lines.append('script tests: none selected')
    lines += [f'ceiling: {config.get("gate.ceiling_s", ROOT)} s (warning only, D-064 (f))']
    gaps = preflight.gate_problems()
    lines.append('preflight: ' + ('ok' if not gaps else f'{len(gaps)} gap(s): ' + '; '.join(gaps)))
    return '\n'.join(lines)


def latest(root):
    reports = sorted((Path(root) / '.gate/records/reports').glob('*/*'), key=lambda path: path.stat().st_mtime)
    return reports[-1] if reports else None


def why(logs):
    import gate_classify
    import gate_report
    logs = Path(logs)
    if not logs.is_dir():  # GATE-GC-CHEIO: a run the folder bound removed is gone, not unfinished
        return (f'gate-dev --why: {logs} is gone; the report folder keeps the newest '
                f'{config.get("gate-gc.reports_shas_keep", ROOT)} shas (gate-gc.reports_shas_keep); '
                'rerun the gate on that sha to rebuild its report')
    try:
        report = json.loads((logs / 'stages.json').read_text())
    except (OSError, ValueError):
        return f'gate-dev --why: no stages.json in {logs} (the run did not reach its report)'
    if report.get('result') == 'PASS':
        return f'gate-dev --why: {logs} passed; nothing failed'
    failed = [stage for stage in report.get('stages', []) if stage.get('result') == 'FAIL']
    lines = [f'gate-dev --why: {report.get("result")} for {sha(str(report.get("sha", "")))}; reports {logs}']
    if report.get('aborted'):
        lines.append(f'aborted: {report["aborted"]}')
    for stage in failed[:1]:
        name = stage['name']
        slug_log = logs / (gate_classify_slug(name) + '.log')
        lines += [f'failing stage: {name} (exit {stage.get("exit")})',
                  f'class: {gate_classify.classify(name, gate_report.stage_log(logs, name))}',
                  f'log: {slug_log}']
    tests = []
    try:
        tests = [item['test'] for item in json.loads((logs / 'script-tests.json').read_text()) if item['result'] == 'FAIL']
    except (OSError, ValueError, KeyError, TypeError):
        pass
    for item in (report.get('failingTests') or [])[:config.get('gate.explain_list_max', ROOT)]:
        lines.append(f'failing test: {item}')
    for test in tests[:config.get('gate.explain_list_max', ROOT)]:
        lines.append(f'failing script test: {test}')
    return '\n'.join(lines)


def gate_classify_slug(name):
    import gate_carry
    return gate_carry.stage_slug(name)


def main(argv):
    parser = argparse.ArgumentParser(prog='gate_explain.py', description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest='command', required=True)
    one = sub.add_parser('explain')
    one.add_argument('--pr', type=int, required=True)
    one.add_argument('--root', default=str(ROOT))
    one.add_argument('--head')
    one.add_argument('--base')
    two = sub.add_parser('why')
    two.add_argument('logs', nargs='?')
    two.add_argument('--latest', action='store_true')
    two.add_argument('--root', default=str(ROOT))
    args = parser.parse_args(argv)
    try:
        if args.command == 'explain':
            print(explain(args.pr, Path(args.root), args.head, args.base))
        else:
            logs = Path(args.logs) if args.logs else latest(args.root)
            print(why(logs) if logs else 'gate-dev --why: no report under .gate/records/reports')
    except (RuntimeError, OSError, subprocess.CalledProcessError) as error:
        print(f'gate-dev --{args.command}: {error}', file=sys.stderr)
        return preflight.SETUP_EXIT
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
