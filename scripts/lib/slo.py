"""Service level objectives folded from the event log (D-069 item 6; plan v3.1 O1).

The reader replays the log through the forge_events port only (D-069 item 7) and is a pure function of it: the same
events and the same settings give the same values (D-069 item 4). Every limit, window and name comes from
config/registry/slo.json; tests pass explicit overrides. It runs on an event (the producer of pr.merged or gate.*, or
the maestro), never on a clock (P-32). When a value is outside its entry it emits slo.breached, keyed by the newest
event the value rests on, so replaying a log never emits twice. fold() and percentile() are reusable by B1.

  slo.py evaluate [--pr N ...]     emit slo.breached for every SLO outside its entry
  slo.py show [--pr N ...]         print the values as JSON, emit nothing
  slo.py dashboard [--pr N ...] [--out PATH]   write the Markdown dashboard (scripts/dashboard)
"""
import argparse
from datetime import datetime, timedelta
import json
from pathlib import Path
import subprocess
import sys

import config
import forge_events
from gate_eta import as_percent, collect, expected_seconds, ledger_steps, moment, ordered, percentile, step_stats  # noqa: F401 - the gate owns them (D-322)
import gate_verdicts

ROOT = Path(__file__).resolve().parents[2]
NAMES = ('slo.train_queue_time_p95_s', 'slo.merged_prs_per_hour_min',
         'slo.gate_failure_rate_max_percent', 'slo.merged_window_s', 'slo.merged_hold_s', 'slo.percentile',
         'slo.sample_window_events', 'slo.min_samples', 'slo.producer', 'slo.step', 'slo.dashboard_path')
INPUTS = gate_verdicts.TYPES + ('pr.ready', 'pr.merged')


def settings(overrides=None):
    """The registry values the reader needs, with explicit overrides (tests) applied on top."""
    overrides = overrides or {}
    values = {name: overrides[name] if name in overrides else config.get(name) for name in NAMES}
    values.update(overrides)
    return values


def fold(events):
    """Series from the log: tier-1 gate verdicts, queue times, merges, and the span of the inputs."""
    tier1, queue, merges, ready, seen = [], [], [], {}, set()
    inputs = [event for event in gate_verdicts.accepted(ordered(events)) if event['type'] in INPUTS]
    for event in inputs:
        payload, at, kind = event['payload'], moment(event), event['type']
        if kind in gate_verdicts.TYPES and payload['tier'] == 1:
            seconds = sum(stage['duration_ms'] for stage in payload['stages']) / 1000
            tier1.append({'at': at, 'value': seconds, 'passed': kind == 'gate.passed', 'event_id': event['event_id']})
        elif kind == 'pr.ready':
            ready.setdefault((payload['pr'], payload['sha']), at)
        elif kind == 'pr.merged' and (payload['pr'], payload['sha']) not in seen:
            seen.add((payload['pr'], payload['sha']))
            merges.append({'at': at, 'event_id': event['event_id']})
            if (payload['pr'], payload['sha']) in ready:
                queue.append({'at': at, 'value': (at - ready[(payload['pr'], payload['sha'])]).total_seconds(),
                              'event_id': event['event_id']})
    span = (moment(inputs[0]), moment(inputs[-1]), inputs[-1]['event_id']) if inputs else None
    return {'tier1': tier1, 'queue': queue, 'merges': merges, 'span': span}


def result(name, bound, limit, value, samples, evidence, enough):
    if not enough:
        state = 'no_data'
    else:
        state = 'breached' if (value > limit if bound == 'max' else value < limit) else 'ok'
    return {'slo': name, 'bound': bound, 'limit': limit, 'value': value if enough else None, 'samples': samples,
            'state': state, 'evidence': evidence}


def throughput(series, conf):
    """Fewest merges in any slo.merged_window_s window ending at a merge of the last slo.merged_hold_s, or None
    when the log does not yet cover the hold plus one window."""
    if series['span'] is None:
        return None, 0
    first, last, _ = series['span']
    window, hold = timedelta(seconds=conf['slo.merged_window_s']), timedelta(seconds=conf['slo.merged_hold_s'])
    if last - first < hold + window:
        return None, 0
    instants = [last] + [merge['at'] for merge in series['merges'] if merge['at'] >= last - hold]
    counts = [sum(t - window <= merge['at'] <= t for merge in series['merges']) for t in instants]
    return min(counts), len(instants)


def evaluate(events, conf=None):
    """The active SLO results (slo, bound, limit, value, samples, state ok|breached|no_data, evidence)."""
    return evaluate_series(fold(events), conf)


def evaluate_series(series, conf=None):
    """The active SLO results of series shaped as fold() makes them (tier1, queue, merges, span), whatever their
    source: the event log here, GitHub's pull requests and check runs in runs.slo_series (scripts/model). The
    Origin-era tier-1 duration SLO was retired by D-351 (REQ-gate-60s is the canonical gate ceiling)."""
    conf = conf or settings()
    window, floor, percent = conf['slo.sample_window_events'], conf['slo.min_samples'], conf['slo.percentile']
    newest = series['span'][2] if series['span'] else None
    results = []
    tier1 = series['tier1'][-window:]
    queue = series['queue'][-window:]
    results.append(result('slo.train_queue_time_p95_s', 'max', conf['slo.train_queue_time_p95_s'],
                          percentile([s['value'] for s in queue], percent) if queue else 0, len(queue),
                          queue[-1]['event_id'] if queue else newest, len(queue) >= floor))
    pace, instants = throughput(series, conf)
    results.append(result('slo.merged_prs_per_hour_min', 'min', conf['slo.merged_prs_per_hour_min'], pace or 0,
                          instants, newest, pace is not None))
    rate = as_percent(sum(not s['passed'] for s in tier1) / len(tier1)) if tier1 else 0
    results.append(result('slo.gate_failure_rate_max_percent', 'max', conf['slo.gate_failure_rate_max_percent'], rate,
                          len(tier1), tier1[-1]['event_id'] if tier1 else newest, len(tier1) >= floor))
    return results


def breach_payload(repo, item):
    fields = {key: item[key] for key in ('slo', 'value', 'limit', 'bound', 'samples', 'evidence')}
    return dict(forge_events.subject(repo, None, None), **fields)


def run(adapter, clock, repo, prs=(), overrides=None, events=None):
    """Evaluate the log and emit slo.breached for each SLO outside its entry, measured as one engine step.

    The correlation id is the newest input event, so a rerun on an unchanged log appends nothing. Returns the results.
    """
    conf = settings(overrides)
    events = collect(adapter, repo, prs) if events is None else events  # GX-25: a caller that already collected passes the log
    results = evaluate(events, conf)
    span = fold(events)['span']
    if span is None:
        return results
    port = forge_events.ForgeEvents(adapter, clock, conf['slo.producer'], span[2])
    with port.batched(), forge_events.measured(port, conf['slo.step'], forge_events.subject(repo, None, None)) as step:
        for item in results:
            if item['state'] == 'breached':
                port.emit('slo.breached', breach_payload(repo, item))
                step.result = 'blocked'
    return results


def cell(value):
    return '-' if value is None else f'{value:g}' if isinstance(value, float) else str(value)


def render(results, steps, span, conf):
    """The dashboard as Markdown: each SLO with its value, its registry entry and its state, then the steps."""
    lines = ['# Engine SLOs', '',
             'Generated from the event log by scripts/dashboard. Do not commit it; the entries live in '
             'config/registry/slo.json.', '']
    lines.append('Log inputs: ' + (f'{span[0].isoformat()} to {span[1].isoformat()}' if span else 'none'))
    lines += ['', '| SLO | Value | Entry | Samples | State |', '|---|---|---|---|---|']
    for item in results:
        sign = '<=' if item['bound'] == 'max' else '>='
        lines.append(f"| `{item['slo']}` | {cell(item['value'])} | {sign} {cell(item['limit'])} | "
                     f"{item['samples']} | {item['state']} |")
    lines += ['', f"Engine steps (p{conf['slo.percentile']} duration):", '',
              '| Step | Runs | Failed | Retries | Duration (ms) |', '|---|---|---|---|---|']
    for step, stats in steps.items():
        lines.append(f"| `{step}` | {stats['runs']} | {stats['failed']} | {stats['retries']} | {stats['duration_ms']} |")
    return '\n'.join(lines) + '\n'


def dashboard(adapter, repo, prs=(), overrides=None, out=None):
    """Write the Markdown dashboard; refuses a path git does not ignore, so a PR never commits it (P-10)."""
    conf = settings(overrides)
    target = ROOT / (out or conf['slo.dashboard_path'])
    if subprocess.run(['git', '-C', str(ROOT), 'check-ignore', '-q', str(target)]).returncode != 0:
        raise SystemExit(f'slo: {target} is not gitignored; the dashboard is never committed (P-10)')
    events = collect(adapter, repo, prs)
    text = render(evaluate(events, conf), step_stats(events, conf['slo.percentile']), fold(events)['span'], conf)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding='utf-8')
    return target


def main(argv=None):
    parser = argparse.ArgumentParser(prog='slo.py')
    parser.add_argument('command', choices=('evaluate', 'show', 'dashboard'))
    parser.add_argument('--pr', type=int, action='append', default=[])
    parser.add_argument('--out')
    args = parser.parse_args(argv)
    repo, adapter = config.get('forge-events.repo'), forge_events.adapter_from_config()
    if args.command == 'dashboard':
        print(dashboard(adapter, repo, args.pr, out=args.out))
        return 0
    if args.command == 'show':
        results = evaluate(collect(adapter, repo, args.pr))
    else:
        results = run(adapter, forge_events.clock_from_config(), repo, args.pr)
    print(json.dumps(results, indent=2, sort_keys=True))
    return 1 if any(item['state'] == 'breached' for item in results) else 0


if __name__ == '__main__':
    sys.exit(main())
