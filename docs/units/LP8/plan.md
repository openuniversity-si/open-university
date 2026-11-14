# LP8 plan — Padrão v3: pass-on rule and planner checklist

Scope (plan.md §2 row LP8): `docs/padrao/v3/**` only. Not activated (activation is a planner decision; `coordinator.padrao_version` and `config/registry/coordinator.json` are not touched).

## Audit (cheap evidence)
- Highest merged version on the base: `v1` (v2 is PD2 #669, not merged). `padrao()` in `coordinator_launch.py` requires `manifest.version == padrao_version`, so v3's manifest says `v3`.
- No structural test of `padrao.json` found beyond `test_coordinator_launch.py` (reads the active version only).
- Branch: the session was assigned `claude/padrao-v3-pass-on-rvfy21` by the launcher; the brief names `mod/lp8`. The launcher's branch is used (never push to another branch).

## Commits (critical path ≈ 15 min, all sequential on separate files, no collision edges)
1. Plan: 1 — `docs/units/LP8/plan.md` (this file) and the v1 rule files copied unchanged into `docs/padrao/v3/` (not yet listed anywhere).

3. Plan: 3 — `pass-on.md`, `live-planning.md` and their manifest entries (one commit, both short; the manifest edit is shared).
4. Plan: 4 — `docs/units/LP8/retro.md`.

Premises: P-51. Tests: `test_coordinator_launch.py`, `test_coordinator.py` with v3 present (31 pass); final gate once.
Not activated: `coordinator.padrao_version` and `config/registry/coordinator.json` are untouched. If PD2 merges v2 first, v3 is rebuilt on v2 in a new commit.
