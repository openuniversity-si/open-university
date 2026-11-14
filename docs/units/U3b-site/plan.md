# U3b plan: site-lane imports to `@ou` addresses

Premises: P-03 (units stay logical; importers name units by address), P-13. D-067 (1), D-069 items 8 and 11.

## Commits (dependency graph)

Each commit owns a disjoint file set and is green alone (its unit battery passes after it). Commits 3 and 4 touch
different files, so they could run in parallel; they run in order here.

1. Audit: `docs/units/U3b-site/audit.md` (no code). Owns: that file.
2. Plan: `docs/units/U3b-site/plan.md`. Owns: that file.
3. `site-domain`: rewrite the cross-unit specifiers in `apps/web/src/site/domain/**` to `@ou/<unit>/<path>`.
   Owns: `apps/web/src/site/domain/**`.
4. `site-server`: rewrite the cross-unit specifiers in `apps/web/src/site/{application,ports,server,testing}/**`.
   Owns: those four directories. Same-unit imports stay; imports of `site-domain` files become `@ou/site-domain/...`.
5. Retro: `docs/units/U3b-site/retro.md` after the final gate (no code).

## Method

- Rewrites come from one scanner (the audit's `scan.py`), not by hand: it resolves relative, `@/` and `@tower/`
  specifiers, maps the target file through `units.unit_of`, and builds the address from the generated map's home.
- Each rewritten specifier keeps its extension form (`.ts` kept if written, dropped otherwise), so the diff is only the
  specifier text. No file moves, no renames, no behaviour change.
- Gaps (4, see the audit) are left as written and listed in the PR body.

## Tests per commit

- Commit 3 and 4: `scripts/unit-battery site-domain` and `scripts/unit-battery site-server` (types = `tsc` over the
  unit's files, unit tests = the unit's test files). Test census must match the baseline: 28 + 13 for domain, 16 + 4 for server.
- Before the gate: `scripts/units check` (address and ownership) and `scripts/units addresses` (no site path imports
  left except the gaps).

## Final gate

- `OU_CREDENTIALS=network scripts/gate-dev --pr <N>` on the exact head (merge of the base first, never rebase).
  Merge only when green on that head.

## Known base defects

- None expected for these units. The timing-sensitive tests named in the brief are not in these units.
