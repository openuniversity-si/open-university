# GX-23 plan — narrow web stage inputs (fail closed)

Deadline: 120 min from launch (01:27 UTC 28/10 → 03:27 UTC). Effort ≈ opus · 2 h.

## Commits (`Plan: N` trailers)

1. **Audit and access trace** — `docs/units/GX23/audit.md` (skeleton, then findings), `docs/units/GX23/trace.md`. Done: 1ee89cee, 7a1351df, 24885039.
2. **Plan** — this file.
3. **Declared inputs and the narrowed key** — owns `scripts/lib/gate-stage-inputs.json` (new), `config/registry/gate-inputs.json` (new: `gate-inputs.enabled`, `gate-inputs.schema_version`) and its generated modules, `scripts/lib/gate_result_cache.py`, `scripts/tests/test_gate_result_cache.py`, `scripts/tests/covers/gate-result-cache.json` (covers the new files), `units/engine-gate-report/unit.json` + `CODEOWNERS` via `scripts/generate`.
4. **RETRO** — `docs/units/GX23/retro.md`.

Dependency graph: 1 → 2 → 3 → (gate) → 4. Every edge is real (3 needs the trace's read set; 4 needs the gate result). Item 3 is one file set of ~200 lines: the registry key, the declaration and the reader are one consequence and are not useful apart (a registry key whose reader is not shipped, or a declaration nobody reads), so no fan-out; no sub-agents. Critical path ≈ 15 (trace, done) + 10 + 25 + gate (~10) + 15 = ~75 min.

## Design

- `gate_result_cache.declared_inputs(stage)` reads `gate-stage-inputs.json`: `shared_inputs` (probe files at the root and `apps/`) + `stages.<stage>.inputs` (globs) and `stages.<stage>.traced` (the exact paths the trace found). The key of a declared stage digests the files matching the union and adds `gate-inputs.schema_version` and the declared lists as key parts, so editing the declaration or the schema misses.
- `key()` (lint, typecheck) and `stage_key()` (unit, integration) both use it. A stage the file does not list keeps its old key byte for byte (whole tree for lint/typecheck, gate-stages.json `inputs` otherwise). `gate-inputs.enabled` false = every key as before GX-23.
- Fail closed (GA-P10): a missing or malformed file or entry raises `ValueError` → `gate_stage_key` returns '' (the stage runs) and the lint/typecheck key call fails the gate; never a wider hit.
- Declared: lint, typecheck, integration tests. **unit tests stays on `**`**: the trace shows it reads every tracked file and lists the whole tree (`git ls-files -z`), so narrowing it would be a false hit.
- Untouched: `gate-stages.json`, `gate-fixed.sh`, `config/registry/gate.json`, `gate_keys.py`, `gate_report.py`, `gate-local`.
- Rollback: one JSON edit — remove a stage from `gate-stage-inputs.json` (it goes back to `**`), or `gate-inputs.enabled` false.

## Premises

| Premise | Radius | Note |
|---|---|---|
| GA-P10 narrowing fails closed | medium | not in the register (register P-10 is a different premise), stated here, not cited |
| P-20 graph selection tier 1 | low | cited |
| P-46 GA-PG1 pinned gate verdict | high, confirmed | cited |

No CRITICAL premise (no money, production or source-of-truth change).

## Tests

- Item 3: `scripts/run test gate-result-cache` (Python cases: a scripts/docs-only change hits lint/typecheck/unit/integration under a declaration; a declared or traced-but-unglobbed change misses; an undeclared stage keys on the whole tree; flag off = old keys; malformed = error; the shipped file declares the three stages, keeps unit on `**`, and covers the app, lockfile and root probes) and `scripts/run test gate-graph`.
- Final: the pinned `scripts/gate-dev --pr 728` once.

## Known base defects expected (not ours)

KD-335a14a4, KD-71c8e5fe, KD-27b768cb, KD-a3870679, KD-41f822d3 (GX-FIX-modules #712, GX-ENV); env tests `claude-session`, `root-identity`, `config` (GX-ENV); the unit test `no-github-actions.test.ts > merge-phase decides on the local gate` red on the untouched base (trace.md).
