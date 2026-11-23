# Staged Workflow and Ruleset Changes (`D-087`, `D-359`)

**Label:** `workflow change — para a Torre instalar`  
**Governance (`D-087`, `D-359`):** instalado pela Torre, D-359 (`Torre por delegação do Daniel 22/11/2026`; `builds on D-352 (1)(3), D-360, D-087`). Sessions never write `.github/workflows/` or apply GitHub rulesets (`D-087`). The files in this folder are staged and verified by `scripts/workflow-attest validate-proposed` and `scripts/tests/workflow-proposals.test.sh` without diverging from the currently installed workflows (`queue-checks` stays green).

## Staged Files and Rollout Scope (`D-359`)

| File | Finding | Rollout Leap (`D-359`) | Purpose |
|---|---|---|---|
| `site-canary.yml` | **M6** | **Salto 1 (approved now)** | Read-only synthetic HTTP probe (`scripts/site-canary`) against `https://openuniversity.si` (`/api/health` + `/` security headers) on `push` to `main`, every 15 minutes, and `workflow_dispatch`, with deduplicated `site-canary-red` issue alerting and zero deploy/AWS secrets. |
| `full-suite.yml` | **C6** | **Salto 2 (Andon in principle; `refresh-snapshots` deferred)** | Keeps `CACHE-PGDATA` byte-for-byte identical to `tower-gate.yml` and adds a deduplicated `main-red-andon` issue on failure (auto-closing on green recovery). `refresh-snapshots` and `TOWER_SNAPSHOT_TOKEN` are deferred by `D-359` (no new key now; prefer an App token over a personal token if introduced later). |
| `tower-gate.yml` | **C6**, **C7** | **Not installed: `main-health` declined by `D-363`** (a flake would freeze the queue; the Andon stops the site release instead, `scripts/workflow-attest promotion-health`). Kept as the record of the D-359 draft: | Adds the `main-health` Andon stop-the-line job (running from `base`'s `scripts/workflow-attest main-health`, refusing non-`fix-main` PRs while `main` is red) and binds `tower/gate` to `needs: [part, pinned, main_health]`. Enters only after fixing `full-suite` reds on `main` (22/11 21:07–21:24 BRT: `gate-areas` coupled to the live covers graph) and stabilizing `full-suite`. |
| `tower-gate-attest.yml` | **C7** | **Salto 2 (subject to conditions B/C/D)** | Staged draft for external GitHub App attestation (`tower-gate-attester`, `THREAT-gate`). Must be updated to satisfy mandatory design conditions **(B)**, **(C)**, and **(D)** of `D-359` before installation in Salto 2. |
| `ruleset-main.json` | **C7** | **Salto 2 (subject to conditions B/C/D)** | Staged draft update to ruleset `27250343` requiring `tower/gate-attested` bound to the external GitHub App `integration_id` (outside `15368`) and `main-health`, while preserving `MERGE` and `ALLGREEN`. Applied only in Salto 2 after `full-suite` stabilizes and conditions **(B)**, **(C)**, **(D)** are met. |

## Torre Installation Runbook — Two Leaps (`D-087`, `D-359`)

### Leap 1 / Salto 1 (Now — `site-canary.yml`, `M6`)

1. **Allowlist `site-canary.yml` first** (separate gate PR citing accepted `D-359`):
   - Add `.github/workflows/site-canary.yml` to `config/registry/gate/gate.allowed_workflows.json`, run `scripts/generate`, and update the allowlist assertion in `scripts/tests/test_verify_commit.py`.
2. **Install `site-canary.yml` in a Torre PR (`D-087`)** (`queue-checks` requires `services/runner/github/site-canary.yml` == `.github/workflows/site-canary.yml`):
   ```bash
   cp services/runner/github/proposed/site-canary.yml services/runner/github/site-canary.yml
   cp services/runner/github/proposed/site-canary.yml .github/workflows/site-canary.yml
   ```
   - Optional repository variable `TOWER_SITE_URL` (defaults to `https://openuniversity.si`). Zero secrets and zero production writes.

### Leap 2 / Salto 2 (After Stabilization and Design Conditions B/C/D)

1. **`full-suite` Andon (`main-red-andon`) and `main-health` (`C6`):**
   - First fix the root cause of `full-suite` reds on `main` (22/11 21:07–21:24 BRT: `gate-areas` test coupled to the live covers graph) and confirm `full-suite` is green and stable on `main`.
   - Keep `refresh-snapshots` and `TOWER_SNAPSHOT_TOKEN` out of Salto 2 while deferred under `D-359` (no new key now; if introduced later, prefer a GitHub App token over a personal token).
   - Then have the Torre install the `full-suite.yml` Andon (`main-red-andon`) into `services/runner/github/` and `.github/workflows/` (`D-087`). `D-363`: the `tower-gate.yml` `main-health` job is **not** installed; a confirmed red stops promotion (`apps/web/deploy/promotion-guard.sh`), never the merge queue.
2. **External GitHub App `tower-gate-attester` (`THREAT-gate`, `C7`) — mandatory conditions before installation:**
   - **(B) Independent AWS-side verification and `main`-restricted environment:** the AWS attester verifies the facts on its own using the GitHub App token (changed files, head repository, required checks on the exact head SHA) and never trusts a verdict sent by the workflow; attester credentials live only in a deployment environment restricted to `main`, never as a repository secret.
   - **(C) Complete trigger and check coverage:** attestation triggers on completion of both `tower-gate` and `web` (and in the merge queue), posting green `tower/gate-attested` only when all required checks are green.
   - **(D) Explicit Torre workflow-installation path (`D-087`):** prevent `tower/gate-attested` from deadlocking Torre workflow installations (for example, an administrator bypass in `pull_request` mode, or accepting `.github/` changes when the PR cites a Torre-approved decision).
3. **Install Leap 2 attestation workflow and apply ruleset `27250343` (Torre PR, `D-087`):**
   - Add `.github/workflows/tower-gate-attest.yml` to `config/registry/gate/gate.allowed_workflows.json` in a gate PR citing `D-359`.
   - Install the revised `tower-gate-attest.yml` into both `services/runner/github/` and `.github/workflows/`.
   - After verifying `tower/gate-attested` posts green on a test PR, replace `"REPLACE_WITH_TOWER_GATE_APP_INTEGRATION_ID"` with the integer `integration_id` of `tower-gate-attester`, update `.github/rulesets/main.json` (and `test_security.py` / `test_verify_commit.py`), apply via `gh api -X PUT repos/openuniversity-si/open-university/rulesets/27250343 --input .github/rulesets/main.json`, and record `THREAT-gate` as `fixed`.
   - Delete `services/runner/github/proposed/` once all approved files are installed.

### Deferred (`D-359`)

- **`refresh-snapshots` and `TOWER_SNAPSHOT_TOKEN`:** deferred under `D-359` (no new key now; if introduced later, prefer a GitHub App token over a personal token).

## Revert Paths

- **Site canary (Salto 1):** Remove `site-canary.yml` from `.github/workflows/`, `services/runner/github/`, and `gate.allowed_workflows` via a Torre PR.
- **Andon (`D-363`):** Re-run `full-suite` on the commit (a flake), close the `main-red-andon` issue, remove the guard call from `apps/web/deploy/build-image.sh`, or restore the prior `full-suite.yml` via a Torre PR.
- **External App attestation (`THREAT-gate`, Salto 2):** Restore the previous `.github/rulesets/main.json` on ruleset `27250343` and remove `tower-gate-attest.yml` via a Torre PR.
- **Decision (`D-359`):** Record a superseding decision by an independent approver (Torre or owner), or by Daniel for money or other people.
