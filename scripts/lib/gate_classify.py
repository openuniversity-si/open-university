"""Class of a red gate stage (D-027): code, env or contract, with the prescribed action (AGENTS.md).

  code      the PR's change broke it: fix this PR and rerun the gate.
  env       toolchain, dependencies, advisory or machine: open an env patch PR first, then continue.
  contract  rules or proofs contradict each other: stop and escalate.
  flake     every failing test of the stage failed, then passed on the one re-run at the same head (TX11,
            gate_flake.py): recorded and listed, not this PR's; a stage with any test that failed again stays code.
  base      every failing test of the stage still red after the known-defect step and the flake re-run also fails on the
            base head (F73, attribute_base): the stage stays red and the PR stays queued, but the lane does not rework
            another unit's red; the base red is reported and gets an owner. A test that passes there, one the base does
            not have, or one that could not run there keeps the stage what the runner said (code).
Every red stage and every driver abort also prints one machine line, `<gate.class_line_prefix> <stage>\t<class>`
(GX-01, D-070), which a consumer such as the train reads instead of the human line.
Usage: gate_classify.py <stage name> <log file>   prints the human line and the machine line.
       gate_classify.py abort <stage> <message>    a driver abort: prints `FAIL <message>` and the machine line.
"""
from pathlib import Path
import re
import sys

# The checkout this module belongs to. Its registry is read by root, because a gate's hermetic tooling may already have
# imported the config module of another checkout (the base-tip gate, D-A3) whose registry lacks this checkout's keys.
ROOT = Path(__file__).resolve().parent.parent.parent

# D-322: the rule is layer 0 (stage_classes, engine-events); the gate's callers keep these names.
from stage_classes import (ACTIONS, BASE_CLASS, BASE_OWN, BASE_RED, CODE, CONTRACT, DRIVER_STAGES, ENV,  # noqa: F401,E402
                           ENV_STAGES, FLAKE_CLASS, FLAKE_OWN, FLAKE_PASSED, base_own, base_red, classify, flake_own,
                           flake_passed)


def stage_log(logs, stage):
    return Path(logs) / (re.sub(r'[^a-zA-Z0-9]', '_', stage) + '.log')


def note(logs, stage, lines):
    """Append `lines` and the stage's class after them to the stage log, so the last class line is the one a reader sees."""
    path = stage_log(logs, stage)
    log = (path.read_text(errors='replace') if path.is_file() else '') + '\n'.join(lines) + '\n'
    kind = classify(stage, log)
    with path.open('a') as handle:
        handle.write('\n'.join(lines) + '\n' + line(stage, log) + '\n' + class_line(stage, kind) + '\n')
    return kind


def on_base(test, base, root):
    """Whether `base` has the test's script: a test the PR adds cannot be red on the base (bash would exit 127 there)."""
    import subprocess
    return subprocess.run(['git', '-C', str(root), 'cat-file', '-e', f'{base}:{test}'], capture_output=True).returncode == 0


def attribute_base(report, logs, base, root=None, outcome=None, present=None):
    """F73: run each failing test the known-defect step and the flake re-run left the PR's own on the base head, once
    per (base, test) (defect_detect.outcome caches it). A failed stage whose every failing test is red there too gets
    class base; it stays FAIL, since the PR may have touched the test or the signature may differ. `outcome(test, base)`
    and `present(test, base)` stand for defect_detect.outcome and on_base in tests. Returns the base-red tests (also
    report['base_red'])."""
    import defect_adapters
    import defect_detect
    report['base_red'] = []
    if not base or report['result'] == 'PASS':
        return []
    root = Path(root) if root else defect_detect.ROOT
    outcome = outcome or (lambda test, sha: defect_detect.outcome(test, sha, root))
    present = present or (lambda test, sha: on_base(test, sha, root))
    excused = {item['id'] for item in (report.get('known_defects') or [])}
    found, _ = defect_adapters.failures(report, logs)
    failing = [item for item in found if defect_adapters.rerunnable(item['stage']) and item['id'] not in excused]
    lines, red = {}, []
    for item in failing:
        if not present(item['id'], base):
            lines.setdefault(item['stage'], []).append(base_own(item['id'], 'the base does not have it'))
            continue
        seen = outcome(item['id'], base)
        if seen.get('result') == defect_detect.FAIL:
            red.append(dict(item, base_sha=base, base_signature=seen.get('signature', '')))
            lines.setdefault(item['stage'], []).append(base_red(item['id'], base))
        else:
            why = 'it passes on the base head' if seen.get('result') == defect_detect.PASS else 'it could not run on the base head'
            lines.setdefault(item['stage'], []).append(base_own(item['id'], why))
    for stage in report['stages']:
        if stage['result'] == 'FAIL' and stage['name'] in lines:
            stage['class'] = note(logs, stage['name'], lines[stage['name']])
    report['base_red'] = red
    return red


def line(stage, log):
    kind = classify(stage, log)
    env = ENV.search(log) if kind != 'env' else None
    also = f' (env evidence too: "{env.group(0)}"; it is not the only cause)' if env else ''
    return f'class: {kind} — {ACTIONS[kind]}{also}'


def class_line(stage, kind):
    """The machine line: `<prefix> <stage>\t<class>`; a tab or newline inside the stage name becomes a space."""
    import config
    return f"{config.get('gate.class_line_prefix', ROOT)} {' '.join(stage.split())}\t{kind}"


def classes(output):
    """{stage: class} of the machine class lines in a gate's output, the last one of each stage: a class set after the
    stage ran (F73's base, printed by gate_report) comes after the runner's own line."""
    import config
    prefix = re.escape(config.get('gate.class_line_prefix', ROOT))
    kinds = '|'.join(map(re.escape, ACTIONS))
    return {stage: kind for stage, kind in re.findall(rf'^{prefix} (.+)\t({kinds})\s*$', output, re.M)}


def main(argv):
    command, *rest = argv or ['']
    if command == 'abort' and len(rest) == len(('stage', 'message')):
        stage, message = rest
        for text in message.splitlines() or ['']:
            print(text if text.startswith('FAIL ') else f'FAIL {text}')
        print(class_line(stage, classify(stage, message)))
        return 0
    if command == 'abort' or len(rest) != 1:
        raise SystemExit('usage: gate_classify.py <stage> <log file> | abort <stage> <message>')
    stage, path = command, Path(rest[0])
    log = path.read_text(errors='replace') if path.is_file() else ''
    print(line(stage, log))
    print(class_line(stage, classify(stage, log)))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
