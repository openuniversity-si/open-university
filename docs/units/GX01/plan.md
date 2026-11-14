# GX-01 plan (mirrored in the PR description)

Decision: D-070 (D-027 classes). Premises: P-26 cloud hosts reachable (low), P-42 (GA-P01) and P-46 (GA-PG1) indirectly (the class line feeds the pinned verdict), GA-PG5 "a preflight / per-stage timeout is not a loosening" (low, GA2 auditor; not in the register).
CRITICAL check: a false-positive preflight blocks every gate on a machine. Mitigation: `gate.preflight_enabled` (default true) is the one-key rollback, and a test proves the default probes pass on a healthy container.

## Commits (sequential; one writer per file)
1. `docs/units/GX01/audit.md` (Plan: 1)
2. `docs/units/GX01/plan.md` (Plan: 2)
3. Classes and the machine class line (Plan: 3): `config/registry/gate.json` (`gate.class_line_prefix`), generated module, `scripts/lib/gate_classify.py` (driver abort strings in `ENV`, driver stages, `class_line()`, `abort` command), `scripts/lib/gate-runner.sh:39` prints the class line through the classifier. Tests: `test_gate_classify.py` (`scripts/run test gate-classify`).
4. Gate preflight probe set (Plan: 4): `config/registry/env.json` (`env.gate_preflight_probes`), `config/registry/gate.json` (`gate.preflight_enabled`), generated modules, `scripts/lib/preflight.py` (`gate` command: database, toolchain, browser_libraries; `FAIL env: <gap>`, exit 2). Tests: `test_preflight.py` incl. healthy-container pass (`scripts/run test preflight`).
5. Abort report path (Plan: 5): `scripts/lib/gate_report.py` (an `abort.json` marker: no adjudication, every expected stage missing, one `gate.failed` with the abort stage classed env). Tests: `test_gate_report_skips.py` via `forge_events.MemoryAdapter` (`scripts/run test gate-report-skips`).
6. Driver (Plan: 6): `scripts/gate-local` runs the preflight before the flock, slot and worktree; `driver_abort` prints the FAIL line and the class line and, with `--pr`, publishes through the commit-5 path; the exit trap passes mode and PR. Throwaway-repo tests turn the switch off in their copied registry. Tests: `gate-local.test.sh` (end-to-end abort: exit 2, < 10 s, no lock/slot/worktree), `gate-db`, `invoker-tooling`, `gate-isolation`.
7. `docs/units/GX01/retro.md` (Plan: 7).

Graph: 1 → 2 → {3, 4} → 5 → 6 → 7. 3 and 4 share `gate.json` and the generated gate module, so they run in sequence (one writer).

Final gate: one `scripts/gate-dev --pr N` from a clean base-tip checkout (verdict of record, D-A3) and one from this checkout (report-only).
Known base defects: none expected.
