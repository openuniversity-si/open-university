# U3b media: plan

Lane `media-lane` owns `media-application`, `media-domain` and `media-server`. The change rewrites each cross-unit
import in the lane's own files to `@ou/<unit>/<path under home>` (the form already merged by the other U3b lanes,
`@ou/<unit>/<file>.ts`). No file moves, no rename, no behaviour change. Same-unit imports stay relative.

## Commits (dependency graph)

```
1 audit + plan (docs only)
  └─ 2 media-domain imports   (files: src/media/client/**, src/media/domain/**)
  └─ 3 media-application imports (files: src/media/application/**, ports/**, testing/**)
  └─ 4 media-server imports   (files: src/media/server/**)
       └─ 5 retro (docs only, after the final gate)
```

- 2, 3 and 4 own disjoint file sets (P-13): no file is owned by two of them, so they could run in parallel. They are
  committed in sequence on one branch for a clean history, and each one is green on its own: a unit's rewrite resolves
  only through the address map (U3a) and the target units' files, which no commit changes.
- 1 is first (the PR body is the mirror of this file).
- The generated address map (`apps/web/tsconfig.json` `@ou/` keys) is NOT touched: it is generated from the manifests,
  and no manifest changes in this PR.

## Per commit

| # | Files | Rewrite | Targeted check (after the commit) |
|---|---|---|---|
| 2 | 26 files of media-domain (the client and domain files, incl. 9 test files) | 32 imports | `scripts/unit-battery media-domain` |
| 3 | 13 files of media-application (application, ports, testing) | 58 imports | `scripts/unit-battery media-application` |
| 4 | 29 files of media-server | 76 imports | `scripts/unit-battery media-server` |

Each rewrite is a string replacement of the import specifier only, from the scan of the lane's files (audit.md). The
four imports that have no address (audit.md) stay relative and are listed in the PR body as contract gaps for U4 of
their owner units.

## Premises and blast radius

| Premise | Radius | If it is wrong |
|---|---|---|
| P-03: a unit is imported by its address | high | A rewritten import resolves to the wrong file; `scripts/units check` and the type-check fail, which the battery shows before the push. |
| P-13: no two lanes edit the same file | medium | A file owned by another lane would conflict; the scan confirms each touched file is owned by a media unit (`scripts/units owner`). |
| `@ou/` resolution in vitest (derived from tsconfig `paths`, U3a) | medium | A test importing `@ou/...` fails to resolve; the unit's tests show it (battery tier 1). |

No premise here is CRITICAL: nothing touches production, money, secrets or the source of truth.

## Tests and the final gate

- Targeted: the unit battery of each unit after its commit (`scripts/unit-battery <id>`).
- Census (before and after, recorded in the PR body): types files per unit (14, 26, 29 at base), unit-test files per unit
  (4, 9, 11 at base) and the vitest census of the lane's test files (82 tests in 23 files at base).
- Final: `scripts/gate-dev --pr <N>` on the exact head.

## Known base defects expected

None expected in the lane. The timing-sensitive tests named by the brief (tower-catalog cover concurrency, read-latency)
are outside the lane; they are not touched and not re-run by hand.
