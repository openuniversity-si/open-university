# ORIGIN-PUSH-HISTORY — plan

Reads `audit.md` `## Causas raiz` (R1–R3). Mirrored in the PR description. Premises line for the PR: `Premises: none` (the registry lookup for the webhook and push route found no P-NN; the measured facts are carried here as A1–A5 with their blast radius).

## Alternativas

### R1 — the engine never journals a ref move (mecanismo faltando)
| Alternativa | Nível | Resolve a raiz? | Custo | Reversibilidade | Risco | Degrau |
|---|---|---|---|---|---|---|
| A1 the adapter answers `pushes` from the current tip (before = after = tip) | remendo | não: the triple is not reconstructed, only the tip | 5 min | easy | reports a history that never happened; a force push is invisible | 0 |
| A2 journal each `refUpdates` entry of `repository.pushed` as a `ref.updated` event on the repository channel, read back by `ControlAdapter` | corrige a classe | sim: every ref move of every branch is recorded at its source | ~1 h (contract, handler, adapter) | high: additive event, removable | the window bounds history (R2) | 1 |
| A3 a separate ref-history store (per-branch channel or a git-ref log) written by a new writer | redesenho | sim | ~1 day | low | a second journal next to the one that exists | 3 |

### R2 — a windowed read cannot say "complete" for one branch (arquitetura/desenho)
| Alternativa | Nível | Resolve a raiz? | Custo | Reversibilidade | Risco | Degrau |
|---|---|---|---|---|---|---|
| A1 return whatever the window holds and log a warning | remendo | não: a truncated read reads as complete | 5 min | easy | silent partial history; the brief forbids it | 0 |
| A2 one completeness rule in one pure function: an answer is given only when the window holds the branch's creation record (`created: true`) or the window is untruncated; otherwise refuse, naming the window | corrige a classe | sim for the branch: the creation record bounds the branch's whole history | ~30 min | high | refusals on branches older than the window (A4) | 1 |
| A3 per-branch channel, so a branch's records are never displaced by other repository traffic | redesenho | sim, without a creation-record proof | ~1 day | low: a channel-model change | more control-plane state | 3 |

### R3 — the coverage test encodes the gap as the contract (mecanismo faltando)
| Alternativa | Nível | Resolve a raiz? | Custo | Reversibilidade | Risco | Degrau |
|---|---|---|---|---|---|---|
| A1 delete the refusal tests and the coverage assertion | remendo | não: nothing shows the gap is closed | 5 min | easy | the gap can reopen silently | 0 |
| A2 the coverage assertion becomes "no gap remains"; each refusal test becomes a behaviour test in a new file, with a proof reference the operation check resolves | corrige a classe | sim: the check fails if a gap returns | ~20 min | high | none new | 1 |
| A3 generate refusal tests from `operation_demands.json` | redesenho | partly | ~half day | medium | over-engineering for three operations | 3 |

## Escolha
- R1 → A2: the triple exists only in the webhook, so journal it at the source. A1 would invent history and hide a force push; A3 adds a second journal for the same facts.
- R2 → A2: one rule answers every branch. The creation record is the only per-branch proof the window can give; if it is not in the window, refuse rather than answer partially. A1 is the silent partial the brief forbids. A3 is deferred: revisit it only if live refusals (A4) show up on the gate.
- R3 → A2: the gap-closed check stays in the test file the operation check reads, and the three refusal tests become behaviour tests. A1 would remove the only evidence that the gap is closed.

## Commits (dependency graph)

Critical path: C3 → (C4 ∥ C5) → C6 → C7. Estimated: C4 15 min, C5 20 min, C6 40 min, C7 10 min, gate run after C7 (~10 min). Path ≈ 85 min with the gate.

Edges: C4 → C6 is real (C6 reads the payload field names C4 fixes). C5 → C6 is real (C6 maps the records C5 writes). C4 ∥ C5 is a file collision edge only and is removed by design: C4 owns `contracts/**`, `scripts/lib/generated/**`, `docs/process/EVENTS.md`; C5 owns `services/control-plane/**`. They run one after the other in this session because each is small, not because they collide.

1. **C1 (Plan: 1)** — `docs/units/ORIGIN-PUSH-HISTORY/audit.md` skeleton. Done (5c4b95e4).
2. **C2 (Plan: 2)** — audit findings and causes. Done (b56d0103).
3. **C3 (Plan: 3)** — this plan. Owns `docs/units/ORIGIN-PUSH-HISTORY/plan.md`.
4. **C4 (Plan: 4)** — contract `ref.updated`. Owns `contracts/events/ref.updated.v1.json` (new), `contracts/events/schemas.lock.json`, the generated TypeScript and Python files for it, and the `docs/process/EVENTS.md` row. Payload: `repo` (defs), `ref` (`refs/heads/…`), `before`, `after` (defs sha), `created`, `deleted`, `forced` (booleans), `pushed_at` (date-time). Natural key: `/payload/repo`, `/payload/ref`, `/payload/before`, `/payload/after`. `additionalProperties: false`.
5. **C5 (Plan: 5)** — control plane. Owns `services/control-plane/src/core.js` and `services/control-plane/test/origin.test.mjs`. `originOf` journals every `refUpdates` entry of `repository.pushed` as `ref.updated` on the repository channel `{repo, pr: null}` (written explicitly, because the existing `journal` helper would also write a `pr: undefined` channel). `ORIGIN_NATURAL_KEY` gains `ref.updated`. `pull_request.head_ref.pushed` keeps journaling `pr.pushed` only. Tests: a two-ref push journals two records; a head push delivered as both events journals one `ref.updated`; a redelivery with the same triple has the same `event_id`; `created` and `forced` survive the write.
6. **C6 (Plan: 6)** — engine. Owns `scripts/lib/forge_origin_history.py` (new, pure), `scripts/lib/forge_origin.py`, `scripts/lib/operation_demands.json` (origin proofs), `scripts/tests/forge_events/test_origin_history.py` (new), `scripts/tests/forge_events/test_forge_contract.py`. The pure function takes envelope payloads in journal order and the window's `complete` flag, dedupes by `(before, after)`, drops deletions, and returns `{before, after, timestamp}` newest first; `forced_only` for `force_pushes`. Refuses when the ref has no record (names the reason: the journal holds no record of the branch, so it cannot say) and when the window neither holds the creation record nor is complete (names the window). `OriginAdapter.pushes` and `force_pushes` read `ControlAdapter.recent(Channel(repo, None))` and call the pure function. The `__getattr__` refusal for `pushes` (`forge_origin.py:69-71`) and the comment at `:89` are removed. Proofs for `pushes` and `force_pushes` name test methods in `test_origin_history.py` that call `adapter.pushes(` / `adapter.force_pushes(`. In `test_forge_contract.py`: `OriginContract.test_force_push_history_refuses_instead_of_returning_empty` and `test_missing_push_history_names_operation_and_concrete_gap` are replaced by the refusal behaviour tests in the new file; `test_coverage_is_measured_from_port_dispatches_and_class_members` asserts `names - set(dir(type(adapter))) == set()`. Parallel to nothing: this commit makes the refusal tests false, so it removes them in the same commit (green after it).
7. **C7 (Plan: 7)** — RETRO: `docs/units/ORIGIN-PUSH-HISTORY/retro.md`, posted as one PR comment after the final gate. Owns that file only.

Coupling guard: C6 and C5 both change a record's field names; C4 is the only place they are fixed. A change to the field list is a C4 change first.

## Premises
Blast radius, CRITICAL when a failure changes scope, spends money, touches production or the source of truth.

- **A1 — CRITICAL.** The `repository.pushed` webhook carries `refUpdates[]` with `before`, `after`, `created`, `deleted`, `forced` for every ref move (brief fact 2). Repo evidence: the fixture at `services/control-plane/test/origin.test.mjs:158-159`. Vendor documentation: not in this repo (fact 1's OpenAPI is also absent), so not verified against the vendor. If false: the mapping is wrong. Safe option taken: the contract requires every field, so a delivery missing one is refused, not guessed. First real verification: a live delivery, at activation (see Tests).
- **A2 — CRITICAL.** `repository.pushed` is delivered for every push, including pushes to PR head branches. If the vendor omits some, a branch can have no record. Safe option: no record for a branch refuses with the reason, so silence never reads as clean. A missing record costs a red gate for that PR, not a silent pass.
- **A3 — CRITICAL.** The control plane is a deployed service (`services/control-plane/wrangler.toml`), not Open University's site (frozen, D-054). The session does not deploy it: the coordinator redeploys after merge. Until the redeploy, the adapter finds no records and refuses, which is what it does today (the `__getattr__` refusal). Action for the coordinator after merge: redeploy, then read the events of a repository with `GET /v1/events?repo=…` and confirm a `ref.updated` record appears for the next push to any branch. No probe PR.
- **A4.** The window: `forge-events.git_ref_window` 2000 and `KEEP_EVENTS` 50000 stay as configured (no threshold change). A branch older than the window with no creation record is refused, not answered. Not critical: a refusal is honest and is the R2 decision.
- **A5.** The creation push: `commit_check.push_errors` judges a creation push (before = 40 zeros, not in the commit list) as bringing `after + 1` commits (audit M5). This is a consumer defect that already exists for GitHub's activity route. It is not changed here (owner: commit-check, `scripts/lib/commit_check.py`). Not critical.

## Tests
- **C4:** `scripts/schema-compat` (contract compatibility) and the generator drift check (`scripts/generate` then `git diff --exit-code` on the generated files). Owned by the contracts gate stage.
- **C5:** `node --test services/control-plane/test/` (core, events, origin tests). New cases in `origin.test.mjs`.
- **C6:** `python3 -m unittest scripts.tests.forge_events.test_origin_history` (new file; covers the pure function, the adapter with a fake log, the refusals, the proof methods); `PYTHONPATH=. bash scripts/tests/forge-events.test.sh` (runs `forge_events/test_*.py`, so the new file is picked up by glob); `OU_CONFIG_STORE=file PYTHONPATH=scripts/lib python3 -m scripts.lib.unit_check --operations --adapter origin` and `--adapter github`.
- **Final:** `scripts/structure-check`; `OU_CONFIG_STORE=file bash scripts/gate-dev --pr 1081`.
- **Real environment (acceptance):** the first live run is after merge and the coordinator's redeploy (A3). The session's acceptance is the local suites plus the operation check; the live check is named in the PR as the post-merge step.

## Base defects expected
- A5 (commit-check creation-push judgement). Owner: commit-check. Not fixed here; named in the PR and the retro.
- The window read is two calls per gate (pushes and force_pushes). Efficiency only; no change in this unit.

## Cheapest useful effort
Action: the origin adapter answers `pushes` and `force_pushes` from the journal, and the control plane writes the ref triple at its source.
Cost: about 90 minutes of session time and about 4 gate runs (none run yet); no money, no production, no source-of-truth change.
Requirement: the coordinator, who needs the origin operation check at 0 refusals before the next gate-dev on origin-hosted PRs, and the commit-check owner for A5.
Cheaper rejected: A1 (invent the history from the tip) hides force pushes; leaving the refusal in place keeps the origin adapter incomplete and the commit check unable to judge pushes at all.
