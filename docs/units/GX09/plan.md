# GX-09 plan: gate.passed|failed v4 readers

Readers only (plan-v2 §4). Contracts, lock, generated modules, EVENTS.md (GX-37), `train.py`/`test_train.py` (GX-30) and the producer pin `gate-contracts.gate_*_version` (GX-10) are not touched.

## Commits (dependency graph)

1. `docs/units/GX09/audit.md` (done, 8efa404a).
2. `docs/units/GX09/plan.md` (this file). Depends on 1.
3. Shared accepted-versions source and the three readers. Depends on 2. Files: NEW `scripts/lib/gate_verdicts.py` (`TYPES`, `accepted_versions(kind)` read from `event_contracts.catalog()` of the contracts directory, `is_verdict(event)`, `verdicts(events)`, `accepted(events)`), `scripts/lib/pr_ready.py` (replay only accepted verdicts), `scripts/lib/slo.py` (fold selects verdicts through the helper), `scripts/lib/stall_report.py` (latest verdict through the helper), manifest `units/engine-commit-plan/unit.json` (claims `gate_verdicts.py` and the new test), covers `scripts/tests/covers/{plan-tick,slo,push-guard}.json` (+ `scripts/lib/gate_verdicts.py`), regenerated `CODEOWNERS` (`scripts/generate`). Tests: `scripts/run test plan-tick`, `slo`, `push-guard`.
4. NEW `scripts/tests/test_gate_v4_readers.py` + its invocation line in `scripts/tests/plan-tick.test.sh` (+ covers line for the test and `scripts/lib/train.py`, `scripts/lib/gate_digest.py`, `scripts/lib/stall_report.py`, `scripts/lib/slo.py`). Depends on 3 (imports the helper). Proves: a v3 and a v4 fixture of each verdict round-trip through `event_contracts`/`ForgeEvents` (build → read), are accepted by `gate_verdicts`, by pr.ready (`emit_ready` cites the v4 pass), by `train.queue_entry` (unedited), by `slo.fold` (tier-1 v4 counted, tier-2 v4 not) and by `stall_report.stalls`; an unlocked version (v5 envelope bypassing the read) is refused by the helper. Tests: `scripts/run test plan-tick`, `event-contracts`.
5. RETRO `docs/units/GX09/retro.md` after the pinned gate. Depends on the gate.

Critical path: 2 (3 min) → 3 (15 min) → 4 (15 min) → pinned gate (~wall) → 5 (10 min). No parallel edge: 4 imports 3's helper (a real edge, not a collision); 3 and 4 are each small enough that sub-agents would cost more than they save (decision recorded in the PR).

## Premises

- P-42 (GA-P01, CRITICAL, decided): proof is content-addressed; v4 carries the binding. GX-09 only reads it.
- P-34 forge agnostic (high): readers go through `ForgeEvents`/`event_contracts`, never a forge API.
- Local: "readers accept every locked version" (`event_contracts.py:5`) is the acceptance rule; the helper derives versions from the catalog, so a new locked version needs no reader edit (low).

## Tests and gate

Targeted per commit as above; one pinned `scripts/gate-dev --pr 723` at the end.

## Known base defects expected

KD-335a14a4, KD-71c8e5fe, KD-27b768cb, KD-a3870679, KD-41f822d3 (gate adjudicated); env: claude-session, root-identity, config tests (GX-ENV); forge_events ModuleNotFoundError class (GX-FIX-modules #712).
