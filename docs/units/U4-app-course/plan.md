# U4 app-course plan (mirrored in the PR description)

## Commit plan
1. Audit (`docs/units/U4-app-course/audit.md`).
2. Plan (this file).
3. Addresses: every `@/` import in the unit becomes `@ou/app-course/...` or `@ou/ui-playback/...`; no behavior change.
4. Literals: the unit's own `c/vocabulary.ts` (D-063 catalog) for route, markup and ARIA words; the unit's rows leave the absolute-literals baseline.
5. Contract and battery: manifest `contract` (entry = the surface other units import today, v1.0.0) and `battery`; regenerate aggregates (`scripts/generate`).
6. Retro (`docs/units/U4-app-course/retro.md`) after the final gate.

## Dependency graph and owned files
`1 -> 2 -> 3 -> 4 -> 5 -> 6`. 3 and 4 both edit the same `view.tsx` files, so they run in sequence; 5 touches only the manifest and generated outputs.
Execution is done by the coordinator directly: the unit is 14 files, sub-agents would cost more than they save.

| Commit | Files owned |
|---|---|
| 3 | `apps/web/src/app/signed-in-c/**`, `apps/web/src/app/c/[courseSlug]/[lessonSlug]/view.tsx` |
| 4 | `apps/web/src/app/c/**` (views, layouts, `vocabulary.ts`), `scripts/lib/literal-catalogs/app.json`, `scripts/lib/absolute-literals-baseline/app.json` |
| 5 | `units/app-course/unit.json`, generated outputs |

## Scope decisions
- **No physical move** (S1 / P-03: units stay logical; App Router routes must stay under `src/app`). The address `@ou/app-course/*` stays the seam.
- **No `text.*` entries**: the unit writes no locale text (audit finding 5).
- **Next route segment config** (`dynamic`, `dynamicParams`, `revalidate`) stays a statically analyzable literal; the baseline rows for it stay and are named in the PR (Next requires them).
- `.css` rows of the baseline stay (this PR must not touch `.css`).

## Premises
Premises: P-03, P-04, P-05, P-07.
- P-03 (high, validated): units are logical. If wrong, the move to packages changes only the generated address map.
- P-05 (high): literals migrate with the unit. If wrong, the baseline rows reappear for the next lane.
- P-07 (high): contract changes expand->contract; 1.0.0 is the first version, nothing to break.
- **CRITICAL**: none (no production, money or source of truth).
- (medium) The only consumer is `CatalogLoading`; a missed consumer shows as a type or structure-check error, not a silent break.

## Targeted tests, then one final gate
3: `tsc`, `scripts/unit-battery app-course`, tests that read these files as text (`lesson-figure`, `lesson-stage`, `screen-measures`, `course-opening`, `progress-reading`, `home-routing`).
4: absolute-literals and literal-catalogs tests, `scripts/structure-check`. 5: `scripts/units check`, `scripts/generate --check`, `scripts/schema-compat`.
Then one `gate-dev`.

## Known base defects expected
Timing-sensitive tests on 4 vCPU (tower-catalog cover concurrency, read-latency); not touched, owner: catalog lane.
