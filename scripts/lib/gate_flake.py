"""Flake attribution on the PR's own head (TX11, D-070; T4/T8: own / base / env / flake, only own turns a PR red).

After the known-base-defect step, every still-failing test of a stage in gate-flake.stages that the PR did not touch is
re-run exactly once (gate-flake.reruns), alone, at the same head, in the checkout under test and the gate's own
environment: gate_test_cache.run with a throwaway store, so the re-run neither reads nor writes a cache marker.

  fails again, errors or has no result  -> nothing changes: the PR's own failure, its stage stays red
  passes                                -> a flake: listed in report['flakes'] and report['known_defects'] (source
                                           flake, base_sha = the head it flaked on), so the status table ("Known base
                                           defect"), the verdict payload (known_defects) and defect.detected ->
                                           scripts/defects sync -> defects.record carry it

A failed stage with at least one flake whose every failing test is now a known defect or a flake becomes PASS with
raw_result FAIL and class flake; the report is PASS once no stage is still FAIL. The stage log gets one line per
re-run test and the class line again (gate_classify), so the class a reader sees is the one after the re-run.

events() adds test.flaked for each flake on the repository channel, then test.quarantined when the log holds
gate-flake.quarantine_after test.flaked of that test inside gate-flake.quarantine_window_s and it is not already open
(quarantine.state). The quarantine changes no policy (quarantine.py): a quarantined test that fails twice still
blocks, and one that flakes is still listed in every report.

  attribute(report, logs, ...)     the one re-run and the report changes; returns the flakes
  events(report, logs, port, repo) the test.flaked / test.quarantined envelopes, built, not published
"""
from datetime import datetime, timedelta
import os
from pathlib import Path
import re
import shutil
import tempfile

import config
import defect_adapters
import defect_detect
import defects
import forge_events
import gate_classify
import gate_test_cache
import quarantine

ROOT = Path(__file__).resolve().parent.parent.parent
SOURCE = 'flake'
FLAKED, QUARANTINED, UNQUARANTINED = 'test.flaked', 'test.quarantined', 'test.unquarantined'


def setting(name):
    return config.get(f'gate-flake.{name}')


def subject_root(environ=None):
    """The checkout under test (gate-local exports it), else this checkout."""
    environ = os.environ if environ is None else environ
    return Path(environ.get(setting('subject_env')) or ROOT)


def rerun(tests, root, tool_root=ROOT):
    """{test: result item} of ONE run of exactly `tests` in `root` through gate_test_cache.run, with a store that
    exists only for this call (no marker read, none kept)."""
    store = Path(tempfile.mkdtemp(prefix=setting('rerun_store_prefix')))
    try:
        found = {}
        for _ in range(setting('reruns')):
            found = {item['test']: item for item in gate_test_cache.run(list(tests), str(root), store,
                                                                        setting('rerun_source'), str(tool_root))}
        return found
    finally:
        shutil.rmtree(store, ignore_errors=True)


def stage_log(logs, stage):
    return Path(logs) / (re.sub(r'[^a-zA-Z0-9]', '_', stage) + '.log')


def note(logs, stage, lines):
    """Append the re-run lines and the stage's class after them (gate_classify) to the stage log."""
    path = stage_log(logs, stage)
    before = path.read_text(errors='replace') if path.is_file() else ''
    text = '\n'.join(lines) + '\n'
    log = before + text
    text += gate_classify.line(stage, log) + '\n' + gate_classify.class_line(stage, gate_classify.classify(stage, log)) + '\n'
    with path.open('a') as handle:
        handle.write(text)


def attribute(report, logs, root=None, runner=None, changed=(), mapping=None):
    """Re-run the failing tests the earlier steps left the PR's own, once; mark the ones that pass as flakes.
    `changed` is what the PR changed (None: unknown, so every test counts as touched); `runner(tests, root)` stands for
    rerun() in tests. Returns the flakes (also report['flakes'])."""
    report['flakes'] = []
    if not setting('enabled') or report['result'] == 'PASS':
        return []
    known = {item['id'] for item in report.get('known_defects') or []}
    found, _ = defect_adapters.failures(report, logs)
    failing = [item for item in found if item['stage'] in setting('stages') and item['id'] not in known]
    lines, todo = {}, []
    for item in failing:
        if setting('never_excuse_touched') and defect_detect.touched(item['id'], changed, ROOT, mapping):
            lines.setdefault(item['stage'], []).append(gate_classify.flake_own(item['id'], 'the PR changed it, not re-run'))
        else:
            todo.append(item)
    seen = (runner or rerun)([item['id'] for item in todo], Path(root) if root else subject_root()) if todo else {}
    flakes = []
    for item in todo:
        again = seen.get(item['id']) or {}
        if again.get('result') == 'PASS':
            unit, owner, _ = defects.derive_owner(item['id'], ROOT)
            flakes.append(dict(item, base_sha=report['sha'], source=SOURCE, owner=owner, unit=unit,
                               defect=defects.defect_id(item['id'], item['signature'])))
            lines.setdefault(item['stage'], []).append(gate_classify.flake_passed(item['id']))
        else:
            lines.setdefault(item['stage'], []).append(gate_classify.flake_own(item['id'], 'it failed again on the one re-run'))
    for stage, text in lines.items():
        note(logs, stage, text)
    report['flakes'] = flakes
    if not flakes:
        return flakes
    report['known_defects'] = list(report.get('known_defects') or []) + flakes
    excused = known | {item['id'] for item in flakes}
    for stage in report['stages']:
        tests = [item for item in found if item['stage'] == stage['name']]
        flaked = [item for item in flakes if item['stage'] == stage['name']]
        if stage['result'] == 'FAIL' and flaked and all(item['id'] in excused for item in tests):
            stage['raw_result'], stage['result'], stage['class'] = 'FAIL', 'PASS', gate_classify.FLAKE_CLASS
            stage['defects'] = sorted({item['defect'] for item in report['known_defects'] if item['stage'] == stage['name']})
    if all(stage['result'] != 'FAIL' for stage in report['stages']):
        report['result'] = 'PASS'
    return flakes


def window_count(log, test, now):
    """test.flaked events of `test` in `log` that occurred inside gate-flake.quarantine_window_s before `now`."""
    start = now - timedelta(seconds=setting('quarantine_window_s'))
    return sum(1 for event in forge_events.dedupe(log)[0] if event['type'] == FLAKED and event['payload']['test'] == test
               and start <= datetime.fromisoformat(event['occurred_at'].replace('Z', '+00:00')) <= now)


def events(report, logs, port, repo, reader=None):
    """test.flaked for each flake and test.quarantined for each that reached gate-flake.quarantine_after inside the
    window, on the repository channel. An unreadable log still yields test.flaked and decides no quarantine. Each
    flake item gets `flaked_in_window` and `quarantined` (open after this run) for the reader."""
    flakes = report.get('flakes') or []
    if not flakes:
        return []
    try:
        log = (reader or (lambda: port.read_recent(repo, kinds=[FLAKED, QUARANTINED, UNQUARANTINED])))()  # D-085
    except Exception:  # noqa: BLE001 - an unreadable log quarantines nothing; the flake is still recorded and listed
        log = None
    open_, now, built = quarantine.state(log or []), port.clock.now(), []
    for item in flakes:
        subject = forge_events.subject(repo, None, item['base_sha'], (), item.get('unit'))
        flaked = port.build(FLAKED, dict(subject, test=item['id'], log=str(stage_log(logs, item['stage']))))
        built.append(flaked)
        count = (window_count(log, item['id'], now) + (flaked['event_id'] not in {e['event_id'] for e in log})) if log is not None else None
        item['flaked_in_window'] = count
        if count is not None and count >= setting('quarantine_after') and item['id'] not in open_:
            built.append(port.build(QUARANTINED, dict(subject, test=item['id'], owner=item['owner'],
                                                      flaked_event=flaked['event_id'])))
            open_[item['id']] = {'owner': item['owner']}
        item['quarantined'] = item['id'] in open_
    return built
