# Plan v3.1: the D-069 delta against plan v3 (1,000 PRs/day and beyond)

**Base.** Plan v3 is `docs/audits/mil-prs-2026-10-26/mil-prs-dia-2026-10-26.v3.md` on branch `audit/mil-prs-v3`
(commit `74c11ccb`). This file is a delta against it. It does not rewrite v3: anything it does not mention stays as v3
says. It applies the engineering standard D-069 ([principles and checks](../principles/D-069.md)) under D-065
(throughput) and D-068 (configuration as code, P-41). Premises: P-02, P-27, P-29, P-41.

**Numbers.** This delta writes a tunable value only as its registry name, `<owner>.<key>` in
`config/registry/<owner>.json` (format: [shared contract](../principles/D-069.md#config-registry-owner-c0-d-068-p-41)).
Each name has one source for its current value, listed in §1. The owning PR declares the entry; until it does, that
source holds the value (D-069 item 1: one source per fact).

## 1. Registry names this plan uses

| Name | Controls | Current value lives in | Declared by |
|---|---|---|---|
| `train.batch_size` | PRs per train batch (B) | [EVENTS.md](../EVENTS.md) › Defaults | M3 |
| `train.queue_growing_factor` | queue length, in batches, that emits `train.queue.growing` | EVENTS.md › Defaults | M3 |
| `gate.tier1_target_s` | tier-1 time target | EVENTS.md › Defaults; D-065 (5) | M2 |
| `gate.slow_window_events`, `gate.slow_median_s` | the `gate.slow` trigger | EVENTS.md › Defaults | M2 |
| `gate.ceiling_s` | the gate-dev warning ceiling | D-064 (f); `scripts/lib/gate-budget.sh` | C0 (migrates the shell default) |
| `gate.slots` | concurrent gates per machine | `scripts/lib/gate-isolation.sh` | C0 |
| `release.merged_prs_per_release` | merged PRs that make a release candidate | EVENTS.md › Defaults | M6 |
| `battery.unit_target_s` | a unit battery's time budget | D-065 (4) | U3a |
| `units.prod_lines_target`, `units.prod_lines_max`, `units.context_tokens_max` | the unit size ceiling | v3 §4.3; P-04 | U0 |
| `premises.batch_max_questions`, `premises.high_blast_unit_share_percent` | a premise batch; the high-blast threshold | v3 §8.5, §8.6 | P1 |
| `slo.gate_tier1_p95_s`, `slo.train_queue_time_p95_s`, `slo.merged_prs_per_hour_min`, `slo.gate_failure_rate_max_percent` | the SLOs | new; O1 sets the first values from v3 §9.2 ("how to know the day went well") | O1 |
| `budgets.regression_tolerance_percent`, `budgets.web_bundle_bytes_max`, `budgets.page_latency_p95_ms` | performance budgets | new; B1 measures the baseline first | B1 |
| `tests.random_seed`, `tests.timeout_ms`, `tests.network_allowed` | hermetic test settings | new | H1 |
| `toolchain.node_version`, `toolchain.pnpm_version`, `toolchain.python_version`, `toolchain.claude_cli_version` | pinned tools | `scripts/cloud/toolchain.json` (no claude CLI yet) | T1 |
| `supply-chain.allowed_registries` | registries a lockfile entry may come from | new | S2 |
| `providers.model_ladder`, `providers.agent_default` | model choice per step tier; the default agent provider | new (v3 names models per PR in prose) | R1 |
| `process.branch_max_age_h` | age that emits `branch.stale` | new | K1 |
| `conventions.*` | naming and language rules the lint configs are generated from | `apps/web/eslint.config.mjs` | N1 |
| `text.*` (`x-text`) | user-facing text, keyed by locale | D-063 catalogs in `apps/web` | L1 |

## 2. New PRs

No new id collides with v3 (A0–A2, X1, M1–M7, P1, U0–U4, S1, V0–V8) or with C0 and K0 of this wave. Every PR follows
D-022 (3–8 commits) and D-025: one that changes the gate cites D-069 in its body and in each commit that touches gate
files. D-069 is recorded by C0, so every PR below depends on C0. Models follow the wave's rule: Opus when the PR fixes a
format or design others build on, Sonnet for mid-sized work, Haiku for leaf or docs work.

| Id | Scope | Wave, lane | Model | Depends on | Closes D-069 items |
|---|---|---|---|---|---|
| **G1** | One generator, `scripts/generate <target>`, for every derived file: Python and TypeScript types from `contracts/`, docs, aggregates, and `CODEOWNERS` at the repository root, generated from the manifests. Adds the `generated drift` gate stage (a committed derived file must equal its regeneration) and the `schema compat` check (a `<name>.v<N>.json` changes only additively; a breaking change is a new version, expand→contract). | 1→2, engine lane | Opus | C0, M2 (formats); U0 for `CODEOWNERS` | 1, 2, 8 (generated part) |
| **O1** | Observability. SLOs in `config/registry/slo.json`. A reader folds `engine.step.measured` and the train events into SLO values and emits `slo.breached` when one is outside its entry. The dashboard (`scripts/dashboard`, Markdown or static HTML) is generated from the log and never committed by a PR. | 1, engine lane | Sonnet | C0, M2; M3 for queue time | 6 |
| **T1** | Toolchain. The pins read through `config/registry/toolchain.json`. `scripts/cloud/toolchain.json` keeps only the per-version checksums, so there is no second version list. The claude CLI is pinned. A lockfile verification check: `pnpm-lock.yaml` matches `package.json`, and the install is frozen in every plan. One entry command for a gate or test, used the same way locally and in the cloud. | 1, env lane | Sonnet | C0 | 12 |
| **S2** | Supply chain and least privilege. A dependency allowlist that extends `scripts/lib/vendor-map.json` to transitive packages (one map, no second list). Lockfile integrity: every entry has an integrity hash from a registry in `supply-chain.allowed_registries`. Each agent's key scope, as secret names only, in a registry entry. The gate reads all three; the secret scan stays as it is. | 1, env lane | Sonnet | C0, T1 | 13 |
| **R1** | Ports for the engine's vendors besides the forge (M2): agent provider (Claude, Codex, Cursor), model ladder (`providers.model_ladder`), CI runner and storage. Each has one adapter module in `scripts/lib/adapters/`. The engine vendor check fails a vendor call (HTTP host, CLI, SDK) from `scripts/` outside its adapter. | 1, engine lane | Opus | C0, M2 | 7 |
| **H1** | Hermetic tests. Unit and script tests run with the network denied (`tests.network_allowed`), a seeded random source (`tests.random_seed`), an injected clock, and timeouts from `tests.timeout_ms`. The check fails a direct wall-clock read, an unseeded random source or a socket in a unit test. A flaky test goes through M7's quarantine. | 2, engine lane | Sonnet | C0, M7 | 5 |
| **B1** | Performance budgets. `config/registry/budgets.json` holds the battery per unit (it reads `battery.unit_target_s`, so there is one name), the web bundle and page latency. The baseline is computed from `engine.step.measured` (B1 measures it first; nothing is guessed). A regression beyond `budgets.regression_tolerance_percent` fails. The registry check refuses a budget made looser without a decision. D-064 (f) stays a warning. | 2, engine lane | Sonnet | C0, M2, U3a, O1 (reader) | 14; 5 (per-unit test budget) |
| **L1** | Locale text. User-facing text becomes `x-text` registry entries keyed by locale (`{"en": ...}`). The D-063 UI-text catalogs read them, and the check refuses a text entry without `en`. Each UI unit moves its own text when it migrates (U4), so no file is edited twice (P-05). L1 delivers the format and the check, plus one pilot unit. | 3, UI lane | Sonnet | C0, G1 (types) | 15 |
| **N1** | Conventions. `config/registry/conventions.json` holds the naming and language rules. ESLint, the Python linter and shellcheck configs are generated from it (G1). A non-English identifier or comment fails. A new linter is pinned through T1 and allowed through S2. | 2, engine lane | Sonnet | C0, G1, T1, S2 | 16 |
| **K1** | Process rules as checks. A blameless postmortem template, `docs/process/postmortems/<date>-<slug>.md`; the check refuses a postmortem that names no existing preventing check (file and test). A decision or ADR must cite its premises (P1). `branch.stale` is emitted past `process.branch_max_age_h`. The first postmortem is today's literal-parameter miss, closed by C0's no-literals check. | 2, engine lane | Haiku | C0, P1 | 9, 10, 11 (branch age) |

Items 3 (config as code) and 4 (append-only log, replay) need no new PR: C0 and M2 already own them.

## 3. How the v3 PRs change under D-069

Two rules apply to all of them. Every value a PR reads comes from the registry (`config.get`, C0); there is no inline
default. Every contract it adds (event payload, manifest, rule data) is a JSON Schema 2020-12 file under `contracts/`.
The rows below list only the specific changes.

| v3 PR | Change under D-069 | D-069 items |
|---|---|---|
| M1 | None: merged as #491 (D-065 amended). | — |
| P1 | Premise files are validated against `contracts/premises/premise.v1.json`. The batch size and high-blast threshold are `premises.*` entries. `premise.*` events use the M2 envelope. | 2, 3, 4, 10 |
| M2 | Also owns `contracts/events/envelope.v1.json`, one payload schema per event in EVENTS.md, `engine.step.measured` emitted by every engine step, and the replay test. The `forge_events` port reads `gate.*` and `forge-events.*` entries. | 2, 4, 6, 7 |
| M3 | Reads `train.*` entries and emits `engine.step.measured` per batch. It merges only through the forge port, and it refuses a change outside the lane's units unless the owner has approved it (from U0). | 3, 6, 7, 8, 11 |
| M4 | Reads its `plan-tick.*` entries and emits metrics. | 3, 6 |
| M5 | The cache key includes the toolchain pins read through T1, and its own settings are `session-cache.*` entries. | 3, 12 |
| M6 | Reads `battery.*` and `release.merged_prs_per_release`, and emits metrics per tier-3 run. | 3, 6 |
| M7 | Quarantine is an event (`test.flaked`, then `test.quarantined`) owned by the unit owner from the manifest. H1 builds on it. | 4, 5, 8 |
| U0 | The manifest schema is `contracts/units/unit.v1.json`, and `owner` is required. The size budget comes from `units.*` entries. A manifest holds only an override, and an override needs a decision. The v3 example's literal `budget` becomes a reference. | 1, 2, 3, 8 |
| U1 | Built on G1's generator and drift stage, so there is one generation mechanism. It generates aggregates from the manifests and adds no separate generator. | 1 |
| U2 | Checker rules are data, validated by a JSON Schema. Its thresholds are registry entries. | 2, 3, 16 |
| U3a | The battery target is `battery.unit_target_s`. The battery emits `engine.step.measured`. `contract.changed` also covers JSON Schema contracts through G1's `schema compat` check. | 2, 6, 14 |
| U3b | Mechanical, unchanged; it emits metrics per lane PR. | 6 |
| U4 | The unit's definition of done grows to include zero literals, with values in the registry (P-05), plus an owner, a test budget, hermetic tests (H1) and, for UI units, `x-text` entries (L1). | 3, 5, 8, 14, 15 |
| S1 | Unchanged; its result is recorded as the answer to P-03. | 10 |
| A1, A2 | Each lane PR lists the D-069 items it satisfies in its body. | all |

## 4. Wave order (replaces the v3 §9.1 order; content otherwise as v3)

Events start each step, not a clock (P-32). A PR starts when the PRs it depends on have merged.

| Wave | PRs, in dependency order | Gate on |
|---|---|---|
| 0: premises | A0, X1, M1 (done, #491), P1 | — |
| 1: engine and standard | C0 and K0 (this PR) in parallel; M2, M4, M5, T1; then M3 (C0, M2), S2 (T1), R1 (M2), O1 (M2, M3); G1 formats and types (C0, M2) | C0 merged before any PR that reads config |
| 2: unit skeleton | U0; G1 `CODEOWNERS` (U0); U1 (G1); U2; U3a; M6; S1; H1 (M7); K1 (P1); B1 (U3a, O1); N1 (G1, S2) | P-01, P-03, P-04 answered |
| 3: migration | U3b, U4 per unit, M7, L1 (before the first UI unit's U4) | P-05; P-06 and P-07 per unit |
| 4: refinements | as in v3, plus tuning when `slo.breached` or a B1 regression asks for it | the event |

**Critical path to 1,000/day:** C0 and M2 in parallel, then M3. C0 joins the path because M3 reads `train.*` from the
registry. The rest of v3 §9.1 holds.

**Model per PR.** v3 assigns sessions, not models. Under D-069, the PRs that fix a format others build on use Opus
(C0, K0, M2, M3, U0, G1, R1). The mid-sized PRs use Sonnet (P1, M4–M7, U1–U3a, S1, O1, T1, S2, H1, B1, L1, N1). The
leaf and docs PRs use Haiku (U3b lanes, K1). The model ladder itself becomes `providers.model_ladder` (R1).
