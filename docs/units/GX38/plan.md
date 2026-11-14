# GX-38 plan

Branch `claude/gx38-driver-hooks-uoctn4` (the session designates it; the brief's `mod/gx38` is not used: one branch, one PR).

## Commits (Plan: N trailers)
- [ ] 1 audit.md
- [ ] 2 plan.md
- [ ] 3 hooks: `scripts/lib/gate-hooks/{pin,tier,proof,prereq,plan,exit}.sh` (no-op functions), sourced and called by `scripts/gate-local` at the fixed points, `OU_GATE_BASE_SHA` exported, new case in `scripts/tests/gate-local.test.sh` (each hook once, in order)
- [ ] 4 `scripts/lib/gate-runner.sh` writes `started_at` into `<stage>.stage.json`
- [ ] 5 pre-claims of every new program path in `units/engine-*/unit.json` (not engine-train); CODEOWNERS regenerated once
- [ ] 6 RETRO

## Dependency graph / critical path
3 -> 4 are independent (different files: gate-local+hooks+test vs gate-runner.sh); 5 is independent of both (manifests) but
CODEOWNERS regenerates last. Real edges: none between 3, 4, 5. File collisions: none. Critical path ~25 min
(3: 12, gate: 8 wait, 5: 5). Work is done sequentially by the one session: the diff is small enough that fan-out costs more than it saves.

## Tests / gate
Targeted: `scripts/tests/gate-local.test.sh`, `scripts/tests/gate-report-skips.test.sh`, unit/generate checks. One final
`gate-dev --pr` from a base-tip checkout (verdict of record) plus an own-checkout run (report-only).

## Known base defects
claude-session, root-identity, config (RegistryMemo) script tests: owned by GX-ENV, not touched.

Premises: GA-PG1 (P-46) medium; seam low. Decision: D-070.
