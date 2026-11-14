# Gate excellence — plan v2 (GA4: re-plan for wall-clock time)

Status: final (GA4, 27/10/2026). Plan only: no code, no PR, no measurement. Branch `mod/ga4`.
Inputs, taken as given: `plan.md` (GA3, `70a5f444`), `audit-1-fable.md`, `audit-2-opus.md`. Unit content (goals, B-blocks, findings closed, done criteria) is GA3's unless §4 says otherwise.
Base re-read at start: `mod/roadmap-integration` moved from `ef01174d` to `25c6f7a8` (GX-01 #694 merged), then to `4bc4dd04` (GX-07 #677 merged) while this plan was written. So **GX-00, GX-01, GX-04 and GX-07 are merged**; nothing of wave 0 is running. GX-02, GX-03 and GX-05 were launched by mistake at 14:55 and halted at 14:57 (Daniel); they are **not started** (no `mod/gx02|03|05` branch exists on the remote).
Rules applied: Daniel 14:44 (optimize wall-clock to program end; parallelism is a means; prep units remove collision edges), 14:19 (max parallelism, the "2 at a time" limit lifted), 14:59 and 15:01 (dynamic planning coordinator, §7.3). Safety rules kept: no two concurrent units edit the same file; no stacking (every unit branches from the base); DECIDE THEN REPORT; targeted tests; commit every 3–4 min; no literals; fix the class.

Time model used for every number below: unit hours are GA3's session-hour estimates (§3.2 of plan.md) unless §4 changes a unit; each unit adds **L = 0.4 h** from last commit to merged (gate ≈ 6 min, merge or train batch ≈ 15 min, launch ≈ 5 min); T0 = the moment this plan is adopted. Edge kinds: **REAL** (B needs A's code, contract or result to start), **REAL-merge** (B can be written in parallel but must merge after A), **COLLISION** (only a shared file), **PROCESS** (a checkpoint or slot barrier, no data).

## 0. Executive summary

1. **Old critical path (GA3 graph, from now, unlimited sessions):** GX-02 → GX-06 → [C1] → GX-09 → GX-10 → GX-11 → GX-12 → GX-30 → GX-31 = 12.5 session-hours + 8 merges ≈ **15.7 h**. As GA3 actually scheduled it (2 at a time, 16 slots left) ≈ **34 h**; with GX-33's "≥ 2 days" stability window the program ends ≈ **67 h** after now.
2. **New critical path:** GX-02 (absorbs GX-06) → GX-30 → GX-31 = 6.75 h + 3 merges ≈ **8.0 h**; near-critical GX-37/38/39 (prep) → GX-10 → GX-20 → GX-26 ≈ 7.9 h. **Engineering end ≈ 8 h after T0** (≈ 9–10 h with base-merge churn and rework), at up to **15 sessions at once**.
3. **Program end ≈ 9–10 h after T0** instead of ≈ 67 h, because GX-33's trigger becomes count-based (≥ 50 consistent heads and ≥ 2 train batches, no minimum of days; D-B12) and GX-17 moves to T0. It still needs the account owner's `statuses:write` (ask now, §7.1). GX-35 stays last, and it is no longer an open ask: Daniel approved the free path on 2026-10-28 (D-073), so the store is built inside R2's free allowance.
4. **What changed:** GA3 has 56 dependency edges plus 5 process barriers; 34 are COLLISION or PROCESS. All 14 PROCESS and 15 COLLISION edges are removed, and 5 thin REAL edges disappear by moving a few lines (§2). Checkpoints C1–C3 and the slot barriers stop being launch barriers (they stay as measurements). Four prep units (GX-37 contracts first, GX-38 driver hooks + manifest pre-claims, GX-39 report/cache seams, GX-42 adopt this graph; 2.75 h, all at T0) let 11 units start at T0 and 15 run at the peak.
5. **Re-split / merged:** GX-06 merged into GX-02; GX-09 shrinks to readers; GX-08 uses per-test sidecar files (no `.test.sh` edits); GX-12, GX-21, GX-23, GX-16 lose their shared-file parts; GX-24, GX-14, GX-17, GX-34 move to T0.
6. **Dynamic planning (Daniel 14:59/15:01):** GX-41 makes the program coordinator ask, on every new piece of information, "does this change the plan, and can I make the rest go better or faster?"; changes are `plan.changed` events folded over the `program.v1` graph; PRs never wait (§7.3). Off the critical path; the coordinator session applies the rule by hand until GX-41 merges.
7. **For Daniel:** no decision. One early account action (`statuses:write`), the visible GX-33 trigger change (D-B12), and GX-35's spend, now answered: the free path only (D-073).

## 1. Old vs new critical path

| | Old (GA3) | New (v2) |
|---|---|---|
| Units left | 31 + GX-36 conditional + GX-35 deferred | 30 + 4 prep + GX-41 + GX-36 conditional + GX-35 last, free tier (D-073) (GX-06 folded into GX-02) |
| Session-hours left | ≈ 47 h (excl. GX-33, GX-35) | ≈ 51 h (≈ 4.25 h of prep and planning added, ≈ 0.5 h saved by merges) |
| Launch rule | slots of 2, next slot after both merge; C1/C2/C3 barriers | event-driven: a unit launches when its REAL deps are merged and its files are free (§5, §6) |
| Max concurrency | 2 | 15 (peak at T0 + 2.4 h); 11 at T0 |
| Critical chain | GX-02 1.5 → GX-06 1.5 → C1 → GX-09 1.5 → GX-10 2 → GX-11 1.5 → GX-12 1 → GX-30 2 → GX-31 1.5 | GX-02(+06) 3 → GX-30 2.25 → GX-31 1.5 |
| Critical path, unlimited sessions | ≈ 15.7 h | **≈ 8.0 h** |
| Engineering end as scheduled | ≈ 34 h (16 slots × max + L) | ≈ 8.0 h (§6 timeline) |
| GX-17 merged (C4 clock starts) | ≈ 17.7 h (S10) | ≈ 1.9 h |
| Program end (GX-33 merged; GX-35 outside the clock — last, free tier) | ≈ 67 h (GX-17 + 48 h window) | ≈ 9–10 h (count trigger, D-B12) |

Chains in v2 and where they end (the first, second and last are within 0.1 h of each other, so a slip on any of them moves the end):

| Chain | Ends at |
|---|---|
| GX-02(+06) → GX-30 → GX-31 | 7.95 h |
| GX-37 ∥ GX-38 ∥ GX-39 → GX-10 → GX-20 → GX-26 | 7.85 h |
| GX-08 → GX-29 | 4.8 h |
| GX-17 → GX-16 → GX-25 → GX-26 | 7.85 h (GX-25 at 6.2 h) |
| GX-10 → GX-28 → GX-31 | 7.95 h if GX-30 slips by > 0.35 h |

Shortening the critical chain further would need a train-file split (`train.py`, `engine_role.py`) before GX-02; it saves ≤ 0.4 h of end time and re-plans wave 0 for that, so it is **not** taken (rule: a prep unit must shorten the path net of its own time). The planning coordinator revisits it if GX-02 or GX-30 overruns (§7.3).

## 2. Edge table

Every `depends_on` edge of GA3's `program.v1` block (56) plus GA3's five process barriers (§4.3, §7 of plan.md). Totals: **REAL 26** (14 kept, 5 already satisfied, 2 re-pointed to GX-37, 5 "thin" ones removed by moving a few lines between units), **REAL-merge 1** (kept), **COLLISION 20** (15 removed, 3 satisfied, 2 kept as lane order off the critical path), **PROCESS 14** (all removed as launch barriers). Satisfied = its source is already merged.

"Thin" REAL edges: B needed one small piece of A (an exported variable, an optional field, one rule in a file B already owns); the piece moves to a prep unit or to the unit that owns the file, and the rest of the edge was collision.

| # | Edge | Kind | Reason | Outcome |
|---|---|---|---|---|
| E01 | GX-00 → GX-01 | REAL | every gate-file PR must cite D-070 (commit_check.gate_errors) | satisfied (merged) |
| E02 | GX-00 → GX-04 | REAL | same D-070 citation | satisfied |
| E03 | GX-00 → GX-07 | REAL | same D-070 citation | satisfied |
| E04 | GX-01 → GX-02 | REAL | GX-02 reads the class line GX-01 prints | satisfied |
| E05 | GX-01 → GX-03 | COLLISION | `config/registry/gate.json` only; sizing needs nothing from preflight | satisfied |
| E06 | GX-01 → GX-05 | COLLISION | `scripts/gate-local` only | satisfied |
| E07 | GX-04 → GX-05 | REAL | the pinned run executes from a checkout not on the head; pr.ready must already work there | satisfied |
| E08 | GX-02 → GX-06 | COLLISION | `train.py`, `engine_role.py`, `train.json`, `train.md`, `test_train_role.py`; the lease, owner, trigger and enabled guard need nothing from halting | **removed**: GX-06 folded into GX-02 (one session, one merge; §4) |
| E09 | GX-07 → GX-08 | COLLISION | `gate-script-tests.json` | satisfied (GX-07 merged) |
| E10 | GX-05 → GX-09 | PROCESS (C1) | pinned verdict; D-A3's interim base-tip run already gives it without code | **removed** |
| E11 | GX-06 → GX-09 | COLLISION | `train.py` reader; `train.queue_entry` matches `type == 'gate.passed'` with no version check, so v4 needs no train edit (only a test) | **removed** |
| E12 | GX-08 → GX-09 | PROCESS (C1) | test-map barrier; GX-09 adds no script test | **removed** |
| E13 | GX-09 → GX-10 | REAL | the producer needs the v4 schema and generated module | **changed**: GX-37 → GX-10 (REAL, schema), GX-09 → GX-10 REAL-merge (readers accept v4 before the producer switches) |
| E14 | GX-10 → GX-11 | COLLISION | `gate-local`, `gate_report.py`; the `tier` value is read through a seam | **removed** by GX-38/GX-39 (`tier.sh`, `gate_tier.py`) |
| E15 | GX-11 → GX-12 | COLLISION | `gate_report.py`; the tier-2 tier value comes from `gate_tier` (mode-derived until GX-11) | **removed** by GX-39 (`gate_publish.py`); GX-06 runbook line moves to GX-26 |
| E16 | GX-10 → GX-13 | REAL (thin) | needs the proof's `base_sha`; `gate-local` already reads `baseRefOid` (`:97-99`) | **removed**: GX-38 exports `OU_GATE_BASE_SHA`; GX-39 gives GX-13 `gate_adjudicate.py` |
| E17 | GX-05 → GX-14 | PROCESS (C1) | none | **removed** |
| E18 | GX-06 → GX-14 | PROCESS (C1) | none | **removed** |
| E19 | GX-08 → GX-14 | COLLISION | `structure.py` (GX-08's header rule) | **removed**: GX-08's rule lives in its own test (§4) |
| E20 | GX-14 → GX-15 | REAL | the metadata part GX-15 splits out is GX-14's gated-sha check; both rewrite `structure.py` | kept |
| E21 | GX-09 → GX-15 | REAL | `pr.checked.v1` contract | **changed**: GX-37 → GX-15 |
| E22 | GX-05 → GX-16 | PROCESS (C1) | none | **removed** |
| E23 | GX-06 → GX-16 | PROCESS (C1) | none | **removed** |
| E24 | GX-08 → GX-16 | PROCESS (C1) | none | **removed** |
| E25 | GX-16 → GX-17 | COLLISION | `gate_status.py`, `forge_github.py`; the status write needs no REST counter | **reversed**: GX-17 first (starts the C4 count), then GX-16 |
| E26 | GX-10 → GX-17 | REAL (thin) | only the `input_digest` prefix in the status description | **removed**: prefix printed when present |
| E27 | GX-08 → GX-18 | COLLISION | covers come through `gate_script_tests.load()`, an API that exists today; GX-08 only changes its source | **removed**; GX-24 → GX-18 COLLISION added (`gate_areas.py`, `gate_policy.py`, `gate-areas.json`) |
| E28 | GX-15 → GX-19 | COLLISION | `gate-local` | **removed** by GX-38 (`exit.sh`); GX-19 owns `gate-runner.sh` after GX-38 |
| E29 | GX-03 → GX-36 | REAL | the trigger is GX-03's cold measurement repeated at C1 | kept (as the C1 measurement) |
| E30 | GX-10 → GX-20 | REAL | carry-over needs the v4 proof and `carried_from` | kept |
| E31 | GX-15 → GX-20 | REAL (thin) | only "pr.ready accepts a carried proof when `pr.checked` passed" | **removed**: the carried plan always executes the structure stage, which already judges metadata on the new head (P-01 holds; D-B6) |
| E32 | GX-18 → GX-20 | REAL | the docs delta must run the covers-matching script tests | kept |
| E33 | GX-05 → GX-20 | REAL-merge | `gate_version` is meaningful only once the pin decides it | kept as merge-after |
| E34 | GX-20 → GX-21 | REAL (thin) | only "a RETRO-only item is satisfied by the carried proof", a `pr_ready.py` rule | **removed**: that rule moves into GX-20 (§4) |
| E35 | GX-15 → GX-21 | REAL | completeness becomes an error of the `pr metadata` module | kept |
| E36 | GX-14 → GX-22 | COLLISION | `commit_check.py` | kept (lane order; off the critical path) |
| E37 | GX-15 → GX-23 | COLLISION | `gate-stages.json` | **removed**: GX-23 declares inputs in its own `scripts/lib/gate-stage-inputs.json` |
| E38 | GX-23 → GX-24 | COLLISION | none (lane order only; AR1 touches areas, GX-23 stages and caches) | **removed**; GX-24 starts at T0 |
| E39 | GX-17 → GX-25 | COLLISION | `gate_status.py` | kept as lane order GX-17 → GX-16 → GX-25 |
| E40 | GX-25 → GX-26 | REAL | `--explain` prints the ETA | kept |
| E41 | GX-21 → GX-26 | REAL | `--explain` prints plan completeness | kept |
| E42 | GX-22 → GX-27 | REAL | the switch lives in `merge.json` (plus the real-batch trigger) | kept |
| E43 | GX-20 → GX-28 | COLLISION | `gate_report.py`, `gate-local` | **removed**; GX-10 → GX-28 REAL (`observed_versions` is a v4 proof field) |
| E44 | GX-22 → GX-28 | PROCESS (C3) | none | **removed** |
| E45 | GX-23 → GX-28 | COLLISION | `gate_result_cache.py` keys | **removed** by GX-39 (`gate_keys.py`) |
| E46 | GX-28 → GX-29 | COLLISION | `scripts/cloud/*` neighbourhood; hermetic seeding, DB residue and trace need no attestation | **removed**; GX-08 → GX-29 REAL (trace compares reads with declared covers) |
| E47 | GX-12 → GX-30 | COLLISION | `train.py` (batch comment) | **removed**: the batch-comment link moves into GX-30 |
| E48 | GX-27 → GX-30 | PROCESS (C3) | "train is the only merger" is not needed to build union plans | **removed**; GX-02 → GX-30 COLLISION kept (train files); GX-22 → GX-30 REAL-merge (the train reads `merge.json`) |
| E49 | GX-28 → GX-31 | REAL | reuse keys on the attested `toolchain_id` | kept |
| E50 | GX-30 → GX-31 | REAL | reuse is checked inside GX-30's rebuilt judge path; same `train.py` | kept |
| E51 | GX-12 → GX-32 | COLLISION | none (C3) | **removed** |
| E52 | GX-13 → GX-32 | REAL | extends GX-13's recorded-base and never-excuse rules | kept; GX-37 → GX-32 REAL added (`base.red/green` contracts) |
| E53 | GX-17 → GX-33 | REAL | the protection requires `tower/gate` (plus the stability trigger) | kept; trigger made count-based (D-B12) |
| E54 | GX-27 → GX-33 | REAL | protection only once the train is the only merger | kept |
| E55 | GX-30 → GX-34 | REAL (thin) | a design doc can be written from GX-30's specification | **removed**; GX-34 starts at T0 |
| E56 | GX-28 → GX-35 | REAL | the store keys on attested digests (the spend is answered: free tier only, D-073) | kept; GX-35 last |
| E57 | C1 barrier (wave 0 → all of wave 1) | PROCESS | wave-1 code needs none of GX-05/06/08; D-A3 covers the verdict | **removed** as a barrier; C1 stays a measurement (§6) |
| E58 | C2 barrier (wave 1 → wave 2) | PROCESS | none beyond the REAL edges above | **removed** |
| E59 | C3 barrier (wave 2 → wave 3) | PROCESS | none beyond the REAL edges above | **removed** |
| E60 | Slot rule (next slot after both merge) | PROCESS | none | **removed** |
| E61 | 2-at-a-time cap | PROCESS | lifted by Daniel 14:19 | **removed** |

### 2.1 Edges added by v2

| Edge | Kind | Why |
|---|---|---|
| GX-37 → GX-09, GX-10, GX-15, GX-25, GX-32, GX-41 | REAL | contracts first: v4 verdicts, `pr.checked`, `gate.started`, `base.red/green`, `plan.changed` locked once |
| GX-38 → GX-05, GX-10, GX-15, GX-19, GX-20 | REAL (seam) | each owns one hook file of `scripts/gate-local` (`pin`, `proof`, `prereq`, `exit`, `plan`) |
| GX-39 → GX-10, GX-11, GX-12, GX-13, GX-20, GX-23 | REAL (seam) | each owns one module split out of `gate_report.py` / the cache key seam |
| GX-09 → GX-10 | REAL-merge | readers accept v4 before the producer switches |
| GX-03 → GX-11, GX-16 | COLLISION kept | `gate_test_cache.py` (GX-11), `config/registry/gate.json` (GX-16 changes an existing key's default); both off the critical path |
| GX-24 → GX-18 | COLLISION kept | selection files; GX-24 is done work (AR1), so it goes first |
| GX-17 → GX-16 → GX-25 | COLLISION kept | `gate_status.py`, `forge_github.py`; GX-17 first to start the C4 count |
| GX-02 → GX-30 → GX-31 | COLLISION + REAL kept | train files; this is the critical chain |
| GX-22 → GX-30 | REAL-merge | the train reads `merge.json` (moved here from GX-22 so GX-22 never edits `train.py`) |
| GX-11 → GX-26 | REAL-merge | docs describe tier behaviour only after it merged |
| GX-02, GX-03, GX-05 → GX-36 | REAL (trigger) | GX-36 runs only if C1's cold base gate fails a timing assertion |

## 3. Preparation units

All four launch at T0. Each is accepted only because it shortens the critical path net of its own time (last column). IDs continue GA3's numbering (`program.v1` ids `GX37` …). Conventions of plan.md §3.1 apply (one PR, 3–8 commits, `Plan: N`, D-070 cited, RETRO). Prep units are **behaviour-preserving**: the existing tests stay green unchanged and a fixture gate's report and v3 payload are byte-identical before and after.

| ID | Tier · h | Files created / split (sole owner while it runs) | Edges it removes | Net effect on the path |
|---|---|---|---|---|
| **GX-37 Contracts first** | sonnet · 1 | New, all locked at once: `contracts/events/gate.passed.v4.json`, `gate.failed.v4.json` (GA2 §6 fields, as GA3 GX-09), `pr.checked.v1.json` (GA3 GX-15), `gate.started.v1.json` (GA3 GX-25), `base.red.v1.json`, `base.green.v1.json` (GA3 GX-32), `plan.changed.v1.json` (§7.3); `schemas.lock.json`; their generated Python and TypeScript modules; `docs/process/EVENTS.md` (one section per new event, the `input_digest` recipe of GA2 Q14, the `env.drift` producer line GA3 gave GX-02); `scripts/lib/gate_digest.py` (the pure `input_digest` function) with its cases in the existing `test_event_contracts.py`. | E13 (start part), E19; every lock/`EVENTS.md` collision among GX-02, GX-09, GX-15, GX-17, GX-25, GX-32, GX-41 (GA3 §4.4 row "contract lock": 6 writers → 1) | GX-10 starts at 1.4 h instead of 1.9 h (after GA3's GX-09); GX-15, GX-25, GX-32, GX-41 stop serializing on the lock. **Accepted** (−0.5 h on the near-critical chain, −≈ 3 h of lock serialization). |
| **GX-38 Driver hooks and manifest pre-claims** | sonnet · 0.75 | `scripts/gate-local` sources `scripts/lib/gate-hooks/{pin,tier,proof,prereq,plan,exit}.sh` (new, each a no-op function) at fixed points: `pin` after the preflight and before the lock; `tier` in argument parsing; `proof` after the base sha is known, exporting `OU_GATE_BASE_SHA` (the `baseRefOid` already read at `:97-99`, or the batch base) and the `.pass` record extras; `prereq` for the prerequisite stage list (`:277-285`); `plan` for the plan source; `exit` in the exit trap. `scripts/lib/gate-runner.sh` writes `started_at` into `<stage>.stage.json` (moved from GX-10). Every new path this program creates (§5.2) is pre-claimed in its `units/engine-*/unit.json` (a glob that matches no file yet is only a warning, `unit_check.py:57`), except `units/engine-train/unit.json` (GX-02 owns it; GX-30 and GX-31 claim their new train modules there themselves, after GX-02); `CODEOWNERS` regenerated once, and no unit running at the same time as GX-38 changes it. Case added to `scripts/tests/gate-local.test.sh`: each hook runs once, in order. Edits no registry file (D-B9). | E14, E24, the `gate-local` part of E16/E39; GA3 §4.4 row `scripts/gate-local` (7 writers → 1 each per hook file); every `units/*/unit.json` and `CODEOWNERS` edit by later units | Without it the `gate-local` writers GX-05 → GX-10 → GX-11 → GX-15 → GX-19 → GX-20 serialize (10.5 h + 6 L ≈ 12.9 h). **Accepted** (−≈ 5 h). |
| **GX-39 Report and cache seams** | sonnet · 0.75 | `scripts/lib/gate_report.py` keeps `main` and the orchestration; split out (moved code or stubs): `gate_proof.py` (verdict payload builder), `gate_adjudicate.py` (KD1 call and `defect_events`), `gate_publish.py` (publish condition and channel, `:233-234`), `gate_tier.py` (`current`, `cacheable`, `adjudicated`: today's mode-based behaviour), `gate_carry.py` (stub), `gate_keys.py` (stub `key_parts()`); `gate_result_cache.py` calls `gate_tier.cacheable` and `gate_keys.key_parts`. Registry reads stay in `gate_report.py` and are passed in, so no `x-readers` change (D-B9). Not `gate_test_cache.py` (GX-03 holds it; GX-11 routes it). Case added to `test_gate_report_skips.py`: identical v3 payload on a fixture. | E14, E15, the report part of E16, E39, E41; GA3 §4.4 row `gate_report.py` (7 writers → 1 per module) | Without it GX-10 → GX-11 → GX-12 → GX-13 → GX-20 → GX-28 serialize on `gate_report.py` (9.5 h + 6 L). **Accepted** (−≈ 4 h, overlapping GX-38's gain). |
| **GX-42 Adopt this graph** | sonnet · 0.25 | `docs/programs/gate-excellence/plan.md`: its `program.v1` block replaced verbatim by §6.1's block, one pointer line to `plan-v2.md` at the top; nothing else in plan.md changes. `scripts/program check gate-excellence` passes. | the coordinator launching from GA3's (wave, id) order | Off the critical path: until it merges the coordinator launches §6 by hand. Accepted because it makes `scripts/coordinator` and GX-41 read the right graph. |

Considered and **rejected** (they do not pay for themselves):

| Candidate | Why not |
|---|---|
| Train-file split (`train.py` → judge / merge / queue modules) before GX-02 | Would let GX-02 ∥ GX-06 and GX-30 ∥ GX-31, but needs wave 0 re-planned and saves ≤ 0.4 h of end time (the GX-10 → GX-20 → GX-26 chain is within 0.1 h). Revisited by the planning coordinator if the train chain slips (§7.3). |
| Test-manifest fragments as a separate prep before GX-08 | GX-07 merged at 15:0x, so GX-08 itself can start at T0 and *is* the per-test manifest split (§4). |
| `gate_status.py` split for GX-16/17/25 | That lane ends at 6.2 h, 1.7 h before the critical path. |
| Per-unit split of `config/registry/gate.json` | Not needed: after GX-03 and GX-16 no unit edits it until GX-26; new keys go to new per-unit registry files (D-B8). |

## 4. Re-split and merged units

Only the differences from GA3 §3.3 are listed; everything else in each unit (goal, B-blocks, findings closed, done criteria, risk, rollback) stands. Units not listed (GX-03, GX-14, GX-27, GX-36) are unchanged; GX-35 keeps its goal and shape and changes only in that it is approved inside R2's free allowance (D-073), not behind a spend ask.

| Old | New | Why |
|---|---|---|
| GX-02 + GX-06 | **GX-02** (opus · 3 h, ≤ 8 commits): `eaa408de` cherry-picked unchanged (its `units/engine-train/unit.json` line is a dependency declaration, not a path, so `CODEOWNERS` does not move; GX-02 is that manifest's only writer while it runs), class line, halt on env/contract, `env.drift` producer documented in `docs/operations/train.md` (the `EVENTS.md` line is GX-37's), `train.trigger_mode=emit_only`, lease and owner, `train.enabled` guard, `train.enabled` default true in the **last** commit. Done = both GA3 done lists. | E08: same files, no data dependency; one session and one merge instead of two on the critical chain (−0.4 h). GX-06 disappears from the graph. |
| GX-05 | Same, but its re-exec lives in `scripts/lib/gate-hooks/pin.sh` (GX-38); `gate-local` itself is not edited. | GX-38 seam. |
| GX-08 | Per-test **sidecar** manifests `scripts/tests/covers/<test>.json` (`script`, `covers`, `modules`), generated mechanically and idempotently from today's JSON; the JSON is deleted; `fallback` moves to a new `config/registry/gate-tests.json`; the "every `*.test.sh` has a manifest" rule lives in its own `test_gate_script_tests.py`, not in `structure.py`; **no `*.test.sh` is edited**. Key-equality test as in GA3. | Amends the letter of D-A6 (header → sidecar), not its intent (per-test declaration, no aggregate). Removes E17 and every `.test.sh` collision (GX-03, GX-22, GX-36 and any unit adding a test); lets GX-08 start at T0 now that GX-07 merged. |
| GX-09 | Readers only (opus · 1 h): `pr_ready.py`, `slo.py`, `stall_report.py` accept v3 and v4; the train-queue case goes in a new `scripts/tests/test_gate_v4_readers.py` run from `plan-tick.test.sh`, so `train.py` and `test_train.py` are not touched. | The contracts are GX-37's; `queue_entry` is version-agnostic (E11). |
| GX-10 | Owns `gate-hooks/proof.sh`, `gate_proof.py`; its key becomes `gate-proof.event_version` in a new `config/registry/gate-proof.json`. `started_at` already exists (GX-38). Must merge after GX-09. | GX-38/39 seams; D-B8. |
| GX-11 | Tier **derived** (D-B5): `--tier3` → 3, `--pr` → 1, `--sha` without `--pr` → 2 (the train and battery commands stay as they are). Owns `gate-hooks/tier.sh`, `gate_tier.py`, `config/registry/forge-events.json` (replaces `tier1_gate_modes` by `adjudicated_tiers`, moving its `x-readers`; after GX-17), `gate_test_cache.py` (tier guard, and routes its key through `gate_keys.key_parts`; after GX-03), new `config/registry/gate-tier.json`. Does **not** touch `train.json`, `battery.json` or `train.md` (the GX-06 runbook line is removed by GX-26). | E14, E15; keeps the train lane free. |
| GX-12 | `gate_publish.py` only (sonnet · 1 h). The batch comment's link to the verdict `event_id` moves to GX-30. | E15, E43: no `train.py` edit. |
| GX-13 | Edits `gate_adjudicate.py` instead of `gate_report.py`; reads `OU_GATE_BASE_SHA` (GX-38). | E16. |
| GX-15 | Prerequisite list in `gate-hooks/prereq.sh`; `pr.checked.v1` and its `EVENTS.md` section come from GX-37. | GX-38, GX-37. |
| GX-16 | Starts after GX-17 (its files) and GX-03 (`gate.json`); otherwise unchanged. | E21 reversed. |
| GX-17 | Starts at T0. Documents the status in a new `docs/operations/gate-status.md` (no `EVENTS.md` edit; GX-26 links it from `EVENTS.md:176-178`). The description prints the `input_digest` prefix when the verdict has one. | E21, E22; starts the C4 count ≈ 16 h earlier. |
| GX-18 | After GX-24; reads covers through `gate_script_tests.load()`, whose source GX-08 switches underneath. | E23. |
| GX-19 | Owns `gate-runner.sh` (per-stage timeout in `step`) and `gate-hooks/exit.sh`; keys in a new `config/registry/gate-gc.json` (`gate-gc.stage_timeout_s`, `reports_keep`, `build_cache_keep`). | E24; D-B8. |
| GX-20 | Gains GX-21's `pr_ready.py` rule (an item ticked only by the RETRO commit is satisfied by the carried proof on that head) and drops the `pr.checked` acceptance clause: the carried plan always **executes** the structure stage (D-B6). Owns `gate-hooks/plan.sh`, `gate_carry.py`, `gate_policy.py`, `gate_areas.py` (after GX-18), `pr_ready.py`, new `config/registry/gate-carry.json`. opus · 2.25 h. Merges after GX-05. | E27, E30. |
| GX-21 | `structure.py` (metadata module) and `plan_tick.py` only; no `pr_ready.py`. | E30. |
| GX-22 | Does not edit `train.py`; the train's read of `merge.json` moves to GX-30. `merge-phase.test.sh` is free (GX-07 merged). | E32 kept; keeps the train lane free. |
| GX-23 | Declares inputs in a new `scripts/lib/gate-stage-inputs.json` and `config/registry/gate-inputs.json` (its schema version is part of the key, so no `gate.stage_cache_version` bump in `gate.json`); does not edit `gate-stages.json` or `gate-fixed.sh`. Starts after GX-39. | E33, E34. |
| GX-24 | Starts at T0 (AR1 is done work; nothing it touches is held). | E34. |
| GX-25 | Keys in a new `config/registry/gate-eta.json`; contract and `EVENTS.md` from GX-37. | GX-37; D-B8. |
| GX-26 | Also: removes the GX-06 runbook line from `train.md` (after GX-11), links `EVENTS.md:176-178` to `gate-status.md`, removes any registry key the program retired, adds a covers sidecar for any source file the gate still reports as uncovered. sonnet · 1 h. Last code unit. | Collects the small doc edits other units no longer make. |
| GX-28 | Owns `gate_keys.py` (fills `key_parts` with the attested `toolchain_id`) and adds `observed_versions` in `gate_proof.py` (after GX-10). Starts after GX-10, not after GX-20/22/23. | E39–E41. |
| GX-29 | After GX-08, not GX-28; keys in a new `config/registry/gate-trace.json` and `cloud.json`. | E42. |
| GX-30 | Gains the batch-comment link (GX-12) and the train's read of `merge.json` (GX-22, merge after it); the queue index goes in a new `scripts/lib/train_queue.py`. opus · 2.25 h. | E43, E44. |
| GX-31 | Reuse lookup in a new `scripts/lib/train_reuse.py` (not in `gate_report.py`). | E39 neighbourhood; keeps `gate_report.py` closed. |
| GX-32 | `base.red/green` contracts from GX-37; no lock or `EVENTS.md` edit. Starts after GX-13. | E47. |
| GX-33 | Trigger becomes count-based (D-B12). | Wall-clock floor removed. |
| GX-34 | Starts at T0. | E51. |

## 5. Waves, lanes and file ownership

### 5.1 Waves (launch levels) and concurrency

A wave here is a launch level, not a barrier: a unit launches the moment its REAL edges are merged and the files it owns are free (§6). Times are the model's (start → merged, hours after T0). GA3's merged units (GX-00, GX-01, GX-04, GX-07) are wave 0.

| Wave | Units (start → merged) | Lanes | Max concurrency |
|---|---|---|---|
| **A — T0** | GX-42 (0 → 0.65), GX-38 (0 → 1.15), GX-39 (0 → 1.15), GX-37 (0 → 1.4), GX-24 (0 → 1.4), GX-14 (0 → 1.9), GX-17 (0 → 1.9), GX-34 (0 → 1.9), GX-03 (0 → 2.4), GX-08 (0 → 2.4), GX-02 (0 → 3.4) | program, driver, report, proof, select ×2, meta, out, design, sizing, train | 11 |
| **B — prep merged** | GX-05 (1.15 → 3.55), GX-12 (1.15 → 2.55), GX-13 (1.15 → 3.05), GX-19 (1.15 → 2.55), GX-23 (1.15 → 3.55), GX-09 (1.4 → 2.8), GX-10 (1.4 → 3.8), GX-18 (1.4 → 2.8), GX-41 (1.4 → 3.3) | driver (pin, gc), report (publish, adjudicate, cache), proof, select, program | 15 (at 1.4–2.4 h) |
| **C — first code merged** | GX-15 (1.9 → 4.3), GX-22 (1.9 → 3.8), GX-11 (2.4 → 4.3), GX-16 (2.4 → 4.3), GX-29 (2.4 → 4.8), GX-32 (3.05 → 4.95), GX-30 (3.4 → 6.05), at C1 (≈ 4.05): GX-27 (→ 4.95), GX-36 if triggered (→ 5.95) | meta ×2, tier, out, select, defects, train, merge | 14–15 (at 2.4 h) |
| **D — proof merged** | GX-20 (3.8 → 6.45), GX-28 (3.8 → 5.7), GX-21 (4.3 → 5.7), GX-25 (4.3 → 6.2), GX-31 (6.05 → 7.95), GX-26 (6.45 → 7.85); trigger-bound: GX-33 (count trigger, ≈ 8–9.5 h); last: GX-35 (free tier, D-073) | proof, keys, meta, out, train, docs | 10 (at 4.05 h), 2 at the end |

Plan for **15 concurrent unit sessions** (set `coordinator.max_sessions` to 15 with `scripts/config set` at T0), plus the train-role session from C1 and the coordinator. Peak load: 15 gates on 15 separate containers (each lane container gates itself; GX-03 sizes the gate to its own container).

### 5.2 File ownership in time order (every file with more than one owner)

No row has two overlapping intervals; the model was checked file by file. A unit owns every file in its §4 / GA3 row; files with one owner are not listed.

| File | Owners in order (start–merged, h) |
|---|---|
| `scripts/lib/train.py`, `engine_role.py`, `config/registry/train.json`, `scripts/tests/test_train.py` | GX-02 (0–3.4) → GX-30 (3.4–6.05) → GX-31 (6.05–7.95; `train.py` only) |
| `units/engine-train/unit.json` | GX-02 → GX-30 → GX-31 (each claims its own new module) |
| `CODEOWNERS`, every other `units/engine-*/unit.json` | GX-38 (0–1.15) → GX-30 (3.4–6.05) → GX-31 (6.05–7.95) (engine-train only) |
| `scripts/gate-local` | GX-38 only; afterwards every change goes to one hook file: `pin.sh` GX-05, `proof.sh` GX-10, `tier.sh` GX-11, `prereq.sh` GX-15, `plan.sh` GX-20, `exit.sh` GX-19 |
| `scripts/lib/gate_report.py` | GX-39 only; afterwards `gate_proof.py` GX-10 → GX-28, `gate_publish.py` GX-12, `gate_adjudicate.py` GX-13, `gate_tier.py` GX-11, `gate_carry.py` GX-20, `gate_keys.py` GX-28 |
| `scripts/lib/gate-runner.sh` | GX-38 (0–1.15) → GX-19 (1.15–2.55) |
| `scripts/lib/gate_result_cache.py` | GX-39 (0–1.15) → GX-23 (1.15–3.55) |
| `scripts/lib/gate_test_cache.py` | GX-03 (0–2.4) → GX-11 (2.4–4.3) |
| `scripts/lib/gate_script_tests.py` | GX-08 (0–2.4) → GX-29 (2.4–4.8) |
| `scripts/lib/gate_areas.py`, `gate_policy.py` | GX-24 (0–1.4) → GX-18 (1.4–2.8) → GX-20 (3.8–6.45) |
| `scripts/lib/gate-areas.json`, `test_gate_areas.py` | GX-24 → GX-18 |
| `scripts/lib/structure.py` | GX-14 (0–1.9) → GX-15 (1.9–4.3) → GX-21 (4.3–5.7) |
| `scripts/lib/commit_check.py`, `test_commit_check.py` | GX-14 (0–1.9) → GX-22 (1.9–3.8) |
| `config/registry/merge.json` | GX-22 (1.9–3.8) → GX-27 (4.05–4.95) |
| `scripts/lib/pr_ready.py` | GX-09 (1.4–2.8) → GX-20 (3.8–6.45) |
| `scripts/lib/slo.py` | GX-09 (1.4–2.8) → GX-25 (4.3–6.2) |
| `scripts/lib/gate_status.py`, `forge_github.py` | GX-17 (0–1.9) → GX-16 (2.4–4.3) → GX-25 (4.3–6.2; `gate_status.py` only) |
| `config/registry/forge-events.json` | GX-17 (0–1.9) → GX-11 (2.4–4.3) → GX-26 (6.45–7.85) |
| `config/registry/gate.json` | GX-03 (0–2.4) → GX-16 (2.4–4.3) → GX-26 (6.45–7.85) |
| `scripts/lib/defect_detect.py`, `config/registry/defects.json` | GX-13 (1.15–3.05) → GX-32 (3.05–4.95) |
| `docs/process/EVENTS.md`, `contracts/events/schemas.lock.json` | GX-37 (0–1.4) → GX-26 (6.45–7.85; `EVENTS.md` only) |
| `docs/operations/train.md` | GX-02 (0–3.4) → GX-26 (6.45–7.85) |
| `scripts/lib/absolute-literals-baseline/engine/*.json` | only GX-38 (engine-gate-run) and GX-39 (engine-gate-report) may edit them, at T0–1.15; every other unit adds no literal and leaves them alone (the list may stay larger, `structure.py:275-296`) |

Rules that keep this table true while the plan moves: a new per-unit registry file (`config/registry/<unit-topic>.json` + its generated module) belongs to the unit that creates it; a unit that moves a registry read updates that key's `x-readers` and therefore owns that registry file for its run (D-B9); generated aggregates follow D-A13 but, with GX-37 and GX-38 done first, no two concurrent units regenerate the same one.

## 6. Launch order

Event-driven: each line fires when its events happen, never on a clock. "Merged" means merged by the coordinator under the current rule (D-A11, verdict per D-A3 until GX-05 merges) before C1, and by the train after C1.

| Step | When | Launch / do |
|---|---|---|
| 0 | T0 (this plan adopted) | Coordinator: set `coordinator.max_sessions` = 15 (registry); close MQ1 #680 if still open (GA3 D-A10); ask the account owner for `statuses:write` on the gate identity (§7.1). Launch by hand (GX-42 makes `scripts/coordinator` able to): **GX-42, GX-37, GX-38, GX-39, GX-02, GX-03, GX-08, GX-14, GX-17, GX-24, GX-34**. |
| 1 | GX-38 merged | GX-05, GX-19 |
| 2 | GX-39 merged | GX-12, GX-13, GX-23 |
| 3 | GX-37 merged | GX-09, GX-41; GX-10 as soon as GX-37, GX-38 and GX-39 are all merged |
| 4 | GX-24 merged | GX-18 |
| 5 | GX-14 merged (and GX-37, GX-38) | GX-15, GX-22 |
| 6 | GX-03 merged (and GX-17, GX-39) | GX-11, GX-16 |
| 7 | GX-08 merged | GX-29 |
| 8 | GX-13 merged | GX-32 |
| 9 | GX-02 merged | GX-30 (it merges after GX-22) |
| 10 | **C1**: GX-02, GX-05, GX-03 merged | Start the train-role session (GX-02 runbook); repeat GX-03's cold base gate on an idle 4-vCPU container → launch GX-36 only if a timing assertion fails; from now on the train is the only merge path. |
| 11 | GX-10 merged | GX-28; GX-20 once GX-18 is merged too (GX-20 merges after GX-05) |
| 12 | GX-15 merged | GX-21 |
| 13 | GX-16 merged | GX-25 |
| 14 | GX-22 merged and the train has merged one real batch (≥ 2 members) | GX-27 |
| 15 | GX-30 and GX-28 merged | GX-31 |
| 16 | GX-20, GX-21, GX-25 merged | GX-26 (merges after GX-11) |
| 17 | GX-17 and GX-27 merged, count trigger met (D-B12), `statuses:write` granted | GX-33, then its account action (protection) |
| 18 | GX-35's spend is answered: free tier only (D-073), nothing is spent | GX-35 (last, inside R2's free allowance) |

Checkpoints keep their measurements but are no longer launch barriers: **C1** = step 10; **C2** (GA3's wave-1 measures) is read when GX-10, GX-15 and GX-16 have merged; **C3** (gates per unit, base-merge share, web cache hits, GX-34's build units, D-A8, fixing GX-35's launch inside the free allowance of D-073) when GX-20, GX-23 and GX-27 have merged; **C4** = step 17. Their "re-plan if" rows (plan.md §7) are inputs to the planning coordinator (§7.3), not stop points.

### 6.1 Graph as data (`program.v1`; GX-42 copies this block into plan.md)

Validated with the repository's own loader (`program.load` on a scratch copy: 41 units, schema, no cycle, no forward-wave dependency). Waves: 1 = GA3's merged wave 0; 2–5 = §5.1's A–D. GX06 is gone (folded into GX02). `depends_on` holds REAL edges and the **kept collision edges** (the coordinator must not launch two owners of a file at once). It cannot express REAL-merge edges (GX-09 → GX-10, GX-05 → GX-20, GX-22 → GX-30, GX-11 → GX-26), so each is enforced by a test in the later unit that exercises the earlier unit's code: the later unit's gate cannot be green on a base without it (GX-41 adds a first-class `merge_after` later, §7.3). Units with an external trigger (GX-27 real batch, GX-33 count + account action, GX-35 free-tier-only scope (D-073), GX-36 C1 measurement) are **held**: the coordinator launches them by hand until GX-41 merges.

```json program.v1
{
  "contract": "program.v1",
  "program": "gate-excellence",
  "complaint": {"symptom": "the gate proves the head sha, not content, judges itself, overloads its container and blames PRs for machine faults; tier 2 is one global serial point", "evidence": "GA1 F-01..F-17 and GA2 G-01..G-15: 151 of 231 re-gates were base merges, 37 RETRO re-gates, cold base gate fails on an idle 4-vCPU container, 3 green PRs ejected on 27/10", "goal": {"metric": "prs_merged_per_day", "comparator": "gte", "target": 1000, "unit": "prs/day"}},
  "units": [
    {"id": "GX00", "title": "Program record: D-070, premises, program graph", "depends_on": [], "owner": "gx-program", "model": "sonnet", "wave": 1, "done": ["D-070 and six premise records merged", "scripts/program check gate-excellence passes"], "area": ["docs/domain/DECISIONS.md", "docs/process/premises/**"]},
    {"id": "GX01", "title": "Preflight first; classified driver aborts", "depends_on": ["GX00"], "owner": "gx-driver", "model": "opus", "wave": 1, "done": ["gate exits 2 with FAIL env before flock/slot/worktree when a probe fails", "driver abort publishes gate.failed class env with --pr"], "area": ["scripts/gate-local", "scripts/lib/preflight.py", "scripts/lib/gate_classify.py", "scripts/lib/gate-runner.sh", "scripts/lib/gate_report.py"]},
    {"id": "GX04", "title": "pr.ready from the gated sha and the recorded base", "depends_on": ["GX00"], "owner": "gx-meta", "model": "sonnet", "wave": 1, "done": ["a gate run from a checkout not on the head emits pr.ready"], "area": ["scripts/lib/pr_ready.py", "scripts/lib/plan_tick.py"]},
    {"id": "GX07", "title": "HD1 #677 landed as is", "depends_on": ["GX00"], "owner": "gx-select", "model": "sonnet", "wave": 1, "done": ["#677 merged with the pinned or base-tip gate green"], "area": ["scripts/tests/rest_fake.py", "scripts/lib/gate-script-tests.json"]},
    {"id": "GX42", "title": "Adopt the plan-v2 graph", "depends_on": ["GX00"], "owner": "gx-program", "model": "sonnet", "wave": 2, "done": ["plan.md program.v1 block equals plan-v2.md section 6.1", "scripts/program check gate-excellence passes"], "area": ["docs/programs/gate-excellence/plan.md"]},
    {"id": "GX37", "title": "Contracts first: every program event contract locked once", "depends_on": ["GX00"], "owner": "gx-proof", "model": "sonnet", "wave": 2, "done": ["v4 verdicts, pr.checked, gate.started, base.red/green and plan.changed locked", "gate_digest.input_digest tested"], "area": ["contracts/events/schemas.lock.json", "docs/process/EVENTS.md", "scripts/lib/gate_digest.py"]},
    {"id": "GX38", "title": "Driver hooks and manifest pre-claims", "depends_on": ["GX01"], "owner": "gx-driver", "model": "sonnet", "wave": 2, "done": ["gate-local sources one hook file per concern; report unchanged on a fixture", "every program path pre-claimed; CODEOWNERS regenerated once"], "area": ["scripts/gate-local", "scripts/lib/gate-hooks/**", "scripts/lib/gate-runner.sh", "units/**"]},
    {"id": "GX39", "title": "Report and cache seams", "depends_on": ["GX01"], "owner": "gx-proof", "model": "sonnet", "wave": 2, "done": ["gate_report.py split into proof, adjudicate, publish, tier, carry, keys modules", "identical v3 payload on a fixture"], "area": ["scripts/lib/gate_report.py", "scripts/lib/gate_result_cache.py"]},
    {"id": "GX02", "title": "Train halts on env/contract; designated tier-2 executor (absorbs GX-06)", "depends_on": ["GX01"], "owner": "gx-train", "model": "opus", "wave": 2, "done": ["eaa408de landed", "27/10 fixture halts with env.drift and no pr.ejected", "pr.ready starts no process in the producer container", "train refuses a machine-local enabled override"], "area": ["config/registry/train.json", "docs/operations/train.md", "scripts/lib/engine_role.py", "scripts/lib/train.py", "scripts/lib/train_trigger.py"]},
    {"id": "GX03", "title": "Size the gate to its container", "depends_on": ["GX01"], "owner": "gx-driver", "model": "sonnet", "wave": 2, "done": ["cold base gate passes on an idle 4-vCPU container", "concurrency and slots derived from vCPUs"], "area": ["scripts/lib/gate_test_cache.py", "scripts/lib/gate-isolation.sh", "config/registry/gate.json"]},
    {"id": "GX08", "title": "Test map from per-test sidecar manifests", "depends_on": ["GX07"], "owner": "gx-select", "model": "sonnet", "wave": 2, "done": ["covers declared in scripts/tests/covers/<test>.json", "script-test cache keys unchanged by the migration", "gate-script-tests.json no longer committed by PRs"], "area": ["scripts/lib/gate_script_tests.py", "scripts/tests/covers/**"]},
    {"id": "GX14", "title": "Structure metadata judged on the gated sha, REST cut", "depends_on": ["GX00"], "owner": "gx-meta", "model": "opus", "wave": 2, "done": ["structure verdict bound to the gated sha", "REST calls per structure check <= 6 on a 12-commit PR"], "area": ["scripts/lib/commit_check.py", "scripts/lib/structure.py"]},
    {"id": "GX17", "title": "Our own tower/gate commit status", "depends_on": ["GX00"], "owner": "gx-out", "model": "sonnet", "wave": 2, "done": ["tower/gate status written per gated head, or a non-fatal 403 line while the scope is pending"], "area": ["scripts/lib/forge_events.py", "scripts/lib/forge_github.py", "scripts/lib/gate_status.py"]},
    {"id": "GX24", "title": "AR1: database area by import graph (fail closed)", "depends_on": ["GX00"], "owner": "gx-select", "model": "sonnet", "wave": 2, "done": ["#671 merged with a fail-closed fixture"], "area": ["scripts/lib/gate-areas.json", "scripts/lib/gate_areas.py", "scripts/lib/gate_policy.py"]},
    {"id": "GX34", "title": "Sharded tier 2: design", "depends_on": ["GX00"], "owner": "gx-design", "model": "opus", "wave": 2, "done": ["design doc with simulation on the 27/10 merge log"], "area": ["docs/programs/gate-excellence/design-sharded-tier2.md"]},
    {"id": "GX05", "title": "Pinned gate: the base tip's tooling judges", "depends_on": ["GX04", "GX38"], "owner": "gx-driver", "model": "opus", "wave": 3, "done": ["a PR that breaks gate-local is red under the pinned gate, green in its report-only run"], "area": ["scripts/gate-local", "scripts/lib/gate_pin.py", "config/registry/gate-pin.json"]},
    {"id": "GX09", "title": "gate.passed|failed v4 readers", "depends_on": ["GX37"], "owner": "gx-proof", "model": "opus", "wave": 3, "done": ["readers accept v3 and v4"], "area": ["scripts/lib/pr_ready.py", "scripts/lib/slo.py", "scripts/lib/stall_report.py"]},
    {"id": "GX10", "title": "v4 producer: proof fields, .pass fields, stage start, cost", "depends_on": ["GX37", "GX38", "GX39"], "owner": "gx-proof", "model": "opus", "wave": 3, "done": ["every gate posts a v4 verdict whose input_digest a verifier recomputes"], "area": ["scripts/lib/gate_report.py", "scripts/gate-local", "scripts/lib/gate-runner.sh"]},
    {"id": "GX12", "title": "Tier 2 leaves evidence", "depends_on": ["GX39"], "owner": "gx-train", "model": "sonnet", "wave": 3, "done": ["a train batch leaves a tier-2 v4 verdict on the repository channel"], "area": ["scripts/lib/gate_report.py", "scripts/lib/train.py"]},
    {"id": "GX13", "title": "Known defects against a recorded base", "depends_on": ["GX39"], "owner": "gx-defects", "model": "opus", "wave": 3, "done": ["adjudication identical across machines", "a test the PR edited is never excused"], "area": ["scripts/lib/defect_detect.py", "scripts/lib/gate_report.py"]},
    {"id": "GX18", "title": "Docs area runs the script tests that read docs", "depends_on": ["GX24"], "owner": "gx-select", "model": "sonnet", "wave": 3, "done": ["a docs-only diff selects exactly the script tests whose covers meet it"], "area": ["scripts/lib/gate-areas.json", "scripts/lib/gate_areas.py"]},
    {"id": "GX19", "title": "Per-stage timeouts; report and build-cache eviction", "depends_on": ["GX38"], "owner": "gx-driver", "model": "sonnet", "wave": 3, "done": ["a hung stage ends classified at its timeout", "report directories bounded"], "area": ["scripts/lib/gate-runner.sh", "scripts/gate-local", "scripts/lib/gate-build.py"]},
    {"id": "GX23", "title": "Narrow web stage inputs (fail closed)", "depends_on": ["GX39"], "owner": "gx-select", "model": "opus", "wave": 3, "done": ["a scripts-only base merge hits the web caches; undeclared inputs miss"], "area": ["scripts/lib/gate-stages.json", "scripts/lib/gate_result_cache.py"]},
    {"id": "GX41", "title": "Planning coordinator: event-driven re-plan", "depends_on": ["GX37"], "owner": "gx-program", "model": "opus", "wave": 3, "done": ["every coordinator event gets a re-plan judgment; changes published as plan.changed and folded into the live graph", "held units launch only on their trigger; launch order by remaining path"], "area": ["scripts/lib/replan.py", "scripts/lib/coordinator.py", "docs/operations/coordinator.md"]},
    {"id": "GX11", "title": "Tier is explicit; D-065 (5) made true", "depends_on": ["GX39", "GX03", "GX17"], "owner": "gx-proof", "model": "opus", "wave": 4, "done": ["a tier-2 run reuses no marker; tier 1 still hits"], "area": ["scripts/gate-local", "scripts/lib/gate_result_cache.py", "scripts/lib/gate_test_cache.py"]},
    {"id": "GX15", "title": "Structure tree part cached; pr metadata stage; pr.checked", "depends_on": ["GX14", "GX37", "GX38"], "owner": "gx-meta", "model": "opus", "wave": 4, "done": ["re-gate of an unchanged tree spends < 1 s in the tree part", "pr.checked published"], "area": ["scripts/lib/structure.py", "scripts/lib/gate-stages.json", "scripts/gate-local", "config/registry/local-checks.json"]},
    {"id": "GX16", "title": "Status comment cost, shape and hygiene; REST counter", "depends_on": ["GX17", "GX03"], "owner": "gx-out", "model": "sonnet", "wave": 4, "done": ["<= 10 content-creating calls per gate"], "area": ["scripts/lib/gate_status.py", "scripts/lib/forge_github.py", "scripts/lib/github_api.py"]},
    {"id": "GX22", "title": "One merge rule in the registry; P-G3 switch default OFF", "depends_on": ["GX14"], "owner": "gx-meta", "model": "opus", "wave": 4, "done": ["merge.json is the only merge rule; default keeps today's behaviour"], "area": ["config/registry/merge.json", "scripts/lib/commit_check.py", "scripts/merge-phase"]},
    {"id": "GX27", "title": "P-G3 switch ON", "depends_on": ["GX22", "GX02", "GX05"], "owner": "gx-meta", "model": "sonnet", "wave": 4, "done": ["only after the train merged a real batch; 10 PRs reach pr.ready without a base merge"], "area": ["config/registry/merge.json"]},
    {"id": "GX29", "title": "Hermetic network; DB residue; covers trace check", "depends_on": ["GX08"], "owner": "gx-driver", "model": "sonnet", "wave": 4, "done": ["a dev gate passes with network denied after install"], "area": ["scripts/cloud/setup.sh", "scripts/lib/hermetic.py", "scripts/lib/test_db.py"]},
    {"id": "GX30", "title": "Train: union plan, proven-prefix merge, rebuild on base move", "depends_on": ["GX02", "GX38"], "owner": "gx-train", "model": "opus", "wave": 4, "done": ["app-only batch runs no script-test stage; a forge refusal merges the rest"], "area": ["scripts/lib/train.py", "scripts/lib/engine_role.py", "scripts/lib/gate_batch.py"]},
    {"id": "GX32", "title": "Base health signal", "depends_on": ["GX13", "GX37"], "owner": "gx-defects", "model": "opus", "wave": 4, "done": ["a base defect of any stage kind is excused with zero base re-runs"], "area": ["scripts/lib/defect_detect.py", "contracts/events/base.red.v1.json"]},
    {"id": "GX36", "title": "Conditional: clock-reading tests class fix", "depends_on": ["GX02", "GX03", "GX05"], "owner": "gx-select", "model": "sonnet", "wave": 4, "done": ["only if C1's cold base gate still fails a timing assertion; then it passes twice in a row"], "area": ["scripts/tests/**"]},
    {"id": "GX20", "title": "Carry-over by delta (the RETRO case)", "depends_on": ["GX10", "GX18", "GX09"], "owner": "gx-proof", "model": "opus", "wave": 5, "done": ["a RETRO commit after a green head gets a carried v4 proof and pr.ready"], "area": ["scripts/lib/gate_policy.py", "scripts/lib/gate_areas.py", "scripts/gate-local", "scripts/lib/gate_report.py", "scripts/lib/pr_ready.py"]},
    {"id": "GX21", "title": "pr.ready completeness at gate time; never an empty commit", "depends_on": ["GX15"], "owner": "gx-meta", "model": "sonnet", "wave": 5, "done": ["plan completeness refused by pr metadata at gate time"], "area": ["scripts/lib/pr_ready.py", "scripts/lib/structure.py"]},
    {"id": "GX25", "title": "Gate lifecycle events, ETA from the ledger, gate.slow", "depends_on": ["GX16", "GX37", "GX09"], "owner": "gx-out", "model": "sonnet", "wave": 5, "done": ["gate.started with a critical-path ETA on a fresh container"], "area": ["contracts/events/gate.started.v1.json", "scripts/lib/gate_status.py", "scripts/lib/slo.py"]},
    {"id": "GX26", "title": "--explain / --why; retire drifted docs", "depends_on": ["GX20", "GX21", "GX25", "GX11", "GX02"], "owner": "gx-proof", "model": "sonnet", "wave": 5, "done": ["--explain shows the carried plan; AGENTS.md drift fixed"], "area": ["scripts/lib/gate_explain.py", "scripts/gate-dev", "AGENTS.md"]},
    {"id": "GX28", "title": "Attestation in keys and proof", "depends_on": ["GX10"], "owner": "gx-proof", "model": "opus", "wave": 5, "done": ["a stale toolchain changes toolchain_id and misses every cache"], "area": ["scripts/lib/toolchain_manifest.py", "scripts/lib/preflight.py", "scripts/lib/gate_result_cache.py"]},
    {"id": "GX31", "title": "Tier-2 reuse of exactly-matching attested proofs", "depends_on": ["GX30", "GX28"], "owner": "gx-train", "model": "opus", "wave": 5, "done": ["an unchanged rebuilt batch runs no stage; any input change re-runs"], "area": ["scripts/lib/train.py"]},
    {"id": "GX33", "title": "Branch protection requiring tower/gate", "depends_on": ["GX17", "GX27"], "owner": "gx-out", "model": "sonnet", "wave": 5, "done": ["protection requires tower/gate after >= 50 consecutive consistent heads and >= 2 train batches (account action)"], "area": ["docs/operations/branch-protection.md"]},
    {"id": "GX35", "title": "Shared store (free tier only, D-073)", "depends_on": ["GX28"], "owner": "gx-design", "model": "opus", "wave": 5, "done": ["the store stays inside R2's free allowance (10 GB-month storage, 1 M Class A writes, 10 M Class B reads, Standard class) and is LRU-capped at 10 GB", "crossing or approaching a free limit falls back to the git-ref store instead of billing"], "area": ["scripts/lib/adapters/**", "config/registry/providers.json"]}
  ]
}
```

## 7. Premises and decisions

GA3's §1 decisions (A Torre's premise decisions, D-A1 … D-A16) stand except where a D-B row below amends one.

### 7.1 For Daniel (critical only)

No decision is open. Two items need an account owner; the money item is answered by D-073 and kept for the record:

| # | Item | Kind | When | If not done |
|---|---|---|---|---|
| 1 | Give the gate's GitHub identity `statuses:write` (GA3 §9.1 item 1, unchanged) | Account action (GA-P03) | **Now** (GA3 said "before C4"): GX-17 merges at ≈ 1.9 h and GX-33's count needs zero missing statuses | GX-33 cannot start; everything else proceeds |
| 2 | Branch protection requiring `tower/gate` on `mod/roadmap-integration` (GX-33's runbook) | Account action (GA-P03) | Step 17 | "Train is the only merger" stays a convention |
| 3 | GX-35 shared store spend (GA3 §8: est. US$ 0–10/month today) | Money (GA-P04) | **Answered 2026-10-28: the free path only** (D-073, "Siga esse caminho, de modo a não gastarmos dinheiro agora") — R2's free allowance, Standard class, 10 GB LRU cap, automatic git-ref fallback; paid tiers stay deferred under P-45 | Nothing to do; if the free allowance is ever not enough, GX-35 falls back instead of billing |

Visible, decided here, reversible with one line: **D-B12** drops GA3's "≥ 2 days" minimum from GX-33's trigger (keeps ≥ 50 consecutive consistent heads). It is what moves the program end from ≈ 67 h to ≈ 9–10 h.

### 7.2 Decided here (DECIDE, THEN REPORT)

| ID | Decision | Reason | Blast radius |
|---|---|---|---|
| D-B1 | C1, C2, C3 and the slot rule stop being launch barriers; they stay as measurements (§6). Merging keeps D-A11: the coordinator merges until C1 (verdict per D-A3 until GX-05 merges), the train only after C1 (= GX-02, GX-05, GX-03 merged and the train session started). | They carried no data (§2: 14 PROCESS edges). D-A3 already gives every pre-GX-05 unit a base-tip verdict. | medium: more units merge under the interim rule; D-A3 is that rule's protection |
| D-B2 | GX-06 is folded into GX-02. | Same files, no data edge; one merge less on the critical chain. | low |
| D-B3 | GX-08 declares covers in per-test sidecar files `scripts/tests/covers/<test>.json` (amends D-A6's "header", keeps its intent). | No `*.test.sh` edit, so no collision with any unit touching a test; same key-equality test. | medium (cache correctness), unchanged mitigation |
| D-B4 | Contracts first: GX-37 locks every new event contract of the program, including `plan.changed.v1`. A unit that needs another field adds a new version (expand), never edits a locked schema. | Removes the lock/`EVENTS.md` serialization (6 writers → 1). | low |
| D-B5 | Tier is derived from the invocation: `--tier3` → 3, `--pr` → 1, `--sha` alone → 2. | No `train.json`/`battery.json` edit by GX-11. A hand `--sha` run becomes uncached tier 2: slower, never less safe. | low |
| D-B6 | A carried proof is accepted because its plan **executes** the structure stage on the new head (never carried), not because a separate `pr.checked` passed. | Removes GX-15 → GX-20; GA-P01 ("the structure/metadata check always reruns") still holds. | low |
| D-B7 | Small moves between units: GX-12's batch link and GX-22's train read → GX-30; GX-21's RETRO-item rule → GX-20; GX-17's `EVENTS.md` paragraph, GX-11's runbook line, retired keys and leftover covers → GX-26. | Each removes one shared file from a concurrent pair. | low |
| D-B8 | New keys go to new per-unit registry files (`config/registry/<topic>.json`, e.g. `gate-gc.stage_timeout_s` for GA3's `gate.stage_timeout_s`); only the namespace changes. | No wave A–D unit edits `gate.json` except GX-16 (an existing default) and GX-26. | low |
| D-B9 | A unit that moves a registry read updates that key's `x-readers` (`config_check.py:62`) and so owns that registry file for its run; the seam units GX-38/39 move no read. | `x-readers` lists file paths; a silent move would make the config check red or make two units edit one registry file. | low |
| D-B10 | REAL-merge edges are enforced by a test in the later unit that exercises the earlier unit's code, until GX-41 adds `merge_after`. | `program.v1` has only `depends_on`; encoding them there would delay GX-10 by 1.4 h. | low |
| D-B11 | Plan for 15 concurrent unit sessions (`coordinator.max_sessions` = 15). | Daniel 14:19; the model's peak. Quota is subscription (P-37); no money. | low |
| D-B12 | GX-33's trigger: ≥ 50 consecutive gated heads whose `tower/gate` equals the v4 verdict, none missing, including ≥ 2 train batches; GA3's "over ≥ 2 days" is dropped. | GA3 set it as a starting value (§9.2, low); "stable on real PRs" (A Torre's P-03) is a count of heads, and 15 parallel units produce them in hours. | medium: a broken status blocks merges on `mod/roadmap-integration` only (main untouched until the next release, D-054); rollback is removing the requirement |
| D-B13 | GA3 §7's "a unit over 2× its estimate stops" is replaced: the unit continues to green; the planning coordinator re-plans the units not yet launched (§7.3). | Daniel 14:59: PRs never stop or wait. | low |
| D-B14 | The 14:55 launches of GX-02/03/05 count as not started. They relaunch from the base on `mod/gx02`, `mod/gx03`, `mod/gx05` (none exists on the remote now). If such a branch appears later from the halted sessions, the new session reads it as notes and works on `mod/gxNN-r1` instead (never a force-push). | Daniel 14:59. | low |

### 7.3 Planning coordinator: the plan is dynamic (Daniel 14:59, corrected 15:01)

**What it is.** A step of the program coordinator (`scripts/coordinator`, D-069 CO1), not a new role. On **every new piece of information** that a PR, a session or the event log surfaces, it re-reads the live plan and asks one open question: **"Does this change the plan in any way, and is there anything I can do to make the rest go better or faster?"** It judges pertinence with judgment, not a checklist. The critical path and the premises are examples of what can change, not the trigger. If nothing changes, nothing is written. If something does, it changes the plan and records the change with its reason and intention.

**Inputs (examples, not a list it is limited to).** `pr.merged`, `pr.opened`, `pr.pushed`; `gate.failed` and its class (code, env, contract); `env.drift`; `train.batch.red`, `pr.ejected`; `session.failed`, `session.ended`, `engine.session.stalled`; `work.assigned` plus the clock observation the coordinator already takes (a unit past its estimate); `lesson.recorded` (a RETRO); PR comments and review threads on program PRs, read through the forge port when a `pr.*` event of that PR arrives; `premise.refuted`, `premise.blocked`; `defect.registered`, `defect.routed`; `gate.slow`, `slo.breached`; `unit.oversize`; `contract.question`; the checkpoints' measurements (§6).

**What it may change (examples).** Insert a short preparation unit ahead of the units it would help, e.g. a small known problem that does not touch the critical path but will hit every other unit (a flaky fixture, a missing helper, a shared env gap) gets fixed first and the others launch after it; reorder launches (longest remaining path first); re-split a unit that is overrunning into what is done and a new unit for the rest, or merge two units that turned out to share their files; move a not-yet-launched unit to another lane; change estimates; hold or release a trigger-bound unit; pull a unit forward when capacity is idle; turn a finding into a new unit.

**What it never does.** It never stops, holds or waits a PR, and never pushes scope into a running unit: the PR fixes or passes and continues; only the plan moves (new work becomes a new unit). It keeps the safety rules: no two concurrent units own one file (the change is refused if §5.2 would break), no stacking, REAL edges respected, D-070 decisions untouched; a change to a CRITICAL premise (scope, money, production, source of truth) goes to Daniel.

**Where the live plan lives.** The `program.v1` block in `docs/programs/gate-excellence/plan.md` (after GX-42, equal to §6.1) is the base; each change is a `plan.changed.v1` event (`{program, trigger_event_id, changes: [{op: insert|remove|reorder|resplit|merge|depends|estimate|hold|release, unit, detail}], reason, intention, critical_path_h_before, critical_path_h_after}`) on the repository event channel; the live graph is the base with those events folded in order (the same way status is folded today). Nothing waits for a docs PR; at each checkpoint a docs-only PR folds the accumulated changes back into plan.md's block.

**Who builds it: GX-41** (opus · 1.5 h, wave B, after GX-37; merged ≈ 3.3 h; 4.6 h of slack, so **not** on the critical path).
- Files: `scripts/lib/replan.py` (new: fold `plan.changed` over the base graph; remaining-path and slack per unit; overrun detection against `coordinator.overrun_factor`; `check(change)` refusing a change that breaks §5.2 ownership, a REAL edge or a held trigger; `merge_after` and `hold` as change ops), `scripts/lib/coordinator.py` (reads the folded graph; launch order by remaining critical path instead of (wave, id); a `replan` action that hands each new event, the live graph and its critical path to the coordinator session with the question above; held units launch only on their trigger event), `scripts/program` (`replan PROGRAM --change FILE --reason --intention` publishes a checked `plan.changed`), `config/registry/coordinator.json` (`coordinator.replan_enabled` true, `coordinator.overrun_factor` 1.5, `coordinator.launch_order` `critical_path`, `coordinator.held_units` {GX27: train batch merged, GX33: count trigger, GX35: free-tier scope confirmed (D-073), GX36: C1 measurement}), `docs/operations/coordinator.md` (the question and the never-list verbatim), tests `scripts/tests/test_replan.py` + its covers sidecar.
- Done: on fixture event streams (an overrun, an `env.drift`, a RETRO lesson naming a problem shared by later units, a merge freeing a file) the coordinator gets one `replan` action per event; a checked change is published and changes the next launches; an unsafe change is refused with the rule it breaks; no PR is held. The judgment itself stays with the coordinator session (an agent); GX-41 builds the inputs, the checks and the record.
- Until GX-41 merges, the coordinator session applies the same question by hand on each event and keeps its changes in its own notes; from GX-37's merge (≈ 1.4 h) it publishes them as `plan.changed` events through the forge port.

### 7.4 Premises this plan rests on

| Premise | If false (blast radius) | Mitigation | Status |
|---|---|---|---|
| Up to 15 unit sessions can run at once, each gating in its own container | medium: fewer lanes; the end moves toward the remaining-path order's sum | launch by remaining critical path (GX-41; by hand before); prep units stay first | Given (Daniel 14:19) |
| Base-merge churn stays near L with ≈ 15 concurrent PRs while `merge.tier1_requires_base_merge` is still true | medium: each merge makes the others behind; ≈ +0.1–0.3 h per unit, ≈ +1–2 h at the end | GX-27 as early as its trigger allows (step 14); the train batches merges after C1; the planning coordinator watches it | Inferred |
| The seam units are behaviour-preserving | medium: every later unit inherits a regression | byte-identical report and v3 payload on a fixture; existing tests unchanged | Decided (done criterion) |
| GA3's per-unit estimates hold | medium: the path moves | the planning coordinator re-splits or reorders (D-B13) | Inferred (GA3) |
| The rest of the engine stays paused (GA3 §9.3) | medium: lane PRs collide with §5.2 files | unchanged from GA3 | Given |

## 8. RETRO

- **Went well:** a small time model (hours + L per merge) and a file-by-file overlap check, both run in a scratchpad, turned "which edges are real" into numbers fast; `program.load` on a scratch copy validated the new graph without touching the repo. The audits and GA3's unit specs were precise enough that no audit work was redone.
- **Hard:** the base moved twice while planning (GX-01, then GX-07 merged), which changed which edges were already satisfied; and two mid-turn additions from Daniel (dynamic planning, then its open-question correction) reshaped §7.3 after it was designed.
- **Hidden collisions** were not in GA3's file lists: `x-readers` in registry files, per-area literal baselines, `CODEOWNERS`, unit manifests and `merge-phase.test.sh`. Check those aggregates first; they are where "different files" quietly become one file.
- **For the next planner:** separate start edges from merge-only edges (`program.v1` cannot express the second yet; GX-41 adds it), and look for "thin" REAL edges: often one exported variable or one rule moved to the owning unit deletes the edge.
- **Watch:** the critical chain is the train lane (GX-02 → GX-30 → GX-31) with the proof chain 0.1 h behind; base-merge churn at 15 concurrent PRs is the biggest unmodelled cost until GX-27.
