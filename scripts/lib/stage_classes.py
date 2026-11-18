"""The class of a red gate stage's log (D-027; D-322): code, env, contract, flake or base, and each class's action.

The pure rule of gate_classify, moved to layer 0 (engine-events, beside the verdict contracts that carry the class) so a
role that runs a gate command and reads its output (engine_role's CommandGate) classifies it without importing the
gate's report. gate_classify re-exports every name here; its docstring is the rule's prose.

  classify(stage, log)     the class
  flake_passed, flake_own, base_red, base_own
                           the lines gate_flake.py and attribute_base append to a stage log, which classify reads
"""
import re

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
                 r"npm audit|command not found|local postgres did not start|"
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
