"""The session's deploy tool (DEP1): ring the deploy doorbell and follow the build to its end, with no AWS credential.

  scripts/deploy ring                  POST to the doorbell; 202 prints the build id
                                       (a 409 the doorbell queued ends it too: the running build's end starts
                                       the next one, RING-QUEUE)
  scripts/deploy queue --sha SHA --ref REF
                                       QUEUE-RELOAD, the merge_group job: ring `prepare` for the merge queue's commit and
                                       end; GitHub's push webhook on main rings `landed` at the doorbell (GITHUB-HOOK)
  scripts/deploy status                the port's GET /v1/deploy/status: last_sha, the last build with its tail and the last
                                       ring/skip decision, as the service observed them (DEP3: it publishes them to the log);
                                       a succeeded build's seconds go into config/validation/runs/deploy.json (record),
                                       a code-only merge's push-to-live seconds into deploy-live.json (record_live, the push clock),
                                       and the newest one's steps (PUSH-STEPS: push, doorbell, port, look, ls-remote, swap, live)
  scripts/deploy status --json         the same answer as JSON (`| scripts/spend record`: the month's AWS spend, D-331)
  scripts/deploy follow [--target SHA] [--build ID] [--since EPOCH]
                                       follow the status until the deploy ends (the port's long poll; pauses with an old
                                       port); a failure prints the failed names and tail

The doorbell is TOWER_DEPLOY_DOORBELL_URL with the bearer TOWER_DEPLOY_DOORBELL_TOKEN (docs/operations/aws.md, 2): the
token is not an AWS credential and is never printed. The status is read through the port (TOWER_PORT_URL,
TOWER_PORT_TOKEN) by the retrying client of the gate (AWS5). The waits are gate-infra.deploy_*.
Exit: 0 the doorbell rang / the deploy succeeded; 1 refused (401) or the build failed; 2 undecided (a build already
running, the wait ran out, the port unreachable, the environment incomplete).
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config  # noqa: E402
import gate_infra  # noqa: E402

DOORBELL_VARS = ('TOWER_DEPLOY_DOORBELL_URL', 'TOWER_DEPLOY_DOORBELL_TOKEN')
PORT_VARS = ('TOWER_PORT_URL', 'TOWER_PORT_TOKEN')
ENDED = ('succeeded', 'nothing_new')
STALE_S = 300  # an observation older than this while a ring was made: the service is not reporting
RUNS_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RUNS_FOLDER = 'config/validation/runs'  # the run snapshots scripts/model's run-durations measure reads (scripts/lib/runs.py)
DEPLOY_RUNS = 'deploy'  # config/validation/runs/deploy.json: the deploy builds' seconds (the slow path's cost)
LIVE_RUNS = 'deploy-live'  # config/validation/runs/deploy-live.json: a code-only merge's landing to live, VAL-deploy-1s
DEPLOY_KEEP = 20


def record(state, root=None, now=None):
    """PADRAO-DEV F8d: the deploy's build seconds recorded the way the gate's runs are (config/validation/runs/,
    read by scripts/model's run-durations measure): the slow path's cost, kept beside deploy-live.json (record_live),
    which VAL-deploy-1s reads since REQ-deploy-1s counts a code-only merge's landing to live. The port answers only the last
    build, so each read adds it to the snapshot (by build id, the newest DEPLOY_KEEP kept); only a succeeded build with
    its own clock counts. The snapshot's `at` is the read's time, which keeps it fresh while sessions read the status.
    Answers the runs recorded, or None when the build is not one to count."""
    import datetime as clock
    build = state.get('last_build') or {}
    if build.get('status') != 'succeeded' or not isinstance(build.get('seconds'), (int, float)) or not build.get('build_id'):
        return None
    iso = lambda epoch: clock.datetime.fromtimestamp(epoch, clock.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    target = os.path.join(root or RUNS_ROOT, RUNS_FOLDER, DEPLOY_RUNS + '.json')
    try:
        with open(target) as handle:
            before = json.load(handle).get('runs') or []
    except (OSError, ValueError):
        before = []
    kept = [run for run in before if run.get('id') != build['build_id']]
    entry = {'id': build['build_id'], 'event': 'deploy', 'conclusion': 'success',
             'started': iso(build.get('started') or build.get('ended') or 0), 'seconds': int(build['seconds'])}
    made = {'workflow': DEPLOY_RUNS, 'source': 'the AWS deploy builds of GET /v1/deploy/status (scripts/deploy status)',
            'at': iso(now if now is not None else time.time()),
            'runs': sorted(kept + [entry], key=lambda run: run['started'], reverse=True)[:DEPLOY_KEEP]}
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, 'w') as handle:
        handle.write(json.dumps(made, indent=1) + '\n')
    return made['runs']


def live_at(state):
    """REQ-deploy-1s: {merge sha: (epoch the merge's code went live, how)} for the code-only merges the status shows
    going live (QUEUE-RELOAD, infra/service/tower_infra/queue_deploy.py: "a code-only merge is live about a second after
    it lands"). A queue swap is live when the heir's task saw its pointer (image_live of the same digest and version),
    else at the pointer's write; an ordered reload (no heir ready) when it is done (its proof ended)."""
    number = lambda value: isinstance(value, (int, float)) and not isinstance(value, bool)  # noqa: E731
    found, lives, reloads = {}, state.get('image_live') or [], state.get('image_reload') or []
    for swap in state.get('image_swap') or []:
        if not isinstance(swap, dict) or swap.get('swapped') is not True or not swap.get('head') or not number(swap.get('at')):
            continue
        versions = set((swap.get('versions') or {}).values()) if isinstance(swap.get('versions'), dict) else set()
        heard = [each['at'] for each in lives if isinstance(each, dict) and number(each.get('at')) and each['at'] >= swap['at']
                 and each.get('digest') == swap.get('digest') and each.get('version') in versions]
        found.setdefault(swap['head'], (min(heard) if heard else swap['at'], 'swap'))
    for order in reloads:
        if not isinstance(order, dict) or order.get('state') != 'ordered' or not order.get('head') or not number(order.get('at')):
            continue
        done = [each['at'] for each in reloads if isinstance(each, dict) and each.get('state') == 'done'
                and each.get('digest') == order.get('digest') and number(each.get('at')) and each['at'] >= order['at']]
        if done:
            found.setdefault(order['head'], (min(done), 'reload'))
    return found


PUSH_PAGE = 100  # the activity API's largest page: the last 100 pushes to main, one call per status read


def iso_epoch(text):
    import datetime as clock
    return clock.datetime.strptime(text, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=clock.timezone.utc).timestamp()


def pushed_at(api, repo, ref='refs/heads/main'):
    """The push clock: {commit sha: epoch of the push that put it on `ref`}, from GitHub's repository activity API (its
    `timestamp`): the push of the merge commit, the earliest true landing (a pull request's merged_at is set 1-2 s
    later). A reversible choice taken under D-325; its revert is reading merged_at again. The timestamp has whole
    seconds while the live instant has milliseconds, so a run's seconds carry up to 1 s of that resolution (long when
    GitHub truncates, as the 1-2 s gap to merged_at suggests; unproved). One page: the last PUSH_PAGE pushes."""
    found = {}
    for push in api(f'repos/{repo}/activity?ref={ref}&per_page={PUSH_PAGE}') or []:
        if isinstance(push, dict) and push.get('after') and push.get('timestamp'):
            found.setdefault(push['after'], iso_epoch(push['timestamp']))
    return found


def record_live(state, root=None, now=None, api=None, repo=None):
    """REQ-deploy-1s: each code-only merge's seconds from its landing to its code live (live_at), in
    config/validation/runs/deploy-live.json, the snapshot VAL-deploy-1s reads; the build seconds stay in deploy.json
    (record), the slow path's cost. The landing is the push of the merge commit to main (pushed_at, whole seconds),
    and such a run carries `from: push`. A run recorded before the push clock (from the pull request's merged_at, no
    `from`) is re-based on its push while the activity page still holds it (live = started + seconds), else kept and
    marked `from: merged_at` (1-2 s short). A run recorded from its push is not read again; offline (TOWER_OFFLINE, no
    gh, the API refusing) nothing changes. Answers the runs recorded, or None when there is nothing to record."""
    import datetime as clock
    seen = live_at(state)
    if not seen:
        return None
    iso = lambda epoch: clock.datetime.fromtimestamp(epoch, clock.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')  # noqa: E731
    target = os.path.join(root or RUNS_ROOT, RUNS_FOLDER, LIVE_RUNS + '.json')
    try:
        with open(target) as handle:
            before = json.load(handle).get('runs') or []
    except (OSError, ValueError):
        before = []
    runs = {run.get('id'): run for run in before if isinstance(run, dict)}
    if api is None and not os.environ.get('TOWER_OFFLINE'):
        import verify_commit  # the gate's github adapter (gh api), as runs.fetch reads GitHub
        api = lambda path: verify_commit.gh_json(verify_commit.run, path)  # noqa: E731
    if repo is None and api is not None:  # the repository runs.repository() names, without the model's unit
        repo = os.environ.get('GITHUB_REPOSITORY') or config.get('forge-events.repo')
    lives = {sha: (run.get('event'), iso_epoch(run['started']) + run['seconds']) for sha, run in runs.items()
             if 'from' not in run and isinstance(run.get('started'), str)
             and isinstance(run.get('seconds'), (int, float))}  # the runs from merged_at: live = merged_at + seconds
    lives.update({sha: (how, live) for sha, (live, how) in seen.items() if (runs.get(sha) or {}).get('from') != 'push'})
    pushes = None
    if lives and api is not None:
        try:
            pushes = pushed_at(api, repo)
        except (OSError, RuntimeError, ValueError):
            pushes = None
    for sha, (how, live) in lives.items() if pushes is not None else ():
        if sha in pushes and live >= pushes[sha]:
            runs[sha] = {'id': sha, 'event': how, 'conclusion': 'success', 'started': iso(pushes[sha]),
                         'seconds': round(live - pushes[sha], 3), 'from': 'push'}
        elif sha in runs and 'from' not in runs[sha]:  # its push left the page: kept from merged_at, said, not asked again
            runs[sha] = dict(runs[sha], **{'from': 'merged_at'})
    made = {'workflow': LIVE_RUNS, 'source': "code-only merges' landing (the push of the merge commit to main, GitHub's "
                                             "activity API) to code live (image_swap/image_live, image_reload of "
                                             'GET /v1/deploy/status)',
            'at': iso(now if now is not None else time.time()),
            'runs': sorted(runs.values(), key=lambda run: run['started'], reverse=True)[:DEPLOY_KEEP]}
    if not made['runs']:
        return None
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, 'w') as handle:
        handle.write(json.dumps(made, indent=1) + '\n')
    return made['runs']


STEPS = ('push', 'heard', 'port', 'look', 'ls-remote', 'verified', 'swap', 'live')


def steps(state, runs):
    """PUSH-STEPS (REQ-deploy-1s): the newest code-only merge that went live (live_at), split at each step's instant, so
    the next cut is chosen by numbers: push (its run in deploy-live.json, `from: push`, whole seconds), heard (the doorbell
    got the word), port (the port recorded it), look (the queue's look took the landing), ls-remote (main answered),
    verified (the claim checked), swap (the pointer written, or the reload ordered), live. Answers (sha, how,
    [(step, instant)]) with the steps the events said, in that order, or None when no merge went live."""
    number = lambda value: isinstance(value, (int, float)) and not isinstance(value, bool)  # noqa: E731
    seen = live_at(state)
    if not seen:
        return None
    sha, (live, how) = max(seen.items(), key=lambda item: item[1][0])
    said = [each for each in state.get('queue_landed') or [] if isinstance(each, dict) and each.get('sha') == sha]
    word = next((each for each in said if each.get('type') == 'platform.deploy.queue'), {})
    outcome = next((each for each in said if each.get('type') == 'platform.deploy.queue_reload'), {})
    run = next((each for each in runs or [] if isinstance(each, dict) and each.get('id') == sha
                and each.get('from') == 'push'), None)
    ordered = next((each.get('at') for each in state.get('image_reload') or [] if isinstance(each, dict)
                    and each.get('state') == 'ordered' and each.get('head') == sha), None)
    at = {'push': iso_epoch(run['started']) if run else None, 'heard': word.get('heard'),
          'port': word.get('port_at', word.get('at')), 'look': outcome.get('began_at'), 'ls-remote': outcome.get('main_at'),
          'verified': outcome.get('verified_at'), 'swap': outcome.get('wrote_at', ordered), 'live': live}
    return sha, how, [(name, at[name]) for name in STEPS if number(at[name])]


def say_steps(found, out=None):
    """`steps <sha> (<how>): push -> heard +0.8 -> ... -> live +0.4 = 1.7 s`: each step's seconds since the step before."""
    if not found or len(found[2]) < 2:
        return
    sha, how, marks = found
    parts = [marks[0][0]] + [f'{name} +{round(at - before, 3)}' for (_, before), (name, at) in zip(marks, marks[1:])]
    print(f"steps {sha[:12]} ({how}): {' -> '.join(parts)} = {round(marks[-1][1] - marks[0][1], 3)} s", file=out or sys.stdout)


def missing(names, environ):
    return [name for name in names if not environ.get(name)]


def say_missing(names, what):
    if what == 'the doorbell':
        print(f'deploy: this environment lacks {" and ".join(names)}. The environment needs exactly two variables, '
              f'{" and ".join(DOORBELL_VARS)}; Daniel provisions them (the token through the secure credential form, '
              f'the URL is not secret). There is no workaround: the session has no AWS credential and must not get one.',
              file=sys.stderr)
    else:
        print(f'deploy: this environment lacks {" and ".join(names)} (the port); Daniel provisions them.', file=sys.stderr)


def ring(environ=None, opener=urllib.request.urlopen, word=None):
    """Ring the doorbell once. Returns (exit code, build id or None). word: QUEUE-RELOAD's {event, sha}, which the
    doorbell passes to the port instead of starting a build."""
    environ = os.environ if environ is None else environ
    absent = missing(DOORBELL_VARS, environ)
    if absent:
        say_missing(absent, 'the doorbell')
        return 2, None
    headers = {'Authorization': f"Bearer {environ['TOWER_DEPLOY_DOORBELL_TOKEN']}"}
    if word:
        headers['Content-Type'] = 'application/json'
    request = urllib.request.Request(environ['TOWER_DEPLOY_DOORBELL_URL'], method='POST',
                                     data=json.dumps(word).encode() if word else b'', headers=headers)
    try:
        with opener(request, timeout=config.get('gate-infra.deploy_ring_timeout_s')) as answer:
            status, body = answer.status, answer.read().decode('utf-8', 'replace')
    except urllib.error.HTTPError as error:
        status, body = error.code, error.read().decode('utf-8', 'replace')
    except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
        print(f'deploy: the doorbell did not answer ({type(error).__name__}); it was not rung twice, so ring again',
              file=sys.stderr)
        return 2, None
    if status == 202 and word:
        print(f"deploy: {word['event']} rung for {word['sha'][:12]}")
        return 0, None
    if status == 202:
        try:
            build = json.loads(body).get('build')
        except (ValueError, AttributeError):
            build = None
        print(f'deploy: rung; build {build}. scripts/deploy follow to see it end')
        return 0, build
    if status == 409:
        try:
            queued = json.loads(body).get('queued') is True
        except (ValueError, AttributeError):
            queued = False
        if queued:  # RING-QUEUE: the doorbell keeps the ring and the running build's end starts the next build
            print('deploy: a build is running (409); the doorbell queued this ring and starts the next build when the '
                  'running one ends. scripts/deploy follow to see it')
            return 0, None
        print('deploy: a build is running already (409); scripts/deploy follow waits for it')
        return 2, None
    if status == 401:
        print('deploy: the doorbell refused the token (401): TOWER_DEPLOY_DOORBELL_TOKEN is not the current one; '
              'Daniel provisions a new one', file=sys.stderr)
        return 1, None
    print(f'deploy: the doorbell answered {status}: {body[:200]}', file=sys.stderr)
    return 1, None


def queue(sha, ref, environ=None, opener=urllib.request.urlopen):
    """QUEUE-RELOAD (infra/service/tower_infra/queue_deploy.py): the merge_group job's part. Rings `prepare` for the queue's
    commit (ref, its gh-readonly-queue branch, is only said) and ends. GITHUB-HOOK (POLL-scripts-lib-deploy-py-queue gone):
    the landing is GitHub's push webhook on main, delivered to the doorbell, which checks its signature and rings
    `landed`; nothing here watches main any more. Returns ring's exit code: 0 rung, 1 refused, 2 undecided."""
    print(f"deploy: {ref}: prepare for {sha[:12]}; GitHub's push to main rings landed")
    return ring(environ, opener, word={'event': 'prepare', 'sha': sha})[0]


LONG_POLL = 'long_poll'  # PORT-LONG-POLL: the mark of an answer the port held (tower_infra.port.LONG_POLL)


def read_status(port, wait_s=None, seen=None):
    """GET /v1/deploy/status; with wait_s, the port's long poll (PORT-LONG-POLL): it answers when the status is not the
    one `seen` names (the digest its previous answer's mark gave) or when wait_s passes. A port without the long poll
    ignores the query and answers at once, unmarked (follow says so and stops)."""
    if wait_s is None:
        return port.call('GET', '/v1/deploy/status')
    query = {'wait_s': max(wait_s, 0.0), **({'seen': seen} if seen else {})}
    return port.call('GET', '/v1/deploy/status?' + urllib.parse.urlencode(query))


def describe(state, out=None):
    out = out or sys.stdout
    build = state.get('last_build')
    if state.get('observed_at') is None:
        print('observed: nothing yet (the service has not published an observation; this is not a failed build)', file=out)
    else:
        print(f"observed_at: {state['observed_at']}", file=out)
    ring = state.get('ring')
    if ring:
        print(f"ring: {ring.get('action')} ({ring.get('reason')}) at {ring.get('at')}", file=out)
    print(f"last_sha: {state.get('last_sha') or 'none'}", file=out)
    canary = (state.get('canary') or [None])[0]  # DEPLOY-CANARY: the newest canary's verdict
    if isinstance(canary, dict):
        print(f"canary: {'ok' if canary.get('ok') else 'RED'}: {canary.get('line')} ({canary.get('key')}, at {canary.get('at')})",
              file=out)
    if not build:
        print('last_build: none recorded', file=out)
        return
    print(f"last_build: {build.get('status')} {build.get('build_id')} base {str(build.get('base_head'))[:12]} "
          f"started {build.get('started')} ended {build.get('ended')}", file=out)
    if build.get('seconds') is not None:  # FAST-PATH-RELOAD: the build's own clock, what a deploy costs end to end
        print(f"build_seconds: {build['seconds']}" + ''.join(f", {each.get('n')} {each.get('t')}s" for each in build.get('steps') or []
                                                         if isinstance(each, dict) and each.get('s') == 'ok'), file=out)
    said = build.get('reload')
    if isinstance(said, dict):  # FAST-PATH-RELOAD: the reload in place a code-only build asked the live service for
        up, proof = said.get('reloaded') or {}, said.get('proven') or {}
        print(f"reload: {said.get('state')} in {said.get('s')}s (bundle {str(said.get('sha256'))[:12]} at {str(said.get('head'))[:12]})"
              + (f"; reloaded {up.get('reload_s')}s after the order (boot {up.get('boot_s')}s)" if up else '')
              + (f"; proven by {proof.get('ticks')} good ticks in {proof.get('window_s')}s" if proof else '')
              + (f": {said['why']}" if said.get('why') else ''), file=out)
    running, lost = state.get('in_progress'), state.get('lost')
    if running:
        print(f"in_progress: step {running.get('step') or '?'}, elapsed {running.get('elapsed_s')}s, silent {running.get('idle_s')}s", file=out)
    if lost:
        print(f"{lost.get('line')} (build {lost.get('build')})", file=out)
    if build.get('status') == 'rolling':  # SLOW-PATH-NO-ROLLOUT-WAIT: ended, its ECS rollouts not waited
        print(f"rolling: {' '.join(sorted((build.get('rolling') or {}).get('stacks') or {}))} started and not waited; "
              'the next build verifies them, runs the smoke and moves last_sha', file=out)
    spent = build.get('spend')
    if isinstance(spent, dict):  # AWS-SPEND (D-331): the month's spend to date, read once a day by the build
        print(f"spend: US$ {spent.get('usd')} from {spent.get('from')} to {spent.get('day')} (scripts/spend record)", file=out)
    if build.get('failed_step'):
        print(f"failed_step: {build['failed_step']}", file=out)
    for each in build.get('steps') or []:
        if each.get('e'):
            print(f"step {each.get('n')} {each.get('s')} (last lines):\n{each['e']}", file=out)
    if build.get('failed'):
        print(f"failed: {' '.join(build['failed'])}", file=out)
    if build.get('left'):
        print(f"left (the next ring resumes them): {' '.join(build['left'])}", file=out)
    if build.get('tail') and build.get('status') in ('failed', 'incomplete'):
        print('tail:\n' + build['tail'], file=out)


def verdict(state, target, since, build_id):
    """'succeeded', 'failed' or None (still going) from one reading."""
    build = state.get('last_build') or {}
    mine = bool(build) and (build_id in build.get('build_id', '') if build_id else (build.get('started') or 0) >= since)
    if target and state.get('last_sha') == target:
        return 'succeeded'
    if mine and build.get('status') in ('failed', 'incomplete'):
        return 'failed'
    if mine and not target and build.get('status') in ENDED:
        return 'succeeded'
    return None


def silent(state, now):
    """True when a ring was made and the newest observation is older than STALE_S: the service stopped reporting."""
    ring, seen = state.get('ring') or {}, state.get('observed_at')
    return seen is not None and ring.get('action') == 'ring' and now - seen > STALE_S


def follow(port, target=None, build_id=None, since=None, sleep=time.sleep, clock=time.monotonic, now=time.time):
    since = now() - config.get('gate-infra.deploy_since_skew_s') if since is None else since
    first, longest = config.get('gate-infra.deploy_poll_s'), config.get('gate-infra.deploy_poll_max_s')
    deadline, pause = clock() + config.get('gate-infra.deploy_wait_s'), first
    seen = None
    while True:
        # PORT-LONG-POLL: each read waits at the port for a change, `first` seconds at most (never longer than the
        # pauses of before the long poll, so nothing is seen later), and is asked again at once. LONG-POLL-ONLY: the
        # live port holds every read (its wake is never None on the Lambda, LONG-POLL-HOLDS), so an answer it did not
        # hold is a port older than PORT-LONG-POLL: said, exit 2, never a pause on an interval. A read that failed is
        # tried again after a pause that grows as before (first, by 1.5, to deploy_poll_max_s) and starts over at the
        # next answer: a backoff on a failure, no later than the pauses of before.
        try:
            state = read_status(port, min(first, max(deadline - clock(), 0.0)), seen)
        except gate_infra.Refused as error:
            print(f'deploy: the status could not be read ({error})', file=sys.stderr)
            state = None
        mark = (state or {}).get(LONG_POLL)
        held = isinstance(mark, dict)
        seen = mark.get('seen') if held else None
        build = (state or {}).get('last_build') or {}
        if build_id and build.get('status') == 'rolling' and build_id in build.get('build_id', ''):
            # SLOW-PATH-NO-ROLLOUT-WAIT: the followed build ended with its stacks rolling out: the build that verifies them
            # (any build that starts from now on) is the one whose verdict counts
            build_id, since = None, build.get('started') or since
        found = state and verdict(state, target, since, build_id)
        if found:
            describe(state)
            return 0 if found == 'succeeded' else 1
        if state and silent(state, now()):
            print('deploy: the service is not reporting (a ring was made, the last observation is older than '
                  f'{STALE_S} s); last reading:', file=sys.stderr)
            describe(state, sys.stderr)
            return 2
        if state and not held:
            print('deploy: the port answered without holding the read (no long_poll: a port older than PORT-LONG-POLL); '
                  'last reading:', file=sys.stderr)
            describe(state, sys.stderr)
            return 2
        if (clock() >= deadline) if state else (clock() + pause > deadline):
            print('deploy: the wait ran out; the build may still be running, last reading:', file=sys.stderr)
            if state:
                describe(state, sys.stderr)
            return 2
        if state:
            pause = first
            continue  # the port waited: ask again at once
        sleep(pause)
        pause = min(longest, pause * 1.5)


def main(argv=None, environ=None):
    environ = os.environ if environ is None else environ
    parser = argparse.ArgumentParser(prog='scripts/deploy', description=__doc__.split('\n')[0])
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('ring')
    queued = sub.add_parser('queue')
    queued.add_argument('--sha', required=True, help="the merge queue's commit (github.sha of the merge_group run)")
    queued.add_argument('--ref', required=True, help="its branch (github.ref: refs/heads/gh-readonly-queue/main/...)")
    status = sub.add_parser('status')
    status.add_argument('--json', action='store_true', help="the port's answer as JSON (scripts/spend record reads it)")
    follows = sub.add_parser('follow')
    follows.add_argument('--target', help='wait until /tower/deploy/last-sha is this commit')
    follows.add_argument('--build', help='the build id ring printed: follow that build only')
    follows.add_argument('--since', type=float, help='epoch seconds; a recorded build that started earlier is not the one')
    args = parser.parse_args(argv)
    if args.command == 'ring':
        return ring(environ)[0]
    if args.command == 'queue':
        return queue(args.sha, args.ref, environ)
    absent = missing(PORT_VARS, environ)
    if absent:
        say_missing(absent, 'the port')
        return 2
    port = gate_infra.Port(environ['TOWER_PORT_URL'], environ['TOWER_PORT_TOKEN'])
    if args.command == 'status':
        try:
            state = read_status(port)
        except gate_infra.Refused as error:
            print(f'deploy: the status could not be read ({error})', file=sys.stderr)
            return 2
        print(json.dumps(state)) if args.json else describe(state)
        recorded, live = record(state), record_live(state)
        if recorded:  # stderr under --json, so the answer stays one JSON document for scripts/spend record
            print(f'recorded: {len(recorded)} build(s) in {DEPLOY_RUNS}.json, the slow path builds\' seconds',
                  file=sys.stderr if args.json else sys.stdout)
        if live:
            print(f'recorded: {len(live)} landing(s) in {LIVE_RUNS}.json, the snapshot VAL-deploy-1s reads',
                  file=sys.stderr if args.json else sys.stdout)
        if live is None:  # PUSH-STEPS: the push of the last landing is in the snapshot even when nothing new was recorded
            try:
                with open(os.path.join(RUNS_ROOT, RUNS_FOLDER, LIVE_RUNS + '.json')) as handle:
                    live = json.load(handle).get('runs') or []
            except (OSError, ValueError):
                live = []
        say_steps(steps(state, live), sys.stderr if args.json else sys.stdout)
        return 0
    return follow(port, args.target, args.build, args.since)


if __name__ == '__main__':
    sys.exit(main())
