# Program censo-no-manifesto: audit

Measured on base `1de1fc2b` (the commands are in `docs/units/CENSO-NO-MANIFESTO/plan.md`):

| Finding | Value |
|---|---|
| Census entries (catalogs + baseline files) | 536 (46 + 490) |
| Units with entries / units | 69 / 107 |
| Entries resolving to no unit / one / two or more | 0 / 536 / 0 |
| Entries held in a file their own unit owns | 0 |
| Area files written by two or more units | 15 of 31; `baseline/scripts.json` has 11 writer units |
| Open PRs touching a census file / `CODEOWNERS` | 16 / 12 of 21 |

What was already there: `scripts/config` as the configuration API, `scripts/generate` with a `generated drift` stage,
the per-unit file pattern of `units/<id>/gate-suite-renames.json` (U1), and the digest chain of
`scripts/lib/audit_chain.py`.

**The constraint that makes this a program.** `structure-check` refuses a PR that touches the units of two lanes
(`lane_errors`, GX-21). The census readers live in two lanes: `engine-structure`, `engine-literals` and
`engine-architecture-check` in the engine lane, and `tooling-literals` (`census-files.ts`, `literal-catalogs.ts`,
`absolute-literals.ts`, `literals-census.ts`) in the tooling lane. The entries cannot move until both lanes read the
records.
