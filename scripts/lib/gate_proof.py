"""The verdict payload of one gate run (GX-39 seam, moved from gate_report.gate_events).

gate_report reads its settings and passes `subject`, `tier1_modes`, `step_prefix` and the expected stages in, with
`log_of(stage name)` for a stage's log text. GX-10 (D-070, GA-P01): this module owns the proof. `bind` runs at the
gate-local proof hook (gate-hooks/proof.sh) and fixes the inputs known there; `verdict_payload` adds the v4 fields when
`gate-proof.event_version` is 4 and the run is fully bound, else the payload stays v3 byte for byte; `version_of` tells
gate_report which contract version the payload is."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import gate_failures
import gate_tier

MS = 1000  # milliseconds per second


def stage_records(report, log_of):
    """One {name, result, duration_ms, class} per stage; a stage that did not pass carries its failure class."""
    from gate_classify import classify
    return [{'name': stage['name'], 'result': stage['result'], 'duration_ms': round(stage['seconds'] * MS),
             'class': None if stage['result'] == 'PASS' else classify(stage['name'], log_of(stage['name']))}
            for stage in report['stages']]


def step_events(port, subject, step_prefix, stages):
    """One engine.step.measured per stage (D-069 item 6)."""
    import forge_events
    return [port.build('engine.step.measured', forge_events.step_payload(
        subject, step_prefix + stage['name'], stage['duration_ms'], 'ok' if stage['result'] == 'PASS' else 'fail'))
        for stage in stages]


def verdict_payload(report, mode, subject, stages, expected, tier1_modes, logs, binding=None, version=None):
    """The payload of gate.passed / gate.failed: v3, plus the proof (v4) when the switch and the binding allow it."""
    sha = report['sha']
    inputs = json.dumps([sha, mode, expected], separators=(',', ':')).encode()
    verdict = dict(subject, tier=gate_tier.current(mode, tier1_modes), plan=mode,
                   stages=stages, missing_stages=report.get('missingStages', []) + [item['name'] for item in report.get('skippedStages', [])],
                   input_hash=hashlib.sha256(inputs).hexdigest())
    # GS1: which tests failed (id and signature) and which passed from the cache (key and source run).
    cached = gate_failures.cached_tests(logs)
    if cached:
        verdict['cached_tests'] = cached
    if report.get('known_defects'):
        verdict['known_defects'] = [{key: item[key] for key in ('id', 'stage', 'signature', 'base_sha', 'defect')}
                                    for item in report['known_defects']]
    if report['result'] != 'PASS':
        verdict['failing_tests'], verdict['failing_tests_total'] = gate_failures.failing(logs)
    version = event_version() if version is None else version
    binding = from_env() if binding is None else binding
    if version == proof_version():
        missing = unbound(binding, sha, mode, verdict['tier'])
        if missing:
            print(f'gate proof: v3 verdict ({missing})', file=sys.stderr)
        else:
            verdict = proof_payload(verdict, report, binding, logs)
    return verdict


# --- GX-10: the v4 proof ------------------------------------------------------------------------------------------
ENV = 'OU_GATE_PROOF'  # the binding of this run, JSON, exported by gate-hooks/proof.sh
PASS_FIELDS = ('head_tree', 'base_sha', 'gate_version', 'toolchain_id', 'input_digest')  # the .pass record extras


def event_version():
    import config
    return config.get('gate-proof.event_version')


def proof_version(kind='gate.passed'):
    """The first locked version of `kind` whose payload requires input_digest (v4), read from the contracts."""
    import event_contracts
    return min(version for version, name in event_contracts.catalog()[kind].items()
               if 'input_digest' in json.loads((event_contracts.directory() / name).read_text())['required'])


def version_of(payload):
    """The contract version of a verdict payload: v4 when it carries the proof, else None (the registry default, v3)."""
    return proof_version() if 'input_digest' in payload else None


def sha256(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def selection_digest(plan, batch=None):
    """sha256 of the selection request: the plan and a batch plan's selection (null for a PR gate). With head tree,
    base and gate version (all in input_digest) it fixes the scoped plan the gate derives, so it is known at the hook."""
    return sha256({'plan': plan, 'batch': batch})


STAT_FIELDS = ('state', 'ppid', 'pgrp', 'session', 'tty_nr', 'tpgid', 'flags', 'minflt', 'cminflt', 'majflt',
               'cmajflt', 'utime', 'stime', 'cutime', 'cstime')  # proc(5) after the command name
CPU_FIELDS = ('utime', 'stime', 'cutime', 'cstime')  # the driver and every child it waited for


def cpu_ticks(pid):
    """utime + stime + cutime + cstime of `pid` (gate-proof.cpu_stat_path, proc(5)), or None off Linux."""
    import config
    try:
        text = Path(config.get('gate-proof.cpu_stat_path').format(pid=pid)).read_text()
        fields = dict(zip(STAT_FIELDS, text.rsplit(')', 1)[1].split()))
        return sum(int(fields[name]) for name in CPU_FIELDS)
    except (OSError, IndexError, ValueError):
        return None


def git(root, *args):
    return subprocess.run(['git', '-C', str(root), *args], capture_output=True, text=True, check=True).stdout.strip()


def tree(root, sha):
    return git(root, 'rev-parse', f'{sha}^{{tree}}')


def gate_version(tool_root):
    """gate_pin.gate_version's recipe: the tree id of scripts/ at the tooling commit (the base tip's under the pin)."""
    return git(tool_root, 'rev-parse', 'HEAD:scripts')


def lane(root, base, sha):
    """GX-04's lane of the change (pr_ready.lane_of); None when several lanes, no unit, or it cannot be read."""
    try:
        import pr_ready
        return pr_ready.lane_of(root, base, sha)
    except Exception:  # noqa: BLE001 - the lane is advisory in the proof; the train's ownership check still judges
        return None


def bind(src_root, tool_root, sha, base, plan, batch=None, started_ms=None, pid=None, toolchain_id=None):
    """The proof inputs known at the proof hook. Raises ValueError when the run cannot be bound (no sha or base) and
    RuntimeError when the toolchain cannot be attested. toolchain_id and observed_versions are gate_keys' attestation
    (GX-28: installed versions + effective registry, never install.stamp), so the proof and the cache keys agree."""
    import gate_digest
    if not (sha and base):
        raise ValueError('no commit or no recorded base')
    observed = None
    if toolchain_id is None:
        import gate_keys
        try:
            attested = gate_keys.attestation()  # the same attestation the cache keys carry (GX-28)
        except Exception as error:  # noqa: BLE001 - an unattested toolchain is never bound into a proof
            raise RuntimeError(f'toolchain not attested ({error})') from error
        toolchain_id, observed = attested['toolchain_id'], attested['observed_versions']
    head_tree, version, selection = tree(src_root, sha), gate_version(tool_root), selection_digest(plan, batch)
    now = int(time.time() * MS)
    return {'sha': sha, 'plan': plan, 'head_tree': head_tree, 'base_sha': base, 'base_tree': tree(src_root, base),
            'gate_version': version, 'toolchain_id': toolchain_id, 'observed_versions': observed,
            'selection_digest': selection,
            'input_digest': gate_digest.input_digest(head_tree, base, plan, selection, toolchain_id, version),
            'lane_id': lane(src_root, base, sha), 'started_ms': started_ms if started_ms is not None else now,
            'bound_ms': now, 'pid': pid, 'cpu_ticks': cpu_ticks(pid) if pid else None}


def pass_extra(binding):
    """The .pass record lines (key=value) of a binding."""
    return '\n'.join(f'{key}={binding[key]}' for key in PASS_FIELDS)


def from_env(environ=None):
    text = (environ if environ is not None else os.environ).get(ENV, '')
    try:
        return json.loads(text) if text else None
    except ValueError:
        return None


def unbound(binding, sha, plan, tier):
    """Why this verdict cannot carry the v4 proof, or '' when it can."""
    if not binding:
        return 'the run has no proof binding (no commit or no recorded base)'
    if binding.get('sha') != sha or binding.get('plan') != plan:
        return f'the binding is for {binding.get("sha")} {binding.get("plan")}, not {sha} {plan}'
    if tier is None:
        return 'the plan has no tier (GX-11 makes it explicit)'
    return ''


def selection(logs, digest):
    """{kind, units, tests, digest}: what the gate selected (logs/selection.json, written by classification)."""
    try:
        data = json.loads((Path(logs) / 'selection.json').read_text())
    except (OSError, ValueError, TypeError):
        data = {}
    data = data if isinstance(data, dict) else {}
    kind = data.get('kind')
    found = {'kind': kind if isinstance(kind, str) and kind else 'full', 'digest': digest}
    for key in ('units', 'tests'):
        items = data.get(key)
        if isinstance(items, list) and all(isinstance(item, str) and item for item in items):
            found[key] = items
    return found


def cost(report, binding, logs, cached_tests, now_ms):
    # rest_calls stays in gate.*.v4 and is 0: the gate counts no forge REST call since the GitHub client left (D-293)
    ticks, start = cpu_ticks(binding['pid']) if binding.get('pid') else None, binding.get('cpu_ticks')
    cpu = max(0, ticks - start) / os.sysconf('SC_CLK_TCK') if ticks is not None and start is not None else 0.0
    cached = sum(1 for stage in report['stages'] if stage.get('cached'))
    return {'wall_s': max(0, now_ms - binding['started_ms']) / MS, 'cpu_s': cpu,
            'rest_calls': 0, 'queue_wait_s': max(0, binding['bound_ms'] - binding['started_ms']) / MS,
            'cache_hits': cached + len(cached_tests), 'cache_misses': len(report['stages']) - cached}


def started_at(seconds):
    from datetime import datetime, timezone
    import forge_events
    return forge_events.rfc3339(datetime.fromtimestamp(seconds, timezone.utc))


def proof_stages(verdict, report, digest):
    """v4 stages: v3's plus started_at, cached and inputs_digest (the whole input until GX-23 declares stage inputs)."""
    raw = {stage['name']: stage for stage in report['stages']}
    stages = []
    for stage in verdict['stages']:
        item = dict(stage, cached=bool(raw.get(stage['name'], {}).get('cached')),
                    inputs_digest=sha256([digest, stage['name']]))
        if isinstance(raw.get(stage['name'], {}).get('started_at'), (int, float)):
            item['started_at'] = started_at(raw[stage['name']]['started_at'])
        stages.append(item)
    return stages


def proof_payload(verdict, report, binding, logs, now_ms=None):
    """The v4 payload: the v3 verdict plus the proof binding, selection, cost and lane (GA2 §6)."""
    now_ms = int(time.time() * MS) if now_ms is None else now_ms
    payload = dict(verdict, stages=proof_stages(verdict, report, binding['input_digest']))
    payload.update({key: binding[key] for key in ('head_tree', 'base_sha', 'base_tree', 'gate_version', 'toolchain_id',
                                                  'input_digest', 'lane_id')})
    if binding.get('observed_versions'):
        payload['observed_versions'] = binding['observed_versions']
    payload['selection'] = selection(logs, binding['selection_digest'])
    payload['cost'] = cost(report, binding, logs, verdict.get('cached_tests', []), now_ms)
    return payload


def main(argv):
    """gate_proof.py bind --src-root R --tool-root T --sha S --base B --plan P [--batch-file F] [--started-ms N] [--pid N]:
    prints the binding (one JSON line) and then the .pass extras; exits 1 with the reason when the run cannot be bound."""
    import argparse
    parser = argparse.ArgumentParser(prog='gate_proof.py')
    parser.add_argument('command', choices=['bind'])
    for name in ('--src-root', '--tool-root', '--sha', '--base', '--plan'):
        parser.add_argument(name, required=True)
    parser.add_argument('--batch-file', default='')
    parser.add_argument('--started-ms', type=int)
    parser.add_argument('--pid', type=int)
    parser.add_argument('--key-parts-file', type=Path, help='write this binding process\'s result-key snapshot')
    args = parser.parse_args(argv)
    try:
        batch = json.loads(Path(args.batch_file).read_text()).get('selection') if args.batch_file else None
        binding = bind(args.src_root, args.tool_root, args.sha, args.base, args.plan, batch, args.started_ms, args.pid)
        if args.key_parts_file:
            import gate_keys
            args.key_parts_file.write_text(gate_keys.snapshot())
    except (ValueError, OSError, subprocess.CalledProcessError, RuntimeError) as error:
        print(f'gate proof: not bound ({error})', file=sys.stderr)
        return 1
    print(json.dumps(binding, sort_keys=True, separators=(',', ':')))
    print(pass_extra(binding))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
