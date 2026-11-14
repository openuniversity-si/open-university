# AR1 plan: the `database` area by import graph

Deadline: green on the exact head and 0 behind base by 14:30 UTC 2026-10-27 (11:30 BRT); merged by 15:00 UTC.
Decisions cited: D-065 (gate tiers, Neon gate-db is evidence for database changes), D-068 (no literals: the import
roots are registry keys), D-069 item 9 (fix the class: a rule, not a per-PR exception).

## Rule

A path is in the `database` area iff (a) it matches the kept schema, migration, Neon and database-script globs of
`gate-areas.json`, or (b) it is a source file under `gate-areas.db_import_scope` whose static imports (`from`,
`import`, `import()`, `require()`) resolve, through relative paths or the tsconfig `paths` aliases, into
`gate-areas.db_import_roots` or `gate-areas.db_adapter_modules`, or name a package of `gate-areas.db_import_packages`.
Content is read at the PR head (base for a deleted file) by `gate_policy`, the working tree otherwise. A file that
cannot be read falls back to the former directory globs (`gate-areas.db_unreadable_fallback`), and an unreadable
registry or tsconfig keeps every in-scope file `database` (fail closed, never loosened).

## Commits (dependency graph)

| # | Item | Files | Depends on |
|---|---|---|---|
| 1 | audit | `docs/units/AR1/audit.md` | none |
| 2 | this plan | `docs/units/AR1/plan.md` | 1 |
| 3 | registry keys | `config/registry/gate-areas.json` | 2 |
| 4 | import rule, narrowed area, tests (zero coverage loss, #607 files) | `scripts/lib/gate_areas.py`, `scripts/lib/gate-areas.json`, `scripts/tests/test_gate_areas.py` | 3 |
| 5 | classifier reads the PR head | `scripts/lib/gate_policy.py`, `scripts/tests/test_gate_areas.py` | 4 |
| 6 | retro | `docs/units/AR1/retro.md` | gate |

Serial: each commit uses the previous one's files; there is no independent pair worth a sub-agent under the deadline.

## Premises and radius

- The db layer is `src/platform/db/**`, `drizzle/**` and the db packages (validated by the audit grep; medium: a missed
  root under-selects gate-db). Guarded by the coverage test, which uses an independent regex.
- `gate_policy` can read `head:path` in the subject root (validated: `classify_pr` fetches base and head first).
- None CRITICAL: no money, production or source-of-truth change.

## Tests

- Commit 3: `python3 scripts/lib/config.py check` equivalent through `scripts/tests/test_config.py`.
- Commits 4-5: `python3 scripts/tests/test_gate_areas.py`, `test_gate_plan.py`, `test_gate_split.py`.
- Final: one `scripts/gate-dev --pr <n>` on the exact head.

## Known base defects

- PR #607 keeps `db=1`: `admin/server/deps.ts` and `admin/server/http-dispatcher-next.test.ts` import the db layer
  (audit). Owner: #607's session, not this unit.
