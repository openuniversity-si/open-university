"""one line per N7 check, pass/warn/fail, exit code; no session needed

Runs the seven check units (budgets, slo, battery, census, literals, vendors, wrappers) through their own scripts and
prints one line each: `<pass|warn|fail> <check>: <detail>`. Exit 1 when one fails, so a monitor can probe it (D-205).
A check reads only its own script's exit code and output; nothing here judges a number a session would have to read.
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
PASS, WARN, FAIL = 'pass', 'warn', 'fail'
PYTHON = os.environ.get('OU_PYTHON', sys.executable)


def _run(*argv):
    return subprocess.run(list(argv), cwd=ROOT, capture_output=True, text=True)


def _last_line(text):
    lines = [line for line in text.strip().splitlines() if line.strip()]
    return lines[-1] if lines else ''


def check_budgets():
    done = _run(str(ROOT / 'scripts/budgets'), 'check')
    if done.returncode != 0:
        return FAIL, 'a performance budget is breached (scripts/budgets show)'
    return PASS, 'no budget breached'


def check_slo():
    done = _run(str(ROOT / 'scripts/slo'), 'show')
    # show exits 1 when an SLO is breached, so its JSON is read whatever the exit code is
    try:
        rows = json.loads(done.stdout)
    except json.JSONDecodeError:
        return FAIL, 'scripts/slo show printed no JSON'
    breached = [row.get('slo', '?') for row in rows if row.get('state') == 'breached']
    if breached:
        return FAIL, f'{len(breached)} SLO breached: {", ".join(sorted(breached))}'
    return PASS, f'{len(rows)} SLO ok'


def check_battery():
    done = _run(str(ROOT / 'scripts/battery'), 'pending')
    if done.returncode != 0:
        return FAIL, 'scripts/battery pending failed'
    tip = _last_line(done.stdout)
    if tip:
        return WARN, f'tier 3 has a tip waiting: {tip.split()[0]}'
    return PASS, 'no tier 3 batch waiting'


def check_census():
    done = _run(str(ROOT / 'scripts/census'), 'check')
    summary = _last_line(done.stdout)
    if done.returncode != 0:
        return FAIL, summary or 'scripts/census check failed'
    return PASS, summary.replace('census: ', '')


def check_literals():
    done = _run(PYTHON, str(ROOT / 'scripts/lib/literal_census.py'))
    if done.returncode != 0:
        return FAIL, _last_line(done.stdout) or 'a unit spells a value more often than the base census'
    return PASS, 'no unit spells a value more than the base census'


def check_vendors():
    done = _run(PYTHON, str(ROOT / 'scripts/lib/vendor_check.py'))
    if done.returncode != 0:
        return FAIL, _last_line(done.stdout) or 'a vendor call sits outside its adapter'
    return PASS, 'every vendor call goes through its adapter'


WRAPPERS = ('scripts/run', 'scripts/test-suite')


def check_wrappers():
    missing = [path for path in WRAPPERS if not os.access(ROOT / path, os.X_OK)]
    if missing:
        return FAIL, f'not executable: {", ".join(missing)}'
    return PASS, f'{len(WRAPPERS)} wrappers executable'


CHECKS = (
    ('budgets', check_budgets),
    ('slo', check_slo),
    ('battery', check_battery),
    ('census', check_census),
    ('literals', check_literals),
    ('vendors', check_vendors),
    ('wrappers', check_wrappers),
)


def run_all():
    results = []
    for name, probe in CHECKS:
        status, detail = probe()
        results.append({'name': name, 'status': status, 'detail': detail})
    return results


def main(argv=None):
    parser = argparse.ArgumentParser(prog='scripts/checks', description=__doc__)
    parser.add_argument('--json', action='store_true', help='the same verdicts as a JSON list')
    args = parser.parse_args(argv)
    results = run_all()
    if args.json:
        print(json.dumps(results))
    else:
        for row in results:
            print(f'{row["status"]} {row["name"]}: {row["detail"]}')
    return 1 if any(row['status'] == FAIL for row in results) else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
