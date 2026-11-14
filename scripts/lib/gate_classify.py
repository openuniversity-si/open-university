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

ACTIONS = {
    'code': "fix this PR's change and rerun the gate",
    'env': 'open an env patch PR first if the toolchain pins need changing (scripts/env-check names the drift; '
           'bash scripts/cloud/setup.sh installs the pinned tools), then continue this PR',
    'contract': 'stop and escalate to the structure owner with the two conflicting rules (D-NNN/INV) and the failing proof',
    'base': "nothing to rework in this PR: the failing test is red on the base head too; report the base red to the "
            "manager (a unit with an owner); the PR stays queued and is delivered again once the base is green",
    'flake': "nothing to fix in this PR: the failure passed on one re-run at the same head; it is recorded as a defect "
             "and listed, and its owner stabilizes it (a second sighting quarantines it)",
}
FLAKE_CLASS = 'flake'
BASE_CLASS = 'base'
# F73: the lines attribute_base appends to a stage log, one per still-failing test it ran on the base head.
BASE_RED = re.compile(r'^base: \S+ fails on the base head \S+ too$', re.M)
BASE_OWN = re.compile(r"^base: \S+ is the PR's own: ", re.M)
# TX11: the lines gate_flake.py appends to a stage log after its one re-run, one per re-run test.
FLAKE_PASSED = re.compile(r'^flake: \S+ failed, then passed on one re-run at the same head$', re.M)
FLAKE_OWN = re.compile(r"^flake: \S+ is the PR's own: ", re.M)
# A driver abort happens before the code under test runs (gate-local's preflight, pin, slot, PR identity, checkout and
# local database steps), so it is always a machine fault: env. `gate pin` is the pin hook's abort (gate-hooks/pin.sh):
# a PR or base it cannot read, never the PR's own failure (GATE-API F7: the train ejected on `code`).
DRIVER_STAGES = {'gate preflight', 'gate pin', 'gate slot', 'PR identity', 'gate checkout', 'local database',
                 'gate driver'}
# F46: the stages env whatever their log says are the driver's; the browser stages left with Open University (D-113).
ENV_STAGES = DRIVER_STAGES
ENV = re.compile(r"Text file busy|No module named 'encodings'|SecurityFatalError|security upgrade|ENOTFOUND|"
                 r"EAI_AGAIN|ECONNRESET|ETIMEDOUT|error while loading shared libraries|Executable doesn't exist|"
                 r"Host system is missing|No space left on device|GLIBC_|env-check:|toolchain: |missing GH_TOKEN|"
                 r"Neon API failed|npm audit|command not found|local postgres did not start|"
                 r"could not (?:create|reset) the local test database|missing TEST_DATABASE_URL|FAIL env: |"
                 r"\(rate-limited\)|runuser: failed to execute \S+: Permission denied", re.I)  # NANO-UNBLOCK: a GitHub limit (github_api, forge_rate) is never the PR's code
# A failure the code under test produced. When one is in the log, the stage is code even if an env line is also there
# (F8: Chromium assertions failed in the same e2e stage where WebKit could not launch, and the stage said env).
CODE = re.compile(r"AssertionError|AssertError|\bexpect\((?:received|locator|page)\)|^\s*(?:Expected|Received):|"
                  r"ModuleNotFoundError: No module named '(?!encodings')|SyntaxError:|ReferenceError:|NameError:|error TS\d{4}",
                  re.M)
# Two rules or proofs that contradict each other, in any stage's log (the migration stages that also read a refused
# constraint as contract left with Open University, F46).
CONTRACT = re.compile(r'contradict|conflicting rules', re.I)


def flake_passed(test):
    return f'flake: {test} failed, then passed on one re-run at the same head'


def flake_own(test, why):
    return f"flake: {test} is the PR's own: {why}"


def base_red(test, sha):
    return f'base: {test} fails on the base head {sha[:12]} too'


def base_own(test, why):
    return f"base: {test} is the PR's own: {why}"


def classify(stage, log):
    if FLAKE_PASSED.search(log) and not FLAKE_OWN.search(log):
        return FLAKE_CLASS
    if stage in ENV_STAGES or (ENV.search(log) and not CODE.search(log)):
        return 'env'
    if CONTRACT.search(log):
        return 'contract'
    if BASE_RED.search(log) and not BASE_OWN.search(log):
        return BASE_CLASS
    return 'code'


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
