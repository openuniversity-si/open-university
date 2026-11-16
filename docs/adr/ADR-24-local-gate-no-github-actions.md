# ADR-24 — Every check runs on our box; no GitHub Actions

Status: superseded by D-314 (the gate runs on GitHub Actions since 14/11/2026; PADRAO-DEV F3a).

Date: 2026-10-14 · Status: accepted (Daniel's standing rule); amended 2026-10-30 by [ADR-41](ADR-41-gate-and-train-services.md) (D-086, D-087): "no GitHub Actions, ever" became "never depend on GitHub Actions": a hosted runner is one optional, budgeted runner kind, its workflow allowlisted by name (`gate.allowed_workflows`), and merging never waits on an Actions minute.

## Context
On 14/10/2026 the free GitHub Actions minutes for the month ran out: CI stopped and no PR could be merged, because
`scripts/merge-phase` required the Actions check "pipeline". Daniel: "Não podemos depender das ações do Github para nada.
Todos os testes, se necessário forem, tem que ser internos."

## Decision
- **No GitHub Actions, ever.** `.github/workflows/` is deleted (ci, nightly, mux-check, preview-sync). The guard test
  `apps/web/src/site/no-github-actions.test.ts` and a gate step fail if a workflow reappears.
- **One gate: `scripts/gate-local`**, run on the box. It is everything the old CI and nightly did: gitleaks (history + tree),
  no-workflows check, shellcheck + script tests, frozen install, lint, typecheck, raster guard, unit tests,
  catalog/editorial checks, integration tests and DB migration gate on the local PostgreSQL 18 (pgtools), catalog parity,
  test build and production build. `--nightly` adds the real cover cache (read-only R2 credential from
  `~/.config/the-tower/r2-ci-ro.env`, never printed), E2E and the fidelity report (non-blocking).
  `scripts/gate-quiet` is an alias that runs it on the working tree.
- **Merging:** `scripts/gate-local --pr N` (or `--sha`) checks the exact head commit out in a throwaway worktree and, on
  success, records `~/.local/state/open-university/gate/<sha>.pass`. `scripts/merge-phase` approves only: PR open, not
  draft, base main|rewrite/v1, MERGEABLE, and a local pass at the head sha; the merge is pinned with
  `--match-head-commit`. GitHub check runs and commit statuses are not consulted. `briefs/automerge-after.sh` runs the
  gate itself (from origin/main's scripts, not the PR's) when the pass is missing.
- **Preview branch:** after a merge into main, merge-phase moves `preview` to main through the API (was preview-sync.yml).
- **Mux check:** run by hand on the box: `pnpm catalog:sync-mux --check` with the read-only Mux token.
- **Vercel:** a merge to `main` still deploys production through Vercel's Git integration, not Actions. Other branches do not deploy on push; one preview is deployed on demand (D-046). Merge does not require a green Vercel preview.
- Branch protection is not available on this private free plan (HTTP 403), so no required status check exists to remove.

## Consequences
No GitHub minutes, no external queue; the box must be up to merge. A pass is local evidence, trusted because only our
agents merge.
