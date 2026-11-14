"""A gate refusal is an incident the machine writes (D-240).

A gate report with result FAIL becomes one `gate-refusal` record: the head, the mode, the PR, the stages that failed and
the failing tests. The records append to one JSON-lines file, so the incident register reads machine data and no one
types it by hand (docs/operations/incidents.md). A PASS writes nothing.

    scripts/lib/gate_incident.py --report REPORT.json --mode dev --pr 12 --out incidents.jsonl
"""
import argparse
import json
import pathlib
import sys

INCIDENT_TYPE = 'gate-refusal'


def incident(report, mode, pr=None):
    """The incident of a refused report, or None when the gate passed."""
    if report.get('result') == 'PASS':
        return None
    stages = [s.get('name') for s in report.get('stages', []) if s.get('result') == 'FAIL']
    tests = [{'id': t.get('id'), 'stage': t.get('stage')} for t in report.get('failingTests', [])]
    return {'type': INCIDENT_TYPE, 'sha': report.get('sha'), 'mode': mode, 'pr': pr,
            'failed_stages': stages, 'failing_tests': tests}


def record(path, entry):
    """Append one incident as one line; the file is created when it is missing."""
    with pathlib.Path(path).open('a', encoding='utf-8') as out:
        out.write(json.dumps(entry, sort_keys=True) + '\n')


def main(argv=None):
    parser = argparse.ArgumentParser(description='Record a refused gate report as a gate-refusal incident.')
    parser.add_argument('--report', required=True)
    parser.add_argument('--mode', required=True)
    parser.add_argument('--pr', type=int)
    parser.add_argument('--out', required=True)
    args = parser.parse_args(argv)
    entry = incident(json.loads(pathlib.Path(args.report).read_text(encoding='utf-8')), args.mode, args.pr)
    if entry is None:
        return 0
    record(args.out, entry)
    return 0


if __name__ == '__main__':
    sys.exit(main())
