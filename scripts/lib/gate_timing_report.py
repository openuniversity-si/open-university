#!/usr/bin/env python3
"""Per-stage quantiles of the gate and the error of its ETA (GX-25; the idea of GS2's timing report, over the ledger).

Sources: `--ledger` (the event log through the forge_events port: engine.step.measured for `gate:` steps and
gate.started / gate.passed / gate.failed), `--events FILE` (a JSON list of envelopes), or `--logs DIR...` (gate log dirs
with `*.stage.json`). Quantiles are gate-eta.report_quantiles; the ETA error is over the newest gate-eta.report_last_gates
gates that have both a gate.started and a verdict: real wall time (verdict.occurred_at - started.occurred_at) minus
expected_wall_s.

  gate_timing_report.py [--ledger | --events FILE | --logs DIR ...] [--last N] [--json]
"""
import argparse
from datetime import datetime, timedelta
import json
import math
from pathlib import Path
import sys

import config

VERDICTS = ('gate.passed', 'gate.failed')


def percentile(values, q):
    """Nearest rank, q a fraction: the ceil(q * n)-th smallest value; None for no values."""
    ordered = sorted(values)
    if not ordered:
        return None
    return ordered[max(1, math.ceil(q * len(ordered))) - 1]


def quantiles():
    """{label: fraction} from gate-eta.report_quantiles (0.9 -> p90), rising."""
    return {'p' + format(q, '.0%').rstrip('%'): q for q in sorted(config.get('gate-eta.report_quantiles'))}


def critical_path(durations, needs, names=None):
    """(seconds, [stage, ...]): the longest path by duration through `needs`, over `names` (default: every duration).
    A stage with no duration counts 0; a need outside `names` is taken as met. The wall of a gate is this, not the sum."""
    names = list(durations if names is None else names)
    wanted, memo = set(names), {}

    def finish(name):
        if name not in memo:
            memo[name] = (0, [])  # a cycle (the graph check refuses one) ends here instead of recursing
            total, path = max((finish(need) for need in needs.get(name, []) if need in wanted),
                              key=lambda item: item[0], default=(0, []))
            memo[name] = (total + durations.get(name, 0), path + [name])
        return memo[name]

    return max((finish(name) for name in names), key=lambda item: item[0], default=(0, []))


def moment(event):
    return datetime.fromisoformat(event['occurred_at'].replace('Z', '+00:00'))


def stage_samples(events):
    """{stage: [seconds, ...]} in time order from engine.step.measured steps named gate:<stage>."""
    import forge_events
    prefix = config.get('forge-events.gate_step_prefix')
    found = {}
    for event in sorted(forge_events.dedupe(events)[0], key=moment):
        step = (event.get('payload') or {}).get('step', '')
        if event['type'] == 'engine.step.measured' and step.startswith(prefix):
            found.setdefault(step[len(prefix):], []).append(timedelta(milliseconds=event['payload']['duration_ms']).total_seconds())
    return found


def stage_samples_from_logs(dirs):
    found = {}
    for directory in map(Path, dirs):
        for path in sorted(directory.glob('*.stage.json')):
            data = json.loads(path.read_text())
            found.setdefault(data['name'], []).append(float(data['seconds']))
    return found


def eta_errors(events, last):
    """[{pr, sha, plan, expected_s, wall_s, error_s}] for the newest `last` gates with a gate.started and its verdict."""
    started, rows = {}, []
    for event in sorted(events, key=moment):
        payload = event['payload']
        pr, sha, plan = payload.get('pr'), payload.get('sha'), payload.get('plan')
        key = (pr, sha, plan)
        if event['type'] == 'gate.started':
            started.setdefault(key, event)
        elif event['type'] in VERDICTS and key in started:
            begin = started.pop(key)
            wall = (moment(event) - moment(begin)).total_seconds()
            expected = float(begin['payload']['expected_wall_s'])
            rows.append({'pr': pr, 'sha': sha, 'plan': plan, 'expected_s': expected, 'wall_s': wall,
                         'error_s': wall - expected})
    return rows[-last:] if last > 0 else []


def report(samples, errors, needs, qs=None):
    qs = qs or quantiles()
    stages = {name: {**{label: percentile(values, q) for label, q in qs.items()}, 'n': len(values)}
              for name, values in sorted(samples.items())}
    top = list(qs)[-1]
    seconds, path = critical_path({name: row[top] or 0 for name, row in stages.items()}, needs)
    absolute = [abs(row['error_s']) for row in errors]
    return {'quantiles': list(qs), 'stages': stages, 'critical_path': path, 'critical_path_s': seconds,
            'eta': {'gates': len(errors), 'mean_abs_error_s': sum(absolute) / len(absolute) if absolute else None,
                    'median_abs_error_s': percentile(absolute, config.get('gate-eta.eta_quantile')), 'rows': errors}}


def _fmt(value):
    return '-' if value is None else f'{value:.1f}'


def render(data):
    """Tab-separated: stage rows (slowest first), the critical path, then the ETA error per gate and its summary."""
    labels = data['quantiles']
    top = labels[-1]
    lines = ['\t'.join(['stage', *labels, 'n'])]
    for name, row in sorted(data['stages'].items(), key=lambda item: -(item[1][top] or 0)):
        lines.append('\t'.join([name, *(_fmt(row[label]) for label in labels), str(row['n'])]))
    lines.append(f'critical path ({top}): ' + ' > '.join(data['critical_path']) + f' = {_fmt(data["critical_path_s"])} s')
    eta = data['eta']
    lines.append(f'ETA error over {eta["gates"]} gate(s): mean |error| {_fmt(eta["mean_abs_error_s"])} s, '
                 f'median |error| {_fmt(eta["median_abs_error_s"])} s')
    lines += ['\t'.join(['pr', 'sha', 'plan', 'expected_s', 'wall_s', 'error_s'])]
    lines += ['\t'.join([str(row['pr']), str(row['sha'])[:config.get('gate.status_sha_chars')], str(row['plan']), _fmt(row['expected_s']),
                         _fmt(row['wall_s']), _fmt(row['error_s'])]) for row in eta['rows']]
    return '\n'.join(lines)


def stage_needs(path=None):
    import gate_graph
    return {name: list(spec.get('needs') or []) for name, spec in gate_graph.load(*([path] if path else [])).items()}


def ledger_events():
    import gate_eta
    import forge_events
    return gate_eta.collect(forge_events.adapter_from_config(), config.get('forge-events.repo'))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    source = parser.add_mutually_exclusive_group()
    source.add_argument('--ledger', action='store_true')
    source.add_argument('--events', metavar='FILE')
    source.add_argument('--logs', nargs='+', metavar='DIR')
    parser.add_argument('--last', type=int, default=None)
    parser.add_argument('--stages-file')
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args(argv)
    last = args.last if args.last is not None else config.get('gate-eta.report_last_gates')
    if args.logs:
        samples, errors = stage_samples_from_logs(args.logs), []
    else:
        events = json.loads(Path(args.events).read_text()) if args.events else ledger_events()
        samples, errors = stage_samples(events), eta_errors(events, last)
    data = report(samples, errors, stage_needs(args.stages_file))
    print(json.dumps(data, indent=1) if args.json else render(data))
    return 0


if __name__ == '__main__':
    sys.exit(main())
