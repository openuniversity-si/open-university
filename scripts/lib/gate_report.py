"""Persist stage outcomes, without subprocess payloads.

With a PR and a commit, the verdict is also THE gate evidence (D-065): gate.passed or gate.failed through the
forge_events port, plus one engine.step.measured per stage (D-069 item 6), in one append on the PR's channel.
"""
import json
import os
from pathlib import Path
import re
import sys
from gate_policy import PLANS
import gate_adjudicate
import gate_classify
import gate_proof
import gate_publish
import config


def stage_results(logs):
    results = []
    for path in sorted(logs.glob('*.stage.json')):
        results.append(json.loads(path.read_text()))
    return results


def expected_stages(mode, logs):
    """Stages this gate must have passed. A scoped dev plan replaces the full dev list."""
    expected = list(PLANS.get(mode, PLANS['full']))
    plan_path = Path(logs) / 'plan.json'
    if mode != 'dev' or not plan_path.is_file():
        return expected
    try:
        plan = json.loads(plan_path.read_text())
    except (OSError, ValueError):
        return expected
    if plan.get('kind') not in ('scoped', 'full') or not isinstance(plan.get('stages'), list):
        return expected
    owned = set(PLANS['dev']) | {'script tests'}
    return [stage for stage in plan['stages'] if stage in owned]


def stage_log(logs, name):
    path = Path(logs) / (re.sub(r'[^a-zA-Z0-9]', '_', name) + '.log')
    return path.read_text(errors='replace') if path.is_file() else ''


def gate_events(report, mode, pr, logs, port, premises):
    """The verdict and per-stage measurements of one gate run, built (not yet published) on the port."""
    import config
    import forge_events
    subject = forge_events.subject(config.get('forge-events.repo'), pr, report['sha'], premises)
    tier1_modes = config.get('forge-events.tier1_gate_modes')
    log_of = lambda name: stage_log(logs, name)
    stages = gate_proof.stage_records(report, log_of)
    events = gate_proof.step_events(port, subject, config.get('forge-events.gate_step_prefix'), stages)
    verdict = gate_proof.verdict_payload(report, mode, subject, stages, expected_stages(mode, logs), tier1_modes, logs)
    events += defect_events(report, mode, report['sha'], logs, port)
    events.append(port.build('gate.passed' if report['result'] == 'PASS' else 'gate.failed', verdict, gate_proof.version_of(verdict)))  # the verdict stays last
    return events


def defect_events(report, mode, sha, logs, port):
    """KD1 events (gate_adjudicate.defect_events) with the registry's tier-1 modes and repository."""
    import config
    return gate_adjudicate.defect_events(report, mode, sha, logs, port, config.get('forge-events.tier1_gate_modes'),
                                         config.get('forge-events.repo'))


def adjudicate_known_defects(report, logs, mode):
    """KD1 adjudication (gate_adjudicate.adjudicate) with the registry's tier-1 modes."""
    import config
    gate_adjudicate.adjudicate(report, logs, mode, config.get('forge-events.tier1_gate_modes'))


def emit_evidence(report, mode, pr, logs, port=None, change=None):
    """Publish the gate events; returns the verdict envelope. The PR body's Premises: line goes in every payload."""
    import config
    import forge_events
    if port is None:
        port = forge_events.ForgeEvents(forge_events.adapter_from_config(), forge_events.clock_from_config(),
                                        config.get('forge-events.gate_producer'), gate_publish.channel(mode, logs))
    try:
        premises = forge_events.premises_from_body((change or port.change(config.get('forge-events.repo'), pr))['body'])
    except forge_events.ForgeCompatibilityError:
        raise
    except forge_events.ForgeEventsError:
        premises = []
    events = gate_events(report, mode, pr, logs, port, premises)
    port.publish(events)
    return events[-1]


def ready_hook(verdict, mode, pr, sha, root=None, adapter=None, clock=None, base=None, change=None):
    """EVENTS.md: a pass with a valid body emits pr.ready (pr_ready.ready_after_gate, plan-tick producer like
    scripts/pr-ready). Prints one line; any failure is printed and never changes the gate result."""
    try:
        import config
        import forge_events
        import pr_ready
        if not verdict or verdict.get('type') != 'gate.passed':
            print(f'pr.ready: not emitted (verdict is {(verdict or {}).get("type")}, not gate.passed)')
            return None
        adapter = adapter or forge_events.adapter_from_config()
        port = forge_events.ForgeEvents(adapter, clock or forge_events.clock_from_config(),
                                        config.get('plan-tick.event_producer'), f'pr-{pr}')
        repo = config.get('forge-events.repo')
        change = change or port.change(repo, pr)
        body = change['body']
        root = root or pr_ready.ROOT
        event, reason = pr_ready.ready_after_gate(port, repo, pr, sha, body, root,
                                                  plan=verdict['payload'].get('plan', mode), base=base,
                                                  recorded=change.get('base'), events=[verdict])
        print(f'pr.ready: emitted #{pr} head={pr_ready.short(sha)}' if event else f'pr.ready: not emitted ({reason})')
    except Exception as error:  # noqa: BLE001 - pr.ready is announced after the gate, never part of its result
        print(f'pr.ready: not emitted ({error})')
        return None
    return event


def publish_status(logs, report, verdict):
    """GV1: the final status comment (a no-op without a live status); a failure to write it never changes the result."""
    import gate_status
    try:
        gate_status.final_from_report(logs, report, [verdict] if verdict else [])
    except Exception as error:  # noqa: BLE001
        print(f'gate status: final not published ({error})', file=sys.stderr)


def apply_coverage(report, logs, mode, check_missing):
    """Every expected stage must have passed. A stage a guard skipped (GK1, gate_skips.py) is reported with the failed
    dependency that skipped it, apart from a stage the run never had (missing). Either makes the result FAIL."""
    import gate_skips
    report['skippedStages'] = gate_skips.load(logs)
    skipped = sorted(item['name'] for item in report['skippedStages'])
    if skipped:
        report['result'] = 'FAIL'
        print('FAIL gate stages skipped by a failed dependency: ' + ', '.join(
            f"{item['name']} ({item['reason']})" for item in report['skippedStages']), file=sys.stderr)
    if not check_missing:
        report.setdefault('missingStages', [])
        return
    expected = expected_stages(mode, logs)
    passed = {s['name'] for s in report['stages'] if s['result'] == 'PASS'}
    report['missingStages'] = sorted(set(expected) - passed - set(skipped))
    if report['missingStages']:
        report['result'] = 'FAIL'
        print('FAIL missing gate stages: ' + ', '.join(report['missingStages']), file=sys.stderr)


ABORT_MARKER = 'abort.json'


INCIDENT_FILE = 'incidents.jsonl'  # the gate-refusal record of this run, beside its stages.json (D-240)


def record_incident(report, logs, mode, pr):
    """A FAIL verdict opens its incident: one gate-refusal record in the run's own logs (gate_incident.incident). Best effort: an
    incident that cannot be written never changes the verdict, and a PASS writes nothing."""
    try:
        import gate_incident
        entry = gate_incident.incident(report, mode or '', int(pr) if pr else None)
        if entry is None:
            return None
        gate_incident.record(Path(logs) / INCIDENT_FILE, entry)
        return entry
    except Exception as error:  # noqa: BLE001 - the incident is a record about the refusal, never a second refusal
        print(f'gate incident: not recorded ({type(error).__name__}: {error})', file=sys.stderr)
        return None


def record_abort(logs, stage, rc, message):
    """GX-01: a driver abort is one FAIL stage with its message as the log, plus the marker that tells the report the
    run ended before its stages: no known-defect adjudication, and every expected stage is listed as missing."""
    logs = Path(logs)
    logs.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r'[^a-zA-Z0-9]', '_', stage)
    (logs / f'{slug}.log').write_text(message + '\n')
    (logs / f'{slug}.stage.json').write_text(json.dumps({'name': stage, 'result': 'FAIL', 'exit': rc, 'seconds': 0}))
    (logs / ABORT_MARKER).write_text(json.dumps({'stage': stage, 'exit': rc}))


def observed_change(logs, pr, sha):
    """The fresh metadata read of this run, bound to its PR and gated sha. Never a cross-run cache."""
    try:
        held = json.loads((Path(logs) / 'pr-snapshot.json').read_text())
        change = held['change']
        if held['pr'] == int(pr) and held['sha'] == sha and isinstance(change['body'], str):
            return change
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


@config.reading()
def main(argv, port=None):
    """gate_report.py <logs> <sha> <rc> [<mode> [<pr>]]; or `abort <logs> <stage> <rc> <message>` (record_abort)."""
    if argv[:1] == ['abort']:
        _, folder, stage, code, message = argv
        record_abort(folder, stage, int(code), message)
        return 0
    folder, sha, code, *rest = argv
    logs, rc = Path(folder), int(code)
    mode, pr = (rest + [None, ''])[:len(('mode', 'pr'))]
    mode, pr = mode or None, pr or ''
    aborted = (logs / ABORT_MARKER).is_file()
    report = {'sha': sha, 'result': 'PASS' if rc == 0 else 'FAIL', 'stages': stage_results(logs), 'failingTests': []}
    if aborted:
        report['result'] = 'FAIL'
        report['aborted'] = json.loads((logs / ABORT_MARKER).read_text())
    report['cached'] = [stage['name'] for stage in report['stages'] if stage.get('cached')]
    if mode and not aborted:
        try:
            adjudicate_known_defects(report, logs, mode)
        except Exception as error:  # noqa: BLE001 - a defect lookup that fails never excuses a failure: the run keeps its result
            print(f'known defects: not applied ({error})', file=sys.stderr)
        rc = 0 if report['result'] == 'PASS' else rc
        for stage in report['stages']:  # F73: a class set after the stage ran (base) is the one the gate's output ends with
            if stage['result'] == 'FAIL' and stage.get('class'):
                print(gate_classify.class_line(stage['name'], stage['class']))
    if mode:
        # An aborted run lists every expected stage it never passed (GX-01), as a complete run with a red stage does not.
        apply_coverage(report, logs, mode, rc == 0 or aborted)
    (logs / 'stages.json').write_text(json.dumps(report, indent=2))
    record_incident(report, logs, mode, pr)
    verdict = None
    if gate_publish.should_publish(mode, pr, sha):
        try:
            import config
            import forge_events
            port = port or forge_events.ForgeEvents(forge_events.adapter_from_config(), forge_events.clock_from_config(),
                                                    config.get('forge-events.gate_producer'), gate_publish.channel(mode, logs))
            change = observed_change(logs, pr, sha) or port.change(config.get('forge-events.repo'), int(pr))
            verdict = emit_evidence(report, mode, int(pr), logs, port, change=change)
            print(f'gate evidence: {verdict["type"]} {verdict["event_id"][:12]} on PR #{pr} '
                  f'(+{len(report["stages"])} engine.step.measured)')
        except Exception as error:  # noqa: BLE001 - any failure to record evidence fails the gate, never silently
            print(f'FAIL gate evidence: forge_events could not record the verdict: {error} (class env)', file=sys.stderr)
            publish_status(logs, report, verdict)
            return 1
        # Independent consumers of the acknowledged verdict: neither needs to wait for the other's forge writes.
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor() as writes:
            ready = None
            if verdict['type'] == 'gate.passed':
                ready = writes.submit(ready_hook, verdict, verdict['payload']['plan'], verdict['payload']['pr'], sha,
                                      adapter=port.adapter, change=change)
            status = writes.submit(publish_status, logs, report, verdict)
            status.result()
            if ready is not None:
                ready.result()
    if verdict is None:
        publish_status(logs, report, verdict)
    return 1 if report['result'] != 'PASS' else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
