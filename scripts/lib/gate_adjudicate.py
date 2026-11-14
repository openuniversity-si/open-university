"""Known-defect adjudication of a gate report and its events (GX-39 seam, moved from gate_report; KD1), then flake
attribution of what is still the PR's own (TX11, gate_flake.py: one re-run at the same head), then the base class of
what is red on the base head too (F73, gate_classify.attribute_base).

The registry reads (`tier1_modes`, `repo`) stay in gate_report and are passed in."""
from pathlib import Path

import gate_tier


def defect_events(report, mode, sha, logs, port, tier1_modes, repo):
    """KD1: defect.detected for each known base defect and defect.verified/reopened for each resolved defect the base
    now passes/fails, on the repository channel (the registry applies them with `scripts/defects sync`)."""
    import forge_events
    import gate_flake
    events = []
    if not gate_tier.adjudicated(mode, tier1_modes):
        return events
    run = Path(logs).resolve().parent.name
    subject = forge_events.subject(repo, None, report.get('base_sha'))
    for item in report.get('known_defects') or []:
        events.append(port.build('defect.detected', dict(
            subject, defect=item['defect'], test=item['id'], signature=item['signature'], owner=item['owner'],
            base_sha=item['base_sha'], stage=item['stage'], run=run)))
    for item in report.get('defect_decisions') or []:
        kind = 'defect.verified' if item['result'] == 'verified' else 'defect.reopened'
        extra = {} if item['result'] == 'verified' else {'observed_signature': item['signature']}
        events.append(port.build(kind, dict(
            subject, defect=item['defect'], test=item['test'], signature=item['recorded_signature'], owner=item['owner'],
            base_sha=report['base_sha'], run=run, **extra)))
    events += gate_flake.events(report, logs, port, repo)  # TX11: test.flaked, and test.quarantined on the second sighting
    return events


def adjudicate(report, logs, mode, tier1_modes):
    """KD1: re-run the failing tests on the integration base; a stage whose failing tests all fail there with the same
    signature is reported PASS and the tests are listed as known defects. Also checks the resolved defects on the base."""
    import defect_detect
    import defects
    import gate_classify
    import gate_flake
    if not gate_tier.adjudicated(mode, tier1_modes):
        return
    base = defect_detect.recorded_base()  # GX-13: the proof's base (OU_GATE_BASE_SHA), not a local ref
    report['base_sha'] = base
    if report['result'] != 'PASS':
        changed = defect_detect.changed_files(base, report.get('sha'))  # GX-13: a touched test is never excused
        defect_detect.apply_to_report(report, logs, base, changed=changed)
        for item in report.get('known_defects') or []:
            item['owner'] = defects.derive_owner(item['id'], defect_detect.ROOT)[1]
        gate_flake.attribute(report, logs, changed=changed)  # TX11: a test still red is re-run once at the same head
        gate_classify.attribute_base(report, logs, base)  # F73: a test still red that is red on the base head too: class base
    records, problems = defects.load(defect_detect.ROOT)
    if base and not problems:
        report['defect_decisions'] = [dict(item, test=records[item['defect']]['test'], owner=records[item['defect']]['owner'],
                                           recorded_signature=records[item['defect']]['signature'])
                                      for item in defect_detect.verification(records, base)]
