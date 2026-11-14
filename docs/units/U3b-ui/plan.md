# U3b-ui plan (mirrored in the PR description)

Lane `ui-lane`, units `ui-billboard`, `ui-course-card`, `ui-foundation`, `ui-identity`, `ui-lesson-row`, `ui-playback`,
`ui-shell`, `ui-showcase`, `ui-tokens`, `ui-universities` (D-067). Brief: rewrite each cross-unit import in the lane's
own files to its `@ou/<target>/<path under home>` address. No file moves, no renames, no behaviour change.

## Commit plan
1. Audit (`docs/units/U3b-ui/audit.md`) - done, pushed as `8ca624e8`.
2. Plan (this file).
3. Rewrite the imports of `ui-playback` and `ui-shell` files (their cross-unit specifiers only).
4. Rewrite the imports of `ui-showcase` files.
5. Rewrite the imports of `ui-universities`, `ui-billboard` and `ui-course-card` files.
6. Rewrite the imports of `ui-foundation`, `ui-identity`, `ui-lesson-row` and `ui-tokens` files, and record the
   census and the unit batteries in `docs/units/U3b-ui/census.md`.
7. Retro (`docs/units/U3b-ui/retro.md`) before the merge, posted as one PR comment titled RETRO.

Each rewrite commit touches only the files its units own, so the commits are disjoint and each is green on its own:
the rewritten specifier resolves to the same file as before, so tsc and the tests of its files pass unchanged.

## Dependency graph and owned files
`1 -> 2 -> {3, 4, 5, 6} -> 7`. Commits 3-6 own disjoint file sets (a file belongs to one unit, and a unit to one
commit), so they could run in parallel; they run in order here because the mechanical tool is one script and each
commit is small. The change has no shared file, so no sub-agent is needed for the rewrite itself.

| Commit | Files owned (rewritten specifiers only) |
|---|---|
| 3 | `apps/web/src/ui/playback/**`, `apps/web/src/ui/Footer/**`, `apps/web/src/ui/TopNav/**` |
| 4 | `apps/web/src/ui/showcase/**`, `apps/web/src/ui/CreditsList/**`, `apps/web/src/ui/LegalPage/**` |
| 5 | `apps/web/src/ui/Universities/**`, `apps/web/src/ui/CountrySection/**`, `apps/web/src/ui/Billboard/**`, `apps/web/src/ui/Rail/**`, `apps/web/src/ui/LazyPoster/**`, `apps/web/src/ui/CourseCard/**`, `apps/web/src/ui/CoverGlass/**`, `apps/web/src/ui/CourseAbout/**`, `apps/web/src/ui/CourseCardSkeleton/**`, `apps/web/src/ui/PlaylistItem/**`, `apps/web/src/ui/PrimaryCTA/**`, `apps/web/src/ui/HomeIntro/**`, `apps/web/src/ui/HomePortals/**`, `apps/web/src/ui/OverlayLayer/**`, `apps/web/src/ui/EditionSelector/**`, `apps/web/src/ui/EmptyCatalog/**` |
| 6 | `apps/web/src/ui/identity/**`, `apps/web/src/ui/lesson-row/**`, `apps/web/src/ui/tokens/**`, `apps/web/src/ui/icons/**`, `apps/web/src/ui/fonts.ts`, `apps/web/src/ui/*.test.ts` at the ui root, the remaining ui root files |

The per-file list is the tool's output, not this table: the tool rewrites a specifier only when the importing file is
owned by a lane unit, the target unit is not the same, and the target is in the address map.

## Premises
- **P-03** (stable unit addresses; the `@ou/` map is the import path). Radius: high. If wrong, an `@ou/` import
  resolves to a different file: caught by the per-specifier check (the rewritten spec resolves to the same file as before,
  `unit_map.Code.resolve_import`), by tsc and by the tests of the touched files. Not CRITICAL.
- **P-13** (no import crosses a unit by path once the unit has an address). Radius: medium. If wrong, the gate's
  `unit_addresses.check` flags the leftover path import in the next gate run: caught.
- The file form `@ou/<id>/<path>` is the form the merged U3b lanes use; no unit has a bare `@ou/<id>` entry yet (no
  manifest has `contract.entry`). Radius: medium. If wrong (a bare address is wanted), the lane's files would still
  resolve; only the form changes in U4.
- Node-run tooling reads relative specifiers only. Radius: high. Checked: the only lane file reached by a plain node run
  is `apps/web/src/ui/Rail/eager.ts`, which has no cross-unit import. If a later change reaches another lane file from
  a plain node run, `perf:budget` or `tokens:check` fails in the gate, and that file keeps relative specifiers (the
  precedent `3c0ffb84`).
- **CRITICAL: none.** No money, production, secret or source of truth is touched. The branch name follows the
  system-designated branch `claude/u3b-ui-addresses-w6a1su`, not the brief's `mod/u3b-ui-addresses`; the designated
  branch is the one the session may push to (decided and recorded in the PR body).

## Targeted tests per commit, then one final gate
Per rewrite commit: `node_modules/.bin/tsc --noEmit` (baseline 37 s, exit 0), `node_modules/.bin/vitest run --project
unit <the touched test files>`, `scripts/units check`. Census: `vitest list --project unit` before and after, the
line count and a diff of the lists (baseline 1256 lines), recorded in `census.md`. Then `scripts/unit-battery <id>` for
each of the ten units. Then one `gate-dev --pr <N>` on the head.

## Known base defects expected
None seen in the audit scope. Any gate failure is classified (`scripts/lib/gate_classify.py`) before a fix; a failure
that is not from the rewrite is reported in a PR comment.

## D-069 items this PR satisfies
- 1 (one source of truth): the address map is generated from manifests; the PR writes no `@ou/` key by hand.
- 8 (ownership): the rewrite stays inside each file's owning unit (`unit_addresses.check` refuses a foreign target).
