# GX-38 audit (read-only)

Base `4bc4dd04` (mod/roadmap-integration). Sources: plan-v2 §3/§5.2 (origin/mod/ga4 bce2cd94), plan.md (GA3).

## Findings
- `scripts/gate-local` (457 lines) has the fixed points the row names: preflight block (`:107-114`) then lock; argument
  parsing loop (`:34-50`); `baseRefOid` read from `pr view` (`:139-146`, or the batch `base` from the plan file `:136-138`);
  scripts/prerequisite stages launched at `:277-285`; plan source (classify / batch plan, `:314-333`); exit trap `finish` (`:156-167`).
- `scripts/lib/gate-runner.sh` `step()` writes `<stage>.stage.json` with name/result/exit/seconds; no `started_at` yet.
- GX-05 (#697) edits the preflight/pin re-exec region and `units/engine-gate-run/unit.json`; this PR only inserts the `pin` call
  after the preflight and keeps everything else in that region untouched.
- Unit ownership (`unit_check.ownership`): only *production* files need an owner and a path claimed by two units is an error;
  a glob/path matching no tracked file is a warning. `config/registry/*.json`, `contracts/events/*`, `docs/**` (outside
  `docs/programs/**`) are owned by no unit today; `scripts/lib/generated/**` is `engine-config`, `scripts/merge-phase`
  `engine-delivery`. `scripts/lib/merge_behind.py`, `gate_pin.py`, `gate-pin.json` are GX-05/GX-22 files (GX-05 edits the
  gate-run manifest itself) and are not pre-claimed here.
- Registry: nothing in this unit reads or adds a key (D-B9).

## Premises
GA-PG1 (pinned gate) medium; behaviour-preserving seam low. No CRITICAL premise.
