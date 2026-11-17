"""The gate's duration estimate (GX-25), read from the event log: the ledger of measured steps, the quantile of each
stage's newest durations, and the log window the gate's verdict hooks read. The gate owns it; measurement (slo)
reads the same functions from here, so the gate never depends on measurement (D-322, PADRAO-DEV F8: the layer break of
gate_status and slo).
"""
from datetime import datetime, timedelta
import json
from pathlib import Path

import config
import forge_events


def moment(event):
    return datetime.fromisoformat(event['occurred_at'].replace('Z', '+00:00'))


def as_percent(fraction):
    """GX-25: 0.5 -> 50, the unit percentile() takes."""
    return fraction * 100


def percentile(values, percent):
    """Nearest rank: the smallest sample with at least `percent` percent of the samples at or below it."""
    ordered = sorted(values)
    rank = int(-(-percent * len(ordered) // 100))  # GX-25: a fractional percent (an ETA quantile) is a valid rank
    return ordered[max(rank, 1) - 1]


def ordered(events):
    """Deduplicated events in time order (ties keep log order): the only order the fold depends on."""
    unique = forge_events.dedupe(events)[0]
    return [event for _, event in sorted(enumerate(unique), key=lambda pair: (moment(pair[1]), pair[0]))]


def step_stats(events, percent):
    """Per engine step: runs, failures and the percentile duration, from engine.step.measured."""
    by_step = {}
    for event in ordered(events):
        if event['type'] == 'engine.step.measured':
            by_step.setdefault(event['payload']['step'], []).append(event['payload'])
    return {step: {'runs': len(items), 'failed': sum(item['result'] == 'fail' for item in items),
                   'retries': sum(item['retries'] for item in items),
                   'duration_ms': percentile([item['duration_ms'] for item in items], percent)}
            for step, items in sorted(by_step.items())}


def expected_seconds(events, names, quantile, window, fallback_s, local=None):
    """GX-25: {stage: {'seconds', 'source'}} for the ETA of a gate that plans `names`.

    Per stage, in order: the `quantile` (a fraction, gate-eta.eta_quantile) of its newest `window` engine.step.measured
    durations in the ledger (step_stats); else the `local` box history ({stage: seconds}); else `fallback_s`
    (gate-eta.fallback_stage_s). So a fresh container with an empty ledger still has an ETA."""
    prefix, local = config.get('forge-events.gate_step_prefix'), local or {}
    steps = {prefix + name: name for name in names}
    seen, newest = {}, []
    for event in reversed(ordered(events)):  # newest first: keep `window` per step
        step = event['payload'].get('step') if event['type'] == 'engine.step.measured' else None
        if step in steps and seen.get(step, 0) < window:
            seen[step] = seen.get(step, 0) + 1
            newest.append(event)
    stats = step_stats(newest, as_percent(quantile))
    found = {}
    for name in names:
        row = stats.get(prefix + name)
        if row:
            found[name] = {'seconds': timedelta(milliseconds=row['duration_ms']).total_seconds(), 'source': 'ledger'}
        elif local.get(name) is not None:
            found[name] = {'seconds': float(local[name]), 'source': 'local'}
        else:
            found[name] = {'seconds': float(fallback_s), 'source': 'fallback'}
    return found


def collect(adapter, repo, prs=()):
    """The shared window of the repository channel (D-085) and every event of the PR channels it names (batches,
    merges) or `prs` adds."""
    port = forge_events.ForgeEvents(adapter, forge_events.SystemClock(), 'reader', 'slo')
    events = port.read_recent(repo)
    numbers = set(prs)
    for event in events:
        numbers.update(event['payload'].get('prs') or [])
        numbers.add(event['payload'].get('pr'))
    for number in sorted(n for n in numbers if n):
        events += port.read(repo, number)
    return forge_events.dedupe(events)[0]


def ledger_steps(adapter, repo):
    """GX-25: every engine.step.measured the adapter holds for `repo`, across channels, with no forge read: the kind is
    file-routed (forge-events.file_kinds), so its log is a local directory (or an in-memory dict in tests). An adapter
    that exposes neither gives the repository channel only."""
    kind = 'engine.step.measured'
    route = getattr(adapter, 'route', None)
    target = route(kind) if callable(route) else adapter
    if hasattr(target, 'logs'):
        found = [event for channel, items in target.logs.items() if channel[0] == repo for event in items]
    elif hasattr(target, 'directory'):
        folder = Path(target.directory) / repo.replace('/', '__')
        found = []
        for path in sorted(folder.glob('*.jsonl')) if folder.is_dir() else []:
            for line in path.read_text(encoding='utf-8').splitlines():
                try:
                    found.append(json.loads(line))
                except ValueError:
                    continue
    else:
        found = target.read(forge_events.Channel(repo, None))
    return forge_events.dedupe([event for event in found if event.get('type') == kind])[0]
