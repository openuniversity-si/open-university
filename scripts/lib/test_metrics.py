"""GATE-SPEED's diagnóstico (Padrão v8, D-116, D-117): the main metric and the guard metrics of the engine's test system,
measured the same way at the baseline and at the end of every phase, in one command, on the box that runs it.

main    cold_wall_s      every script test of the checkout run, none answered by key (a fresh, empty result store, no shared results), at
                         the box's parallelism (gate_test_cache.script_tests_workers): the wall from the first start to the
                         last end.
guards  cpu_s            CPU-seconds (user + system) of every process the cold run started: what a smaller box pays.
        script_tests     scripts/tests/*.test.sh the suite judges.
        test_functions   `def test_` lines in scripts/tests/**.py (OU-DECOUPLE's G2).
        failed           script tests that failed in the cold run.
        coverage_pct     with --coverage: line coverage of the engine's Python (scripts/, tests excluded) under the whole
                         suite, every Python process the tests start through the hermetic sitecustomize included.
        warm_wall_s      with --warm N: N more passes over the same store, every unchanged test answered by its key;
                         the median (one pass of about a second moves with the box's noise).
With --write-costs the cost hints are each test's least wall over gate.cost_hint_passes cold passes (VAZÃO F52).
With --write-costs FILE --test PATH only that test runs (alone, the same passes) and its one entry is merged into FILE (F67).
The wall and the CPU are measured without coverage; a coverage run is its own pass (its tracer slows every test).
Run it as `scripts/test-suite --metrics [--warm] [--coverage DIR] [--json FILE]`, the gate's own test environment.
"""
import json
import os
from pathlib import Path
import re
import resource
import statistics
import sys
import tempfile
import time

import gate_script_tests
import gate_test_cache
import shared_results

TEST = re.compile(r'\bdef test_')


def test_functions(root):
    """`def test_` lines in scripts/tests/**.py, the count OU-DECOUPLE's G2 kept."""
    return sum(len(TEST.findall(path.read_text(encoding='utf-8', errors='replace')))
               for path in sorted((Path(root) / 'scripts' / 'tests').rglob('*.py')))


def _cpu():
    used = resource.getrusage(resource.RUSAGE_CHILDREN)
    return used.ru_utime + used.ru_stime


def suite_pass(root, tool_root, store, workers=None, scripts=None):
    """One pass of the whole suite (or of scripts) against the result store at store: (results, wall_s, cpu_s,
    {script: seconds}).
    The pass measures this box: no PASS is taken from another box's shared results (GATE-SPEED F10, VAZÃO F40), which
    scripts/test-suite turns on for every suite, or a "cold" pass answers those tests by key and times none of them."""
    saved = {name: os.environ.get(name) for name in (gate_test_cache.STORE_ENV, shared_results.ENV)}
    os.environ[gate_test_cache.STORE_ENV] = str(store)
    os.environ.pop(shared_results.ENV, None)
    try:
        scripts = list(scripts or gate_script_tests.discover(root))
        timings, cpu, began = {}, _cpu(), time.monotonic()
        results = gate_test_cache.run(scripts, root, gate_test_cache.store_location(), 'test-metrics', tool_root,
                                      concurrency=workers, timings=timings)
        return results, time.monotonic() - began, _cpu() - cpu, timings
    finally:
        _restore(saved)


def _restore(saved):
    for name, value in saved.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value


def coverage_pass(root, tool_root, library, workers=None):
    """Line coverage of scripts/ (tests excluded) under one cold pass: {pct, statements, missing, files, failed}."""
    with tempfile.TemporaryDirectory(prefix='test-metrics-coverage-') as scratch:
        rc = Path(scratch) / 'coveragerc'
        rc.write_text('[run]\nparallel = True\n'
                      f'data_file = {scratch}/data/.coverage\n'
                      f'source = {Path(root).resolve() / "scripts"}\n'
                      'omit =\n    */scripts/tests/*\n    */scripts/lib/generated/*\n')
        (Path(scratch) / 'data').mkdir()
        # every test runs under coverage: suite_pass takes no PASS from another box (GATE-SPEED F10)
        saved = {name: os.environ.get(name) for name in ('PYTHONPATH', 'COVERAGE_PROCESS_START')}
        os.environ['PYTHONPATH'] = os.pathsep.join(filter(None, [str(library), saved['PYTHONPATH']]))
        os.environ['COVERAGE_PROCESS_START'] = str(rc)
        try:
            results, _, _, _ = suite_pass(root, tool_root, Path(scratch) / 'store', workers)
        finally:
            _restore(saved)
        sys.path.insert(0, str(library))
        import coverage
        measured = coverage.Coverage(config_file=str(rc))
        measured.combine(strict=False)
        measured.save()
        with open(os.devnull, 'w') as sink:
            pct = measured.report(file=sink, ignore_errors=True)
        statements = missing = 0
        data, absent_lines = measured.get_data(), {}
        for name in data.measured_files():
            _, executable, _, absent, _ = measured.analysis2(name)
            statements, missing = statements + len(executable), missing + len(absent)
            if absent:  # which lines no test reaches, per file: a drop of the guard names its lines
                absent_lines[str(Path(name).resolve().relative_to(Path(root).resolve()))] = sorted(absent)
        return {'pct': pct, 'statements': statements, 'missing': missing, 'absent': absent_lines,
                'files': len(data.measured_files()), 'failed': sum(1 for item in results if item['result'] != 'PASS')}


def measure(root, tool_root, workers=None, warm=False, coverage_library=None, cold=1):
    """The metrics document: main and guards, and the slowest tests of the cold pass. cold > 1 adds cold passes, each on
    its own empty store, to the document's cold_passes, the cost hints' measures (write_costs); the main metric and the
    guards stay those of the first pass."""
    workers = workers or gate_test_cache.script_tests_workers()
    with tempfile.TemporaryDirectory(prefix='test-metrics-store-') as store:
        results, wall, cpu, timings = suite_pass(root, tool_root, store, workers)
        out = {'box': {'cpus': os.cpu_count(), 'workers': workers},
               'main': {'name': 'cold_wall_s', 'better': 'lower', 'value': wall},
               'guards': {'cpu_s': cpu, 'script_tests': len(results),
                          'test_functions': test_functions(root),
                          'failed': sorted(item['test'] for item in results if item['result'] != 'PASS'),
                          'by_key': sorted(item['test'] for item in results if item['cached'])},
               'tails': {item['test']: item['tail'] for item in results if item['result'] != 'PASS'},
               'slowest': [[name, seconds] for name, seconds in sorted(timings.items(), key=lambda pair: -pair[1])]}
        out['cold_passes'] = [{'timed': dict(timings), 'by_key': out['guards']['by_key']}]
        if warm:
            passes = [suite_pass(root, tool_root, store, workers) for _ in range(max(1, int(warm)))]
            walls = sorted(wall for _, wall, _, _ in passes)
            out['guards']['warm_wall_s'] = statistics.median(walls)  # a pass of about 1 s moves with the box's noise
            out['guards']['warm_walls'] = walls
            out['guards']['warm_by_key'] = min(sum(1 for item in again if item['cached']) for again, _, _, _ in passes)
    # after the main and warm passes, so the main metric is measured the way every phase measured it
    out['cold_passes'] += [_cold_timings(root, tool_root, workers) for _ in range(max(1, int(cold)) - 1)]
    if coverage_library:
        out['guards']['coverage'] = coverage_pass(root, tool_root, coverage_library, workers)
    return out


def _cold_timings(root, tool_root, workers):
    """One more cold pass on its own empty store: {timed: {script: seconds}, by_key: [script answered by key]}."""
    with tempfile.TemporaryDirectory(prefix='test-metrics-store-') as store:
        results, _, _, timings = suite_pass(root, tool_root, store, workers)
    return {'timed': dict(timings), 'by_key': sorted(item['test'] for item in results if item['cached'])}


def _committed(path):
    """The cost hints the file holds now, {} when it is absent or unreadable: the base a single pass is judged against."""
    try:
        held = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return {}
    return held if isinstance(held, dict) else {}


def one_cost(root, tool_root, test, passes=None, workers=None):
    """The walls of one script test run alone, each pass on its own empty store, gate.cost_hint_passes of them (VAZÃO
    F67): a new test gets its hint without a whole-suite measure. Refused (ValueError) when test is not a script test of
    root or a pass did not run it to a PASS."""
    test = Path(test).resolve().relative_to(Path(root).resolve()).as_posix() if Path(test).is_absolute() else \
        Path(test).as_posix()
    if test not in gate_script_tests.discover(root):
        raise ValueError(f'write-costs: {test} is not a script test of {root}')
    passes = gate_test_cache.setting('cost_hint_passes') if passes is None else passes
    walls = []
    for _ in range(max(1, int(passes))):
        with tempfile.TemporaryDirectory(prefix='test-metrics-store-') as store:
            results, _, _, timings = suite_pass(root, tool_root, store, workers, scripts=[test])
        ran = [item for item in results if item['test'] == test]
        if not ran or ran[0]['result'] != 'PASS' or ran[0]['cached'] or test not in timings:
            raise ValueError(f"write-costs: {test} did not run to a PASS ({ran[0]['result'] if ran else 'not run'}); "
                             'no hint written')
        walls.append(timings[test])
    return test, walls


def write_one_cost(test, walls, path, ratio=None, floor=None):
    """test's least wall as its cost hint, merged into the committed hints at path (every other entry kept). One pass
    is refused the same jump write_costs refuses."""
    held = _committed(path)
    seconds = round(min(walls), 1)
    if len(walls) == 1:
        ratio = gate_test_cache.setting('cost_hint_jump_ratio') if ratio is None else ratio
        floor = gate_test_cache.setting('cost_hint_jump_floor_s') if floor is None else floor
        before = held.get(test)
        if seconds > floor and isinstance(before, (int, float)) and seconds > ratio * before:
            raise ValueError(f'write-costs: one cold pass put {test} {before} -> {seconds} s, above {ratio}x the '
                             'committed hint; measure again with gate.cost_hint_passes of 2 or more')
    held[test] = seconds
    Path(path).write_text(json.dumps(held, indent=1, sort_keys=True) + '\n')
    return seconds


def write_costs(document, path, ratio=None, floor=None):
    """The cold passes' walls as the committed cost hints (gate_test_cache.costs, D-120), one decimal, sorted: each
    test's least wall over the document's cold_passes (gate.cost_hint_passes). A wait (the box lock, a stall, a busy
    CPU) only ever adds to a wall, so the least is the test's own cost: one pass wrote 32-34 s for four tests of 2-4 s
    (VAZÃO F52). A pass that did not run and time every test it judged writes nothing: a test left out costs 0 s to
    covers-cost and runs last. A single pass is refused when a hint above floor seconds jumped above ratio times its
    committed hint: that jump needs a second measure."""
    total = document['guards']['script_tests']
    passes = document.get('cold_passes') or [{'timed': dict(document['slowest']),
                                              'by_key': document['guards'].get('by_key', [])}]
    for one in passes:
        untimed = one['by_key'] or sorted(set(passes[0]['timed']) - set(one['timed']))
        if untimed or len(one['timed']) != total:
            raise ValueError(f"write-costs: the cold pass timed {len(one['timed'])} of {total} script tests; "
                             f"untimed: {', '.join(untimed) or '?'}")
    hints = {name: round(min(one['timed'][name] for one in passes), 1) for name in sorted(passes[0]['timed'])}
    if len(passes) == 1:
        ratio = gate_test_cache.setting('cost_hint_jump_ratio') if ratio is None else ratio
        floor = gate_test_cache.setting('cost_hint_jump_floor_s') if floor is None else floor
        held = _committed(path)
        jumps = [f'{name} {held[name]} -> {seconds} s' for name, seconds in hints.items()
                 if seconds > floor and isinstance(held.get(name), (int, float)) and seconds > ratio * held[name]]
        if jumps:
            raise ValueError(f'write-costs: one cold pass put {len(jumps)} hint(s) above {ratio}x the committed one '
                             f"({'; '.join(jumps)}); measure again with gate.cost_hint_passes of 2 or more")
    Path(path).write_text(json.dumps(hints, indent=1, sort_keys=True) + '\n')


def main(args, tool_root):
    """`scripts/test-suite --metrics [--workers N] [--warm] [--coverage DIR] [--json FILE]`: print one line, write the
    document; exit 1 when a test failed (a guard). With `--write-costs FILE --test PATH` only that test is measured and
    its one hint merged into FILE (VAZÃO F67)."""
    costs, test = getattr(args, 'write_costs', None), getattr(args, 'test', None)
    if test and not costs:
        print('test-metrics: --test names the one test --write-costs measures', file=sys.stderr)
        return 2
    if test:
        try:
            test, walls = one_cost(args.root, tool_root, test, workers=args.workers)
            seconds = write_one_cost(test, walls, costs)
        except ValueError as refused:
            print(refused, file=sys.stderr)
            return 1
        print(f"write-costs: {test} {seconds} s (least of {', '.join(f'{wall:.2f}' for wall in walls)}) in {costs}")
        return 0
    out = measure(args.root, tool_root, args.workers, args.warm, args.coverage,
                  cold=gate_test_cache.setting('cost_hint_passes') if costs else 1)
    if args.json:
        Path(args.json).write_text(json.dumps(out, indent=1) + '\n')
    if costs:
        try:
            write_costs(out, costs)
        except ValueError as refused:
            print(refused, file=sys.stderr)
            return 1
    guards = out['guards']
    print(f"main cold_wall_s {out['main']['value']:.2f} on {out['box']['cpus']} CPUs ({out['box']['workers']} workers); "
          f"cpu_s {guards['cpu_s']:.1f}; script_tests {guards['script_tests']}; "
          f"test_functions {guards['test_functions']}; failed {len(guards['failed'])}"
          + (f"; warm_wall_s {guards['warm_wall_s']:.2f}" if 'warm_wall_s' in guards else '')
          + (f"; coverage {guards['coverage']['pct']:.2f} %" if 'coverage' in guards else ''))
    return 1 if guards['failed'] else 0
