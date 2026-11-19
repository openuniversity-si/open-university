"""The session's deploy tool (DEP1): ring the deploy doorbell and follow the build to its end, with no AWS credential.

  scripts/deploy ring                  POST to the doorbell; 202 prints the build id
  scripts/deploy queue --sha SHA --ref REF
                                       QUEUE-RELOAD, the merge_group job: ring `prepare` for the merge queue's commit, watch
                                       main (git ls-remote) and ring `landed` the moment main is that commit
  scripts/deploy status                the port's GET /v1/deploy/status: last_sha, the last build with its tail and the last
                                       ring/skip decision, as the service observed them (DEP3: it publishes them to the log);
                                       a succeeded build's seconds go into config/validation/runs/deploy.json (record)
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
import http.client
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
import source_remote  # noqa: E402

DOORBELL_VARS = ('TOWER_DEPLOY_DOORBELL_URL', 'TOWER_DEPLOY_DOORBELL_TOKEN')
PORT_VARS = ('TOWER_PORT_URL', 'TOWER_PORT_TOKEN')
ENDED = ('succeeded', 'nothing_new')
STALE_S = 300  # an observation older than this while a ring was made: the service is not reporting
RUNS_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RUNS_FOLDER = 'config/validation/runs'  # the run snapshots scripts/model's run-durations measure reads (scripts/lib/runs.py)
DEPLOY_RUNS = 'deploy'  # config/validation/runs/deploy.json: the snapshot VAL-deploy-1s reads
DEPLOY_KEEP = 20


def record(state, root=None, now=None):
    """PADRAO-DEV F8d: the deploy's build seconds recorded the way the gate's runs are (config/validation/runs/,
    read by scripts/model's run-durations measure), so VAL-deploy-1s has a source. The port answers only the last
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
        print('deploy: a build is running already (409); scripts/deploy follow waits for it')
        return 2, None
    if status == 401:
        print('deploy: the doorbell refused the token (401): TOWER_DEPLOY_DOORBELL_TOKEN is not the current one; '
              'Daniel provisions a new one', file=sys.stderr)
        return 1, None
    print(f'deploy: the doorbell answered {status}: {body[:200]}', file=sys.stderr)
    return 1, None


WARM_S = 5.0  # QUEUE-BELL: how often the watch rings `prepare` again, to keep the connection and both Lambdas warm


class Bell:
    """QUEUE-BELL (the Torre, 15/11): one HTTPS connection to the doorbell, kept open for the whole watch. The `landed`
    ring was 236-1400 ms on five merges (#34-#39): a new TLS connection from the runner each time, and a doorbell or port
    Lambda that had gone cold since `prepare`. The watch now sends every word on this connection (HTTP/1.1 keep-alive)
    and rings `prepare` again every WARM_S while it waits: the port records a prepare once (http_port.QUEUE_SAID) and
    wakes nobody for the repeats, so they only keep the connection, the doorbell and the port warm for the landing. A
    connection the server closed is opened again once and the word sent again (the port's record is idempotent).
    send() answers the HTTP status, or None when the doorbell did not answer; the token is never printed."""

    def __init__(self, environ, connect=http.client.HTTPSConnection, timeout_s=10.0):
        parts = urllib.parse.urlsplit(environ['TOWER_DEPLOY_DOORBELL_URL'])
        self.host, self.path = parts.netloc, parts.path or '/'
        self.headers = {'Authorization': f"Bearer {environ['TOWER_DEPLOY_DOORBELL_TOKEN']}",
                        'Content-Type': 'application/json'}
        self.connect, self.timeout_s, self.connection = connect, timeout_s, None

    def send(self, word):
        body = json.dumps(word).encode()
        for attempt in (1, 2):
            try:
                if self.connection is None:
                    self.connection = self.connect(self.host, timeout=self.timeout_s)
                self.connection.request('POST', self.path, body=body, headers=self.headers)
                answer = self.connection.getresponse()
                answer.read()
                return answer.status
            except (http.client.HTTPException, OSError):
                self.close()
        return None

    def close(self):
        if self.connection is not None:
            try:
                self.connection.close()
            except OSError:
                pass
            self.connection = None


def queue(sha, ref, environ=None, bell=None, heads=None, clock=time.monotonic, sleep=time.sleep,
          limit_s=1800.0, every_s=0.25, gone_s=15.0, warm_s=WARM_S):
    """QUEUE-RELOAD (infra/service/tower_infra/queue_deploy.py): the merge_group job's part. Rings `prepare` for the queue's
    commit at once, then watches main and the queue's branch every every_s: main at sha rings `landed` at once (the
    service checks it again before it orders anything); the branch gone for gone_s with main elsewhere is the group
    leaving the queue unmerged. GitHub pushes nothing to a job, so this is the one bounded watch: limit_s at most, the
    job's own timeout above it. QUEUE-BELL: every word goes on one kept connection (Bell), and `prepare` is rung again
    every warm_s while it waits. Returns 0 when the landing was rung (202) or nothing landed, 1 when it was refused, 2
    when the doorbell did not answer or the environment lacks it."""
    environ = os.environ if environ is None else environ
    if bell is None:
        absent = missing(DOORBELL_VARS, environ)
        if absent:
            say_missing(absent, 'the doorbell')
            return 2
        bell = Bell(environ)
    if heads is None:  # the forge's adapter (D-069 item 7): its URL and its ls-remote
        url = source_remote.repo_url(environ)
        heads = lambda: source_remote.heads(url, ['refs/heads/main', ref])  # noqa: E731
    began, gone = clock(), None
    status = bell.send({'event': 'prepare', 'sha': sha})  # a failed prepare does not stop the watch: landed prepares too
    print(f'deploy: prepare rung for {sha[:12]} ({status}, {(clock() - began) * 1000:.0f} ms)')
    warmed = clock()
    try:
        while clock() - began < limit_s:
            found = heads()
            if found.get('refs/heads/main') == sha:
                seen = clock()
                status = bell.send({'event': 'landed', 'sha': sha})
                print(f'deploy: main is {sha[:12]} {seen - began:.1f} s after the watch began; landed rung in '
                      f'{(clock() - seen) * 1000:.0f} ms ({status})')
                return 0 if status == 202 else 1 if status in (400, 401, 403) else 2
            if found and ref not in found:
                gone = clock() if gone is None else gone
                if clock() - gone >= gone_s:
                    print(f'deploy: {ref} left the queue and main is not {sha[:12]}: nothing landed')
                    return 0
            else:
                gone = None
            if clock() - warmed >= warm_s:  # QUEUE-BELL: the connection and both Lambdas stay warm for the landing
                bell.send({'event': 'prepare', 'sha': sha})
                warmed = clock()
            sleep(every_s)
        print(f'deploy: {sha[:12]} did not land within {limit_s:.0f} s: the push rings the deploy build when it does')
        return 0
    finally:
        bell.close()


RING_WAIT_S = 240.0  # RING-RETRY: the push job's 5 minutes, less its checkout and the last ring
RING_EVERY_S = 10.0


def ring_until_free(environ=None, opener=urllib.request.urlopen, wait_s=None, every_s=RING_EVERY_S, clock=time.monotonic,
                    sleep=time.sleep):
    """RING-RETRY (15/11, #41): the push job's ring. A 409 means another deploy build runs (CodeBuild runs one at a
    time), and nobody rings again for this merge (deploy.auto is false on GitHub): #41's build never ran, last-sha stayed
    behind main, and the next merges' queue swap was refused by its parent check. In a GitHub Actions job
    (GITHUB_ACTIONS=true) the 409 is rung again every every_s until a build starts or wait_s ends; a later build deploys
    main's head, which carries this merge. Elsewhere (a session's scripts/deploy ring) it is one ring, as before.
    Returns ring()'s (exit code, build id or None)."""
    environ = os.environ if environ is None else environ
    if wait_s is None:
        wait_s = RING_WAIT_S if environ.get('GITHUB_ACTIONS') == 'true' else 0.0
    began = clock()
    while True:
        code, build = ring(environ, opener)
        if code != 2 or build is not None or clock() - began + every_s > wait_s:
            return code, build
        if missing(DOORBELL_VARS, environ):
            return code, build
        print(f'deploy: ringing again in {every_s:g} s, until a build starts ({wait_s:g} s at most)')
        sleep(every_s)


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
    sub.add_parser('status')
    follows = sub.add_parser('follow')
    follows.add_argument('--target', help='wait until /tower/deploy/last-sha is this commit')
    follows.add_argument('--build', help='the build id ring printed: follow that build only')
    follows.add_argument('--since', type=float, help='epoch seconds; a recorded build that started earlier is not the one')
    args = parser.parse_args(argv)
    if args.command == 'ring':
        return ring_until_free(environ)[0]
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
        describe(state)
        recorded = record(state)
        if recorded:
            print(f'recorded: {len(recorded)} build(s) in {DEPLOY_RUNS}.json, the snapshot VAL-deploy-1s reads')
        return 0
    return follow(port, args.target, args.build, args.since)


if __name__ == '__main__':
    sys.exit(main())
