# GX-37 plan

Critical path: contracts (15 min) → EVENTS rows (same commit, a test binds them) → digest + cases (10 min) → retro. Edges are real; no parallel fan-out is worth it for ~200 lines.

1. [x] Audit and plan documents. Files: `docs/units/GX37/{audit,plan}.md`.
2. [ ] The seven contracts locked, generated modules, EVENTS.md sections and the `env.drift` producer line. Files: `contracts/events/*.json` (6 new; `plan.changed.v1` dropped, LP2 owns it), `schemas.lock.json`, generated py/ts, `docs/process/EVENTS.md`. Test: `scripts/run test event-contracts`.
3. [ ] `gate_digest.input_digest` and its cases. Files: `scripts/lib/gate_digest.py`, `scripts/tests/test_event_contracts.py`.
4. [ ] RETRO. Files: `docs/units/GX37/retro.md`.

Premises: GA-P01=P-42 (high), GA-PG1=P-46 (medium); none CRITICAL. Final gate: base-tip `gate-dev --pr`. Expected base defects: claude-session, root-identity, config (RegistryMemo) script tests (GX-ENV).
