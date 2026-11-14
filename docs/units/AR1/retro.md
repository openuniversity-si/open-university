# AR1 retro: `database` gate area by import graph

PR #671, branch `mod/ar1`, base `mod/roadmap-integration`. Times UTC, 2026-10-27.

## 1. Brief quality

- Wrong premise: "none of [#607's 15 admin files] imports the db layer". Two do: `admin/server/deps.ts`
  (`platform/db/{security,admin,catalog}`) and `admin/server/http-dispatcher-next.test.ts` (`platform/db/security`).
  Under the brief's own rule (b) #607 stays `db=1`. The test asserts the 2/13 split instead of the brief's 0/15.
- Branch conflict: the session's designated branch was `claude/ar1-pf9x87`; the brief said `mod/<unit>`. The brief's
  explicit rule was followed (`mod/ar1`).
- Missing: the brief named the files AR1 owns but `plan_for` had no access to file contents, so the rule could not be
  computed without touching a reader (`gate_policy.py`, 4 lines). A brief for a rule that needs content should name
  the call site that has the revision.
- Missing: the registry owner file. `config/registry/gate.json` is in KF3's diff, so a new owner `gate-areas` was made.
- `apps/web/src/catalog/server/table-io.ts`, listed in the area, no longer exists.

## 2. Audit and plan

- Premises held: the db layer is `src/platform/db/**`, `drizzle/**` and the db packages (the coverage test with an
  independent regex found no importer outside the rule); `classify_pr` fetches base and head before reading.
- Plan unchanged in shape (6 items, serial). One design choice added during execution: the fail-closed fallback to the
  former globs when content, tsconfig or registry is unreadable. It keeps the rule never looser than the base and kept
  the reader tests (`test_gate_split`, `test_gate_plan`, fake revisions) green without editing them.
- No sub-agents: the graph was serial (each commit used the previous one's files) and the deadline was 57 minutes
  from launch. Sub-agent fan-out would have cost context hand-offs with nothing to parallelise.

## 3. Execution

| time | event |
|---|---|
| 13:32 | launch; base `efc7f3b4` |
| 13:5x | audit `95daed78`, plan `3a58acb8`, draft PR #671, registry `38cce4e9` |
| ~14:00 | import rule `fba1e4d3`; classifier at head `3943619e` |
| 14:09 | STATUS comment; gate run 1 on `3943619e` |
| 14:15 | base merged `599a0e17` (merge commit); retro committed; gate run 2 on the final head |

Failures and classes:

- Registry commit `38cce4e9` pushed without its generated types (`scripts/generate python-types`). Found by
  `test_generate` before commit 4, fixed in commit 4. Class: a new registry owner needs generated types. Lesson 1.
- Literal census: `match.group(2)` and a test count `50` were flagged as unregistered numbers. Fixed with a named group
  and a structural assertion. Class: integers in engine code. Already covered by LT1; no new rule.
- Coverage test false positive: a string fixture in `apps/web/scripts/lib/intent-tables.test.ts` looks like a db
  import. Listed as `NOT_AN_IMPORT` with its reason (1 entry).
- Gate run 1: structure check failed on (a) the PR body `Premises:` line, which held prose after `none` and was
  parsed as ids, and (b) the head being 6 commits behind the moved base. Fixed by a bare `Premises: none` line and a
  merge commit. Class (a): a free-text tail on a trailer line. Lesson 2.

## 4. Gate

- Run 1 (`3943619e`): FAIL structure check (premises line, behind base). Stopped once the cause was known. DB
  classification of this PR: `db=0`.
- Run 2: on the final head; result in the RETRO comment and the MERGE-READY comment.
- GX-24 resume (27/10): the base moved 49 commits; merged it (clean, no conflict). Verdict of record is
  `scripts/gate-dev --pr 671` from a clean checkout of the base tip (D-070, D-A3); the own-checkout run is
  report-only. Numbers are in the MERGE-READY comment.
- Known base defect: `scripts/tests/gate-db.test.sh` fails 7/22 on the base too (`ModuleNotFoundError: gate_select`,
  the fixture's copy list misses it). Owner: HD1.

## 5. Lessons

1. A new `config/registry/<owner>.json` must ship with `scripts/generate python-types` in the same commit. Change:
   the local push check could run `generate.drift` when a registry file is in the push (owner: local-checks registry).
2. Trailer lines are parsed to the end of the line. Change: the PR template should say "`Premises: none` alone on its
   line, explanation on another line" (owner: brief template / PD2).
3. Briefs that cite evidence ("none imports X") should include the command that proves it, so the audit checks it in
   seconds (owner: brief template).
4. #607 needs a decision from its own session: it edits import lines of a db importer, so gate-db is correct for it
   under this rule (owner: #607's session).
5. (GX-24) The first AR1 rule was open on one side: a file whose import the classifier could not resolve (computed
   `import(x)`, template specifier, a path leaving the repo) was judged not-database, while an unreadable file was
   judged by the old globs. Class: an undecidable input must keep the gate (fail closed). Fix: such a file stays in
   the database area (`DbImports._is_db`/`_DYNAMIC` in `gate_areas.py`), test
   `test_ar1_an_unresolvable_import_keeps_the_database_area`. Cost on this checkout: 2 more files select gate-db
   (100 vs 98 of `apps/web`). No new config key. Owner of later changes: GX-18.
