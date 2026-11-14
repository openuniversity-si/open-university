# TRAIN-DEFINITIVE — coordinator rollout

The session changes source and PR #1086 only. The coordinator performs the VM and Worker-secret cutover below.
Daniel closed outcome (c) by owner decision on 2026-11-02 at 22:19 BRT, accepting 10.523 s ordinary and approximately
16.8 s cold. Stop speed optimization in this unit. The runtime job budget remains ten seconds; phase observations
from this cutover feed the later performance unit. A job that exhausts the budget must answer negatively and free
its resources; do not raise the budget to accommodate the accepted gate timing.

Apply the atomic job-v2 cutover with the old runner stopped. The integration ancestry check below must succeed
before deploying or starting the new runner. If the PR is not merged yet, leave the three services stopped and
complete its merge through the train, then continue; do not start mixed protocol versions.

Run as `atorre` on `the-tower-runner`, in its existing checkout. Stop the watchdog timer, its service, then the runner before the atomic protocol cutover:

```bash
set -euo pipefail
set +x
export OU_CONFIG_STORE=file
tower_checkout="$(systemctl --user show tower-runner.service --property=WorkingDirectory --value)"
cd "$tower_checkout"
systemctl --user stop tower-runner-watch.timer
systemctl --user stop tower-runner-watch.service
systemctl --user stop tower-runner.service
git fetch origin mod/roadmap-integration:refs/remotes/origin/mod/roadmap-integration
git switch mod/roadmap-integration
git merge --ff-only origin/mod/roadmap-integration
tower_pr_head="$(git ls-remote origin refs/pull/1086/head | cut -f1)"
git merge-base --is-ancestor "$tower_pr_head" HEAD
bash scripts/cloud/setup.sh
. scripts/cloud/env.sh
umask 077
mkdir -p ~/.config/tower ~/.config/systemd/user
test -f ~/.config/tower/runner.env || install -m 600 /dev/null ~/.config/tower/runner.env
chmod 600 ~/.config/tower/runner.env
${EDITOR:-vi} ~/.config/tower/runner.env
```

Use the secret manager to set these variables in that existing file, without displaying values. Use one
`NAME='value'` assignment per line, with no `export` prefix or shell commands, so both systemd and the bootstrap
subshell can consume it: `OU_RUNNER_TOKEN`
must equal Worker `RUNNER_TOKEN`; `TOWER_EVENTS_TOKEN` must equal Worker `EVENTS_TOKEN`; `GH_TOKEN` (or
`GITHUB_TOKEN`) must authorize repository contents and PR writes. Add `CLOUDFLARE_API_TOKEN`, scoped to Workers
Scripts:Edit on account `24f3bba6ed24fb6ae6cf207026f891f8`. On any rotation, update every holder in
`service.token_holders`, then restart the holders. Preserve the Worker's `GITHUB_WEBHOOK_SECRET`, `ADMIN_TOKEN`,
`RUNNER_TOKEN` and `EVENTS_TOKEN`; initial deployment uses `keep_bindings` rather than recreating them.

Load that file only inside the coordinator command, validate names, inspect upload metadata, then bootstrap the Worker:

```bash
(
  set -euo pipefail
  set +x
  set -a
  . ~/.config/tower/runner.env
  set +a
  export OU_CONFIG_STORE=file
  python3 scripts/lib/service_credentials.py --kind vm
  python3 - <<'PY'
import os, socket, subprocess, sys
sys.path.insert(0, 'scripts/lib')
import config, forge_events, forge_git_ref
clock = forge_events.SystemClock()
lock = config.get('train.lock_ref')
held = forge_git_ref.GitRefs().read(lock)
if held and held[1].get('expires', '') > forge_events.rfc3339(clock.now()):
    owner = held[1].get('owner', '')
    producer = config.get('train.producer')
    host = socket.gethostname()
    runner = os.environ.get('OU_RUNNER_NAME', host)
    if not owner.startswith((f'{producer}@{host}:', f'{producer}@{runner}/')):
        raise SystemExit('another owner holds the train lock; wait for that owner, do not clear it')
    # Use the registered cleanup CLI in its own process, retaining its exact-owner comparison.
    subprocess.run(['timeout', '--kill-after=1', '9', sys.executable, 'scripts/lib/service_lock.py',
                    '--repo', config.get('forge-events.repo'), '--owner', owner.split('@', 1)[1]], check=True)
    print('released the stopped VM service lock')
PY
  python3 scripts/lib/service_deploy.py --dry-run
  python3 scripts/lib/service_deploy.py
)
scripts/service runner --print-unit --kind vm > ~/.config/systemd/user/tower-runner.service
scripts/service runner --print-unit tower-runner-watch.service > ~/.config/systemd/user/tower-runner-watch.service
scripts/service runner --print-unit tower-runner-watch.timer > ~/.config/systemd/user/tower-runner-watch.timer
systemctl --user daemon-reload
systemctl --user enable --now tower-runner.service tower-runner-watch.timer
scripts/service liveness
```

The unit uses required `EnvironmentFile=%h/.config/tower/runner.env`, `KillMode=control-group` and
`TimeoutStopSec=1`. Confirm the upload kept its bindings, `/readyz` succeeds, and these two tree IDs match:

```bash
python3 - <<'PY'
import json, subprocess, sys, urllib.request
sys.path.insert(0, 'scripts/lib')
import config
base = config.get('service.control_url').rstrip('/')
def read(path):
    request = urllib.request.Request(base + path, headers={'User-Agent': config.get('service.user_agent')})
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.load(response)
assert read('/readyz')['ready']
status = read('/status')
expected = subprocess.check_output(['git', 'rev-parse', 'HEAD:services/control-plane'], text=True).strip()
assert status['deployed_tree'] == expected, 'deployed Worker tree differs from the merged source'
print(json.dumps({'deployed_tree': status['deployed_tree'], 'health': status['health']}))
for row in read('/events')['events']:
    if row.get('kind') in ('result', 'died'):
        print(json.dumps({name: row.get(name) for name in
                          ('at', 'kind', 'job', 'outcome', 'reason', 'duration_s', 'started_at', 'finished_at', 'phases')}))
PY
```

For actual VM measurements use each result's `phases` offsets, subtract adjacent offsets for phase durations, and
subtract `started_at` from the Worker's result event `at` for claim-to-reported time. Verify the enforced budget,
explicit negative answers on exhaustion, and resource release for gate/train/sweep/deploy and TERM/KILL/restart:
the runner slot and exact-owner train lock are free after termination, and older heads or closed PRs do not return.
Treat improving completion time within ten seconds as the later unit's target, not a blocker that reopens (c). Observe the next control-plane merge deploy itself, rather than
treating the manual bootstrap as that proof. Record evidence in the engine diary, never a PR status comment.

The Worker snapshot observed by this session had `deployed_tree=null` and no phase data. This session therefore
cannot provide post-change VM phase measurements, secret-preservation confirmation or automatic-deploy confirmation.
