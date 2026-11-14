"""The gate's stage graph as data, and a deterministic bounded runner for independent work (GS1, D-064 (f), D-069 items 4, 5, 6).

scripts/lib/gate-stages.json declares, per stage, what it needs (`needs`), which scarce resources it holds
(`resources`: heavy_db) and whether its pass may be cached (gate_result_cache). The graph is the single description of the
dependencies that gate-local's schedule implements; `check` fails when the two drift, so a stage added to the schedule
without a declaration, a dependency on an unknown stage or a cycle is a red structure check, not a surprise at 3 a.m.

  load()                      the declared stages, in declared order
  validate(stages, known)     the errors: unknown stage, unknown need, self need, cycle, undeclared resource
  schedule(names, needs, run, concurrency)
                              run the independent work of `names` concurrently, at most `concurrency` at a time. A name
                              runs once every need has passed; a name whose need failed or was skipped is `SKIPPED`.
                              The result is a list in the order of `names`, whatever order the work finished in, so
                              a parallel run reports exactly what the serial run (concurrency 1) reports.
  run_commands(commands, concurrency, env)
                              the same runner for independent shell commands (the script tests): per-command output,
                              results in command order.

gate_graph.py check                       validate the shipped graph against the gate's stage names
gate_graph.py resources <stage>           the resources the stage holds, space separated (empty for none)
gate_graph.py run-commands <list-file>    run the commands listed (`label<TAB>command` or `command`, one per line) at
                                          gate.script_tests_concurrency
"""
import json
import os
import re
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import config

DECLARATIONS = Path(__file__).with_name('gate-stages.json')
RESOURCES = ('heavy_db',)
PASS, FAIL, SKIPPED = 'PASS', 'FAIL', 'SKIPPED'


class GraphError(ValueError):
    pass


def load(path=DECLARATIONS):
    return json.loads(Path(path).read_text())['stages']


def validate(stages, known=None):
    """The errors of a declared graph; empty when it is sound. `known` is the set of stage names the gate runs."""
    errors = []
    for name, spec in stages.items():
        if known is not None and name not in known:
            errors.append(f'{name}: not a stage of the gate')
        for need in spec.get('needs', []):
            if need == name:
                errors.append(f'{name}: needs itself')
            elif need not in stages:
                errors.append(f'{name}: needs {need}, which is not declared')
        for resource in spec.get('resources', []):
            if resource not in RESOURCES:
                errors.append(f'{name}: resource {resource} is not one of {", ".join(RESOURCES)}')
        if spec.get('deterministic') and not (spec.get('inputs') and isinstance(spec.get('version'), int)):
            errors.append(f'{name}: a deterministic stage declares its inputs and an integer version')
    if not errors:
        errors += [f'cycle through {name}' for name in _cyclic(stages)]
    return errors


def _cyclic(stages):
    state, found = {}, []

    def visit(name):
        if state.get(name) == 'done':
            return
        if state.get(name) == 'open':
            found.append(name)
            return
        state[name] = 'open'
        for need in stages[name].get('needs', []):
            visit(need)
        state[name] = 'done'

    for name in stages:
        visit(name)
    return sorted(set(found))


def schedule(names, needs, run, concurrency):
    """Run `run(name) -> bool` over `names`, respecting `needs`, at most `concurrency` at once.

    Returns [{'name', 'result': PASS|FAIL|SKIPPED}] in the order of `names`. A need outside `names` is taken as met."""
    if concurrency < 1:
        raise GraphError('concurrency must be a positive integer')
    names = list(names)
    if len(set(names)) != len(names):
        raise GraphError('a name appears twice in the run')
    wanted = set(names)
    pending = {name: [need for need in needs.get(name, []) if need in wanted] for name in names}
    outcome = {}
    wake = threading.Condition()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        running = {}

        def finish(name, future):
            with wake:
                try:
                    outcome[name] = PASS if future.result() else FAIL
                except Exception:  # noqa: BLE001 - a crashed stage is a failed stage, never a silent pass
                    outcome[name] = FAIL
                running.pop(name, None)
                wake.notify_all()

        with wake:
            while len(outcome) < len(names):
                moved = False
                for name in names:
                    if name in outcome or name in running:
                        continue
                    state = [outcome.get(need) for need in pending[name]]
                    if any(value in (FAIL, SKIPPED) for value in state):
                        outcome[name] = SKIPPED
                        moved = True
                    elif all(value == PASS for value in state) and len(running) < concurrency:
                        future = pool.submit(run, name)
                        running[name] = future
                        future.add_done_callback(lambda done, who=name: finish(who, done))
                        moved = True
                if len(outcome) < len(names):
                    if not moved and not running:
                        raise GraphError('deadlock: ' + ', '.join(n for n in names if n not in outcome))
                    wake.wait()
    return [{'name': name, 'result': outcome[name]} for name in names]


def run_commands(commands, concurrency, env=None, cwd=None, timings=None, ended=None, answered=None):
    """Run independent shell commands; each result carries its exit code and output, in command order.

    `commands` is a list of commands, or of (label, command) pairs when the report should name something shorter.
    `timings`, when given, is filled with each label's wall time in seconds; `ended(label)`, when given, is called as
    each command ends (the suite's jobserver, GATE-SPEED F1, D-118); `answered(label, passed)` too, with its verdict
    (FULL-RUN-KEEP: a batch says each test's as it ends)."""
    pairs = [(item, item) if isinstance(item, str) else tuple(item) for item in commands]
    shell = dict(pairs)
    outputs = {}
    took = {} if timings is None else timings  # label -> seconds, kept out of the results so serial and parallel reports stay equal

    def run(label):
        began = time.monotonic()
        done = subprocess.run(shell[label], shell=True, executable='/bin/bash', capture_output=True, text=True,
                              env=None if env is None else {**os.environ, **env}, cwd=cwd)
        outputs[label] = (done.returncode, done.stdout + done.stderr)
        took[label] = time.monotonic() - began
        if ended is not None:
            ended(label)
        if answered is not None:
            answered(label, done.returncode == 0)
        return done.returncode == 0

    results = schedule([label for label, _ in pairs], {}, run, concurrency)
    for result in results:
        result['exit'], result['output'] = outputs.get(result['name'], (None, ''))
    return results


def check():
    import gate_policy
    stages = load()
    known = set(gate_policy.FULL_STAGES) | set(gate_policy.DEV_STAGES) | {'script tests'}
    errors = validate(stages, known)
    missing = sorted(set(gate_policy.DEV_STAGES) - set(stages))
    errors += [f'{name}: a dev stage without a declaration' for name in missing]
    return errors


# AWS7: the compact failure summary every script-test report ends with (a runner returns only a check's last 2000 characters)
ANSI = re.compile(r'\x1b\[[0-9;]*[A-Za-z]')
FAILED_LINE = re.compile(r'^\s*(?:[A-Za-z_.]*(?:Error|Exception)\b|FAIL\b|FAILED\b|not ok\b|Traceback)')


SUMMARY_CHARS = 1500  # a runner returns only the last ~2000 characters of a check's output (tower_infra.runner TAIL_CHARS)
SUMMARY_LINE = 200
BLOCK = re.compile(r'^={20,}\s*$|^Ran \d+ tests? in ')  # where a report's next failure or its footer starts
HEADER = re.compile(r'^(?:FAIL|ERROR): ')
ASSERT = re.compile(r'^\s*(?:[\w.]*AssertionError|[\w.]*Error|[\w.]*Exception)\b')


def failure_lines(output, per_test=6):
    """The compact evidence of one failed test, from its whole output: each unittest `FAIL:`/`ERROR:` header with the
    first assertion line after it and the lines that follow it (a message's first lines), else the last error lines."""
    lines = [ANSI.sub('', line).rstrip() for line in (output or '').splitlines()]
    found = []
    for index, line in enumerate(lines):
        if not HEADER.match(line):
            continue
        found.append(line)
        end = next((at for at in range(index + 1, len(lines)) if BLOCK.match(lines[at])), len(lines))
        shown = next((at for at in range(index + 1, end) if ASSERT.match(lines[at])), None)
        if shown is not None:
            found.extend(item for item in lines[shown:min(end, shown + 12)] if item.strip(' -'))
    if not found:
        found = [line for line in lines if FAILED_LINE.match(line)][-3:] or [line for line in lines if line.strip()][-1:]
    return [line.strip()[:SUMMARY_LINE] for line in found[:per_test * 4]]


def summary(failed, limit=SUMMARY_CHARS):
    """The FAILURE SUMMARY block, at most `limit` characters, for the LAST lines of a check's output: `failed` is
    [(test id, its lines)]. Empty when nothing failed. The cut keeps the head: ids first, then their first lines."""
    if not failed:
        return ''
    out = [f'FAILURE SUMMARY ({len(failed)} failed)']
    for test, lines in failed:
        out.append(f'FAIL {test}')
        out.extend(f'  {line}' for line in lines)
    text = '\n'.join(out)
    return text if len(text) <= limit else text[:limit - 12].rstrip() + '\n[cut]'


def main(argv):
    if len(argv) >= 2 and argv[1] == 'check':
        errors = check()
        for error in errors:
            print(f'FAIL gate-stages.json: {error}')
        return 1 if errors else 0
    if len(argv) == 3 and argv[1] == 'resources':
        print(' '.join((load().get(argv[2]) or {}).get('resources', [])))
        return 0
    if len(argv) == 3 and argv[1] == 'run-commands':
        commands = [tuple(line.split('\t', 1)) if '\t' in line else line
                    for line in Path(argv[2]).read_text().splitlines() if line.strip()]
        results = run_commands(commands, config.get('gate.script_tests_concurrency'))
        failed, evidence = 0, []
        for result in results:
            print(f'{"PASS" if result["result"] == PASS else "FAIL"} {result["name"]}')
            if result['result'] != PASS:
                failed = 1
                print('\n'.join(result['output'].splitlines()[-config.get('gate.script_tests_log_lines'):]))
                evidence.append((result['name'], result['output']))
        if evidence:
            print(summary([(name, failure_lines(out)) for name, out in evidence]))
        return failed
    sys.exit('usage: gate_graph.py check | resources <stage> | run-commands <list-file>')


if __name__ == '__main__':
    sys.exit(main(sys.argv))
