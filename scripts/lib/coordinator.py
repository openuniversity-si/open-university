"""The program coordinator (D-069 CO1): one decision function over the repo's own state and events.

next(state, events, limits) -> actions is pure. State is derived: the program graph (scripts/lib/program.py), the event
log (the forge_events port) and three observations a caller passes in (open defects, remaining quota, the clock). Every
limit is a coordinator.* registry value (limits()). Actions, in coordinator.actions order:
  launch         {unit, attempt, plan_version} start the unit's session (the launcher port renders and starts it)
  mark_blocked   {unit, blocked_by}           the unit waits on a unit that ran out of retries
  open_fix_unit  {defect}                     a known defect with no fix unit; KD1's router opens it
  enqueue        {pr, sha, unit}              the PR is eligible for the merge train (TR1's queue_entry predicate)
  escalate       {unit, reason}               a person must look: retry budget spent
run() applies them through injected ports (launch, route, notify); with dry_run it applies none.

Live plan (live-planning LP5, D-071, design 4): the plan next() reads is the folded live plan (live_plan(): program.v1 block
+ plan.changed log through plan_live.fold, or any `provider` callable). A unit in `holds` is not launched; the hold key
HOLD_ALL holds every launch, and so does the file at planner.launch_hold_path when it exists (observations()). Inside a
wave `priority` ranks launches before the unit id. A launch carries the plan_version it was decided on; run() re-reads the
plan and refuses the launch when that unit's entry, hold, priority or brief lines changed since (the plan moved).
work.assigned has no plan_version field (contracts/events is not LP5's), so the version lives in the launch action and in
the record run() returns.

CLI: coordinator.py next|status|run PROGRAM [--events FILE] [--briefs] [--apply [--launcher NAME]]   (dry-run unless --apply)
"""
import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys

import config
import forge_events  # the queue predicate (queue_entry) lives with the log, below the train (D-322)
import program as programs

ROOT = programs.ROOT
HOLD_ALL = 'all'  # the key of `holds` that holds every launch (design 4: LAUNCH-HOLD maps to a hold all)


class CoordinatorError(RuntimeError):
    pass


def limits():
    """The registered limits as a plain dict; the one place next() receives configuration from."""
    names = ('max_sessions', 'launch_rate_max', 'launch_rate_window_s', 'retry_budget', 'quota_headroom_percent',
             'lane_item', 'router_by', 'producer', 'actions', 'queue_owner')
    return {name: config.get(f'coordinator.{name}') for name in names}


def live_plan(plan, root=None, provider=None):
    """The folded live plan of a program.v1 mapping. provider(plan) -> folded plan is the seam (default: plan_live.fold over
    the plan log); until the fold exists the plan is returned with no holds, priorities or brief lines."""
    if provider is not None:
        return provider(plan)
    import plan_live
    try:
        return plan_live.fold(plan, plan_live.read_log(plan['program'], root))
    except NotImplementedError:
        return dict(plan, version=0, holds={}, brief_lines={}, priority={})


def plan_version(plan):
    return plan.get('version', 0)


def held(plan, unit_id):
    holds = plan.get('holds') or {}
    return HOLD_ALL in holds or unit_id in holds


def unit_view(plan, unit_id):
    """What a launch of the unit depends on in the live plan; a change to any of it makes an earlier decision stale."""
    unit = next_unit(plan, unit_id)
    return (unit, (plan.get('holds') or {}).get(unit_id), (plan.get('holds') or {}).get(HOLD_ALL),
            (plan.get('priority') or {}).get(unit_id), (plan.get('brief_lines') or {}).get(unit_id))


def next_unit(plan, unit_id):
    for unit in plan['units']:
        if unit['id'] == unit_id:
            return unit
    return None


def launch_hold(root=None):
    """True when the global brake file named by planner.launch_hold_path exists (empty setting = no brake)."""
    path = config.get('planner.launch_hold_path')
    return bool(path) and (Path(root or ROOT) / path).exists()


def moment(stamp):
    return datetime.fromisoformat(stamp.replace('Z', '+00:00')).astimezone(timezone.utc)


def failures(unit_id, events):
    kind = config.get('coordinator.event_failed')
    return sum(event['type'] == kind and event['payload'].get('unit') == programs.unit_event_id(unit_id) for event in events)


def launches_in_window(plan, events, now, limit):
    ids = {programs.unit_event_id(unit['id']) for unit in plan['units']}
    kind, since = config.get('coordinator.event_assigned'), now - timedelta(seconds=limit['launch_rate_window_s'])
    return sum(event['type'] == kind and event['payload'].get('unit') in ids and moment(event['occurred_at']) >= since
               for event in events)


def pr_events(events, number):
    return [event for event in events if event['payload'].get('pr') == number]


def next(state, events, limit):
    """The actions that follow from state and events. state: {program, now, open_defects: [id], quota_remaining_percent}."""
    plan = state['program']
    rows = {row['id']: row for row in programs.status(plan, events)}
    spent = {unit_id for unit_id, row in rows.items()
             if row['stage'] == 'failed' and failures(unit_id, events) > limit['retry_budget']}
    found = {name: [] for name in limit['actions']}
    for defect in state.get('open_defects', []):
        found['open_fix_unit'].append({'defect': defect})
    for unit in plan['units']:
        row = rows[unit['id']]
        if unit['id'] in spent:
            found['escalate'].append({'unit': unit['id'], 'reason': f'{failures(unit["id"], events)} failed sessions, budget {limit["retry_budget"]}'})
        elif row['stage'] == 'ready' and row['pr'] is not None:
            log = pr_events(events, row['pr'])
            heads = [event['payload']['sha'] for event in log if event['payload'].get('sha')]
            entry = forge_events.queue_entry(log, heads[-1]) if heads else None
            if entry is not None:
                found['enqueue'].append({'pr': entry.pr, 'sha': entry.sha, 'unit': unit['id']})
        elif row['stage'] in ('pending', 'failed') and row['blocked_by'] and spent & set(row['blocked_by']):
            found['mark_blocked'].append({'unit': unit['id'], 'blocked_by': sorted(spent & set(row['blocked_by']))})
    running = sum(row['stage'] in ('running', 'open', 'ready') for row in rows.values())
    quota = state.get('quota_remaining_percent')
    room = limit['max_sessions'] - running
    room = min(room, limit['launch_rate_max'] - launches_in_window(plan, events, state['now'], limit))
    if quota is not None and quota < limit['quota_headroom_percent']:
        room = 0
    if state.get('launch_hold'):
        room = 0
    ranks = plan.get('priority') or {}
    unranked = max(ranks.values(), default=0) + 1
    for unit in sorted(plan['units'], key=lambda item: (item['wave'], ranks.get(item['id'], unranked), item['id'])):
        row = rows[unit['id']]
        if room <= 0:
            break
        if unit.get('owner') == limit.get('queue_owner'):  # D-277: a unit no lane holds waits; it is never launched
            continue
        if row['stage'] in ('pending', 'failed') and not row['blocked_by'] and unit['id'] not in spent and not held(plan, unit['id']):
            found['launch'].append({'unit': unit['id'], 'attempt': failures(unit['id'], events) + 1, 'plan_version': plan_version(plan)})
            room -= 1
    return [dict(action=name, **item) for name in limit['actions'] for item in found[name]]


def run(plan, events, state, limit, ports, dry_run=True, emit=None, reread=None):
    """Apply next()'s actions through ports {launch(unit_entry, attempt) -> session id, route() -> routed, notify(text)}.
    A dry run applies nothing and returns the actions. emit(kind, payload) records a launch as work.assigned.
    reread() -> the live plan now: a launch whose unit changed in the plan since the decision is refused (stale)."""
    actions = next(state, events, limit)
    if dry_run:
        return actions
    done = []
    for item in actions:
        kind = item['action']
        if kind == 'launch':
            if reread is not None:
                now = reread()
                if now is not None and unit_view(now, item['unit']) != unit_view(state['program'], item['unit']):
                    done.append(dict(item, refused='stale plan_version', current_plan_version=plan_version(now)))
                    continue
            unit = find_unit(plan, item['unit'])
            session = ports['launch'](unit, item['attempt'])
            if emit is not None:
                emit('work.assigned', {'lane_id': unit['owner'], 'unit': programs.unit_event_id(unit['id']), 'units': [],
                                       'item': limit['lane_item'].format(program=plan['program'], unit=unit['id'], attempt=item['attempt'])})
            done.append(dict(item, session=session))
        elif kind == 'open_fix_unit':
            if not any(entry['action'] == kind for entry in done):
                ports['route']()
            done.append(item)
        elif kind in ('escalate', 'mark_blocked'):
            ports['notify'](json.dumps(item, sort_keys=True))
            done.append(item)
        else:
            done.append(item)  # enqueue: the train reads the same predicate; reported, not written
    return done


def find_unit(plan, unit_id):
    for unit in plan['units']:
        if unit['id'] == unit_id:
            return unit
    raise CoordinatorError(f'unknown unit {unit_id}')


def observations(root, plan, now=None):
    """The state that is not in the log: open defects without a fix unit (KD1's register) and the clock. Quota is the
    launcher's to report; None means unknown."""
    import defects
    found, _ = defects.load(root)
    wanted = config.get('defects.statuses')[0]
    return {'program': plan, 'now': now or datetime.now(timezone.utc), 'quota_remaining_percent': None,
            'launch_hold': launch_hold(root),
            'open_defects': sorted(ident for ident, record in found.items() if record['status'] == wanted)}


def main(argv=None):
    parser = argparse.ArgumentParser(prog='scripts/coordinator', description=__doc__.splitlines()[0])
    parser.add_argument('command', choices=('next', 'status', 'run'))
    parser.add_argument('program')
    parser.add_argument('--events', help='JSON-lines file of event envelopes instead of the forge port')
    parser.add_argument('--apply', action='store_true', help='run: apply the actions (default is a dry run)')
    parser.add_argument('--briefs', action='store_true', help='dry run: also print the launch brief of each launch')
    parser.add_argument('--launcher', help='launcher adapter (default coordinator.launcher_default)')
    args = parser.parse_args(argv)
    try:
        plan = live_plan(programs.load(args.program), ROOT)
        events = programs.read_events(args.events) if args.events else programs.live_events(plan)
        if args.command == 'status':
            print(programs.render_status(plan, programs.status(plan, events)))
            return 0
        state = observations(ROOT, plan)
        limit = limits()
        import coordinator_launch
        lessons = coordinator_launch.lessons_port(ROOT)
        if args.command == 'next' or not args.apply:
            actions = next(state, events, limit)
            for item in actions:
                print(json.dumps(item, sort_keys=True))
            if args.briefs:
                rows = programs.status(plan, events)
                for name, text in coordinator_launch.briefs_for(plan, rows, lessons, ROOT).items():
                    print(f'\n===== brief {name} =====\n{text}')
            return 0
        from adapters import launcher
        vendor = launcher.adapter(args.launcher)
        try:
            vendor.preflight()  # L1 (D-206 (d)): a stale launch flag refuses here, before any unit is assigned
        except RuntimeError as error:
            print(error, file=sys.stderr)
            return 1
        ports, emit = coordinator_launch.build_ports(plan, vendor, lessons, ROOT)
        for item in run(plan, events, state, limit, ports, dry_run=False, emit=emit,
                        reread=lambda: live_plan(programs.load(args.program), ROOT)):
            print(json.dumps(item, sort_keys=True))
    except (programs.ProgramError, CoordinatorError) as error:
        print(error, file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
