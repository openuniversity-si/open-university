"""The measures of the phase-1 path (MEDIR 1, P6 F1): the p50 and p99 of what the infrastructure and the delivery
measure, for the numbers ARQUITETURA-ALVO §7 leaves open.

From the tenant's log, read through the port (TOWER_PORT_URL, TOWER_PORT_TOKEN), page by page from a point: the seconds
of the forge's calls to Origin (run.usage forge_merge_s for a merge, forge_view_s for a dry run's view), the seconds of
every run from run.started to run.ended by executor, and the CPU seconds of the checks (run.usage cpu_s). From the
deliveries' logs (~/.cache/the-tower/deliver/pr-*.log): the seconds of `origin pr merge` as scripts/deliver measured
them. Each measure answers its count and its quantiles (nearest rank, medir.quantiles). The webhooks' latency is each
forge.* event's arrival in the log less its eventTime at the forge (webhook_s, P4 F2b), and a cold task's start is in
the runner's own log (`run-container: up`). For the executors whose runs a runner takes (they relay run.running), the
waits INFRA-SVC 5 and INFRA-EXE 1e cut: take_s, from the hand-over to the take (the runner's poll), and dispatch_s,
from a slot that freed to the next run's start when its job was already waiting (the dispatcher's tick).

The cost of each run (MEDIR 2, D-310): its run.usage priced by the tenant's meter rates as the log keeps them
(limit.rate.defined, the last rate of a meter), as cost_<derived meter>:<executor> per run, with their sum; an API
call's tokens in and out become dollars this way (cost_usd:api-bedrock).

The shadow's agreement with the box (GATE-INFRA 4, P5 F3): scripts/deliver keeps the box's verdict on each head the
shadow also judges (box-<pr>-<head>.json beside the shadow's pr-<pr>-<head>.json); the pairs, the PRs whose every pair
agrees out of the medir.shadow_prs the switch needs, the pairs that differ (and those whose shadow could not even
prepare a check, the infrastructure's fault rather than the head's) and the shadow's ready-to-landed seconds. After
the switch (delivery.judge infra) the infrastructure keeps its real verdicts beside them (GATE-INFRA 10), and their
seconds from the last check to the merge are ready_to_merged_s, apart from the shadow's dry runs.

The switch line (MEDIR 4) answers P5 F4's question from P5 F3's two criteria. The PRs judged the same must reach
medir.shadow_prs, and the shadow's ready to landed p50 must be at most the box's merge p50 plus medir.landing_slack_s.
A third came from the rollback of 05/11 (MEDIR 5): the infrastructure judges the heads both timed no slower than the
box's gate, p50 against p50, from the gate's seconds deliver keeps in the box's verdict.
With --since, the seconds to land count only the verdicts kept since that point (a deploy's own samples), while the
agreement keeps every pair.

The webhook ingress from the registry (PORT6): every delivery's pre_send, a lower bound of its ACK, listed when over the limit.
The webhook ACK (PORT4, medir.webhook_ack_limit_s, default 1 s): with --ingress-log the ingress's own lines give the ACK
it took per delivery, cold or warm; any one over the limit is a failure and is listed. webhook_s is another thing (the
registry's arrival less Origin's eventTime, queue and consumer included) and is not the ACK.

  scripts/medir [--since <timestamp>] [--json] [--ingress-log FILE]
"""
import argparse
import bisect
from datetime import datetime
import json
import math
import os
from pathlib import Path
import re
import sys

LIB = Path(__file__).resolve().parent
sys.path.insert(0, str(LIB))
import config  # noqa: E402

MERGED = re.compile(r'^deliver: origin merged #\d+ in ([0-9.]+) s$', re.M)


def quantile(values, fraction):
    """The nearest-rank quantile of the values, or None for none."""
    ordered = sorted(values)
    return ordered[max(math.ceil(fraction * len(ordered)), 1) - 1] if ordered else None


def summary(values, total=False):
    found = {'n': len(values), **{'p' + format(fraction, '.0%').rstrip('%'): quantile(values, fraction)
                                  for fraction in config.get('medir.quantiles')}}
    return {**found, 'sum': sum(values)} if total else found


def events(port, since):
    """Every event of the tenant from `since`, page by page, each once."""
    seen, found = set(), []
    while True:
        page = port.call('POST', '/v1/log/query', {'since': since, 'limit': config.get('medir.log_page')})['events']
        fresh = [event for event in page if event['event_id'] not in seen]
        seen.update(event['event_id'] for event in fresh)
        found += fresh
        if not fresh or len(page) < config.get('medir.log_page'):
            return found
        since = page[-1]['occurred_at']


def orchestration(runs, used):
    """What a forge run spent besides its call to Origin (AWS6): the run's seconds from run.started to run.ended less the
    seconds of its forge_merge_s / forge_view_s usage, as orchestration_s:origin-forge. It is the part of ready_to_landed_s
    the code owns (the workflow, the credential, the end of the run); the dispatcher's wait for the tick is the rest and
    shows in ready_to_landed_s less this and the Origin call. A measure to read the criterion by, never part of it."""
    calls = {}
    for run, _executor, meter, quantity in used:
        if meter in ('forge_merge_s', 'forge_view_s'):
            calls[run] = calls.get(run, 0) + quantity
    found = [(run['end'] - run['start']).total_seconds() - calls[name] for name, run in runs.items()
             if name in calls and run.get('start') and run.get('end')]
    return {'orchestration_s:origin-forge': found} if found else {}


def waits(created, runs):
    """INFRA-SVC 5's and INFRA-EXE 1e's measures, of the executors whose runs a runner takes (they relay run.running):
    take_s, from the hand-over to the take; dispatch_s, from a slot that freed to the next run's start when that run's
    job was already waiting (a job created later waited for nothing). runs: {run: {executor, job, start, running, end}}."""
    measures, taken = {}, {}
    for run in runs.values():
        if run.get('running') and run.get('start'):
            measures.setdefault(f"take_s:{run['executor']}", []).append((run['running'] - run['start']).total_seconds())
            taken.setdefault(run['executor'], []).append(run)
    for executor, mine in taken.items():
        ends = sorted(run['end'] for run in mine if run.get('end'))
        for run in mine:
            freed = bisect.bisect_right(ends, run['start'])
            job_at = created.get(run['job'])
            if freed and job_at is not None and job_at <= ends[freed - 1]:
                measures.setdefault(f'dispatch_s:{executor}', []).append((run['start'] - ends[freed - 1]).total_seconds())
    return measures


def first_checks(created, runs):
    """first_check_s: for each runner task (the runner's name less its slot), the seconds from the job's creation to the end
    of the first run that task took on the fargate-runner executor, the check after a task change (a cold start: image pull,
    setup, checkout). A task is a new name in run.running's `runner`; a run that has not ended or a job never seen counts
    for nothing. FIRST-CHECK-NOT-A-RETRY: a run that is not its job's first attempt (n > 1: the job was already running on
    a task that was lost, a Spot interruption, and was run again from its start on the next one) is no cold start: its
    seconds from the job's creation hold the lost attempt and the wait for a runner. It is first_check_after_loss_s, a
    measure of its own (live 12/11: 620 s read as the cold start's worst). Returns the lists that have something."""
    first = {}
    for run in runs.values():
        task = str(run.get('runner') or '').split('/')[0]
        if task and run.get('running') and run.get('executor') == 'fargate-runner':
            if task not in first or run['running'] < first[task]['running']:
                first[task] = run
    found = {}
    for run in first.values():
        if run.get('end') and created.get(run['job']) is not None:
            name = 'first_check_after_loss_s' if run.get('n', 1) > 1 else 'first_check_s'
            found.setdefault(name, []).append((run['end'] - created[run['job']]).total_seconds())
    return found


def from_log(found):
    """The measures of the infrastructure's log: {name: [values]}, the cost of each run among them."""
    measures, started, rates, used, created, runs = {}, {}, {}, [], {}, {}
    # DEPLOY-CANARY: a canary's job (its job.created says `canary`) is not a check: its events are left out of every
    # measure here (after a deploy it would be the new runner task's first_check_s); its seconds are deploy_canary_s
    canaries = {(event.get('payload') or {}).get('job_id') for event in found
                if event['type'] == 'job.created' and (event.get('payload') or {}).get('canary')}
    for event in found:
        payload = event.get('payload') or {}
        if payload.get('job_id') in canaries:
            continue
        at = datetime.fromisoformat(event['occurred_at'])
        if event['type'] == 'job.created':
            created[payload.get('job_id')] = at
        elif event['type'] in ('run.started', 'run.running', 'run.ended') and payload.get('run_id'):
            run = runs.setdefault(payload['run_id'], {'executor': payload.get('executor'), 'job': payload.get('job_id')})
            run.setdefault({'run.started': 'start', 'run.running': 'running', 'run.ended': 'end'}[event['type']], at)
            run['executor'] = run['executor'] or payload.get('executor')
            if event['type'] == 'run.running' and payload.get('runner'):
                run['runner'] = payload['runner']
            if isinstance(payload.get('n'), int):  # FIRST-CHECK-NOT-A-RETRY: which attempt of its job the run is
                run['n'] = max(run.get('n', 0), payload['n'])
        if event['type'] == 'limit.rate.defined':
            rates.setdefault(payload.get('meter'), {})[payload.get('derived_meter')] = float(payload.get('rate') or 0)
        elif event['type'] == 'run.usage' and isinstance(payload.get('quantity'), (int, float)):
            measures.setdefault(payload.get('meter'), []).append(payload['quantity'])
            used.append((payload.get('run_id'), payload.get('executor'), payload.get('meter'), payload['quantity']))
        elif event['type'].startswith('forge.') and ((payload.get('delivery') or {}).get('event') or {}).get('eventTime'):
            sent = payload['delivery']['event']['eventTime'].replace('Z', '+00:00')
            measures.setdefault('webhook_s', []).append(
                (datetime.fromisoformat(event['occurred_at']) - datetime.fromisoformat(sent)).total_seconds())
        elif event['type'] == 'run.started':
            started[payload.get('run_id')] = event['occurred_at']
        elif event['type'] == 'run.ended' and payload.get('run_id') in started:
            seconds = (datetime.fromisoformat(event['occurred_at'])
                       - datetime.fromisoformat(started[payload['run_id']])).total_seconds()
            measures.setdefault(f"run_s:{payload.get('executor')}", []).append(seconds)
    costs = {}
    for run, executor, meter, quantity in used:
        for derived, rate in (rates.get(meter) or {}).items():
            per_run = costs.setdefault(f'cost_{derived}:{executor}', {})
            per_run[run] = per_run.get(run, 0) + quantity * rate
    measures.update({name: list(per_run.values()) for name, per_run in costs.items()})
    measures.update(waits(created, runs))
    measures.update(first_checks(created, runs))
    measures.update(orchestration(runs, used))
    return measures


def from_shadows(folder, since=None, lock_log=None):
    """Each head the box and the shadow both judged, paired by PR and head; a head the shadow saw move is not compared.
    The agreement counts every pair; the seconds to land count the verdicts kept since `since` (a Unix time), so a
    deploy's effect is read from its own samples (MEDIR 4). A box verdict a backfill kept has no seconds of its own; the
    box's lock log (`lock_log`, delivery.gate_lock_log) holds how long the gate held the box for that PR, which times
    it when it is there."""
    kept_at = {}

    def read(pattern):
        found = {}
        for path in sorted(Path(folder).glob(pattern)):
            try:
                verdict = json.loads(path.read_text(encoding='utf-8'))
                found[(str(verdict['pr']), verdict['head'])] = verdict
                kept_at[id(verdict)] = path.stat().st_mtime
            except (OSError, ValueError, KeyError, TypeError):  # a verdict still being written, or not one
                continue
        return found
    boxes, shadows = read('box-*-*.json'), read('pr-*-*.json')
    recent = [verdict for verdict in shadows.values()
              if since is None or kept_at.get(id(verdict), since) >= since]
    pairs = [(key, boxes[key], shadows[key]) for key in sorted(set(boxes) & set(shadows))
             if shadows[key].get('verdict') != 'moved']
    differ = [{'pr': pr, 'head': head, 'box': box.get('verdict'), 'shadow': shadow.get('verdict'),
               'red': shadow.get('red') or [], 'unprepared': bool(shadow.get('unprepared'))}
              for (pr, head), box, shadow in pairs if box.get('verdict') != shadow.get('verdict')]
    same_per_pr = {}
    for (pr, _head), box, shadow in pairs:
        same_per_pr[pr] = same_per_pr.get(pr, True) and box.get('verdict') == shadow.get('verdict')
    return {'pairs': len(pairs), 'same': len(pairs) - len(differ), 'differ': differ,
            'unprepared': sum(1 for item in differ if item['unprepared']), 'prs': len(same_per_pr),
            'prs_same': sum(1 for same in same_per_pr.values() if same), 'needed': config.get('medir.shadow_prs'),
            'ready_to_landed_s': [verdict['ready_to_landed_s'] for verdict in recent
                                  if isinstance(verdict.get('ready_to_landed_s'), (int, float))
                                  and verdict.get('shadow', True)],
            'ready_to_merged_s': [verdict['ready_to_landed_s'] for verdict in recent
                                  if isinstance(verdict.get('ready_to_landed_s'), (int, float))
                                  and not verdict.get('shadow', True)],
            'judged_s': timed(pairs, kept_at, since, held_by_pr(lock_log))}


def held_by_pr(lock_log):
    """{pr: seconds the box's gate held the box} from the lock log (the last gate of the PR that held it), or {}."""
    held = {}
    try:
        lines = Path(os.path.expanduser(str(lock_log))).read_text(encoding='utf-8').splitlines() if lock_log else []
    except OSError:
        return held
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if row.get('pr') is not None and isinstance(row.get('held_s'), (int, float)) and row['held_s'] > 0:
            held[str(row['pr'])] = row['held_s']
    return held


def timed(pairs, kept_at, since, held=None):
    """MEDIR 5: the seconds each judged the same heads in, the box's gate and the shadow, for the pairs where both
    kept them, since `since` like the seconds to land: {'box': [...], 'shadow': [...]}, in the same order. The box's
    seconds are those deliver kept in its verdict, else the gate's hold of the box for the PR in the lock log
    (`held`). Beside them the honest counts: `judged` heads the shadow timed since `since`, `untimed` of them with no
    seconds of the box's anywhere (a merge the box gated before deliver kept them), and the rest `timed`."""
    held = held or {}
    both, judged = [], 0
    for (pr, _head), box, shadow in pairs:
        if since is not None and kept_at.get(id(shadow), since) < since:
            continue
        if not isinstance(shadow.get('seconds'), (int, float)):
            continue
        judged += 1
        seconds = box.get('seconds') if isinstance(box.get('seconds'), (int, float)) else held.get(str(pr))
        if seconds is not None:
            both.append((seconds, shadow['seconds']))
    return {'box': [seconds for seconds, _ in both], 'shadow': [seconds for _, seconds in both],
            'judged': judged, 'untimed': judged - len(both)}


def switch(agreement, merges):
    """P5 F4's question, from P5 F3's two criteria and the lesson of 05/11: (ready, why). The PRs whose every head the
    box and the shadow judged the same reach medir.shadow_prs; the shadow's ready to landed p50 is at most the box's
    merge p50 (`merges`, the deliveries' merges through Origin) plus medir.landing_slack_s; and the infrastructure
    judges the same heads no slower than the box's gate (p50 of both, MEDIR 5: on 05/11 the switch was rolled back
    after 393 s against ~150 s, which the landing alone did not show)."""
    half, slack = float('0.5'), config.get('medir.landing_slack_s')
    landed, merged = quantile(agreement['ready_to_landed_s'], half), quantile(merges, half)
    missing = []
    if agreement['prs_same'] < agreement['needed']:
        missing.append(f"{agreement['prs_same']} of {agreement['needed']} PRs judged the same")
    if landed is None or merged is None:
        missing.append('no ready to landed sample yet' if landed is None else 'no merge of the box measured')
    elif landed > merged + slack:
        missing.append(f'ready to landed p50 {landed:.2f} s over the box merge p50 {merged:.2f} s + {slack:g} s')
    judged = agreement.get('judged_s') or {'box': [], 'shadow': []}
    box_s, shadow_s = quantile(judged['box'], half), quantile(judged['shadow'], half)
    if box_s is None or shadow_s is None:
        missing.append('no head timed by both the box and the shadow yet')
    elif shadow_s > box_s:
        missing.append(f'the infrastructure judges in {shadow_s:.0f} s against the box gate {box_s:.0f} s '
                       f'(p50 of {len(judged["box"])} heads both timed; {judged.get("untimed", 0)} of '
                       f'{judged.get("judged", len(judged["box"]))} judged heads have no box time)')
    if missing:
        return False, 'not yet: ' + '; '.join(missing)
    return True, (f"ready: {agreement['prs_same']} of {agreement['needed']} PRs judged the same; ready to landed p50 "
                  f"{landed:.2f} s within the box merge p50 {merged:.2f} s + {slack:g} s; the infrastructure judges in "
                  f"{shadow_s:.0f} s against the box gate {box_s:.0f} s")


def from_deliveries(folder):
    """The seconds of every merge scripts/deliver measured, from its logs."""
    return [float(found) for path in sorted(Path(folder).glob('pr-*.log'))
            for found in MERGED.findall(path.read_text(encoding='utf-8', errors='replace'))]


def from_ingress(paths, limit=None):
    """The webhook ACK acceptance (PORT4): the ingress's own JSON lines (`ingress`, `ack_ms`, `cold`, `id`), as
    CloudWatch exports them (a line may carry a prefix before the JSON). The 1 s limit (medir.webhook_ack_limit_s)
    applies to this ACK, the time the ingress took from the gateway's stamp to its answer, and not to webhook_s, which
    is the registry's arrival less Origin's eventTime and so includes the queue and the consumer. Failure is any single
    delivery over the limit, a cold start included; each is listed. A sample, never a guarantee."""
    limit = config.get('medir.webhook_ack_limit_s') if limit is None else limit
    acks, over = [], []
    for path in paths:
        for line in Path(path).read_text(encoding='utf-8', errors='replace').splitlines():
            start = line.find('{')
            try:
                found = json.loads(line[start:]) if start >= 0 else None
            except ValueError:
                continue
            if not isinstance(found, dict) or 'ingress' not in found or not isinstance(found.get('ack_ms'), (int, float)):
                continue
            seconds = found['ack_ms'] / 1000
            acks.append(seconds)
            if seconds > limit:  # judged here by the registry's limit, whatever limit the line was stamped with
                over.append({'id': found.get('id'), 'seconds': round(seconds, 3), 'cold': bool(found.get('cold'))})
    return {'limit_s': limit, 'n': len(acks), 'ack_s': acks, 'over_limit': over}


NEAR_S = 0.1  # "within 100 ms of the limit": at or above limit - NEAR_S


def from_registry_ingress(found, limit=None):
    """PORT6: the ingress timing every delivery carries in the registry (`payload.ingress`, written by the consumer from the
    message the ingress queued: cold, gateway_to_handler_ms, pre_send_ms, origin_sent_to_handler_s). pre_send_ms is the
    gateway stamp to just BEFORE the SQS send, so it is a LOWER BOUND of the ACK (the send, tens of ms warm, is not in
    it): a pre_send over the limit is a definite failure, one under it proves nothing. Events without it (before PORT6)
    are not counted. Never a guarantee."""
    limit = config.get('medir.webhook_ack_limit_s') if limit is None else limit
    seen = []
    for event in found:
        timing = (event.get('payload') or {}).get('ingress')
        if not event['type'].startswith('forge.') or not isinstance(timing, dict) \
                or not isinstance(timing.get('pre_send_ms'), (int, float)):
            continue
        seen.append({'id': ((event['payload'].get('webhook') or {}).get('id')) or event['event_id'],
                     'seconds': timing['pre_send_ms'] / 1000, 'cold': bool(timing.get('cold'))})
    over = [{**item, 'seconds': round(item['seconds'], 3)} for item in seen if item['seconds'] > limit]
    cold = [item['seconds'] for item in seen if item['cold']]
    return {'limit_s': limit, 'n': len(seen), 'cold_n': len(cold), 'over_limit': over,
            'max_cold_pre_send_s': round(max(cold), 3) if cold else None,
            'near_limit_share': round(sum(item['seconds'] >= limit - NEAR_S for item in seen) / len(seen), 4)
            if seen else None}


LANDINGS = 100  # STATUS-LANDINGS: the landings a measure with --since asks the status for (it keeps ten for any other caller)


def deploy_status_of(port, landings=None):
    """GET /v1/deploy/status, or {} when the port does not answer it (a measure missing is not a failure of the others).
    STATUS-LANDINGS: landings asks for the swaps of that many of the newest landings (a series since a moment)."""
    try:
        found = port.call('GET', '/v1/deploy/status' + (f'?landings={int(landings)}' if landings else ''))
        return found if isinstance(found, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def from_deploy_status(status, since=None):
    """DEP7: seconds and US$ of the slow-path cycles the status keeps (the newest 20), as deploy_cycle_s and
    deploy_cycle_usd (the p50 of the first is the 3 minute goal), and deploy_rollout_wait_s; empty when no cycle was recorded."""
    cycles = [each for each in status.get('cycles') or [] if isinstance(each, dict) and each.get('seconds') is not None]
    found = {'deploy_cycle_s': [each['seconds'] for each in cycles],
             'deploy_cycle_usd': [each.get('usd') or 0 for each in cycles]} if cycles else {}
    # SLOW-PATH-NO-ROLLOUT-WAIT: the ECS rollouts are on no build's clock: from the end of the build that started them to
    # the last stack stable, as the build that verified them measured it (deploy_cycle_s no longer holds this wait)
    waits = [each['rollout_wait_s'] for each in cycles if isinstance(each.get('rollout_wait_s'), (int, float))
             and not isinstance(each.get('rollout_wait_s'), bool)]
    found = {**found, **({'deploy_rollout_wait_s': waits} if waits else {})}
    swaps = [each['swap_ms'] for each in status.get('fast') or [] if isinstance(each, dict) and each.get('ok')
             and each.get('swap_ms') is not None]  # DEP8: the milliseconds of each alias swap that went green
    props = [each['propagation_ms'] for each in status.get('fast') or [] if isinstance(each, dict) and each.get('ok')
             and each.get('propagation_ms') is not None]  # FAST-SMOKE-ORDER: until the alias answered the new version
    acts = [each['activate_ms'] for each in status.get('fast') or [] if isinstance(each, dict) and each.get('ok')
            and each.get('activate_ms') is not None]  # FAST-WAIT-ACTIVE: code update + publish + version Active
    warm = [float(each['seconds']) for each in status.get('runner_warm') or [] if isinstance(each, dict) and each.get('ok')
            and isinstance(each.get('seconds'), (int, float))]  # RUNNER-WARM-STATUS: installation events, not the tenant's log
    found = {**found, **({'prewarm_s': warm} if warm else {})}
    swapped = [float(each['swap_s']) for each in status.get('image_live') or [] if isinstance(each, dict)
               and isinstance(each.get('swap_s'), (int, float)) and not isinstance(each.get('swap_s'), bool)]
    found = {**found, **({'image_swap_s': swapped} if swapped else {})}  # IMAGE-PREWARM-A: pointer write to standby live
    landed = [float(each['landed_s']) for each in status.get('image_swap') or [] if isinstance(each, dict)
              and each.get('swapped') is True and isinstance(each.get('landed_s'), (int, float))]
    found = {**found, **({'image_landing_s': landed} if landed else {})}  # IMAGE-PREWARM-C: landing to pointer written
    ends = image_landing_to_live(status)
    found = {**found, **({'image_landing_to_live_s': ends} if ends else {})}  # IMAGE-SWAP-TIGHTEN: Daniel's 1 s
    backs = [each['rollback_ms'] for each in status.get('fast') or [] if isinstance(each, dict) and each.get('rolled_back')
             and each.get('rollback_ms') is not None]  # FAST-ROLLBACK-MS: the alias written back after a red swap
    found = {**found, **({'fast_rollback_ms': backs} if backs else {})}
    stale = [float(each['stale_s']) for each in status.get('image_retired') or [] if isinstance(each, dict)
             and each.get('by') == 'failover' and isinstance(each.get('stale_s'), (int, float))
             and not isinstance(each.get('stale_s'), bool)]  # IMAGE-SWAP-FAILOVER: how long the pointed image had no live beat
    found = {**found, **({'image_failover_s': stale} if stale else {})}
    # SUCCESSOR-LOST: a swap whose promoted process ended and whose role the process before it covered (platform.deploy.
    # successor {state: covered}): how long the cover lasted, until the bundle's new process was live (or the watch's
    # failover): the landing's own seconds are image_code_landing_s, by the first work of that new process
    covered = [float(each['covered_s']) for each in status.get('successor') or [] if isinstance(each, dict)
               and each.get('state') == 'covered' and isinstance(each.get('covered_s'), (int, float))
               and not isinstance(each.get('covered_s'), bool)]
    found = {**found, **({'image_swap_covered_s': covered} if covered else {})}
    # COVER-GAP: and how long the role had no process before the cover began (the pointer's write to the cover)
    gaps = [float(each['gap_s']) for each in status.get('successor') or [] if isinstance(each, dict)
            and each.get('state') == 'covered' and isinstance(each.get('gap_s'), (int, float))
            and not isinstance(each.get('gap_s'), bool)]
    found = {**found, **({'image_swap_gap_s': gaps} if gaps else {})}
    paths = slow_paths(status)  # VERIFY-AT-UP: the slow path whole, from the build that started it to the one that verified it
    found = {**found, **({'deploy_slow_path_s': paths} if paths else {})}
    ups = [float(seconds) for each in status.get('cycles') or [] if isinstance(each, dict)
           for seconds in (each.get('settled') or {}).values() if isinstance(seconds, (int, float)) and not isinstance(seconds, bool)]
    found = {**found, **({'deploy_settled_s': ups} if ups else {})}  # VERIFY-AT-UP: a stack's update to its new task's up
    for name, values in rollout_parts(status).items():  # ROLLOUT-PARTS: each slow-path rollout, part by part
        found = {**found, **({name: values} if values else {})}
    lost = runner_task_loss_gap(status)
    found = {**found, **({'runner_task_loss_gap_s': lost} if lost else {})}  # SPOT-KEEP: the role with no runner
    back = [float(each['reload_s']) for each in status.get('image_reload') or [] if isinstance(each, dict)
            and each.get('state') == 'reloaded' and isinstance(each.get('reload_s'), (int, float))
            and not isinstance(each.get('reload_s'), bool)
            and not each.get('order')]  # IMAGE-SWAP-RELOAD: the swap to the ECS task working on its bundle
    found = {**found, **({'image_reload_s': back} if back else {})}
    alone = image_reload_nostandby(status)
    found = {**found, **({'image_reload_nostandby_s': alone} if alone else {})}  # RELOAD-WITHOUT-STANDBY
    # IMAGE-CODE-LANDING: every code-only landing, whichever path it took: the measure the 1 s goal is judged by (p99)
    landings = image_code_landing(status, since)  # MEDIR-LANDINGS-SINCE: with --since, only the landings from that point
    if landings:
        found = {**found, 'image_code_landing_s': landings,
                 'image_code_landing_over_1s_s': [each for each in landings if each > 1.0],
                 'image_code_landing_slow_s': [each for each in landings if each >= SLOW_S]}
    # SWAP-MEASURE (the Torre, 13/11 21:35 BRT): the official series is of the swaps with every cut up to #617 (e835fb72):
    # from its landing on (CUTS_AT), the landings and the measured rounds, per role and whole; what came before is kept,
    # labelled as before the cuts, and judges nothing
    official = image_code_landing(status, CUTS_AT if since is None else max(since, CUTS_AT))
    if official:
        found = {**found, 'image_code_landing_official_s': official,
                 'image_code_landing_official_over_1s_s': [each for each in official if each > 1.0]}
    if since is None or since < CUTS_AT:
        before = image_code_landing({**status, 'image_swap': [each for each in status.get('image_swap') or [] if isinstance(
            each, dict) and isinstance(each.get('at'), (int, float)) and each['at'] < CUTS_AT]}, since)
        found = {**found, **({'image_code_landing_before_cuts_s': before} if before else {})}
    for name, values in swap_roles(status, CUTS_AT if since is None else max(since, CUTS_AT)).items():
        found = {**found, **({name: values} if values else {})}
    canaries = [float(each['seconds']) for each in status.get('canary') or [] if isinstance(each, dict)
                and each.get('ok') is True and isinstance(each.get('seconds'), (int, float))
                and not isinstance(each.get('seconds'), bool)]  # DEPLOY-CANARY: a green canary's creation to its end
    found = {**found, **({'deploy_canary_s': canaries} if canaries else {})}
    # FIRST-JOB-REHEARSED: the first job after a swap is the swap's canary (created by the service that took the role
    # right after its first tick): its creation to its dispatch (the service's first claim of a job) and its dispatch to
    # its take (the runner's first TAKE of a run), in the processes the swap promoted. With --since, from that point on
    for name, part in (('swap_first_job_dispatched_s', 'dispatched_s'), ('swap_first_job_taken_s', 'taken_s')):
        first = [float(each[part]) for each in status.get('canary') or [] if isinstance(each, dict)
                 and each.get('by') == 'swap' and isinstance(each.get(part), (int, float))
                 and not isinstance(each.get(part), bool)
                 and (since is None or (isinstance(each.get('at'), (int, float)) and each['at'] >= since))]
        found = {**found, **({name: first} if first else {})}
    return {**found, **({'fast_activate_ms': acts} if acts else {}), **({'fast_swap_ms': swaps} if swaps else {}), **({'fast_propagation_ms': props} if props else {})}


def image_reload_nostandby(status):
    """RELOAD-WITHOUT-STANDBY: each landing with no standby pair from its landing to both ECS tasks working on its bundle:
    the landing to the order (the ordered event's landed_s) + the order to the slower role's first work on the bundle
    (its reloaded event's reload_s). An order without both roles' reloaded is left out."""
    said = [each for each in status.get('image_reload') or [] if isinstance(each, dict) and each.get('order')]
    found = []
    for order in said:
        if order.get('state') != 'ordered' or not isinstance(order.get('landed_s'), (int, float)):
            continue
        ends = {each.get('role'): each.get('reload_s') for each in said
                if each.get('state') == 'reloaded' and each.get('order') == order.get('head')}
        if set(ends) == {'runner', 'service'} and all(isinstance(each, (int, float)) and not isinstance(each, bool)
                                                      for each in ends.values()):
            found.append(round(float(order['landed_s']) + max(ends.values()), 3))
    return found


SLOW_S = 600.0  # IMAGE-CODE-LANDING: what a landing that took the slow path counts (deploy.sh's DEPLOY_ROLLOUT_EXPECT_S)
# PROMOTED-SUCCESSOR-STAYS: who emptied a swapped bundle's pointers when the swap did not hold (image_retired `by`); the
# ways it holds are handover (the promoted process keeps the role) and reconciled (the slow path caught up with it)
TAKEN_BACK = ('handback', 'failover', 'canary', 'revert')


def image_code_landing(status, since=None):
    """IMAGE-CODE-LANDING (Daniel, 11/11 09:12 BRT: the image swap is measured in p50 and p99 over N >= 10 landings, the
    standby Spot took included, not by its best swap; the 1 s goal is the p99's). Every code-only landing the status
    keeps (image_swap: one event a landing, swapped or not, the newest 20), from its landing to both roles working on
    its code, by the path it took: the swap (as image_landing_to_live); the reload in place with no standby pair (as
    image_reload_nostandby); else the slow path (an image build and two ECS rollouts), counted SLOW_S: minutes, never
    under the goal. A swap whose first work was not recorded for both roles is left out (it is not a path).
    IN-TASK-STANDBY: a landing that found no standby and was swapped onto the successors its order started has two
    events, the landing's (not swapped, why) and the swap (by: order, landed_s from the landing): it is one landing,
    measured by its swap. PROMOTED-SUCCESSOR-STAYS: a swap that was taken back (its bundle's pointers emptied by the
    promoted process's handback, the watchdog's failover, a red canary or a revert: image_retired) did not put the code
    to work for good, whatever its first work says: the head went the slow way, and counts SLOW_S (live 11/11 23:58
    UTC: 0.694 s by its first work, a handback 8 s later and a rollout of 275 s).
    MEDIR-LANDINGS-SINCE: since (a Unix time) keeps the landings recorded from that point on (each event's `at`,
    STATUS-EVENTS-AT; one with no time is left out), so a change is judged by the landings after it."""
    live = {(each.get('role'), each.get('digest'), each.get('version')): each.get('swap_s')
            for each in status.get('image_live') or [] if isinstance(each, dict)}
    reloads = [each for each in status.get('image_reload') or [] if isinstance(each, dict) and each.get('order')]
    number = lambda value: isinstance(value, (int, float)) and not isinstance(value, bool)  # noqa: E731
    found = []
    undone = {each.get('digest') for each in status.get('image_retired') or []
              if isinstance(each, dict) and each.get('by') in TAKEN_BACK}
    swapped = {swap.get('head') for swap in status.get('image_swap') or [] if isinstance(swap, dict) and swap.get('swapped') is True}
    for swap in status.get('image_swap') or []:
        if not isinstance(swap, dict) or not swap.get('head') or (swap.get('swapped') is not True and swap['head'] in swapped):
            continue
        if since is not None and not (number(swap.get('at')) and swap['at'] >= since):
            continue
        if swap.get('swapped') is True:
            versions = {str(key).rsplit('_', 1)[-1]: version for key, version in (swap.get('versions') or {}).items()}
            ends = [live.get((role, swap.get('digest'), versions.get(role))) for role in ('runner', 'service')]
            if swap.get('digest') in undone:
                found.append(SLOW_S)
            elif number(swap.get('landed_s')) and all(number(each) for each in ends):
                found.append(round(float(swap.get('decide_s') or 0) + float(swap['landed_s']) + max(ends), 3))
            continue
        ordered = next((each for each in reloads if each.get('state') == 'ordered' and each.get('head') == swap['head']), None)
        ends = {each.get('role'): each.get('reload_s') for each in reloads
                if each.get('state') == 'reloaded' and each.get('order') == swap['head']}
        if ordered and number(ordered.get('landed_s')) and set(ends) == {'runner', 'service'} and all(
                number(each) for each in ends.values()):
            found.append(round(float(ordered['landed_s']) + max(ends.values()), 3))
        else:
            found.append(SLOW_S)
    return found


CUTS_AT = 1794529320.0  # 2026-11-13T00:22:00Z: the landing of #617 (e835fb72, 00:22:04 UTC), the official series' first


def swap_roles(status, since):
    """SWAP-MEASURE: each swap since `since` that both roles turned live on, by role (the pointer's write to that role's
    first work on the bundle: image_live swap_s of the swap's digest and pointer version, the promoted reserve's when a
    drill ended the successor) and whole (as image_landing_to_live); the measured rounds (by: measure) also apart, all
    and drilled. Answers {name: [seconds]}."""
    live = {(each.get('role'), each.get('digest'), each.get('version')): each.get('swap_s')
            for each in status.get('image_live') or [] if isinstance(each, dict)}
    number = lambda value: isinstance(value, (int, float)) and not isinstance(value, bool)  # noqa: E731
    found = {name: [] for name in ('image_swap_runner_s', 'image_swap_service_s', 'image_measure_s',
                                   'image_measure_runner_s', 'image_measure_service_s', 'image_measure_drilled_s',
                                   'image_measure_plain_s')}
    for swap in status.get('image_swap') or []:
        if not isinstance(swap, dict) or swap.get('swapped') is not True or not number(swap.get('landed_s')):
            continue
        if since is not None and not (number(swap.get('at')) and swap['at'] >= since):
            continue
        versions = {str(key).rsplit('_', 1)[-1]: version for key, version in (swap.get('versions') or {}).items()}
        ends = {role: live.get((role, swap.get('digest'), versions.get(role))) for role in ('runner', 'service')}
        if not all(number(each) for each in ends.values()):
            continue
        whole = round(float(swap.get('decide_s') or 0) + float(swap['landed_s']) + max(ends.values()), 3)
        for role, seconds in ends.items():
            found[f'image_swap_{role}_s'].append(round(float(seconds), 3))
        if swap.get('by') == 'measure':
            found['image_measure_s'].append(whole)
            for role, seconds in ends.items():
                found[f'image_measure_{role}_s'].append(round(float(seconds), 3))
            found['image_measure_drilled_s' if swap.get('drill') is not False else 'image_measure_plain_s'].append(whole)
    return found


def image_landing_to_live(status):
    """IMAGE-SWAP-TIGHTEN: each swap from its landing to the later of the two roles working on the new code: the landing's
    reads before its statement (decide_s, when the landing swapped) + landing to both pointers written (landed_s) + the
    slower role's pointer write to its first work (image_live swap_s of the swap's digest and pointer version). A swap
    without both roles' image_live is left out."""
    live = {(each.get('role'), each.get('digest'), each.get('version')): each.get('swap_s')
            for each in status.get('image_live') or [] if isinstance(each, dict)}
    found = []
    for swap in status.get('image_swap') or []:
        if not isinstance(swap, dict) or swap.get('swapped') is not True or not isinstance(swap.get('landed_s'), (int, float)):
            continue
        versions = {str(key).rsplit('_', 1)[-1]: version for key, version in (swap.get('versions') or {}).items()}  # role -> version
        ends = [live.get((role, swap.get('digest'), versions.get(role))) for role in ('runner', 'service')]
        if all(isinstance(each, (int, float)) and not isinstance(each, bool) for each in ends):
            found.append(round(float(swap.get('decide_s') or 0) + float(swap['landed_s']) + max(ends), 3))
    return found


def at_of(value):
    """Epoch seconds of an ISO time of ECS's (or a number), None for none."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    try:
        return datetime.fromisoformat(str(value).replace('Z', '+00:00')).timestamp()
    except ValueError:
        return None


ROLLOUT_PARTS = ('running', 'up', 'healthy', 'exit', 'deprovision', 'after', 'placed', 'pull')


def slow_paths(status):
    """VERIFY-AT-UP: each slow path whole, in seconds: from the start of a build that started rollouts (a `rolling` cycle: its
    end less its seconds) to the end of the next cycle, the build that verified them (the smoke and last-sha). The Torre's
    ~520 s of 13/11 (#622: build 121 s, rollout 363 s, verification 36 s) is one of these."""
    cycles = sorted((each for each in status.get('cycles') or [] if isinstance(each, dict) and at_of(each.get('at'))
                     and isinstance(each.get('seconds'), (int, float))), key=lambda each: float(each['at']))
    def began(each):  # the build's own start when the cycle carries it; else its record's time less its seconds
        return float(each['started']) if isinstance(each.get('started'), (int, float)) else float(each['at']) - float(each['seconds'])

    def ended(each):
        return float(each['ended']) if isinstance(each.get('ended'), (int, float)) and each['ended'] else float(each['at'])
    return [round(ended(after) - began(before), 3)
            for before, after in zip(cycles, cycles[1:]) if before.get('status') == 'rolling' and after.get('status') != 'rolling']


def rollout_parts(status):
    """ROLLOUT-PARTS (the Torre, 13/11 00:18 BRT): each slow-path rollout of an ECS stack, from the end of the build that
    started it (a `rolling` cycle) to the stack's end (that build's own rollout seconds, the next cycle's `rollout`), in
    the parts of the task ECS replaced and the one it started (platform.ecs.task_stopped of each, the new one's once it
    stopped in its turn; the runner's platform.deploy.task_up): rollout_running_s (the build's end to the new task
    RUNNING), rollout_up_s (RUNNING to its task_up: the runner's warm-up), rollout_healthy_s (RUNNING to the old task
    stopping: the new one HEALTHY), rollout_exit_s (the old one stopping to its containers ended), rollout_deprovision_s
    (that to STOPPED: Fargate's), rollout_after_s (STOPPED to the stack's end: what CloudFormation waits after ECS),
    rollout_placed_s (the build's end to the new task made) and rollout_pull_s (its image's pull). A part with no evidence
    is left out."""
    cycles = sorted((each for each in status.get('cycles') or [] if isinstance(each, dict) and at_of(each.get('at'))),
                    key=lambda each: each['at'])
    tasks = [each for each in status.get('ecs') or [] if isinstance(each, dict) and each.get('type') == 'platform.ecs.task_stopped']
    ups = [each for each in status.get('runner_life') or [] if isinstance(each, dict) and each.get('type') == 'platform.deploy.task_up']
    found = {f'rollout_{name}_s': [] for name in ROLLOUT_PARTS}
    began = None
    for cycle in cycles:
        if cycle.get('status') == 'rolling':
            began = float(cycle['at'])
            continue
        if began is None or not isinstance(cycle.get('rollout'), dict):
            continue
        for stack, seconds in cycle['rollout'].items():
            group = 'service:' + str(stack).replace('tower-app-', 'tower-')
            end = began + float(seconds)
            old = next((each for each in tasks if each.get('group') == group and each.get('stop_code') == 'ServiceSchedulerInitiated'
                        and began <= (at_of(each.get('stopping_at')) or 0) <= end), None)
            if old is None:
                continue
            stopping = at_of(old.get('stopping_at'))
            new = next((each for each in tasks if each.get('group') == group and each is not old
                        and began <= (at_of(each.get('started_at')) or 0) <= stopping), None)
            parts = {'exit': (at_of(old.get('execution_stopped_at')), stopping, 1),
                     'deprovision': (at_of(old.get('stopped_at')), at_of(old.get('execution_stopped_at')), 1),
                     'after': (end, at_of(old.get('stopped_at')), 1)}
            if new is not None:
                running = at_of(new.get('started_at'))
                up = next((at_of(each.get('at')) for each in ups if each.get('stack') == stack
                           and running <= (at_of(each.get('at')) or 0) <= end), None)
                parts.update(running=(running, began, 1), healthy=(stopping, running, 1), up=(up, running, 1),
                             placed=(at_of(new.get('created_at')), began, 1),
                             pull=(at_of(new.get('pull_stopped_at')), at_of(new.get('pull_started_at')), 1))
            for name, (later, earlier, _) in parts.items():
                if later is not None and earlier is not None:
                    found[f'rollout_{name}_s'].append(round(later - earlier, 3))
        began = None
    return found


def runner_task_loss_gap(status):
    """SPOT-KEEP: for each runner task Spot interrupted (ECS's own event, platform.ecs.task_stopped, stop_code
    SpotInterruption, group service:tower-runner), how long the role had no runner: from the stop of that task's
    process (the first platform.process.stopped of a task after the interruption's stoppingAt, less 5 s) to the first
    task_up of another runner task after the warning; 0 when the process was kept until it (SPOT-KEEP). Interruptions
    whose replacement is not up yet are left out."""
    from datetime import datetime
    lives = [each for each in status.get('runner_life') or [] if isinstance(each, dict) and isinstance(each.get('at'), (int, float))]
    gaps = []
    for stop in status.get('ecs') or []:
        if not (isinstance(stop, dict) and stop.get('type') == 'platform.ecs.task_stopped'
                and stop.get('stop_code') == 'SpotInterruption' and stop.get('group') == 'service:tower-runner'):
            continue
        try:
            warned = datetime.fromisoformat(str(stop.get('stopping_at')).replace('Z', '+00:00')).timestamp()
        except ValueError:
            continue
        ended = sorted((each for each in lives if each.get('type') == 'platform.process.stopped'
                        and warned - 5 <= each['at'] <= warned + 130), key=lambda each: each['at'])
        if not ended:
            continue
        task = ended[0].get('task')
        up = sorted(each['at'] for each in lives if each.get('type') == 'platform.deploy.task_up'
                    and each.get('task') != task and each['at'] > warned - 5)
        if up:
            gaps.append(round(max(0.0, up[0] - ended[0]['at']), 3))
    return gaps


def main(argv=None):
    parser = argparse.ArgumentParser(prog='scripts/medir', description=__doc__.splitlines()[0])
    parser.add_argument('--since', help="the log's point to read from (default: everything the port keeps)")
    parser.add_argument('--json', action='store_true')
    parser.add_argument('--ingress-log', action='append', default=[], metavar='FILE',
                        help="the ingress's log lines (/aws/lambda/tower-port-ingress, exported), for the ACK acceptance")
    parser.add_argument('--deliveries', default=str(Path.home() / '.cache' / 'the-tower' / 'deliver'))
    parser.add_argument('--shadows', default=str(Path(os.environ.get('XDG_CACHE_HOME') or Path.home() / '.cache')
                                                 / 'the-tower' / 'gate-infra'))
    args = parser.parse_args(argv)
    registry = None
    measures = {'deliver_merge_s': from_deliveries(args.deliveries)}
    since = datetime.fromisoformat(args.since.replace('Z', '+00:00')).timestamp() if args.since else None
    agreement = from_shadows(args.shadows, since, config.get('delivery.gate_lock_log'))
    for name in ('ready_to_landed_s', 'ready_to_merged_s'):  # the shadow's dry runs; the real merges (GATE-INFRA 10)
        if agreement[name]:
            measures[name] = agreement[name]
    url, token = os.environ.get('TOWER_PORT_URL'), os.environ.get('TOWER_PORT_TOKEN')
    if url and token:
        import gate_infra
        port = gate_infra.Port(url, token)
        logged = events(port, args.since)
        measures.update(from_deploy_status(deploy_status_of(port, LANDINGS if since else None), since))
        measures.update(from_log(logged))
        registry = from_registry_ingress(logged)
    ack = from_ingress(args.ingress_log) if args.ingress_log else None
    if ack:
        measures['ingress_ack_s'] = ack['ack_s']
    answer = {name: summary(values, total=name.startswith('cost_') or name == 'deploy_cycle_usd')
              for name, values in sorted(measures.items())}
    if url and token:
        answer['first_check_s'] = {**summary(measures.get('first_check_s', [])), 'max': max(measures.get('first_check_s', []),
                                                                                               default=None)}
    if url and token:
        answer['prewarm_s'] = {**summary(measures.get('prewarm_s', [])), 'max': max(measures.get('prewarm_s', []), default=None)}
    if ack:
        answer['webhook_ack'] = {key: value for key, value in ack.items() if key != 'ack_s'}
    if registry and registry['n']:
        answer['webhook_ingress'] = registry
    if agreement['pairs']:
        answer['shadow'] = {key: value for key, value in agreement.items()
                            if key not in ('ready_to_landed_s', 'ready_to_merged_s')}
        ready, why = switch(agreement, measures['deliver_merge_s'])
        answer['switch'] = {'ready': ready, 'why': why}
    if args.json:
        print(json.dumps(answer, indent=1))
        return 0
    if not (url and token):
        print('medir: no port (TOWER_PORT_URL and TOWER_PORT_TOKEN); only the deliveries are read')
    for name, numbers in answer.items():
        if name == 'first_check_s':
            print(f"first_check_s after runner task change: n={numbers['n']} p50={numbers['p50']} max={numbers['max']}")
            if not numbers['n']:
                print('  no runner task started in the window (no run.running with a new runner after a job.created that '
                      'ended); a merge touching infra/service changes the runner image, so the next deploy produces one')
        elif name == 'prewarm_s':
            print(f"runner prewarm_s: n={numbers['n']} p50={numbers['p50']} max={numbers['max']}")
        elif name not in ('shadow', 'switch', 'webhook_ack', 'webhook_ingress'):
            print(f"{name}: n={numbers['n']} " + ' '.join(f'{key}={value}' for key, value in numbers.items()
                                                       if key != 'n'))
    if ack:
        print(f"webhook ack (limit {ack['limit_s']:g} s): n={ack['n']}, over limit: {len(ack['over_limit'])} "
              "(the ingress's ACK, gateway stamp to answer; webhook_s above is the registry's latency, not the ACK)")
        for item in ack['over_limit']:
            print(f"  over limit: {item['id']} {item['seconds']} s {'cold' if item['cold'] else 'warm'}")
        if ack['n'] and not ack['over_limit']:
            print(f"  no over-limit delivery in {ack['n']} samples (a sample, not a guarantee)")
    if registry and registry['n']:
        print(f"webhook ingress (limit {registry['limit_s']:g} s, from the registry): n={registry['n']}, "
              f"cold n={registry['cold_n']}, deliveries whose pre_send already exceeds the limit: "
              f"{len(registry['over_limit'])}")
        for item in registry['over_limit']:
            print(f"  over limit before the send: {item['id']} {item['seconds']} s {'cold' if item['cold'] else 'warm'}")
        if registry['cold_n']:
            print(f"  max pre_send among cold deliveries: {registry['max_cold_pre_send_s']} s")
        print(f"  share within {NEAR_S * 1000:g} ms of the limit (or over it): {registry['near_limit_share']:.1%}")
        print("  pre_send is the gateway stamp to just before the SQS send: the send (tens of ms warm; ack_ms in "
              "CloudWatch) is NOT in this figure, so it is a LOWER BOUND of the ACK and a sample, not a guarantee")
    if agreement['pairs']:
        print(f"shadow: {agreement['pairs']} head(s) of {agreement['prs']} PR(s) judged by both, "
              f"{agreement['same']} the same, {len(agreement['differ'])} differ ({agreement['unprepared']} with checks "
              f"the runner could not prepare); PRs with the same verdicts: {agreement['prs_same']} of "
              f"{agreement['needed']} (P5 F3)")
        for item in agreement['differ']:
            if not item['unprepared']:  # a real disagreement on the head, the one a person reads
                print(f"  #{item['pr']} {item['head']}: box {item['box']}, shadow {item['shadow']}"
                      + (f" ({', '.join(item['red'])})" if item['red'] else ''))
        stamped = agreement['judged_s']
        print(f"timing (MEDIR 5): n={len(stamped['box'])} heads timed by both (box p50 {quantile(stamped['box'], 0.5)}, "
              f"infrastructure p50 {quantile(stamped['shadow'], 0.5)}); {stamped['untimed']} of {stamped['judged']} "
              f"judged heads have no box time")
        print(f"switch (P5 F4, delivery.judge infra): {answer['switch']['why']}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
