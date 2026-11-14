# Live planning — plan (LP1)

Status: final (LP1, 27/10/2026, branch `mod/lp1`).

Implements [design.md](design.md) from the findings of [audit.md](audit.md). Base `mod/roadmap-integration` at `4bc4dd04`.
Plan only: no unit is launched by LP1.

## 0. Summary

1. **9 units after this one** (LP2–LP10, ids without hyphen in `program.v1`), ≈ 11.25 session-hours, **critical path ≈ 4.5 h**
   wall-clock from launch of LP2, at up to **6 sessions at once**.
2. **Value from minute zero:** the hand procedure (design §2 checklist, `plan.changed` lines written by hand to `plan/live`)
   is usable by A Torre as soon as LP2 publishes the runbook; code then removes the hand work, it does not enable it.
3. **One preparation unit (LP2)** locks the three event contracts, the registry file, the unit-manifest paths, the test
   registration and the function stubs, so LP3–LP6 run in parallel with no shared file.
4. **gate-excellence is the first tenant** (§5): its plan-v2 becomes version 0 of its live plan, GX-41 is dropped in favour of
   this program, and seven seed inputs from the audit (S1–S7) are the planner's first decisions.
5. **Nothing for Daniel:** no money, no production, no scope change; LP-P1 (decision log on a `plan/live` branch) is decided
   here, reversible, and reported.

## 1. Time model and rules applied

- Unit time = agent session-hours at the stated tier; each unit adds **L = 0.4 h** from last commit to merged (gate,
  merge, launch), the same model as `origin/mod/ga4:docs/programs/gate-excellence/plan-v2.md` so the two programs compare.
- Every unit: one PR from and to `mod/roadmap-integration`, 3–8 commits with `Plan: N` trailers, Padrão v1 rules,
  `Decision: D-071`, `Premises:` with the register ids LP2 creates, `Fit-Review: not reviewed (Daniel 2026-10-25: no review
  step)`, RETRO at `docs/units/LPN/retro.md`. Merged by the coordinator or the train, never by its session.
- No literals: every number below that ends in code (thresholds, sizes, limits) is a key in `config/registry/planner.json`,
  created with defaults by LP2.
- The gate-excellence program keeps running on its own plan while LP runs (Daniel 15:03). LP units touch **no gate file**
  (`scripts/gate-*`, `scripts/lib/gate*`, `structure-check`, `commit-check`), so they never collide with a GX unit and need
  no gate-change D-NNN beyond D-071 for the program record.

## 2. Units

| ID | Title | Deps (REAL only) | Tier · effort | Files owned (no file owned twice) |
|---|---|---|---|---|
| **LP2** | **Preparation:** program record and contracts | — | sonnet · 0.75 h | `docs/domain/DECISIONS.md` (D-071), `docs/process/premises/<LP-P1..P5>.yml`, `docs/programs/live-planning/{brief,retro}.md` + this folder's audit/design/plan brought from `mod/lp1`, the `program.v1` block below, `contracts/events/plan.{changed,note,input,candidate}.v1.json` + `schemas.lock.json`, `config/registry/planner.json` (all keys of §2.1), `units/engine-coordinator/unit.json` (new paths), `scripts/lib/gate-script-tests.json` (register LP test files, until GX-08's headers exist), stubs `scripts/lib/plan_live.py`, `scripts/lib/plan_triage.py`, `scripts/plan` (signatures + docstrings, raise `NotImplementedError`), `docs/process/live-planning.md` (the hand runbook: §2 checklist, how to append a `plan.changed` line by hand, how to read it) |
| LP3 | Fold, validate and log the live plan | LP2 | opus · 1.5 h | `scripts/lib/plan_live.py` (fold, op validation against `program.v1`, hash chain, optimistic `parent` check), `scripts/lib/program.py` (`plan`, `log` subcommands), `scripts/program`, `scripts/tests/test_plan_live.py` |
| LP4 | Triage and the pass-on interface | LP2 | opus · 2 h | `scripts/lib/plan_triage.py` (signature dedupe, affected set from units/premises/areas, overrun derivation, candidate vs seen), `scripts/plan` (`note`, `input`, `triage`), `scripts/tests/test_plan_triage.py` |
| LP5 | Launch reads the live plan | LP2 | sonnet · 1.5 h | `scripts/lib/coordinator.py` (fold input, `hold`, `priority`, `plan_version` in `work.assigned`, refuse a stale-version launch, `LAUNCH-HOLD` path from the registry mapped to `hold all`), `scripts/lib/coordinator_launch.py` (`brief_lines`), `scripts/tests/test_coordinator*.py`, `docs/operations/coordinator.md` |
| LP6 | Planner role session and wake path | LP2 | opus · 1.5 h | `scripts/lib/planner_role.py` (role lease via `engine_role.py`'s existing API, sole-writer append to `plan/live`, non-fast-forward → merge, never force), `scripts/lib/adapters/planner_wake*.py` (port + Claude adapter + dry-run adapter), `scripts/tests/test_planner_role.py`, `docs/process/live-planning.md` §"role" (LP2 leaves the section stub) |
| LP7 | Wire the lost inputs | LP2 | sonnet · 1.5 h | `scripts/lib/premises.py` (publish `premise.*` through the `forge_events` port instead of printing, `:272-274`), `scripts/lib/lessons.py` + `lessons_brief.py` (an `apply_lesson` path the planner can call, with audit line), their tests |
| LP8 | Padrão: pass-on rule and planner checklist | LP2 + Padrão v2 folder free (PD2 #669 owns `docs/padrao/v2`) | sonnet · 0.5 h | `docs/padrao/v<next>/pass-on.md`, `docs/padrao/v<next>/live-planning.md`, that version's `padrao.json` |
| LP9 | Handover of gate-excellence and first live decisions | LP3, LP5, LP6 | opus · 1 h | `plan/live:docs/programs/gate-excellence/plan-log.jsonl` (version 0 = the merged plan-v2 graph, or plan.md if GA4 has not merged; then S1–S7 of §5 as decided `plan.changed` entries), `docs/units/LP9/{plan,retro}.md`; base: `docs/programs/gate-excellence/plan.md` gets one line pointing to the live plan |
| LP10 | Measures | LP3, LP4 | sonnet · 1 h | `scripts/lib/plan_measures.py`, one section in `scripts/lib/slo.py`'s dashboard render, tests |

### 2.1 Registry keys LP2 creates (defaults are starting values)

`planner.triage_promote_sightings` (2), `planner.decision_context_max_tokens` (20000), `planner.partition_recent_decisions`
(10), `planner.overrun_factor` (2.0, from `gate-excellence/plan.md:673`), `planner.log_branch` (`plan/live`),
`planner.launch_hold_path` (empty = none), `planner.subagents_max` (3), `planner.enabled` (false; LP9 turns it on for
gate-excellence only).

### 2.2 `program.v1` block (written into the base by LP2)

```json program.v1
{
  "contract": "program.v1",
  "program": "live-planning",
  "complaint": {
    "symptom": "plans are static; information found mid-flight is rediscovered by every unit instead of changing the plan",
    "evidence": "docs/programs/live-planning/audit.md cases L1-L12",
    "goal": {"metric": "prs_merged_per_day", "comparator": "gte", "target": 1000, "unit": "prs/day"}
  },
  "units": [
    {"id": "LP2", "depends_on": [], "owner": "engine-lane", "model": "claude-sonnet-5-5", "wave": 1, "done": ["D-071, premises, contracts, registry, stubs and runbook merged; scripts/program check live-planning passes"]},
    {"id": "LP3", "depends_on": ["LP2"], "owner": "engine-lane", "model": "claude-opus-5-5", "wave": 2, "done": ["scripts/program plan --at N reproduces any past version; a stale parent is refused"]},
    {"id": "LP4", "depends_on": ["LP2"], "owner": "engine-lane", "model": "claude-opus-5-5", "wave": 2, "done": ["replaying 27/10's gate.failed events yields one candidate per signature (L1, L2, L5, L6)"]},
    {"id": "LP5", "depends_on": ["LP2"], "owner": "engine-lane", "model": "claude-sonnet-5-5", "wave": 2, "done": ["a held unit is not launched; a launch on a stale plan_version is refused; brief_lines reach the brief"]},
    {"id": "LP6", "depends_on": ["LP2"], "owner": "engine-lane", "model": "claude-opus-5-5", "wave": 2, "done": ["role lease and sole-writer append proven with two concurrent writers; dry-run wake adapter"]},
    {"id": "LP7", "depends_on": ["LP2"], "owner": "engine-lane", "model": "claude-sonnet-5-5", "wave": 2, "done": ["premise.* published through the port; a lesson can be applied and reaches the next brief"]},
    {"id": "LP8", "depends_on": ["LP2"], "owner": "engine-lane", "model": "claude-sonnet-5-5", "wave": 2, "done": ["new Padrão version with pass-on and planner checklist; previous version untouched"]},
    {"id": "LP9", "depends_on": ["LP3", "LP5", "LP6"], "owner": "engine-lane", "model": "claude-opus-5-5", "wave": 3, "done": ["gate-excellence launches come from the folded live plan; S1-S7 decided and logged"]},
    {"id": "LP10", "depends_on": ["LP3", "LP4"], "owner": "engine-lane", "model": "claude-sonnet-5-5", "wave": 3, "done": ["rediscovery count and input-to-decision time on the dashboard"]}
  ]
}
```

## 3. Dependency graph and critical path

| Edge | Class | Why / how removed |
|---|---|---|
| LP3 → LP5 (coordinator needs the fold) | REAL in code, **removed by design** | LP2 fixes `plan_live.fold(plan, changes) -> plan` and its fixture; LP5 tests against the fixture |
| LP4 → LP6 (planner reads candidates) | REAL in data, **removed by design** | LP2 locks `plan.candidate.v1`; LP6 tests with fixture candidates |
| LP3/LP4/LP5/LP6/LP7 on `config/registry/*.json`, `units/engine-coordinator/unit.json`, `gate-script-tests.json`, `schemas.lock.json` | COLLISION | **removed**: LP2 writes all of them once |
| LP4 ↔ LP6 on `docs/process/live-planning.md` | COLLISION | **removed**: LP2 creates the file; LP6 owns its own section only, LP4 documents in the CLI help |
| LP8 → PD2 #669 (`docs/padrao/v2`) | REAL (folder ownership) | kept; LP8 is off the critical path and the planner itself decides at launch time whether to wait for PD2 or take the next version number |
| LP9 → LP3, LP5, LP6 | REAL | the handover needs a valid log, launches that read it, and its writer |
| LP10 → LP3, LP4 | REAL | measures fold the log and candidates |

```
LP2 (0.75+0.4) ─┬─ LP3 (1.5+0.4) ─┬─ LP9 (1+0.4)        ← critical
                ├─ LP5 (1.5+0.4) ─┤
                ├─ LP6 (1.5+0.4) ─┘
                ├─ LP4 (2+0.4) ──── LP10 (1+0.4)
                ├─ LP7 (1.5+0.4)
                └─ LP8 (0.5+0.4, waits on the Padrão folder)
```

- **Critical path:** LP2 → {LP3 ∥ LP5 ∥ LP6} → LP9 = 1.15 + 1.9 + 1.4 = **4.45 h**. Near-critical: LP2 → LP4 → LP10 = 1.15 +
  2.4 + 1.4 = 4.95 h, but LP10 is a measure, not on the path to "the planner runs"; if LP4 overruns, LP10 slides, nothing
  else does.
- **Max parallelism:** 6 sessions after LP2 (LP3–LP8), then 2. Within Max limits (A Torre runs ≤ 15 per plan-v2).
- **Without the prep unit** the four shared files (registry, manifest, test map, lock) would serialise LP3–LP7 into ≈ 4
  slots (≈ 8 h); LP2 costs 1.15 h and buys ≈ 4 h.

## 4. Execution

- **Launch order:** LP2 now (nothing blocks it; it is docs, contracts, data and stubs). On `pr.merged` of LP2, launch LP3–LP8
  at once. LP9 on the third of LP3/LP5/LP6 merged; LP10 on LP3 + LP4.
- **Running it by hand meanwhile:** from LP2's merge, A Torre applies `docs/process/live-planning.md` to gate-excellence
  (seed inputs §5) — this is the "coordinator applies the rule by hand" of plan-v2 §0.6, made concrete and recorded.
- **Dogfood:** from LP9 on, LP's own remaining units (LP10, and LP8 if still waiting) are planned by the planner.
- **Stop rules:** a red base stops new launches (existing rule); any LP change found to need a gate file goes to the
  gate-excellence planner as a candidate, not into the LP unit.
- **Premises** (design §8): LP-P1…P5, none CRITICAL; LP2 records them. LP-P2 (off-repo launcher calls `coordinator next`)
  is A Torre's action at LP9; until then launches stay manual and read `scripts/program plan`.

## 5. Handover of gate-excellence

1. **Who owns the plan from when.** Until LP9 merges, A Torre is the gate-excellence planner and follows the hand runbook
   (from LP2). From LP9, the planner session is; A Torre keeps the global brake (`v3/LAUNCH-HOLD`, mapped to `hold all`).
2. **Version 0.** If GA4's `plan-v2.md` (`origin/mod/ga4`, `6651cd4a`, 6 of 9 sections pending at 18:05) has merged by LP9,
   its `program.v1` block is version 0; otherwise `plan.md`'s block is, and plan-v2's changes (edge removals, GX-06 into
   GX-02, the four prep units, GX-33 trigger) are entered as the first `plan.changed` entry with `inputs` = Daniel's rules of
   14:19/14:44/14:59/15:01 and `intention` = plan-v2's. Either way GA4's work is reused, not redone.
3. **GX-41 is dropped** from gate-excellence (this program is its implementation). **`plan.changed` contract**: plan-v2's
   prep unit GX-37 also locks a `plan.changed` contract (`plan-v2.md:120`); only one may own it. Decision: **LP2 owns it**
   and GX-37 drops it from its list; if GX-37 has already merged one, LP2 adopts it and extends it (additive v1 fields or a
   v2), never a second contract. This is the first input the planner (A Torre by hand) must handle — a live example.
4. **Seed inputs** — the audit's open cases, each to be judged with the §2 checklist at handover (recommended action in
   brackets; the planner decides on the state it then sees):

| Seed | Input (audit) | Recommended action |
|---|---|---|
| S1 | L1 base-tip verdict vs new registry keys | `insert_unit` prep "config root from `OU_SUBJECT_ROOT`" before the next key-adding launches, unless GX-05 lands first; meanwhile `brief_line` on every pending GX unit |
| S2 | L3 literal census not in local checks | `insert_unit` prep: add the census to `config/registry/local-checks.json` (F-15 local part pulled from GX-15) |
| S3 | L5 env failures mis-classed (`root-identity`, `StoreError`) | `register_defect` env ×2; `brief_line` "env-only, do not loop"; class fix routed to the env unit already named (GX-ENV-root-identity) |
| S4 | L6 load-sensitive psql timeouts | `reorder`: GX-03 (sizing) first among wave-0 leftovers; `hold` no extra parallel gates beyond the container's size until then |
| S5 | L7 `eaa408de` not on the base | `reorder`: GX-02 first (plan-v2 already folds it); `hold` the train until then |
| S6 | L4 GX-07 "as is" false; L2 duplicate fix | `note` + estimate correction for any further "land as is" unit (re-audit premise before launch) |
| S7 | L12 brief branch vs harness branch | `brief_line` naming both, and a candidate to the launcher owner |

5. **Running GX sessions at handover** get no message unless a seed makes their output wrong (design §2.4); S1–S7 touch
   pending units and briefs only.

## 6. Cost

≈ 11.25 session-hours (opus 6, sonnet 5.25), ≈ 14 with a 20 % margin; wall ≈ 4.5–5 h. Running cost of the planner: design
§6 (≈ 1–2 unit sessions of quota per day today). No money.

## RETRO (LP1)

- **Brief:** clear on intention and limits; two cited sources do not exist in the repo (`v3/LAUNCH-HOLD`,
  `/workspace/torre/motor/sessions.log` — both off-repo, as GA1/GA2 had found); planned from what exists. The brief names
  branch `mod/lp1` while the harness bound `claude/lp1-…` (audit L12): worked on `mod/lp1` as the brief says.
- **Audit:** three read-only sub-agents (engine, program history, PR comments) in parallel, ≈ 2.5 min each; the main session
  verified the key claims (coordinator fold, 16 `proposed` lessons, premise printing, `c87c9fd1`) before writing.
- **Biggest finding:** the engine already has the inputs and a plan-reading coordinator; what is missing is the owner of the
  question and a versioned change record — so the design adds a fold and a log, not a new system.
- **Collision found late:** plan-v2's GX-37 also locks `plan.changed`; resolved by a single-owner rule (§5.3). Lesson: a
  planning unit should `rg` sibling in-progress branches for its contract names before designing (owner: brief template, A Torre).
- **Mistake:** one in-place edit truncated the audit's last sections; caught at once and rewritten before the commit.
- **Not done (out of scope):** no measurement of decision cost; the quota numbers in design §6 are estimates to verify in LP10.
