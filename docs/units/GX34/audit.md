# GX-34 audit (read-only, base 4bc4dd04)

Unit: GX-34 "Sharded tier 2: design" (plan.md §3.3, plan-v2 §4 row: starts at T0, E51/E55 removed). Deliverable:
`docs/programs/gate-excellence/design-sharded-tier2.md`. Docs only: no code, no tests, no config keys.

## Cited sources, verified on the base

| Cited | Exists? | Evidence |
|---|---|---|
| plan.md §3.3 GX-34 and GX-30 rows | yes | `docs/programs/gate-excellence/plan.md:441-484` |
| plan-v2 (GA4) | yes, on `origin/mod/ga4` only | `git show origin/mod/ga4:docs/programs/gate-excellence/plan-v2.md` (384 lines); GX-34 rows at `:108,184,194` |
| B-21, G-09, open question 7 | yes | `audit-2-opus.md:125-130` (G-09), `:317` (B-21), `:386` (open Q7: "adaptive batch size … simulate on the 27/10 merge log") |
| "GA2 open Q7" | ambiguity | GA2 has a **Q7** (API budget per gate, `audit-2-opus.md:222`) and an **open question 7** (bisection cost / adaptive batch, `:386`). The GX-34 row means the second (plan.md:732 confirms: "GA2 open Q7: adaptive batch size / bisection cost — simulated in GX-34"). |
| O-14 executor pool | yes | `audit-1-fable.md:314-316`; GA2 re-orders it: "the first executor pool is the train (G-09)" (`audit-2-opus.md:61`) |
| P-27 thousand a day is the start | yes, `confirmed`, radius high | `docs/process/premises/thousand-a-day-is-the-start.yml` |
| P-14 combined-head failure rate | yes, `to-validate`, medium | f = 3 % today, ≈ 0.5 % with contracts |
| P-15 tier-2 cloud duration | yes, `to-validate`, medium | ≈ 240 s estimated; GA2 Q1 measured 614 s cold on 4 vCPU |
| P-23 unit daily capacity | yes, `inferred`, low | 10–50 PRs/day per unit, then the unit splits (`unit.hot`) |
| aggregates not written by PRs | yes, premise file | `aggregates-not-written-by-prs.yml` |
| GX-30 code (union plan, proven prefix, rebuild) | **not built** (GX-30 is wave 3, after C3) | the design starts from GX-30's specification, as plan-v2 says |

## The train today (what the design shards)

- One `LockedRole`, one forge lock `train.lock_ref = train/lock`, lease 3600 s (`config/registry/train.json`).
- `drain` (`train.py:228-245`): queue → batch of `train.batch_size = 8` → `start_batch` builds the combined head on the
  tip, one combined commit per member (`build`, `:173-187`) → one tier-2 run (`train.tier2_command = scripts/gate-dev
  --sha`, timeout 1800 s) → green: `merge` member by member, then the **tree proof**: the tip after the merges must have
  the tree of the tested combined commit (`:268-283`) → red: `bisect` (`engine_role.first_red`, at most
  `ceil(log2 n)` runs, `train.bisection_max_runs = 4`) ejects the first red prefix's last member and **merges nothing**
  (`run_batch` returns `[]`, `:247-262`); the other members re-queue and the next batch re-runs them.
- A tip move between build and merge halts the train (`:265-267`); GX-30 turns that into a rebuild.
- `queue()` re-reads every open PR's log and head per batch (`:141-149`); GX-30 indexes it.
- Ownership: `train_ownership.UnitOwnership` reads `units/*/unit.json` at the tip; a head touching another lane's unit
  without its owner's approval is refused (`pr.refused`). The lane key of a PR therefore already exists in the engine.
- Aggregates: `train.publish_aggregates` (default false) and `train_aggregates.snapshot` already let the train write
  generated aggregates on its own ref (`train.py:304-309`).
- The train has never run on real PRs: `train.enabled = false`; 27/10's merges were done by the coordinator by hand.

## The 27/10 merge log (the simulation input)

Source: `git log --merges --first-parent origin/mod/roadmap-integration` between 2026-10-27 00:00 and 24:00 BRT
(03:00Z–03:00Z next day). The repository event log (PR comments) was not read: the train was off, so it holds no
`train.batch.*` events to replay, and paging every PR's comments costs ≈ 71 × pages REST calls for data git already has.

- **71 merges**, 00:04–14:54 BRT. 47 of them between 00:04 and 05:13; 40 in the hour 04:00–05:00 (a backlog drained
  by hand). Head → merge median 6.7 min, p90 19.5 min.
- **110 base merges inside the 71 PRs** (60 PRs carry at least one): serial merging forced each PR to merge the moving
  base and re-gate. The train removes this class; sharding must not bring it back.
- Lanes (mapped with today's `units/*/unit.json`, 106 manifests, 18 lanes; first manifest whose paths match):
  48 PRs touch one lane, 14 touch 2–4, 9 touch none (files only in paths no manifest claims). **engine-lane is in 39 of
  71 PRs (55 %)**, tooling-lane in 19, ui-lane in 7, every other lane ≤ 2.
- Hot shared files: `CODEOWNERS` 25 PRs, `apps/web/tsconfig.json` 16, `scripts/lib/gate-script-tests.json` 15,
  `config/registry/l10n.json` 7, `scripts/gate-local` 6, `config/registry/tests.json` 5, `docs/process/EVENTS.md` 5.
  `CODEOWNERS` and the `@ou` paths of `tsconfig.json` are **generated** (`scripts/generate` targets `codeowners`,
  `generate_addresses.py`); `gate-script-tests.json` is a hand-edited shared registry that GX-08 replaces with
  per-test sidecar files.
- Every one of the 71 PRs touches at least one file no manifest claims (`CODEOWNERS` alone is in 25).

## Findings that shape the design

1. **Lane partitioning is capped by the hottest lane, not by the executor count.** With 55 % of PRs in engine-lane,
   any disjoint-lane scheme gives at most ≈ 1 / 0.55 ≈ 1.8× on the 27/10 mix. It scales only as units split
   (P-23: a hot unit splits), i.e. it relies on the repository's own growth model.
2. **Shared files break disjointness on every PR** unless generated aggregates leave PR diffs (the
   aggregates premise) and hand-edited shared registries are split (GX-08's sidecars, D-B8 per-unit registry files).
   A partition key must therefore be "lanes ∪ non-generated shared files", and the design has to name who removes
   the remaining shared files.
3. **Speculative batches do not depend on the lane mix** but waste executor time on every red batch (all later
   in-flight batches are cancelled) and need GX-30's rebuild-on-base-move and proven-prefix merge to be safe.
4. **Bisection is serial today** (`first_red` on one executor). With more than one executor the probes of a red
   batch can run in parallel, which changes the open-Q7 trade-off (a red batch of 8 costs 1 + 3 serial runs today).
5. The cheap final tree check already exists (`merge`, tree of the tip vs tree of the tested commit); a lane
   design reuses it per shard.
6. No measurement of the real tier-2 red rate exists (P-14 `to-validate`). GA2 reports three ejections on 27/10
   (`audit-2-opus.md:338`), ≈ 3/71 ≈ 4 %, consistent with P-14's 3 %. The simulation sweeps f instead of assuming one.

## Known base defects

`claude-session.test.sh`, `root-identity.test.sh`, `config.test.sh` (RegistryMemo) and the uid-65534 fs-encoding
crash fail on the base without any PR (GX-ENV owns them). Not touched here.

## Branch

The brief names `mod/gx34`; this cloud session's harness designates `claude/gx34-sharded-tier2-design-42tm99` and
forbids pushing elsewhere. One branch, one PR, on the designated branch (decision recorded in the first PR comment).
