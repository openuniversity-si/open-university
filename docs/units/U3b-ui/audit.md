# U3b-ui audit: cross-unit imports of the ui-lane to `@ou/` addresses

Read-only findings with evidence (D-067, D-069 items 1, 7, 8). Base `a2c09043` (#576 merged; U3a, U2, T1 and the other
U3b lanes are merged). Counts come from `scripts/units addresses --json` and a dry-run classifier that only reads the
tracked TypeScript files (no test or type-check run).

## What the brief assumes, and what the base says
- **Addresses exist for the ui units.** `unit_addresses.addresses()` gives all ten lane units (`ui-billboard`,
  `ui-course-card`, `ui-foundation`, `ui-identity`, `ui-lesson-row`, `ui-playback`, `ui-shell`, `ui-showcase`,
  `ui-tokens`, `ui-universities`) an `@ou/<id>` and a home. None has a bare `@ou/<id>` entry (no manifest has
  `contract.entry`), so the only importable form is the file form `@ou/<id>/<path under home>`, as the merged U3b
  lanes wrote it (`@ou/site-domain/reader-copy.ts`).
- **`addressable` in `scripts/units addresses` does not mean "has an address".** It is `address and no path importer
  left` (`unit_addresses.scan`). All ten ui units are `addressable: false` today only because they still have
  path importers. This is the expected state before this PR, not a blocker.
- **Every target of a lane import has an address.** Of the 25 target units the lane imports, all 25 are in the map
  (`found`). No import has to wait for a unit move (U4).

## Inventory (dry run over the lane's tracked `.ts/.tsx/.mts/.js` files)
| Class | Count | Meaning |
|---|---|---|
| REWRITE | 148 | cross-unit import in a lane file, target has an address: `@/…` (136), relative (11), `@tower/playback-engine` (1) |
| same-unit | 85 | imports inside one unit: kept as written (brief) |
| unresolved | 122 | npm packages and `node:` built-ins (`react`, `next/link`, `vitest`, `node:fs`): not units, not touched |
| already `@ou/` | 0 | none yet |
| target-unaddressed | 0 | no blocker |
| node-native-keep | 0 | see below; no lane import is reached by a plain `node` run |

- 148 rows in 52 files; target units: 25 (`catalog-application`, `catalog-compile`, `catalog-hierarchy`,
  `config-documents`, `config-theme`, `identity`, `kernel-ids`, `kernel-protocol`, `media-domain`, `playback-client`,
  `playback-domain`, `progress`, `release-domain`, `site-domain`, `site-text`, `testing-support`, `tooling-brand`, and
  the ui units `ui-billboard`, `ui-course-card`, `ui-foundation`, `ui-identity`, `ui-lesson-row`, `ui-shell`,
  `ui-showcase`, `ui-universities`).
- `vi.mock("@/…")` or `vi.mock("./…")` calls in the lane: 0. Only `import`, `export … from`, `import()` and
  `require()` specifiers are rewritten.
- `new URL("../../src/ui/…", import.meta.url)` in tests is not an import and stays as written.

## Node-run constraint (D-069 item 7, precedent `3c0ffb84`)
Plain `node <file>.ts` loads TypeScript natively and cannot read the tsconfig `paths` map. The `package.json` scripts
that run this way are `tokens:generate`, `perf:budget`, `bundle:check`, `verify:no-video`, `db:*`, `catalog:bake`
(postinstall) and `fidelity/*`. Their import closure (relative specifiers only) reaches one lane file:
`apps/web/src/ui/Rail/eager.ts` (ui-billboard, reached from `scripts/lib/perf-budget.ts`). `eager.ts` has no cross-unit
import, so nothing in it changes. Every other rewrite is in a file the browser, Next or vitest loads, which all honour
the `@ou/` paths.

## Existing mechanisms (reused, not duplicated)
- Address map: `scripts/generate addresses` writes `paths` into `apps/web/tsconfig.json` (`@ou/<id>/*` →
  `./src/…`); tsc, Next and vitest read it. `scripts/lib/unit_addresses.py` already has `resolve`, `check` and `scan`.
- Import check: `unit_addresses.check` refuses an `@ou/` import that names another unit's file or an unknown unit, so a
  wrong target in this PR fails the gate instead of going unnoticed.
- No new function is needed; the rewrite is a textual change of the specifier with the same resolved file.

## Known risks and how the plan answers them
- A rewrite that resolves to a different file would break behaviour silently: mitigated by checking every rewritten
  specifier resolves (via `unit_map.Code.resolve_import`) to the same file as before, and by tsc and the test census.
- Extension form: specifiers keep their written tail (`.ts`, `.tsx`, `.css`, none), so the expansion of `@/…` and
  of `./…` is preserved exactly. The `@tower/playback-engine` exact alias names one file, so its address names the file
  with its extension.
- Base defects not caused by this PR: none seen in the audit scope; any failure found in the gate is classified first
  (`scripts/lib/gate_classify.py`).

## Census before and after (the brief's required evidence)
Recorded in the PR body from the runs in `plan.md`. The baseline type-check is taken on the base before any edit.
