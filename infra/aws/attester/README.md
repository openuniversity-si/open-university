# tower-gate-attester — the AWS verifier of `tower/gate-attested` (THREAT-gate, C7, `D-359` Salto 2)

**Authority:** `D-359` (3) — Torre por delegação do Daniel 22/11/2026; builds on D-352, D-087.
**Threat closed:** any workflow file a PR changes runs on that PR, so a PR (or a fork) can make GitHub Actions
(integration `15368`) report a green `tower/gate`. A required check bound to an App *outside* Actions, whose verdict is
computed in AWS from facts it reads itself, cannot be forged by a workflow.

## Shape

```
GitHub App tower-gate-attester ──webhook──▶ Lambda URL tower-gate-attester (front: HMAC, filter, 202 in ms)
                                                   │ async invoke (Lambda queues + retries)
                                                   ▼
                                    tower-gate-attester-worker (reserved concurrency 1)
                                      App JWT (RS256, key in Secrets Manager) → installation token
                                      reads check runs, PR files, comments, permissions, commit parents
                                      POST /check-runs  name=tower/gate-attested  head_sha=<exact SHA>
```

| File | What |
|---|---|
| `attester.py` | front + worker + the pure verdict; `evaluate` CLI previews a verdict with a reader token, writing nothing |
| `stack.json` | stack `tower-gate-attester` (us-east-1): 2 secrets, 1 log group, 1 role, 2 functions, Function URL |
| `deploy.sh` | deterministic zip → `s3://tower-outputs-<acct>-us-east-1/artifacts/lambda/tower-gate-attester/<sha256>.zip` → deploy |
| `app_manifest.py` | the App manifest page, the local callback server and the code→secrets conversion (prints no secret) |

The stack is **not** under `infra/aws/stacks/` and is not named `tower-app-*`: the app deployer never touches it; the
Torre deploys it with `infra/aws/attester/deploy.sh [APP_ID]`. Its role `tower-gate-attester` carries no
`tower-boundary` because that boundary allows no secret but `tower/agent-env/*` and `tower/torre-webhook-*`; instead
the role itself is the limit: `logs:CreateLogStream`/`PutLogEvents` on its log group, `secretsmanager:GetSecretValue`
on its two secrets only, `lambda:InvokeFunction` on its worker only (tested by `scripts/tests/test_gate_attester.py`).

## Design conditions (problems A–I)

- **(A) Backend.** Lambda + Function URL (`AuthType NONE`, like `tower-deploy-doorbell`), webhook HMAC
  `X-Hub-Signature-256` verified against `tower/gate-attester/webhook-secret`; App key in
  `tower/gate-attester/private-key`. No repository secret, no workflow: the App receives GitHub's own webhooks.
- **(B) Facts, never verdicts.** Nothing a workflow sends is read. For a PR head: the newest run (by id) of each required
  check (`tower/gate`, `web`, `gate pinned to the base`) *reported by integration 15368* on that exact SHA is completed
  and `success` (a same-named run of another App is ignored); the PR's own file list (fail closed past 3000 files, renames
  count both names); the head repository (fork or not).
- **(C) Triggers, no race.** `check_run`/`check_suite` completed (Actions), `status`, `merge_group`, `pull_request`
  (opened/synchronize/reopened/edited), `issue_comment` with a Decision, and a re-run of our own check. Every event only
  enqueues `{sha, pr, branch}`; the single worker re-reads all facts, so the last verdict always reflects the latest
  facts. Not all complete → `in_progress`; any red → `failure`; a job for a head that moved is dropped.
  Merge queue: on `gh-readonly-queue/main/pr-N-<prefix>` the worker requires the required checks green on the group
  commit, the commit to be GitHub's merge of exactly `[prefix, PR head]`, and that PR head to carry a green
  `tower/gate-attested` of this App.
- **(D) The Torre's workflow installs (D-087) — decision.** *No ruleset bypass actor is added* (`bypass_actors` stays
  `[]`). A PR touching `.github/workflows/`, `.github/actions/` or `.github/rulesets/` is attested only when a
  repository **administrator** commented on it a body that starts with `Decision:` and contains the line
  `Attest-Head: <the PR head SHA>` — the Torre's existing Decision comment plus one line binding it to the exact code.
  A new push needs a new line; a fork touching anything under `.github/` is always refused. Rationale: a bypass would
  let the bypassing actor skip every required check on every PR (and the queue); the comment path keeps the queue, the
  gate and the audit trail, and is the option D-359 (D) names ("accepting `.github/` changes when the PR cites a
  Torre-approved decision").
- **(E) Andon.** `main-health`/`full-suite` are not inputs and the prepared ruleset does not require `main-health`: the
  Andon never freezes the queue through this check.
- **(F) Latency.** The front answers in milliseconds; the worker posts ~1–2 s after the last required check completes
  (5–7 GitHub reads, one write). No polling.
- **(G) No personal token.** Only the App's installation token (1 h, minted per container); `TOWER_SNAPSHOT_TOKEN`
  stays out (D-359 (4)).
- **(H) App ID.** The ruleset entry `tower/gate-attested` gets the App's numeric id (from `app.json` after conversion);
  the stack parameter `AppId` too. Until then the worker refuses every job.
- **(I) Negative canary first.** See step 5 below: a red attestation must be seen before the ruleset requires it.

## Runbook (Torre)

1. `infra/aws/attester/deploy.sh` — stack up, secrets hold generated placeholders (never read by anyone).
2. `python3 infra/aws/attester/app_manifest.py serve --out <dir>` on the box, open `http://127.0.0.1:8765/` in the
   browser logged in as an org owner, click, then "Create GitHub App". The callback converts the code, writes the key
   and webhook secret straight to Secrets Manager, writes `<dir>/app.json` and redeploys with `AppId`.
3. Install the App on `openuniversity-si/open-university` **only** (`https://github.com/apps/<slug>/installations/new`).
4. Watch a PR: `tower/gate-attested` appears from the App and turns green after `tower/gate`, `web`, `gate pinned to the base`.
5. Negative canary: a throw-away PR that changes `.github/workflows/` without the Decision line must get `failure`;
   adding `Attest-Head: <head>` in a Decision comment flips it to `success`; then close the PR without merging.
6. Apply ruleset `27250343` with `tower/gate-attested` bound to the App id (prepared PUT), in a Torre step citing D-359,
   and update `.github/rulesets/main.json` and its tests in a PR.

## Rollback

- Ruleset: `gh api -X PUT repos/openuniversity-si/open-university/rulesets/27250343 --input <backup>` (the GET taken
  before the change, without `id`/`_links`/timestamps) — immediate, the queue no longer waits for the attester.
- App: suspend or uninstall it in the org settings; delete the App if abandoned.
- AWS: `aws cloudformation delete-stack --stack-name tower-gate-attester` (the two secrets are `Retain`: delete them
  with `aws secretsmanager delete-secret` if abandoned).
