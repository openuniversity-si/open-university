# The Tower — the engine

Open source under the [Apache License 2.0](LICENSE). This public repository starts with a fresh history (one initial
commit, 14/11/2026); contributions follow [CONTRIBUTING.md](CONTRIBUTING.md), and security reports
[SECURITY.md](SECURITY.md). Operations runbooks and internal records are not part of the public tree.

This repository is the engine of A Torre: the gate that judges every pull request, the event log, the contracts, the
configuration registry, and the services the engine deploys and runs. Agents start from [AGENTS.md](AGENTS.md).

Open University, the course site, left this repository (D-105, D-111; archive `567176bb`, D-110) and came back under
`apps/web` with a fresh history (D-319). It runs on AWS with its media on Cloudflare R2, and its Lambda image is built
from this repository (`apps/web/deploy/`).

## Structure

| Path | Purpose |
|---|---|
| `scripts/` | The gate (`gate-dev`, `gate-quiet`, `gate-noite`), the train (`train`), the services (`service`), the checks and the generators; libraries in `scripts/lib/`, script tests in `scripts/tests/` |
| `config/registry/` | The configuration registry: one file per key, and each owner's generated aggregate |
| `contracts/` | JSON contracts of events, units and the registry, and their generated types |
| `apps/web/` | Open University's site (D-319): its own Next.js app and lockfile, and `deploy/`, which builds its Lambda image ([apps/web/README.md](apps/web/README.md)) |
| `units/` | The engine's unit manifests |
| `services/runner/` | The Origin-era runner, kept in the tree and stopped (D-314); its control plane, a Cloudflare Worker, was retired (D-323); `services/runner/github/` stages the GitHub workflows |
| `docs/` | Decisions, process, architecture, operations, and the units' records |

## Local setup

```bash
bash scripts/cloud/setup.sh      # the pinned toolchain in .toolchain/ and the local PostgreSQL
source scripts/cloud/env.sh      # PATH and the local test database defaults
scripts/cloud/preflight          # names every gap and exits 2 when there is one
```

## Commands

| Command | Purpose |
|---|---|
| `scripts/run gate [dev\|quiet\|noite] [args]` | Run a gate the same way locally and in the cloud |
| `scripts/run test <name>` | Run `scripts/tests/<name>.test.sh` the way the gate runs it |
| `scripts/gate-dev --pr <n>` | The gate of a pull request's exact head; `--explain` prints the plan and runs nothing |
| `scripts/test-suite` | The whole script suite |
| `scripts/structure-check --base <ref>` | The structure check of a change |
| `scripts/generate --check` | Every generated file is current |
| `scripts/deploy status` | The engine's deploy on AWS: the last build, `last-sha` and the live code |

## Workflow

- **GitHub `openuniversity-si/open-university` is the source of truth** (D-314). A pull request branches from `main`
  and targets it, with a commit plan in its body ([AGENTS.md](AGENTS.md), delivery flow).
- **It lands through GitHub's merge queue.** The queue requires the `tower/gate` status, which a GitHub Actions job
  (`.github/workflows/tower-gate.yml`) posts by running `scripts/verify-commit` on the pull request and on the queue's
  merge commit. Run it yourself with `scripts/verify-commit --sha <commit> --base <base> --no-post`.
- **Every merge into `main` deploys the engine.** The `deploy-doorbell` workflow rings the deploy on AWS, which
  applies only what the merge changed. A change to the service's code alone is prepared while the queue verifies it,
  and the running service reloads it in place when `main` moves. No one deploys by hand
  ([RELEASES.md](docs/process/RELEASES.md)).
- **After each merge, the whole script suite runs** (`.github/workflows/full-suite.yml`); a red run opens an issue.

## Legacy backup

The pre-rewrite app was removed in the first `rewrite/v1` commit and remains permanently preserved by the
**`legacy-final`** and **`rewrite-base`** tags and the **`legacy`** branch, all at commit `134c168`. Keep these
references intact.
