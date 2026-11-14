"""GV1 (D-069): one live, readable gate status comment per PR head and gate mode.

The comment starts with gate.status_marker, the head sha and the mode, so it is found again and edited in place, never
duplicated. It shows, in order: the planned stages with their expected duration (median of the last local runs) and a
total estimate; each stage as it starts and ends; then the final table (failing tests and signatures, known base defects,
tests reused from the cache, one-line verdict) with the machine events collapsed below it.

GX-17: the same module also sets the commit status `forge-events.status_context_gate` (tower/gate) of the head through the
forge port: pending at begin, success or failure from the verdict. A refusal (403: the identity lacks statuses:write) is
printed once per run as `status: unavailable (403)` and the run goes on; nothing here touches Vercel.

F37 (D-299): the check run is its own switch. gate.check_run_enabled alone creates the run's state and writes tower/gate on
the judged head (pending, then the verdict) with no comment, no gate.started and no verdict hooks: those stay the panel's
(gate.status_enabled). forge-events.status_enabled still turns every status write off.

GX-25: at the first begin it also publishes `gate.started` (gate-eta.started_enabled) with the ETA: per stage the
gate-eta.eta_quantile of its newest gate-eta.eta_history_events `engine.step.measured` in the ledger, else the local report
history, else gate-eta.fallback_stage_s; the wall is the critical path over gate-stages.json, never the sum. On a tier-1
verdict `final` calls forge_events.gate_slow and slo.run (event-driven, P-32).

This module renders and publishes only. It never selects, classifies, caches or compares tests (KD1, GS1), and a failure
to write the comment is reported on stderr and never changes the gate result.

CLI (shell producers; every command exits 0):
  gate_status.py begin       --logs DIR --sha SHA --pr N --mode MODE   create/replan the state and publish
  gate_status.py stage-start --logs DIR --name STAGE
  gate_status.py stage-end   --logs DIR --name STAGE                   reads DIR/<stage>.stage.json
"""
import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import statistics
import sys
import time

import config
from forge_events import ForgeCompatibilityError

STATE_FILE = 'status.json'
LOCK_FILE = 'status.lock'
VERSION = 1  # contracts/gate-status/v1.json: additive within the version
BLOCKS, MERGEABLE = 'BLOCKS', 'MERGEABLE'
ICON = {'pending': '⏳', 'running': '🔄', 'passed': '✅', 'failed': '❌', 'cached': '♻️'}


def short(sha):
    """The abbreviated sha shown in the comment (gate.status_sha_chars)."""
    return sha[:config.get('gate.status_sha_chars')]


def slug(name):
    return re.sub(r'[^a-zA-Z0-9]', '_', name)


def marker_line(sha, mode):
    """First line of the comment. One per PR (GX-16, gate.status_one_per_pr): the marker alone, so every head and mode of
    the PR finds and edits the same comment (the +advisory view keeps its own); otherwise the old one comment per head and mode."""
    if config.get('gate.status_one_per_pr') and not mode.endswith(ADVISORY):
        return config.get('gate.status_marker')
    return f'{config.get("gate.status_marker")} sha={sha} mode={mode}'


ADVISORY = '+advisory'  # the pinned gate's report-only view (gate_pin.py): its own comment, never the PR's status
HEAD_LINE = re.compile(r'^<!-- head sha=(?P<sha>[0-9a-f]+) mode=(?P<mode>\S+) -->$', re.M)
EARLIER = re.compile(r'^- head `([0-9a-f]+)` (\S+): (.*)$', re.M)
VERDICT = re.compile(r'^\*\*(BLOCKS|MERGEABLE)\*\*', re.M)


def earlier_heads(previous, state):
    """GX-16: the one-line outcomes of the heads this comment showed before, newest last, the current head left out and
    at most gate.status_earlier_heads kept. previous is the body being replaced (None: nothing to carry)."""
    if not previous:
        return []
    kept = [f'- head `{sha}` {mode}: {text}' for sha, mode, text in EARLIER.findall(previous)]
    shown = HEAD_LINE.search(previous)
    if shown and (shown['sha'], shown['mode']) != (state['sha'], state['mode']):
        verdict = VERDICT.search(previous)
        kept.append(f'- head `{short(shown['sha'])}` {shown['mode']}: {verdict.group(1) if verdict else "superseded before a verdict"}')
    kept = [line for line in kept if not line.startswith(f'- head `{short(state["sha"])}` {state["mode"]}:')]
    return kept[-config.get('gate.status_earlier_heads'):]


def render_earlier(lines):
    if not lines:
        return ''
    return ('\n<details><summary>Earlier heads of this PR (superseded)</summary>\n\n' + '\n'.join(lines) + '\n\n</details>\n')


def seconds_text(value):
    if value is None:
        return '–'
    value = int(round(value))
    return f'{value // 60}m{value % 60:02d}s' if value >= 60 else f'{value}s'


def cell(text, limit=None):
    """A table cell: one line, no pipe or newline, optionally cut."""
    text = ' '.join(str(text or '').replace('|', '\\|').split())
    return text if limit is None or len(text) <= limit else text[:limit - 1] + '…'


def history(record_dir, names):
    """{stage: expected seconds} from the passing stage files of the newest runs under record_dir/reports."""
    runs = config.get('gate.status_history_runs')
    files = sorted(Path(record_dir).glob('reports/*/*/stages.json'), key=lambda path: path.stat().st_mtime, reverse=True)
    seen = {name: [] for name in names}
    for path in files[:runs]:
        for stage in sorted(path.parent.glob('*.stage.json')):
            try:
                data = json.loads(stage.read_text())
            except (OSError, ValueError):
                continue
            if data.get('name') in seen and data.get('result') == 'PASS' and not data.get('cached'):
                seen[data['name']].append(float(data['seconds']))
    return {name: statistics.median(values) for name, values in seen.items() if values}


def stage_needs():
    """{stage: [needs]} of gate-stages.json; empty when the file cannot be read (the ETA then sums nothing in series)."""
    try:
        import gate_graph
        return {name: list(spec.get('needs') or []) for name, spec in gate_graph.load().items()}
    except ForgeCompatibilityError:
        raise
    except Exception:  # noqa: BLE001 - the graph is advice for the ETA, never a reason to fail the gate
        return {}


def expectation(record_dir, planned, publisher):
    """GX-25: {stage: seconds} for the planned stages, from the ledger, else the local history, else the fallback.
    Never empty for a planned stage, so the panel and gate.started never say 'no history'."""
    import slo
    events = []
    try:
        events = slo.ledger_steps(publisher.events.adapter, publisher.repo)
    except ForgeCompatibilityError:
        raise
    except Exception as error:  # noqa: BLE001 - an unreadable ledger leaves the local history and the fallback
        print(f'gate eta: ledger not read ({error})', file=sys.stderr)
    found = slo.expected_seconds(events, planned, config.get('gate-eta.eta_quantile'), config.get('gate-eta.eta_history_events'),
                                 config.get('gate-eta.fallback_stage_s'), local=history(record_dir, planned))
    return {name: row['seconds'] for name, row in found.items()}


def wall_estimate(expected, names=None):
    """(seconds, [stage...]) of the critical path over the stage graph for `names` (default: every expected stage)."""
    import gate_timing_report
    return gate_timing_report.critical_path(expected, stage_needs(), names)


def publish_started(publisher, state, expected):
    """GX-25: publish gate.started v1 for this head (once: its natural key is repo, pr, sha, plan). Never raises."""
    if not config.get('gate-eta.started_enabled'):
        return
    try:
        import forge_events
        import gate_tier
        tier = gate_tier.current(state['mode'], config.get('forge-events.tier1_gate_modes'))
        if tier is None:
            return
        premises = []
        try:
            premises = forge_events.premises_from_body(publisher.port.change(publisher.repo, state['pr'])['body'])
        except ForgeCompatibilityError:
            raise
        except Exception:  # noqa: BLE001 - premises are context; the event is still worth publishing
            pass
        seconds, path = wall_estimate(expected, state['planned'])
        publisher.events.emit('gate.started', dict(forge_events.subject(publisher.repo, state['pr'], state['sha'], premises),
                                                  tier=tier, plan=state['mode'], expected_wall_s=round(seconds),
                                                  critical_path=path))
    except ForgeCompatibilityError:
        raise
    except Exception as error:  # noqa: BLE001 - a lifecycle event never changes the gate
        print(f'gate started: not published ({error})', file=sys.stderr)


def verdict_hooks(publisher, verdict):
    """GX-25: on a tier-1 verdict, forge_events.gate_slow and slo evaluate over the log, once, event-driven (P-32, no timer).
    Never raises and never changes the result."""
    payload = (verdict or {}).get('payload') or {}
    if not config.get('gate-eta.started_enabled') or payload.get('tier') != 1:
        return
    try:
        import forge_events
        import gate_verdicts
        import slo
        port, repo = publisher.port, publisher.repo
        events = slo.collect(port.adapter, repo, prs=(payload.get('pr'),) if payload.get('pr') else ())
        verdicts = [event for event in gate_verdicts.accepted(slo.ordered(events)) if event['type'] in gate_verdicts.TYPES]
        fields = forge_events.gate_slow(verdicts)
        if fields:
            forge_events.ForgeEvents(port.adapter, port.clock, port.producer, verdict['event_id']).emit(
                'gate.slow', dict(forge_events.subject(repo, None, None), **fields))
        slo.run(port.adapter, port.clock, repo, events=events)
    except ForgeCompatibilityError:
        raise
    except Exception as error:  # noqa: BLE001 - the verdict is already recorded; this only reports
        print(f'gate verdict hooks: {error}', file=sys.stderr)


def new_state(sha, pr, mode, planned, expected, now):
    return {'version': VERSION, 'sha': sha, 'pr': pr, 'mode': mode, 'started': now, 'planned': list(planned),
            'expected': expected, 'stages': {}, 'last_publish': 0, 'comment_id': None}


def rows(state):
    """(name, state, seconds, expected) for the planned stages, then any other stage that ran."""
    names = list(state['planned']) + [name for name in state['stages'] if name not in state['planned']]
    return [(name, state['stages'].get(name, {}).get('state', 'pending'), state['stages'].get(name, {}).get('seconds'),
             state['expected'].get(name)) for name in names]


def header(state):
    return f'{marker_line(state["sha"], state["mode"])}\n<!-- head sha={state["sha"]} mode={state["mode"]} -->\n### Gate `{state["mode"]}` on `{short(state["sha"])}`'


def render_live(state, now, earlier=''):
    table = rows(state)
    waiting = [name for name, kind, *_ in table if kind in ('pending', 'running')]
    remaining, total = wall_estimate(state['expected'], waiting)[0], wall_estimate(state['expected'], [name for name, *_ in table])[0]
    done = sum(1 for _, kind, *_ in table if kind in ('passed', 'failed', 'cached'))
    lines = [header(state), '',
             f'**Running** · {done}/{len(table)} stages done · elapsed {seconds_text(now - state["started"])} · '
             f'expected time left {seconds_text(remaining)} of {seconds_text(total)} (critical path; stages overlap)', '',
             '| Stage | State | Duration | Expected |', '|---|---|---|---|']
    for name, kind, seconds, expected in table:
        lines.append(f'| {cell(name)} | {ICON[kind]} {kind} | {seconds_text(seconds)} | {seconds_text(expected)} |')
    return '\n'.join(lines) + '\n' + earlier


def verdict_line(report, failing, known_ids):
    """BLOCKS or MERGEABLE in one line, with the reason."""
    own = [item for item in failing if item['id'] not in known_ids]
    missing = report.get('missingStages') or []
    failed_stages = [stage['name'] for stage in report['stages'] if stage['result'] == 'FAIL']
    if report['result'] == 'PASS':
        base = f'{len(known_ids)} failing test(s) are known base defects' if known_ids else 'every planned stage passed'
        return f'**{MERGEABLE}** — {base}.'
    if own:
        return f'**{BLOCKS}** — {len(own)} failing test(s) are not known base defects (first: `{own[0]["id"]}`).'
    if missing:
        return f'**{BLOCKS}** — gate stage(s) did not run: {", ".join(missing)}.'
    if failed_stages:
        return f'**{BLOCKS}** — stage(s) failed without a test id: {", ".join(failed_stages)}.'
    return f'**{BLOCKS}** — the gate failed before any stage result (see the run log).'


def failed_detail(logs, name):
    """GX-16: ` (class code) · log <path>` of a red stage: the class is the machine line gate_classify.py printed into the
    stage log (gate.class_line_prefix), the path is that log, so the author opens the evidence without a search."""
    path = Path(logs) / f'{slug(name)}.log'
    prefix = config.get('gate.class_line_prefix') + ' '
    kind = None
    try:
        for line in path.read_text(errors='replace').splitlines():
            if line.startswith(prefix) and '\t' in line:
                kind = line.rsplit('\t', 1)[1].strip()
    except OSError:
        return ''
    return (f' (class {cell(kind)})' if kind else '') + f' · log `{cell(path)}`'


def redact(value, env=None):
    """`value` without credentials: URLs, forge tokens, auth headers, key=value secrets and the opaque credentials the
    process environment holds; terminal escapes and unprintable characters are dropped."""
    value = re.sub(r'(?i)\b[a-z][a-z0-9+.-]*://[^\s<>"\']+', '[redacted-url]', value)
    value = re.sub(r'(?i)\b(?:gh[pousr]_[\w-]+|github_pat_[\w-]+|crsr_[\w-]+)', '[redacted-token]', value)
    value = re.sub(r'(?i)\b(?:bearer|basic)\s+\S+', '[redacted-auth]', value)
    value = re.sub(r'(?i)\b([\w-]*(?:token|password|secret|api[_-]?key)[\w-]*\s*[=:]\s*)\S+', r'\1[redacted]', value)
    shortest = config.get('gate.status_redact_min_chars')
    for key, secret in (os.environ if env is None else env).items():
        if re.search(r'(?i)token|password|secret|api_?key|database_url', key) and len(secret) >= shortest:
            value = value.replace(secret, '[redacted]')
    value = re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', value)
    return ''.join(c for c in value if c in '\n\t' or c.isprintable())


def render_final(state, report, failing, total, cached, known, events, elapsed, earlier='', logs=None):
    """The final comment. failing: gate_failures items; known: report known_defects; events: envelopes (dicts)."""
    known_by_id = {item['id']: item for item in known}
    merged = list(failing) + [{'id': item['id'], 'stage': item['stage'], 'signature': item['signature']}
                              for item in known if item['id'] not in {entry['id'] for entry in failing}]
    lines = [header(state), '', verdict_line(report, failing, set(known_by_id)), '',
             f'Finished in {seconds_text(elapsed)}.', '', '| Stage | Result | Duration | Expected |', '|---|---|---|---|']
    results = {stage['name']: stage for stage in report['stages']}
    for name in list(state['planned']) + [name for name in results if name not in state['planned']]:
        stage = results.get(name)
        kind = 'pending' if stage is None else ('cached' if stage.get('cached') else 'passed' if stage['result'] == 'PASS' else 'failed')
        label = kind if stage else 'did not run'
        if kind == 'failed' and logs is not None:  # GX-16: the D-027 class and the log of every red row
            label += failed_detail(logs, name)
        lines.append(f'| {cell(name)} | {ICON[kind]} {label} | '
                     f'{seconds_text(stage["seconds"] if stage else None)} | {seconds_text(state["expected"].get(name))} |')
    if merged:
        lines += ['', f'**Failing tests ({len(merged)}{"" if total is None or total == len(failing) else f" of {total}"})**', '',
                  '| Test | Stage | Error signature | Known base defect |', '|---|---|---|---|']
        for item in merged:
            defect = known_by_id.get(item['id'], {}).get('defect')
            # GX-16: a failing-test row carries a log line (its error signature); it is redacted here, before any forge
            # sees the body, so a token or URL a test printed never reaches the comment (D-293: whatever the forge)
            lines.append(redact(f'| `{cell(item["id"], 120)}` | {cell(item["stage"])} | {cell(item["signature"], 120)} | '
                                f'{"yes: " + cell(defect) if defect else "no"} |'))
    if cached:
        lines += ['', f'<details><summary>{len(cached)} test(s) reused from the cache</summary>', '']
        lines += [f'- `{cell(item["id"], 120)}` (key `{short(str(item["key"]))}`, run {cell(item["source"], 60)})' for item in cached]
        lines += ['', '</details>']
    body = '\n'.join(lines) + '\n' + earlier
    return body + render_events(events, config.get('gate.status_max_chars') - len(body))


def render_events(events, room):
    """The forge_events jsonl, collapsed. Cut to fit; an event that does not fit is dropped whole."""
    if not events:
        return ''
    head, tail = '\n<details><summary>forge_events (machine)</summary>\n\n```jsonl\n', '\n```\n\n</details>\n'
    kept, used = [], len(head) + len(tail)
    for event in events:
        line = json.dumps(event, sort_keys=True, separators=(',', ':'))
        if used + len(line) + 1 > room:
            break
        kept.append(line)
        used += len(line) + 1
    return head + '\n'.join(kept) + tail if kept else ''


class Publisher:
    """Creates the head's status comment once and edits it in place, through the forge adapter (D-069 item 7)."""

    def __init__(self, port=None):
        if port is None:
            import forge_events
            port = forge_events.ForgeEvents(forge_events.adapter_from_config(), forge_events.clock_from_config(),
                                            config.get('forge-events.gate_producer'), 'gate:status')
        self.port = port
        self.events = port  # GX-25: where lifecycle events go; a test may point it at an in-memory log
        self.repo = config.get('forge-events.repo')

    def set_status(self, sha, github_state, description, landing=False):
        """CHECK-IN-LANDING: with landing, the check run's body when the landing posts it (the port's route), else None
        once published."""
        return self.port.set_status(self.repo, sha, config.get('forge-events.status_context_gate'), github_state, description,
                                    **({'landing': True} if landing else {}))

    def publish(self, state, body, best_effort=False):
        """The comment id; found by its first line (marker, sha, mode) unless the run already stored it. A best-effort
        (live) edit never waits for the write budget (GX-FIX-forge-rate): it is dropped and the next one carries it."""
        return self.port.upsert_comment(
            self.repo, state['pr'], marker_line(state['sha'], state['mode']), body, comment_id=state.get('comment_id'),
            pages=config.get('gate.status_find_pages'), timeout=config.get('gate.status_timeout_s'),
            **({'max_wait_s': 0} if best_effort else {}))


def status_description(kind, state, verdict, wall):
    """The commit status text: result, tier, plan, wall time and the input_digest prefix when the verdict has one."""
    payload = (verdict or {}).get('payload') or {}
    tier = payload.get('tier')
    parts = [kind, f'tier {tier if tier is not None else "-"}', f'plan {payload.get("plan") or state["mode"]}']
    if wall is not None:
        parts.append(seconds_text(wall))
    digest = payload.get('input_digest')
    if digest:
        parts.append(f'input {str(digest)[:config.get('forge-events.status_digest_chars')]}')
    text = ' · '.join(parts)
    limit = config.get('forge-events.status_description_chars')
    return text if len(text) <= limit else text[:limit - 1] + '…'


def set_status(store, publisher, github_state, description):
    """Write the tower/gate commit status of the run's head. Never raises; the first refusal is printed and the rest of
    the run writes no more statuses."""
    state = store.state
    if not config.get('forge-events.status_enabled') or state.get('status_unavailable'):
        return
    try:
        publisher.set_status(state['sha'], github_state, description)
    except ForgeCompatibilityError:
        raise
    except Exception as error:  # noqa: BLE001 - a status write never changes the gate
        state['status_unavailable'] = True
        code = str(error).split(':', 1)[0]
        print(f'status: unavailable ({code if code.isdigit() else error})', file=sys.stderr)
    store.save()


class Store:
    """The run's state file under the logs directory, locked so parallel stages update it one at a time."""

    def __init__(self, logs):
        self.path, self.lock_path = Path(logs) / STATE_FILE, Path(logs) / LOCK_FILE

    def exists(self):
        return self.path.is_file()

    def __enter__(self):
        self.handle = self.lock_path.open('a')
        fcntl.flock(self.handle, fcntl.LOCK_EX)
        self.state = json.loads(self.path.read_text()) if self.path.is_file() else None
        return self

    def save(self):
        self.path.write_text(json.dumps(self.state, indent=2))

    def __exit__(self, *exc):
        self.handle.close()


def push(store, publisher, render, now, force):
    """Publish render(earlier) when forced or the minimum interval has passed; remember the comment id. Never raises.
    earlier is the collapsed block of the heads this PR's comment showed before (GX-16)."""
    state = store.state
    if not config.get('gate.status_enabled') or (not force and now - state['last_publish'] < config.get('gate.status_min_interval_s')):
        store.save()
        return
    try:
        def body(previous):
            if previous is not None or 'earlier' not in state:
                state['earlier'] = earlier_heads(previous, state)
            return render(render_earlier(state['earlier']))

        state['comment_id'] = publisher.publish(state, body, **({} if force else {'best_effort': True}))
        state['last_publish'] = now
    except ForgeCompatibilityError:
        raise
    except Exception as error:  # noqa: BLE001 - a status write never changes the gate
        print(f'gate status: not published ({error})', file=sys.stderr)
    store.save()


def begin(logs, sha, pr, mode, record_dir, publisher=None, now=None):
    """Create the state (or replan it when the scoped plan arrives later) and publish the start comment and gate.started."""
    import gate_report
    panel = config.get('gate.status_enabled')
    if not panel and not config.get('gate.check_run_enabled'):
        return
    now = time.time() if now is None else now
    planned = gate_report.expected_stages(mode, Path(logs))
    with Store(logs) as store:
        publisher = publisher or Publisher()
        expected = expectation(record_dir, planned, publisher) if panel else {}  # F37: the ETA is the panel's
        if store.state is None:
            store.state = new_state(sha, int(pr), mode, planned, expected, now)
            push(store, publisher, lambda earlier: render_live(store.state, now, earlier), now, True)
            set_status(store, publisher, 'pending', status_description('running', store.state, None, None))
            if panel:
                publish_started(publisher, store.state, expected)
        else:  # GX-16: the second begin (the scoped plan) only replans; the next stage end carries it, no extra write
            store.state.update(planned=planned, expected=expected)
            store.save()


def trails_held():
    """TRAIL-AFTER-LANDING: the status trails asked while the gate judges and lands, written once it landed."""
    import forge_events
    return forge_events.trails_held()


def check_hooks(sha, publisher=None, log=None, mode='infra'):
    """D-313 (F37-INFRA-CHECK): (pending(), before_landing(ok, red, seconds)) that publish tower/gate on `sha` through the gate's own
    publisher (gate_status; forge-events.check_run_publisher chooses the control plane), or None when
    gate.check_run_enabled is off. A failed publish is logged and the delivery goes on, unless gate.check_run_required
    (the forge requires the check): then it raises and nothing merges. A red verdict never needs the publish to stop."""
    if not config.get('gate.check_run_enabled') or not config.get('forge-events.status_enabled'):
        return None
    log = log or (lambda text: print(text, file=sys.stderr, flush=True))
    state = {'mode': mode}  # EMERGENCY-EXIT-CHECK: `box` when the box's gate judged (scripts/lib/deliver.py box_check)

    def publish(github_state, text, blocks, landing=False):
        try:
            return (publisher or Publisher()).set_status(sha, github_state, text, **({'landing': True} if landing else {}))
        except ForgeCompatibilityError:
            raise
        except Exception as error:  # noqa: BLE001 - the publisher's failure is the delivery's to judge, not a crash
            if blocks and config.get('gate.check_run_required'):
                raise RuntimeError(f'tower/gate {github_state} not published ({error}); gate.check_run_required: '
                                   'nothing merged') from error
            log(f'gate status: tower/gate {github_state} not published ({error}); the delivery goes on')

    def pending():
        publish('pending', status_description('running', state, None, None), True)

    def before_landing(ok, red, seconds, landing=False):
        """CHECK-IN-LANDING: with landing (the infra gate's own landing follows), a success that the landing job posts
        (gate.check_in_landing, through the port) comes back as its body, unpublished; else it is published, None."""
        landing = bool(landing and ok and publisher is None and config.get('gate.check_in_landing')
                       and config.get('forge-events.adapter') == 'origin'
                       and config.get('forge-events.check_run_publisher') == 'port')
        return publish('success' if ok else 'failure',
                       status_description('passed' if ok else 'failed', state, None, seconds), ok, landing)
    return pending, before_landing


def stage_event(logs, name, ending, publisher=None, now=None):
    now = time.time() if now is None else now
    with Store(logs) as store:
        if store.state is None:
            return
        entry = store.state['stages'].setdefault(name, {})
        if not ending:
            entry.update(state='running', started=now)
        else:
            path = Path(logs) / f'{slug(name)}.stage.json'
            data = json.loads(path.read_text()) if path.is_file() else {}
            entry.update(state='passed' if data.get('result') == 'PASS' else 'failed', seconds=data.get('seconds'))
        if ending and config.get('gate.status_enabled'):  # GX-16: the comment is edited at stage end; F37: panel only
            push(store, publisher or Publisher(), lambda earlier: render_live(store.state, now, earlier), now, False)
        else:
            store.save()


def final(logs, report, failing, total, cached, known, events, publisher=None, now=None, inline_hooks=False):
    """Publish the final comment of the run; True when a status existed for it. The verdict hooks run detached when
    the run publishes through the forge (no publisher passed in) and gate.verdict_hooks_detached is on; inline when a
    publisher is passed in or inline_hooks asks for it (a test that bounds every read of the run)."""
    detached = publisher is None and not inline_hooks
    now = time.time() if now is None else now
    with Store(logs) as store:
        if store.state is None:
            return False
        publisher = publisher or Publisher()
        wall = now - store.state['started']
        push(store, publisher, lambda earlier: render_final(store.state, report, failing, total, cached, known, events, wall,
                                                      earlier, logs), now, True)
        verdict = next((event for event in reversed(events) if event.get('type') in ('gate.passed', 'gate.failed')), None)
        passed = report['result'] == 'PASS'
        set_status(store, publisher, 'success' if passed else 'failure',
                   status_description('passed' if passed else 'failed', store.state, verdict, wall))
    if not config.get('gate.status_enabled'):
        return True  # F37 (D-299): a check-run-only run publishes the verdict and nothing else
    if detached and config.get('gate.verdict_hooks_detached') and verdict:
        detach_hooks(logs, verdict)  # GATE-SPEED R4: the verdict answers first; the hooks finish on their own
    else:
        verdict_hooks(publisher, verdict)  # GX-25: after the lock; the verdict is the wake (P-32)
    return True


HOOKS_FILE = 'verdict-hooks.json'


def detach_hooks(logs, verdict):
    """GATE-SPEED R4 (D-092): run verdict_hooks (gate.slow and the SLO evaluation, which read every PR channel the
    repository window names) in a process of its own session, after the verdict is published and recorded, so the gate
    does not wait for them. Its output goes to verdict_hooks.log in the run's logs. A process that cannot start runs
    the hooks here instead. Never raises."""
    import subprocess
    try:
        path = Path(logs) / HOOKS_FILE
        path.write_text(json.dumps(verdict))
        with open(Path(logs) / 'verdict_hooks.log', 'ab') as log:
            subprocess.Popen([sys.executable, str(Path(__file__).resolve()), 'verdict-hooks', '--logs', str(logs)],
                             stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
    except ForgeCompatibilityError:
        raise
    except Exception as error:  # noqa: BLE001 - the hooks only report
        print(f'gate verdict hooks: not detached ({error}); running them now', file=sys.stderr)
        verdict_hooks(Publisher(), verdict)


def final_from_report(logs, report, events=(), publisher=None, now=None):
    """The gate_report call site: derive the failing tests, cached tests and known defects from the report and logs."""
    import gate_failures
    failing, total = [], 0
    if report['result'] != 'PASS' and config.get('gate.status_enabled'):  # F37: only the panel renders the failures
        failing, total = gate_failures.failing(logs)
    return final(logs, report, failing, total, gate_failures.cached_tests(logs), report.get('known_defects') or [],
                 list(events), publisher=publisher, now=now)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('command', choices=['begin', 'stage-start', 'stage-end', 'verdict-hooks'])
    parser.add_argument('--logs', required=True)
    parser.add_argument('--sha')
    parser.add_argument('--pr')
    parser.add_argument('--mode')
    parser.add_argument('--name')
    parser.add_argument('--record-dir')
    args = parser.parse_args(argv)
    try:
        if args.command == 'verdict-hooks':
            verdict_hooks(Publisher(), json.loads((Path(args.logs) / HOOKS_FILE).read_text()))
        elif args.command == 'begin':
            if args.pr and args.sha and re.fullmatch(r'[0-9a-f]{40}', args.sha):
                begin(args.logs, args.sha, args.pr, args.mode, args.record_dir)
        else:
            stage_event(args.logs, args.name, args.command == 'stage-end')
    except ForgeCompatibilityError:
        raise
    except Exception as error:  # noqa: BLE001 - never fails the gate
        print(f'gate status: {error}', file=sys.stderr)
    return 0


if __name__ == '__main__':
    sys.exit(main())
