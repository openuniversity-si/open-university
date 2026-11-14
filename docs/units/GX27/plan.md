# GX-27 plan

Premises: P-47 (GA-PG3, CRITICAL, decided). Decision: D-070. Critical path: 3 sequential small commits, ~15 min; all edits are tiny, no fan-out.

- [ ] 1. audit.md (done, with findings)
- [ ] 2. plan.md
- [ ] 3. Flip `merge.tier1_requires_base_merge` default to false in `config/registry/merge.json` (description updated), `scripts/generate`, and adjust `test_commit_check.py` so the case that pins the old default sets the switch on explicitly. Tests: `scripts/run test commit-check`.
- [ ] 4. RETRO `docs/units/GX27/retro.md` after the pinned gate.

Padrão: no "0 behind" line exists in `docs/padrao/v1/*` (see audit); no padrão edit. Rollback: `scripts/config set` or flip the default back (one key).
Known base defects expected: KD-335a14a4, KD-71c8e5fe, KD-27b768cb, KD-a3870679, KD-41f822d3; env failures per brief.
