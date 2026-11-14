"""The session's deploy tool (DEP1): ring the deploy doorbell and follow the build to its end, with no AWS credential.

  scripts/deploy ring                  POST to the doorbell; 202 prints the build id
  scripts/deploy status                the port's GET /v1/deploy/status: last_sha, the last build with its tail and the last
                                       ring/skip decision, as the service observed them (DEP3: it publishes them to the log)
  scripts/deploy follow [--target SHA] [--build ID] [--since EPOCH]
                                       poll the status until the deploy ends; a failure prints the failed names and tail

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
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config  # noqa: E402
import gate_infra  # noqa: E402

DOORBELL_VARS = ('TOWER_DEPLOY_DOORBELL_URL', 'TOWER_DEPLOY_DOORBELL_TOKEN')
PORT_VARS = ('TOWER_PORT_URL', 'TOWER_PORT_TOKEN')
ENDED = ('succeeded', 'nothing_new')
STALE_S = 300  # an observation older than this while a ring was made: the service is not reporting


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


def ring(environ=None, opener=urllib.request.urlopen):
    """Ring the doorbell once. Returns (exit code, build id or None)."""
    environ = os.environ if environ is None else environ
    absent = missing(DOORBELL_VARS, environ)
    if absent:
        say_missing(absent, 'the doorbell')
        return 2, None
    request = urllib.request.Request(environ['TOWER_DEPLOY_DOORBELL_URL'], method='POST', data=b'',
                                     headers={'Authorization': f"Bearer {environ['TOWER_DEPLOY_DOORBELL_TOKEN']}"})
    try:
        with opener(request, timeout=config.get('gate-infra.deploy_ring_timeout_s')) as answer:
            status, body = answer.status, answer.read().decode('utf-8', 'replace')
    except urllib.error.HTTPError as error:
        status, body = error.code, error.read().decode('utf-8', 'replace')
    except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
        print(f'deploy: the doorbell did not answer ({type(error).__name__}); it was not rung twice, so ring again',
              file=sys.stderr)
        return 2, None
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


def read_status(port):
    return port.call('GET', '/v1/deploy/status')


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
    while True:
        try:
            state = read_status(port)
        except gate_infra.Refused as error:
            print(f'deploy: the status could not be read ({error})', file=sys.stderr)
            state = None
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
        if clock() + pause > deadline:
            print('deploy: the wait ran out; the build may still be running, last reading:', file=sys.stderr)
            if state:
                describe(state, sys.stderr)
            return 2
        sleep(pause)
        pause = min(longest, pause * 1.5)


def main(argv=None, environ=None):
    environ = os.environ if environ is None else environ
    parser = argparse.ArgumentParser(prog='scripts/deploy', description=__doc__.split('\n')[0])
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('ring')
    sub.add_parser('status')
    follows = sub.add_parser('follow')
    follows.add_argument('--target', help='wait until /tower/deploy/last-sha is this commit')
    follows.add_argument('--build', help='the build id ring printed: follow that build only')
    follows.add_argument('--since', type=float, help='epoch seconds; a recorded build that started earlier is not the one')
    args = parser.parse_args(argv)
    if args.command == 'ring':
        return ring(environ)[0]
    absent = missing(PORT_VARS, environ)
    if absent:
        say_missing(absent, 'the port')
        return 2
    port = gate_infra.Port(environ['TOWER_PORT_URL'], environ['TOWER_PORT_TOKEN'])
    if args.command == 'status':
        try:
            describe(read_status(port))
        except gate_infra.Refused as error:
            print(f'deploy: the status could not be read ({error})', file=sys.stderr)
            return 2
        return 0
    return follow(port, args.target, args.build, args.since)


if __name__ == '__main__':
    sys.exit(main())
