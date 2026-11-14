# web-build plan (mirrored in the PR description)

Premises: P-03 (high: the files cannot leave `apps/web`; if wrong the move is a later mechanical PR), P-04 (size under the ceiling, low), P-05 (zero literals verified, low), P-07 (no contract change; none can be published until the unit has its own directory, medium).

Commits:
1. `docs/units/web-build/audit.md`, `plan.md`: audit findings and this plan.
2. `docs/units/web-build/retro.md` after the final gate.

Targeted tests: `scripts/unit-battery web-build`, `scripts/generate --check`, `scripts/structure-check`. One final `scripts/gate-dev --pr N`.
D-069 items: 3 (zero literals, allowlist empty), 5 (no generated output changes; drift check green), 8 (ownership untouched), 14 (battery under the limit, never loosened).
