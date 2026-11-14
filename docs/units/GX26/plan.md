# GX-26 plan

Critical path: item 1 (gate_explain.py + test, ~25 min) -> item 2 (gate-dev flag, ~5 min) -> gate (~7 min, script tests) -> retro. Item 3 (docs) is independent of 1-2 (no shared file) and runs in parallel; a mere file-collision edge does not exist (docs vs scripts/lib).

1. `scripts/lib/gate_explain.py` (new): `explain` and `why`, plus `scripts/tests/gate-explain.test.sh` and its covers sidecar. Reuses `gate_policy.select_dev_plan/selection_for/carry_plan`, `gate_script_tests.select_plan`, `gate_test_cache.key/lookup`, `preflight.gate_problems`; never runs a stage, never writes. ETA, completeness and base status degrade to "unknown (GX-25|GX-21|GX-13 not merged)".
2. `scripts/gate-dev`: `--explain` (plan, no run) and `--why [<report dir>]`; a red run prints `why` for its report dir. Flag only.
3. Docs: AGENTS.md (`.gate/logs` -> `.gate/records/reports`, gate-quiet's real plan, `--explain`/`--why`), local-gate.md (one budget D-064 (f), D-065 (5) tier wording, graph's real role per D-A8, new commands), ADR-28/33 notes, train.md GX-06 line, EVENTS.md link to gate-status.md.
4. Covers sidecars for any `uncovered path` and any retired registry key (default none; measured).

Premises (P-46): the base plan code is importable without side effects (blast: item 1); GX-25/21/13 stay unmerged (blast: only the "unknown" lines; none CRITICAL). Nothing touches Neon, Vercel or production.

Tests: item 1 `bash scripts/tests/gate-explain.test.sh`; item 2 same test (flag path); final: pinned `scripts/gate-dev --pr 764`.
Known base defects: none expected.
