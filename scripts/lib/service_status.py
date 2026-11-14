"""Status, health and metrics of the gate and the train as services (GATE-TRAIN-SERVICES R3, D-086, ADR-41).

What a person or a monitor needs to see without opening a session, read cheaply from four sources:
  git      the train's lock ref (a fetch of one ref, no REST): who holds the lock and until when, and, once released,
           why the last run died when it raised (`died`, TRAIN-TEMP-FIX R1: a warned check);
  forge    the shared window of the repository channel (D-085): merges and their admission, pr.ready, the train's
           batches, its REST budget, rate refusals; and one paged read of the open PRs on train.base_branch;
  control  the control plane's public `GET /status` (service.control_url, D-290): its queue, the engine's only job
           channel; one entry per PR (the newest), kept only while the forge reports the PR open (a closed PR leaves);
  runner   the state file of a Tower runner on this machine (service.state_path): heartbeat, current job, recent results.
`train/wake` is not read: it is no job channel any more (D-290). status() is a contracts/service/status.v1.json document
with its health checks (pass, warn, fail); metrics() renders the same numbers as Prometheus text. Read only: nothing
here writes to the forge, the control plane or a ref. A source that cannot be read is a failed check, never an
exception, and the queue is then unknown, never a stale or unfiltered number."""
from datetime import datetime
import json
import math
from pathlib import Path
import statistics
import subprocess
import sys
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config  # noqa: E402
import forge_events  # noqa: E402
import forge_git_ref  # noqa: E402

ROOT = Path(__file__).resolve().parents[1].parent
PASS, WARN, FAIL = 'pass', 'warn', 'fail'
ORDER = (PASS, WARN, FAIL)  # worst last
SCOPES = {'runner': 'machine', 'control': 'control_plane', 'control-health': 'control_plane'}  # every other check reads the repository
METRIC = 'tower_'
QUOTE = '"'  # never inside a Prometheus label value


def setting(name):
    return config.get(name, ROOT)


def moment(text):
    """A datetime of an RFC 3339 text (events, git, the state file), or None."""
    try:
        return datetime.fromisoformat(str(text).replace('Z', '+00:00'))
    except ValueError:
        return None


class Sources:
    """The read paths, each replaceable in a test: the git lock ref, the forge window and open PRs, the control plane's
    status and the runner state file."""

    def __init__(self, root=None, refs=None, port=None, clock=None):
        self.root = Path(root or ROOT)
        self.refs = refs or forge_git_ref.GitRefs(self.root)
        self.port = port
        self.clock = clock or forge_events.clock_from_config()

    def lock(self):
        held = self.refs.read(setting('train.lock_ref'))
        if held is None:
            return None
        sha, record = held
        return {'sha': sha, 'owner': record.get('owner'), 'expires': record.get('expires') or None,
                'died': record.get('died') or None}

    def landed(self, sha):
        """True when `sha` is already in the base branch's history: a PR the session merged itself (no pr.merged event)
        is not waiting for the train (D-143). An unknown commit is not landed."""
        base = 'origin/' + setting('train.base_branch')
        done = subprocess.run(['git', '-C', str(self.root), 'merge-base', '--is-ancestor', sha, base],
                              capture_output=True, text=True)
        return done.returncode == 0

    def forge(self):
        return self.port or forge_events.ForgeEvents(forge_events.adapter_from_config(), self.clock, 'reader', 'service')

    def window(self):
        events, complete = self.forge().read_window(setting('forge-events.repo'))
        return events, complete

    def open_prs(self):
        """The numbers of the PRs the forge reports open on train.base_branch, drafts included: one paged read."""
        pulls = self.forge().open_pulls(setting('forge-events.repo'), setting('train.base_branch'))
        return {pull['number'] for pull in pulls}

    def control(self):
        """The control plane's `GET /status` document (public, no token): its `queue` is the job channel's queue."""
        request = urllib.request.Request(setting('service.control_url').rstrip('/') + '/status',
                                         headers={'user-agent': setting('service.user_agent')})  # D-091
        with urllib.request.urlopen(request, timeout=setting('service.control_timeout_s')) as response:
            return json.loads(response.read())

    def runner(self):
        try:
            return json.loads((self.root / setting('service.state_path')).read_text())
        except (OSError, ValueError):
            return None

    def switches(self):
        found = {}
        for key, name in (('paused', 'service.paused'), ('transport', 'service.transport'),
                          ('train_switch', 'train.enabled'), ('trigger_mode', 'train.trigger_mode')):
            try:
                found[key] = config.shared(name) if hasattr(config, 'shared') else config.get(name)
            except Exception as error:  # noqa: BLE001 - the registry default is shown and the error is a failed check
                found[key] = config.entry(name)['default']
                found.setdefault('unreadable', []).append(f'{name}: {str(error).splitlines()[0]}')
        return found


def attempt(read):
    """(value, None) of read(), or (None, the error in one line): a source that fails is a check, not a crash."""
    try:
        return read(), None
    except Exception as error:  # noqa: BLE001 - reported by the caller's health check
        return None, f'{type(error).__name__}: {str(error).splitlines()[0] if str(error) else ""}'.rstrip(': ')


def seconds(later, earlier):
    first, second = moment(later), moment(earlier)
    return (first - second).total_seconds() if first and second else None


def control_queue(document, open_prs, landed):
    """One entry per PR of the control plane's queue (its newest woken_at and that entry's head), kept only while the
    forge reports the PR open and its head is not in the base's history. The store keeps a job per pushed head and the
    jobs of closed PRs (CONTROL-STORE), so the forge is the judge of open."""
    newest = {}
    for item in (document or {}).get('queue') or []:
        pr, sha = item.get('pr'), item.get('sha')
        if not isinstance(pr, int) or not sha:
            continue
        held = newest.get(pr)
        if held is None or (item.get('woken_at') or '') >= (held.get('woken_at') or ''):
            newest[pr] = {'pr': pr, 'sha': sha, 'woken_at': item.get('woken_at')}
    return [item for pr, item in sorted(newest.items()) if pr in open_prs and not landed(item['sha'])]


def status(sources):
    """The status document (contracts/service/status.v1.json) and, inside it, the health checks."""
    now = sources.clock.now()
    at = forge_events.rfc3339(now)
    recent = setting('service.recent')
    checks = []
    switches = sources.switches()
    lock, lock_error = attempt(sources.lock)
    window, window_error = attempt(sources.window)
    remote, control_error = attempt(sources.control)
    open_prs, open_error = attempt(sources.open_prs)
    events, complete = window if window else ([], False)
    runner = sources.runner()
    merged, ready = {}, {}
    for event in events:
        payload = event.get('payload') or {}
        if event.get('type') == 'pr.merged':
            merged[(payload.get('pr'), payload.get('sha'))] = event
        elif event.get('type') == 'pr.ready':
            ready.setdefault((payload.get('pr'), payload.get('sha')), event.get('occurred_at'))  # the first green
    timed = {(item.get('pr'), item.get('sha')): item.get('green_to_merged_s')
             for item in (remote or {}).get('merges') or [] if isinstance(item, dict)}
    known = not (control_error or open_error)
    queue = control_queue(remote, open_prs, sources.landed) if known else []
    merges = []
    for (pr, sha), event in merged.items():
        payload = event.get('payload') or {}
        lag = timed.get((pr, sha))
        merges.append({'pr': pr, 'sha': sha, 'batch_id': payload.get('batch_id'), 'occurred_at': event['occurred_at'],
                       'green_to_merged_s': lag if lag is not None else seconds(event['occurred_at'],
                                                                                ready.get((pr, sha)))})
    merges.sort(key=lambda item: item['occurred_at'], reverse=True)
    checks.append(('git', FAIL, f'the train lock is not readable ({lock_error})') if lock_error
                  else ('git', PASS, 'train/lock read over git'))
    checks.append(('forge', FAIL, f'the repository window is not readable ({window_error})') if window_error
                  else ('forge', PASS, f'{len(events)} events in the window'))
    checks.append(('control', FAIL, f'the control plane status is not readable ({control_error})') if control_error
                  else ('control', PASS, f'{len((remote or {}).get("queue") or [])} queue entries in GET /status'))
    remote_health = control_health(remote)
    if remote_health:
        checks.append(remote_health)
    checks.append(('forge-open', FAIL, f'the open PRs are not readable ({open_error})') if open_error
                  else ('forge-open', PASS, f'{len(open_prs)} open PR(s) on {setting("train.base_branch")}'))
    checks.append(lock_check(lock, now))
    checks.append(queue_check(queue, now) if known else
                  ('queue', WARN, 'the queue is unknown: the control plane or the open PRs could not be read'))
    checks.append(runner_check(runner, now))
    if switches.get('unreadable'):  # e.g. service.transport still `git` in the store: the runner refuses it (D-290)
        checks.append(('switches', FAIL, '; '.join(switches['unreadable'])))
    if switches.get('paused'):
        checks.append(('paused', WARN, 'service.paused is on: runners take no new job'))
    worst = max((status_ for _, status_, _ in checks), key=ORDER.index)
    return {'at': at, 'switches': {'paused': bool(switches.get('paused')), 'transport': switches.get('transport'),
                                   'train_switch': switches.get('train_switch'),
                                   'trigger_mode': switches.get('trigger_mode')},
            'train': {'lock': lock, 'wake': None},
            'queue': sorted(queue, key=lambda item: item['woken_at'] or '')[-recent:],
            'merges': merges[:recent],
            'runner': runner_view(runner, recent),
            'window': {'events': len(events), 'complete': bool(complete)},
            'control_plane': {'runners': 'unknown', 'jobs': 'unknown',
                              'detail': 'the queue is read from GET /status; runners and jobs are not summarized here, '
                                        'and repository and machine checks do not establish global availability'},
            'health': {'status': worst, 'scope': 'repository_and_machine',
                       'checks': [{'name': name, 'status': status_, 'detail': detail,
                                   'scope': SCOPES.get(name, 'repository')}
                                                   for name, status_, detail in checks]},
            'metrics': numbers(events, merges, queue, lock, runner, now, known)}


def control_health(remote):
    """The control plane's own non-passing health checks (its runners' heartbeats among them), relayed as one warned
    check: a runner that stopped beating is on the status a session reads, not only in GET /status (TRAIN-TEMP-FIX R1).
    None when the control plane was not read or its checks all pass."""
    checks = ((remote or {}).get('health') or {}).get('checks') or []
    failing = [check for check in checks if isinstance(check, dict) and check.get('status') in (WARN, FAIL)]
    if not failing:
        return None
    return 'control-health', WARN, '; '.join(f'{check.get("name")}: {check.get("detail")}' for check in failing)


def lock_check(lock, now):
    if lock is not None and not lock.get('expires') and lock.get('died'):
        return 'lock', WARN, f'the last train run ({lock.get("owner")}) died: {lock["died"]}'  # TRAIN-TEMP-FIX R1
    if lock is None or not lock.get('expires'):
        return 'lock', PASS, 'the train lock is free'
    ends = moment(lock['expires'])
    if ends is None:
        return 'lock', WARN, f'the train lock has an unreadable lease end {lock["expires"]!r}'
    late = (now - ends).total_seconds()
    if late > setting('service.lock_stale_s'):
        return 'lock', WARN, f'{lock.get("owner")} left the lock {round(late)} s past its lease (a train that died)'
    if late > 0:
        return 'lock', PASS, f'the lease of {lock.get("owner")} ended {round(late)} s ago: free'
    return 'lock', PASS, f'held by {lock.get("owner")} until {lock["expires"]}'


def queue_check(queue, now):
    ages = [(now - moment(item['woken_at'])).total_seconds() for item in queue if moment(item['woken_at'])]
    if not ages:
        return 'queue', PASS, (f'{len(queue)} open PR(s) in the control-plane queue' if queue
                               else 'no open PR in the control-plane queue')
    oldest = max(ages)
    if oldest > setting('service.queue_stale_s'):
        return 'queue', WARN, f'{len(queue)} open PR(s) in the control-plane queue; the oldest for {round(oldest)} s'
    return 'queue', PASS, f'{len(queue)} open PR(s) in the control-plane queue'


def runner_check(runner, now):
    if runner is None:
        return 'runner', WARN, 'no Tower runner state on this machine (service.state_path)'
    beat = moment(runner.get('heartbeat'))
    if beat is None:
        return 'runner', FAIL, 'the runner state has no readable heartbeat'
    age = (now - beat).total_seconds()
    if age > setting('service.heartbeat_stale_s'):
        return 'runner', FAIL, f'runner {runner.get("name")} last beat {round(age)} s ago'
    return 'runner', PASS, f'runner {runner.get("name")} beat {round(age)} s ago'


def runner_view(runner, recent):
    if runner is None:
        return None
    return {'name': runner.get('name'), 'kind': runner.get('kind'), 'heartbeat': runner.get('heartbeat'),
            'transport': runner.get('transport'), 'current': runner.get('current'),
            'results': (runner.get('results') or [])[-recent:]}


def numbers(events, merges, queue, lock, runner, now, known=True):
    """{metric: [(labels, value)]}: the counts and latencies metrics() renders, all from the read sources. An unknown
    queue (a source unreadable) has no queue_depth sample: no number is better than a wrong one."""
    found = {}

    def put(name, value, **labels):
        found.setdefault(name, []).append((labels, value))

    by_admission = {}
    for item in merges:
        key = (item.get('batch_id') or '?').split('-')[0]
        by_admission[key] = by_admission.get(key, 0) + 1
    for key, count in sorted(by_admission.items()):
        put('merges_total', count, admission=key)
    latencies = sorted(item['green_to_merged_s'] for item in merges if item['green_to_merged_s'] is not None)
    for name, value in quantiles(latencies).items():
        put('green_to_merged_seconds', value, quantile=name)
    batches = {}
    for event in events:
        kind = event.get('type', '')
        if kind in ('train.batch.green', 'train.batch.red'):
            batches[kind.rsplit('.', 1)[1]] = batches.get(kind.rsplit('.', 1)[1], 0) + 1
    for result, count in sorted(batches.items()):
        put('train_batches_total', count, result=result)
    rest = [event['payload'] for event in events if event.get('type') == 'budget.measured'
            and (event.get('payload') or {}).get('metric') == 'train.rest_calls_per_run_max']
    if rest:
        put('train_rest_calls', rest[-1].get('value'))
        put('train_rest_calls_budget', setting('train.rest_calls_per_run_max'))
    put('rate_limited_total', sum(1 for event in events if event.get('type') == 'forge.rate.limited'))
    if known:
        put('queue_depth', len(queue))
    held = lock is not None and bool(lock.get('expires')) and moment(lock['expires']) is not None \
        and moment(lock['expires']) > now
    put('train_lock_held', int(held))
    for result in (runner or {}).get('results') or []:
        if result.get('duration_s') is not None:
            put('job_seconds', result['duration_s'], kind=str(result.get('job', '')).split(':')[0],
                outcome=result.get('outcome'))
    if runner is not None and moment(runner.get('heartbeat')):
        put('runner_heartbeat_age_seconds', (now - moment(runner['heartbeat'])).total_seconds(), runner=runner.get('name'))
    return {name: [[labels, value] for labels, value in values] for name, values in found.items()}


def quantiles(values):
    """{quantile: value} of sorted `values` by nearest rank, for each of service.latency_quantiles; {} for none."""
    if not values:
        return {}
    return {str(share): values[min(len(values), max(1, math.ceil(share * len(values)))) - 1]
            for share in setting('service.latency_quantiles')}


HELP = {
    'merges_total': 'PRs merged in the repository window, by the batch_id prefix (v strict verdict, s shard, b tier-2 batch).',
    'green_to_merged_seconds': 'From the pr.ready (green verdict) of a head to its pr.merged, over the merges in the window.',
    'train_batches_total': "The train's tier-2 batches in the window, by result.",
    'train_rest_calls': 'REST calls of the latest train run (budget.measured).',
    'train_rest_calls_budget': 'train.rest_calls_per_run_max.',
    'rate_limited_total': 'forge.rate.limited events in the window: the quota refused a call.',
    'queue_depth': 'PRs in the control-plane queue the forge reports open.',
    'train_lock_held': '1 while a train holds train/lock within its lease.',
    'job_seconds': "Duration of this machine's runner's recent jobs.",
    'runner_heartbeat_age_seconds': "Seconds since this machine's runner last beat.",
    'up': '1: the status was read.',
}


def metrics(document):
    """The Prometheus text exposition (format 0.0.4) of a status document's numbers."""
    lines = [f'# HELP {METRIC}up {HELP["up"]}', f'# TYPE {METRIC}up gauge', f'{METRIC}up 1']
    for name, values in document['metrics'].items():
        lines += [f'# HELP {METRIC}{name} {HELP.get(name, name)}',
                  f'# TYPE {METRIC}{name} {"counter" if name.endswith("_total") else "gauge"}']
        for labels, value in values:
            text = ','.join(f'{key}="{str(item).replace(QUOTE, "")}"' for key, item in sorted(labels.items()))
            lines.append(f'{METRIC}{name}{{{text}}} {value}' if text else f'{METRIC}{name} {value}')
    return '\n'.join(lines) + '\n'


def human(document):
    """The status for a person, one line per fact."""
    switches, train = document['switches'], document['train']
    lines = [f'service: {document["health"]["status"].upper()} at {document["at"]} '
             f'(paused={switches["paused"]}, transport={switches["transport"]}, train.enabled={switches["train_switch"]}, '
             f'trigger_mode={switches["trigger_mode"]})']
    lines.append('health scope: repository and this machine; global availability unknown')
    remote = document.get('control_plane')
    if remote:
        lines.append(f'control plane: runners={remote["runners"]}, jobs={remote["jobs"]} ({remote["detail"]})')
    lock = train['lock']
    lines.append('lock: none' if not lock else f'lock: held by {lock["owner"]} until {lock["expires"]}'
                 if lock['expires'] else f'lock: free (released by {lock["owner"]}'
                 + (f'; that run died: {lock["died"]})' if lock.get('died') else ')'))
    unknown = any(check['name'] == 'queue' and 'unknown' in check['detail'] for check in document['health']['checks'])
    lines.append('queue: unknown (the control plane or the open PRs could not be read)' if unknown else
                 f'queue: {len(document["queue"])} open PR(s) in the control-plane queue'
                 + ''.join(f'\n  #{item["pr"]} {item["sha"]} queued {item["woken_at"]}' for item in document['queue']))
    for item in document['merges']:
        latency = item['green_to_merged_s']
        lines.append(f'merged: #{item["pr"]} {item["batch_id"]} at {item["occurred_at"]}'
                     + (f' ({latency:.0f} s after its pr.ready)' if latency is not None else ''))
    lags = [item['green_to_merged_s'] for item in document['merges'] if (item['green_to_merged_s'] or 0) > 0]
    if lags:
        lines.append(f'pr.ready to merge: median {statistics.median(lags):.0f} s over {len(lags)} merge(s) '
                     '(a pr.ready after the merge is left out)')
    runner = document['runner']
    lines.append(f'runner: {runner["name"]} beat {runner["heartbeat"]}, current {runner["current"]}' if runner
                 else 'runner: none on this machine')
    for check in document['health']['checks']:
        lines.append(f'check {check["name"]} [{check.get("scope", "unknown")}]: {check["status"]} ({check["detail"]})')
    return '\n'.join(lines)
