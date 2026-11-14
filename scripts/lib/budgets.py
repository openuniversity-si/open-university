"""Performance budgets with a measured baseline (D-069 item 14; plan v3.1 B1).

The budget of a metric is a registry entry; its baseline is the p95 of the newest measurements in the event log, read
through the slo.py reader (collect, ordered, percentile) and written to budgets.baseline_path; a measurement beyond the
baseline plus budgets.regression_tolerance_percent, or beyond the entry, is a regression. Every value comes from
config/registry/budgets.json, battery.json and slo.json; tests pass explicit overrides. The one budgeted metric is the
battery of each unit, battery.unit_time_limit: there is no second name for it. The web bundle and page latency budgets
left with Open University's web app (OU-DECOUPLE, D-111; VAZÃO F44). Nothing is guessed: with fewer than
budgets.min_samples measurements a metric is no_data and never fails.

  budgets.py baseline [--write]     compute the baseline from the log (print it, or write budgets.baseline_path)
  budgets.py show                   print the measurements and the verdicts as JSON
  budgets.py check                  exit 1 when a measurement regressed
"""
import argparse
from datetime import timedelta
import json
from pathlib import Path
import sys

import config
import forge_events
import json_schema
import slo

ROOT = Path(__file__).resolve().parent.parent.parent
BATTERY = 'battery.unit_time_limit'
METRICS = (BATTERY,)

NAMES = ('budgets.regression_tolerance_percent', 'budgets.window_samples', 'budgets.min_samples', 'budgets.baseline_path',
         'budgets.percent_whole', 'battery.unit_time_limit', 'battery.unit_step', 'slo.percentile')


def settings(overrides=None):
    """The registry values the tool needs, with explicit overrides (tests) applied on top."""
    values = {name: config.get(name) for name in NAMES}
    values.update(overrides or {})
    return values


def samples(events, conf):
    """Measurements by (metric, subject), oldest first, each (value, event_id): the battery of each unit in seconds from
    engine.step.measured (the whole-battery step, not its sub-steps). A budget.measured of another metric (the train's
    REST calls) is not a budget of this tool and is not folded."""
    found = {}
    for event in slo.ordered(events):
        payload = event['payload']
        if event['type'] != 'engine.step.measured' or payload['step'] != conf['battery.unit_step']:
            continue
        value = timedelta(milliseconds=payload['duration_ms']).total_seconds()
        found.setdefault((BATTERY, payload['unit']), []).append((value, event['event_id']))
    return found


def folded(events, conf):
    """Per (metric, subject): the p95 of the newest budgets.window_samples measurements, their count and the event id
    the value rests on; fewer than budgets.min_samples is not folded (no data, nothing invented)."""
    out = {}
    for key, items in sorted(samples(events, conf).items()):
        window = items[-conf['budgets.window_samples']:]
        if len(window) >= conf['budgets.min_samples']:
            out[key] = {'value': slo.percentile([value for value, _ in window], conf['slo.percentile']),
                        'samples': len(window), 'evidence': window[-1][1]}
    return out


def baseline(events, conf=None):
    """The baseline document of contracts/budgets/baseline.v1.json, computed from the log."""
    conf = conf or settings()
    metrics = [{'metric': metric, 'subject': subject, **fold}
               for (metric, subject), fold in folded(events, conf).items()]
    return {'version': 1, 'percentile': conf['slo.percentile'], 'window_samples': conf['budgets.window_samples'],
            'metrics': metrics}


def schema_errors(document):
    schema = json.loads((ROOT / 'contracts' / 'budgets' / 'baseline.v1.json').read_text(encoding='utf-8'))
    return json_schema.validate(schema, document)


def render(document):
    return json.dumps(document, indent=True, sort_keys=True) + '\n'


def write_baseline(document, conf=None, root=None):
    """Write the baseline after validating it against its schema; returns the path."""
    conf = conf or settings()
    errors = schema_errors(document)
    if errors:
        raise SystemExit('budgets: the baseline does not match contracts/budgets/baseline.v1.json: ' + '; '.join(errors))
    target = Path(root or ROOT) / conf['budgets.baseline_path']
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render(document), encoding='utf-8')
    return target


def load_baseline(conf=None, root=None):
    """The committed baseline, or an empty one when none was written yet (nothing is guessed)."""
    conf = conf or settings()
    path = Path(root or ROOT) / conf['budgets.baseline_path']
    if not path.is_file():
        return {'version': 1, 'percentile': conf['slo.percentile'], 'window_samples': conf['budgets.window_samples'],
                'metrics': []}
    return json.loads(path.read_text(encoding='utf-8'))


def judge(metric, subject, value, samples, evidence, document, conf):
    """The verdict of one value: ok, over_limit (beyond the registry entry) or regressed (beyond the baseline value grown
    by budgets.regression_tolerance_percent); no_data when value is None."""
    base = {(item['metric'], item['subject']): item for item in document['metrics']}.get((metric, subject))
    row = {'metric': metric, 'subject': subject, 'limit': conf[metric], 'baseline': base['value'] if base else None,
           'regression_limit': None, 'value': value, 'samples': samples, 'evidence': evidence, 'state': 'no_data'}
    if base:
        row['regression_limit'] = base['value'] * (1 + conf['budgets.regression_tolerance_percent'] / conf['budgets.percent_whole'])
    if value is not None:
        if value > row['limit']:
            row['state'] = 'over_limit'
        elif row['regression_limit'] is not None and value > row['regression_limit']:
            row['state'] = 'regressed'
        else:
            row['state'] = 'ok'
    return row


def verdicts(events, document, conf=None):
    """One verdict per (metric, subject) measured or in the baseline. Fewer than budgets.min_samples measurements is
    no_data and never a failure. The entry is battery.unit_time_limit; a regression is a p95 beyond the baseline plus
    the tolerance."""
    conf = conf or settings()
    fold = folded(events, conf)
    keys = sorted(set(fold) | {(item['metric'], item['subject']) for item in document['metrics']})
    return [judge(metric, subject, fold[(metric, subject)]['value'] if (metric, subject) in fold else None,
                  fold[(metric, subject)]['samples'] if (metric, subject) in fold else 0,
                  fold[(metric, subject)]['evidence'] if (metric, subject) in fold else None, document, conf)
            for metric, subject in keys]


def failing(results):
    return [item for item in results if item['state'] in ('over_limit', 'regressed')]


def adapter_for(log_dir=None):
    return forge_events.FileAdapter(log_dir) if log_dir else forge_events.adapter_from_config()


def main(argv=None):
    parser = argparse.ArgumentParser(prog='budgets.py')
    parser.add_argument('command', choices=('baseline', 'show', 'check'))
    parser.add_argument('--write', action='store_true', help='write budgets.baseline_path instead of printing')
    parser.add_argument('--log-dir', help='read a local JSON Lines log (forge_events.FileAdapter) instead of the configured one')
    args = parser.parse_args(argv)
    repo = config.get('forge-events.repo')
    events = slo.collect(adapter_for(args.log_dir), repo)
    if args.command in ('show', 'check'):
        results = verdicts(events, load_baseline())
        print(json.dumps(results, indent=True, sort_keys=True))
        return 1 if args.command == 'check' and failing(results) else 0
    document = baseline(events)
    if args.write:
        print(write_baseline(document))
    else:
        print(render(document), end='')
    return 0


if __name__ == '__main__':
    sys.exit(main())
