"""How a failed gate stage's failing tests are read (GX-32, harvested from BD1 #667): the one shape the gate produces.

  script    `script tests`: the FAIL entries of script-tests.json; re-runnable on the base (GX-13)

  failures(report, logs)   ([failure {id, stage, signature}], [failed stages no failing test accounts for])
  rerunnable(stage)        whether a failure of the stage can be re-run on the base (only the script shape)

Any other failed stage (a scan, the structure check, shellcheck, a log with no test in it) has no per-test failure to
excuse: it is always the PR's. The vitest and Playwright shapes left with Open University's stages (F46, D-113).
Every signature is gate_failures' own, the one base.red carries.
"""
import gate_failures

SCRIPT_STAGE = 'script tests'


def rerunnable(stage):
    return stage == SCRIPT_STAGE


def extract(stage, logs):
    return gate_failures.script_failures(gate_failures._records(logs)) if stage == SCRIPT_STAGE else []


def failures(report, logs):
    """Every failing test of every failed stage (uncapped), and the failed stages with none attributed."""
    found, unattributed = [], []
    for stage in [item['name'] for item in report['stages'] if item['result'] == 'FAIL']:
        tests = extract(stage, logs)
        found += tests
        if not tests:
            unattributed.append(stage)
    return found, unattributed
