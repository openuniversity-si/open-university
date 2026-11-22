# Proposed Workflow and Ruleset Changes (`D-087`, `D-359` proposed)

**Label:** `workflow change — para a Torre instalar`  
**Owner decision required:** Sessions never write `.github/workflows/` or apply GitHub rulesets (`D-087`). The files in this folder are staged and verified by `scripts/workflow-attest validate-proposed` and `scripts/tests/workflow-proposals.test.sh` without diverging from the currently installed workflows (`queue-checks` stays green).

## Included Proposals

| File | Finding | Purpose |
|---|---|---|
| `full-suite.yml` | **C6** | Keeps `CACHE-PGDATA` byte-for-byte identical to `tower-gate.yml`, opens/updates a deduplicated `main-red-andon` issue on failure (auto-closing on green recovery), and refreshes `config/validation/{verdicts,slo,runs/tower-gate}.json` + `scripts/tests/traced-covers.json` via a normal merge-queue PR (`TOWER_SNAPSHOT_TOKEN`, loop-guarded). |
| `tower-gate.yml` | **C6**, **C7** | Adds the `main-health` Andon stop-the-line job (running from `base`'s `scripts/workflow-attest main-health`, refusing non-`fix-main` PRs while `main` is red) and binds `tower/gate` to `needs: [part, pinned, main_health]`. |
| `site-canary.yml` | **M6** | Read-only synthetic HTTP probe (`scripts/site-canary`) against `https://openuniversity.si` (`/api/health` + `/` security headers) on `push` to `main`, every 15 minutes, and `workflow_dispatch`, with deduplicated `site-canary-red` issue alerting and zero deploy/AWS secrets. |
| `tower-gate-attest.yml` | **C7** | `workflow_run` on `main` (never checks out or executes PR code): runs `scripts/workflow-attest verify` to refuse workflow/action/ruleset modifications, fork `.github/` changes, or missing/non-green checks, then dispatches to the external GitHub App / AWS Port (`TOWER_GATE_ATTESTER_URL`) to post `tower/gate-attested` outside `integration_id: 15368`. |
| `ruleset-main.json` | **C7** | Proposed update to ruleset `27250343` requiring `tower/gate-attested` bound to the external GitHub App `integration_id` (closing `THREAT-gate`) and `main-health`, while preserving `MERGE` and `ALLGREEN`. |

## Owner / Torre Installation Steps (`D-087`)

1. **Approve `D-359`** (`docs/domain/decisions/D-359.md`, currently `status: proposed`) after Daniel decides on items 1–4 in the PR description.
2. **Provision GitHub App and secrets (Daniel / Torre):**
   - `TOWER_SNAPSHOT_TOKEN` (repository secret): fine-grained token or App token able to push `automation/refresh-snapshots-*` and open PRs that trigger `tower/gate` (never pushes to `main`).
   - External GitHub App `tower-gate-attester` (permissions: `statuses: write` or `checks: write`, `contents: read`): private key lives exclusively outside GitHub Actions (e.g. in the AWS Port handler). Note its integer `integration_id`.
   - `TOWER_GATE_ATTESTER_URL` and `TOWER_GATE_ATTESTER_TOKEN` (repository secrets): endpoint and bearer token for the external attester.
   - Optional repository variable `TOWER_SITE_URL` (defaults to `https://openuniversity.si`).
3. **Allowlist new workflows first** (gate PR citing approved `D-359`):
   - Add `.github/workflows/site-canary.yml` and `.github/workflows/tower-gate-attest.yml` to `config/registry/gate/gate.allowed_workflows.json`, run `scripts/generate`, and update the allowlist assertion in `scripts/tests/test_verify_commit.py`.
4. **Install workflows atomically in one owner PR** (`queue-checks` requires `services/runner/github/<name>` == `.github/workflows/<name>`):
   ```bash
   for f in full-suite.yml tower-gate.yml site-canary.yml tower-gate-attest.yml; do
     cp "services/runner/github/proposed/$f" "services/runner/github/$f"
     cp "services/runner/github/proposed/$f" ".github/workflows/$f"
   done
   ```
5. **Apply the updated ruleset `27250343`** after verifying `tower/gate-attested` posts green on a test PR:
   - Replace `"REPLACE_WITH_TOWER_GATE_APP_INTEGRATION_ID"` in `services/runner/github/proposed/ruleset-main.json` with the integer `integration_id` of `tower-gate-attester`.
   - Copy to `.github/rulesets/main.json` (updating `test_security.py` / `test_verify_commit.py` to expect the external App ID for `tower/gate-attested`) and apply via `gh api -X PUT repos/openuniversity-si/open-university/rulesets/27250343 --input .github/rulesets/main.json`.
   - Retire `TAIL-gate-fork-workflow` and `TAIL-ssdf-pw2-gate` (`D-344`) and record `THREAT-gate` spoofing finding as `fixed`.
6. **Clean up:** Delete `services/runner/github/proposed/` once all files are installed.

## Revert Paths

- **Andon (`main-health`):** Apply label `fix-main` to an urgent PR, close the `main-red-andon` issue, or restore the prior `full-suite.yml` / `tower-gate.yml` via an owner PR.
- **Site canary:** Remove `site-canary.yml` from `.github/workflows/`, `services/runner/github/`, and `gate.allowed_workflows`.
- **External App attestation (`THREAT-gate`):** Restore the previous `.github/rulesets/main.json` on ruleset `27250343` and remove `tower-gate-attest.yml` via an owner PR.
