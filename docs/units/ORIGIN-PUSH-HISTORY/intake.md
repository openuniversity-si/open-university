# ORIGIN-PUSH-HISTORY — intake

## Pedido
Answer `pushes(repo, branch)` and `force_pushes(repo, branch)` on the Origin forge adapter from the engine's own journal, so `unit_check --operations --adapter origin` ends at 0 refusals (from 3), and github stays at 0. Brief: the operation check's three refusals for origin (stall_report pushes; commit_check pushes and force_pushes).

## Intenção
Make the Origin adapter a complete forge for the operations the engine's consumers need, without inventing history: a force push that happened must be visible, and a gap must be named, never read as "clean".

## Contexto
- The Origin public API has no push-history route (brief fact 1; not re-verified: the repo holds no OpenAPI file).
- `repository.pushed` carries the ref triple (`refUpdates[]`: before, after, created, deleted, forced) and the control plane receives it (fixture: `services/control-plane/test/origin.test.mjs:158-159`). It keeps two ref updates and drops the rest (`services/control-plane/src/core.js:364-375`).
- GitHub answers both operations from `/repos/{repo}/activity` (`scripts/lib/forge_github.py:453`, `:568`).
- Consumers: `scripts/lib/commit_check.py` (push_errors, force_push_errors, lines 74-92) and `scripts/lib/stall_report.py:41`.

## Regras
- One branch, one PR: `claude/origin-push-history-8yzfcu` (the session's designated branch; the brief's `feat/origin-push-history` name is not used).
- Merge commits only; never force-push; the train merges (never the session).
- Every commit carries a `Plan: N` trailer; the commit plan is in the PR body.
- The engine reads no credential files; Origin tokens stay in the environment.
- Production is frozen (D-054): no deploy from this session. The control plane redeploy is the coordinator's step.
- Thresholds are not loosened: `forge-events.git_ref_window` and `KEEP_EVENTS` keep their values.

## Problema real
Origin's adapter refuses `pushes` and `force_pushes` because the engine never writes ref moves to its journal, and the adapter's only source (the vendor API) has no such route. Until a ref move is journaled at its source, no operation can answer from history, and the commit discipline (no pushed-history rewrite, one commit per push) cannot be judged on origin.

## Lacunas
- The vendor's push delivery: whether every push, including pushes to PR head branches, arrives as `repository.pushed` (plan premises A1, A2). Not verifiable without a live delivery.
- The journal window at production volume: how many records a branch's history spans before the window ends. Not measured here.
- Whether the redeployed control plane writes `ref.updated` before the first gate on an origin-hosted PR (plan premise A3). Activation is the coordinator's step after merge.
