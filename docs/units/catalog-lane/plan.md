# U3b catalog lane: plan

Mechanical: rewrite every import that crosses a unit boundary in the lane's files to `@ou/<target-unit>/<path>`
(U3a's generated map). No file moves, no renames, no behaviour change. Evidence: [audit.md](audit.md).

## Commits (a dependency graph; no file is owned by two commits)

Every commit touches only files of its own units, so the commits do not depend on each other and any order is
valid; the order below is the review order (domain first, then application, then server).

| # | Plan item | Files owned | Depends on | Targeted tests |
|---|---|---|---|---|
| 1 | Audit and plan documents | `docs/units/catalog-lane/audit.md`, `plan.md` | none | none (docs) |
| 2 | Domain layer imports to addresses: catalog-hierarchy, catalog-rules, catalog-schema, catalog-batch, catalog-compile | 53 files of those units | 1 | `scripts/unit-battery` for each of the five |
| 3 | Application and core imports to addresses: catalog-application, catalog-server-core | 32 files | 1 | `scripts/unit-battery` for both |
| 4 | Server imports to addresses: catalog-authoring-server, catalog-ship-server, catalog-release-server | 23 files | 1 | `scripts/unit-battery` for the three |
| 5 | Census record: baseline and after, per unit (type-check and test counts), docs only | `docs/units/catalog-lane/census.md` | 2, 3, 4 | the same batteries, read back |

Parallel: 2, 3 and 4 are independent (disjoint file sets) and may run in parallel; this session runs them in
sequence because the rewrite is one scripted pass with one checker.

## Premises and blast radius

| Premise | Radius | What breaks if it is wrong |
|---|---|---|
| P-03: `@ou/<id>/<path>` resolves to the file under the unit's home | high | every rewritten import fails tsc; `scripts/units check` names it. Caught by the unit batteries before each push. |
| P-13: one owner per file | medium | a rewritten file owned by another lane would collide; checked by `scripts/units owner` before commit 2. |
| P-05 / P-07: no contract changes | low | a changed export would show in tsc; none is changed here. |

No premise is CRITICAL (no spend, no production, no source-of-truth change).

## Checks per commit

- The unit batteries of the commit's units (tier 1, `scripts/unit-battery <id>`).
- Before the first push of commit 2: `scripts/units check`.
- Final: one gate-dev on the head (`scripts/gate-dev --pr <n>`).

## Known base defects expected

None known for these units. Timing-sensitive tests named in the brief (tower-catalog cover concurrency, read latency)
are not changed; if only they fail, the gate is re-run after the base merge, per the brief.

## Census

Baseline per unit (`scripts/unit-battery <id> --json`, untouched base) and the same after commits 2 to 4 go into
`census.md` (commit 5). Identical type-check output and test census is the acceptance check.
