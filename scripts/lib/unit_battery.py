"""The unit battery, tier 1 of the gate for units (P-12, veto V5, plan v3 §4.2 item 6): `scripts/unit-battery <id>`.

A unit's battery is the whole of what the unit owns, never a sample: its project types (tsc over the unit's own
TypeScript files and their imports, through a per-unit tsconfig written outside git), its tests (every test file of
the unit and the suites whose covers match its production, each in the vitest project or shell runner that owns its kind), and its contract (the manifest's contract
entry must exist inside the unit, and the contract tests of the units that require it run with it). The steps are
data, the registry entry battery.unit_steps; the time limit is battery.unit_time_limit, and a battery slower than it
is red (D-069 item 14: the limit is never loosened). Steps run concurrently; the wall time is the battery's.

  plan(unit)     the steps that apply to a unit, each with its files and commands
  run(unit)      run them; {'unit', 'result', 'duration_ms', 'limit_s', 'steps': [...], 'failing': [...]}
  emit(...)      run inside the forge_events port: one engine.step.measured per step and one for the battery
                 (D-069 item 6)

scripts/unit-battery <id> [--json] [--emit [--pr N]]; exit 0 green, 1 red, 2 for an unknown unit.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading

import config
import unit_map
import units


class BatteryError(ValueError):
    pass


def setting(name, root=None):
    return config.get(f'battery.{name}', None if root is None else Path(root))


def unit_files(unit, root=None, files=None):
    """The tracked files the unit's battery covers: its own, plus the contract tests of the units that require it."""
    root = units._root(root)
    known = units.manifests(root)
    if unit not in known:
        raise KeyError(unit)
    files = sorted(unit_map.git(root, 'ls-files').split()) if files is None else sorted(files)
    mine = units.matcher(known[unit]['paths'])
    own = [path for path in files if mine.fullmatch(path)]
    contract_tests = units.matcher(setting('contract_test_globs', root))
    consumers = [units.matcher(manifest['paths']) for other, manifest in sorted(known.items())
                 if other != unit and unit in (manifest.get('requires') or {})]
    theirs = [path for path in files if contract_tests.fullmatch(path) and any(c.fullmatch(path) for c in consumers)]
    return own + [path for path in theirs if path not in own]


def _globs(step, key, root):
    found = list(step.get(key) or [])
    for name in step.get(f'{key}_entries') or []:
        found += config.get(name, None if root is None else Path(root))
    return found


def _relative(path, cwd):
    return path if cwd in ('', '.') else Path(path).relative_to(cwd).as_posix()


def select(step, files, root=None):
    """The files of a step: under its cwd, matching an include glob and no exclude glob (repository-relative)."""
    cwd = step['cwd']
    include = _globs(step, 'include', root)
    exclude = _globs(step, 'exclude', root)
    inside = units.matcher(include) if include else None
    outside = units.matcher(exclude) if exclude else None
    return [path for path in files
            if (cwd in ('', '.') or path.startswith(cwd + '/')) and inside and inside.fullmatch(path)
            and not (outside and outside.fullmatch(path))]


def types_project(unit, step, chosen, root=None):
    """The per-unit tsconfig (outside git, under battery.unit_types_dir): the project's tsconfig with `include`
    narrowed to the unit's files and the step's global declarations; tsc follows their imports."""
    root = units._root(root)
    project = root / step['cwd']  # the step runs in its TypeScript project (OU-DECOUPLE F4 (D-111): no address map)
    globals_ = [str(project / glob) for glob in step.get('globals') or []]
    document = {'extends': str(root / setting('project_tsconfig', root)), 'compilerOptions': {'incremental': False},
                'include': [str(root / path) for path in chosen] + globals_}
    target = root / setting('unit_types_dir', root) / f'{unit}.tsconfig.json'
    return target, json.dumps(document, indent=2) + '\n'


def proof_suites(root):
    """Read suite associations without crossing unit ownership boundaries.

    The gate validates the covers map; the battery also refuses missing or malformed
    associations rather than silently dropping a suite.
    """
    directory = root / config.get('gate-tests.covers_dir')
    for script in sorted((root / 'scripts/tests').glob('*.test.sh')):
        target = directory / f'{script.name.removesuffix(".test.sh")}.json'
        try:
            entry = json.loads(target.read_text())
        except (OSError, ValueError) as error:
            raise BatteryError(f'{target}: cannot read proof association: {error}') from error
        name = script.relative_to(root).as_posix()
        if (not isinstance(entry, dict) or entry.get('script') != name
                or not isinstance(entry.get('covers'), list) or not entry['covers']
                or not all(isinstance(pattern, str) and pattern for pattern in entry['covers'])):
            raise BatteryError(f'{target}: invalid proof association for {name}')
        yield name, units.matcher(entry['covers'])


def plan(unit, root=None, files=None):
    """[{'name', 'cwd', 'files', 'commands', 'project'}] of the steps that have files for this unit."""
    root = units._root(root)
    covered = unit_files(unit, root, files)
    manifest = units.manifests(root)[unit]
    steps = []
    production = units.production(covered, root)[0]
    proofs = set()
    if production:
        mapping = list(proof_suites(root))
        for path in production:
            suites = {script for script, pattern in mapping if pattern.fullmatch(path)}
            proofs.update(suites)
            if not suites:
                steps.append({'name': f'proof:{path}', 'cwd': '.', 'files': [path], 'commands': [],
                              'project': None, 'error': f'{unit}: production file {path} has no proof in covers'})
    covered = sorted(set(covered) | proofs)
    contract = manifest.get('contract')
    if contract:
        home = units.home(manifest)  # OU-DECOUPLE F4 (D-111): the unit's home, no longer its @ou address
        entry = f'{home}/{contract["entry"]}' if home else contract['entry']
        steps.append({'name': 'contract', 'cwd': '.', 'files': [entry] if entry else [], 'commands': [],
                      'project': None, 'error': None if entry and entry in covered and units.units_of(entry, root) == [unit]
                      else f'the contract entry {contract["entry"]} is not a file of {unit}'})
    for step in setting('unit_steps', root):
        chosen = select(step, covered, root)
        if not chosen:
            continue
        project = None
        if step['mode'] == 'types':
            project = types_project(unit, step, chosen, root)
        names = [_relative(path, step['cwd']) for path in chosen]
        commands = []
        for command in step['commands']:
            if step['mode'] == 'each' and any('{file}' in part for part in command):
                commands += [[part.replace('{file}', name) for part in command] for name in names]
                continue
            argv = []
            for part in command:
                if part == '{files}':
                    argv += names
                elif part == '{project}':
                    argv.append(str(project[0]))
                else:
                    argv.append(part)
            commands.append(argv)
        steps.append({'name': step['name'], 'cwd': step['cwd'], 'files': chosen, 'commands': commands,
                      'project': project, 'error': None})
    return steps


def shell(argv, cwd, log):
    """The default runner: one command, its output appended to the step's log; returns the exit code."""
    try:
        return subprocess.run(argv, cwd=cwd, stdout=log, stderr=subprocess.STDOUT).returncode
    except OSError as error:
        log.write(f'{argv[0]}: {error}\n'.encode())
        return 127


def _elapsed_ms(clock, start):
    return int((clock.now() - start).total_seconds() * 1000)


def run(unit, root=None, clock=None, runner=shell, files=None):
    """Run every step of the unit's battery concurrently; red when a step fails or the wall time exceeds
    battery.unit_time_limit."""
    import forge_events  # the clock lives with the port (D-069 item 5: no wall clock read directly)
    root = units._root(root)
    clock = clock or forge_events.clock_from_config()
    steps = plan(unit, root, files)
    limit = setting('unit_time_limit', root)
    tail = setting('unit_log_lines', root)
    results = [None] * len(steps)
    start = clock.now()

    def work(index, step):
        began = clock.now()
        if step['error']:
            results[index] = dict(step, code=1, duration_ms=0, output=step['error'])
            return
        if step['project']:
            path, text = step['project']
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding='utf-8')
        code = 0
        with tempfile.TemporaryFile() as log:
            for argv in step['commands']:
                code = runner(argv, str(root / step['cwd']), log) or code
            log.seek(0)
            output = log.read().decode('utf-8', errors='replace')
        results[index] = dict(step, code=code, duration_ms=_elapsed_ms(clock, began),
                              output='\n'.join(output.splitlines()[-tail:]))

    threads = [threading.Thread(target=work, args=(index, step)) for index, step in enumerate(steps)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    duration_ms = _elapsed_ms(clock, start)
    failing = [step['name'] for step in results if step['code']]
    over = duration_ms > limit * 1000
    return {'unit': unit, 'result': 'fail' if failing or over else 'ok', 'duration_ms': duration_ms, 'limit_s': limit,
            'over_limit': over, 'failing': failing,
            'steps': [{'name': step['name'], 'files': len(step['files']), 'duration_ms': step['duration_ms'],
                       'result': 'fail' if step['code'] else 'ok', 'output': step['output'] if step['code'] else ''}
                      for step in results]}


def emit(unit, root=None, pr=None, port=None, sha=None, premises=(), runner=shell, files=None):
    """Run the battery and publish one engine.step.measured per step and one for the whole battery through the
    forge_events port; re-emitting the same unit at the same sha is a no-op."""
    import forge_events
    root = units._root(root)
    sha = sha or unit_map.git(root, 'rev-parse', 'HEAD').strip()
    name = setting('unit_step', root)
    if port is None:
        port = forge_events.ForgeEvents(forge_events.adapter_from_config(), forge_events.clock_from_config(),
                                        setting('unit_producer', root), f'{name}:{unit}:{sha}')
    report = run(unit, root, port.clock, runner, files)
    subject = forge_events.subject(config.get('forge-events.repo', root), pr, sha, premises, unit)
    events = [port.build('engine.step.measured', forge_events.step_payload(
        subject, f'{name}.{step["name"]}', step['duration_ms'], step['result'])) for step in report['steps']]
    events.append(port.build('engine.step.measured', forge_events.step_payload(
        subject, name, report['duration_ms'], report['result'])))
    port.publish(events)
    return report


def text(report):
    lines = [f'{step["result"]:4}  {step["name"]:12} {step["files"]:4} file(s)  {step["duration_ms"] / 1000:6.2f} s'
             for step in report['steps']]
    for step in report['steps']:
        if step['result'] == 'fail':
            lines += [f'--- {step["name"]} ---', step['output']]
    over = f' (over the limit of {report["limit_s"]} s, battery.unit_time_limit)' if report['over_limit'] else ''
    lines.append(f'unit-battery {report["unit"]}: {"green" if report["result"] == "ok" else "red"} in '
                 f'{report["duration_ms"] / 1000:.2f} s{over}' +
                 (f'; failing: {", ".join(report["failing"])}' if report['failing'] else ''))
    return '\n'.join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(prog='scripts/unit-battery', description=__doc__.splitlines()[0])
    parser.add_argument('unit', help='the unit id (units/<id>/unit.json)')
    parser.add_argument('--json', action='store_true', help='print the report as JSON')
    parser.add_argument('--emit', action='store_true', help='publish engine.step.measured through the forge_events port')
    parser.add_argument('--pr', type=int, help='the change the events are about (default: the repository)')
    parser.add_argument('--root', type=Path, help='repository (default: this checkout)')
    args = parser.parse_args(argv)
    try:
        report = emit(args.unit, args.root, args.pr) if args.emit else run(args.unit, args.root)
    except KeyError:
        print(f'unit-battery: unknown unit {args.unit} (scripts/units list)', file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2) if args.json else text(report))
    return 0 if report['result'] == 'ok' else 1


if __name__ == '__main__':
    sys.exit(main())
