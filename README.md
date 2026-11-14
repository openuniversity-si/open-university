# The Tower — the engine

Open source under the [Apache License 2.0](LICENSE). This public repository starts with a fresh history (one initial
commit, 14/11/2026); contributions follow [CONTRIBUTING.md](CONTRIBUTING.md), and security reports
[SECURITY.md](SECURITY.md). Operations runbooks and internal records are not part of the public tree.

This repository is the engine of A Torre: the gate that judges every pull request, the merge train that merges them,
the event log they share, the contracts, the configuration registry and the services that run the gate and the train
without an AI session. Agents start from [AGENTS.md](AGENTS.md).

Open University, the course site that lived in this repository, left the repository (D-105, D-111). Its archive is commit
`567176bb`, with full history (D-110). Its production site is frozen until Daniel pauses it
([RELEASES.md](docs/process/RELEASES.md)).

## Structure

| Path | Purpose |
|---|---|
| `scripts/` | The gate (`gate-dev`, `gate-quiet`, `gate-noite`), the train (`train`), the services (`service`), the checks and the generators; libraries in `scripts/lib/`, script tests in `scripts/tests/` |
| `config/registry/` | The configuration registry: one file per key, and each owner's generated aggregate |
| `contracts/` | JSON contracts of events, units and the registry, and their generated types |
| `units/` | The engine's unit manifests |
| `services/runner/` | The Tower runner: gates new PR heads and runs the train |
| `services/control-plane/` | The control plane, a Cloudflare Worker that owns the queue, the leases and the event log |
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
| `scripts/service status` | The gate and the train as services |

## Workflow

- **GitHub `openuniversity-si/open-university` is the working repository.** A PR branches from `mod/roadmap-integration` and targets
  it; the merge train merges it with a merge commit once the gate passes on its exact head ([AGENTS.md](AGENTS.md),
  delivery flow).
- **No GitHub Actions dependency.** Every test runs through the local gate. A hosted runner is one optional, budgeted
  runner kind (ADR-41, D-086, D-087).
- **`main` is frozen** (D-054). A release is one merge of `mod/roadmap-integration` into `main`, and none is made while
  production is frozen.

## Legacy backup

The pre-rewrite app was removed in the first `rewrite/v1` commit and remains permanently preserved by the
**`legacy-final`** and **`rewrite-base`** tags and the **`legacy`** branch, all at commit `134c168`. Keep these
references intact.
