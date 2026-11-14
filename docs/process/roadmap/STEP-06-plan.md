# Step 6 plan: literals and the absolute gate

Target: every value in the production and tooling code of `apps/web` (strings, numbers, booleans, UI text, even `0`,
`1` and `true`) is read from a key of a declared, documented catalog, and the absolute gate is on: the census must
equal a recorded exception list, and that list may only shrink until it is empty. No visual change: rendered pixels,
responses and rows stay the same; every PR is a behavior-preserving refactor. Root causes and counts:
[STEP-06-audit.md](STEP-06-audit.md).

Every PR branches from `origin/mod/roadmap-integration`, targets it, has 3–8 commits, stays under the B5 size budget
(≤ ~600 changed lines without tests and generated files), and ends with `Capability: CAP-011` and
`Fit-Review: not reviewed (Daniel 2026-10-25: no review step)` (D-055). Each reduction PR states the census before and
after for its area and shrinks its area's `absolute-literals-baseline/<area>.json` by exactly the literals it removed
(`pnpm literals:census --write <area>`). No PR in this step touches the database shape or production data.

**Parallel fronts (D-064 a).** No front edits a shared control file: a front writes only its own area's exception list
(`scripts/lib/absolute-literals-baseline/<area>.json`) and its own area's catalog manifest
(`scripts/lib/literal-catalogs/<area>.json`); no total is stored anywhere, the census computes it. A front does not
edit `STATUS.md` or this plan: integration records each merged front there. A front that needs a value of 2+ areas reads
it from the common catalog in `apps/web/src/kernel/` (D-064 c); a catalog file the manifest declares counts toward no
context's size budget nor B5 (D-064, amended).

## Target (D-063)

### The reading

`apps/web/scripts/lib/absolute-literals.ts` reads the TypeScript AST (the compiler `apps/web` already has), not
characters. Each offender carries its file, line, kind (`string`, `number`, `boolean`, `regex`) and role (type, key,
JSX attribute, JSX text, schema argument, comparison, bare value, number in string, sheet, other). Scope: every
production file of `apps/web`: `src/` (`proxy.ts` is `src/proxy.ts`), `next.config.ts`, `scripts/` and `fidelity/`
(`*.test.ts`, `*.int.test.ts`, `*.test-helpers.ts`, `testing/`, snapshots, `e2e/` and `test/` are tests and stay out).
`pnpm literals:census` prints the totals by area and role, which each PR body quotes; `--list [area]` prints each
offender with its line (done, PR 6.2).

What is not an offender is a closed list, the D-050 structural exceptions plus nothing new: an import or export
specifier, a `"use client"` / `"use server"` directive, a `var(--…)` reference, a `@media` / `@supports` length that is
exactly a catalog value, a CSS attribute selector that repeats a catalog phrase, a DOM key name compared with `key`,
SQL text in the database package, and `LIMIT 1`.

### The catalog manifest

`scripts/lib/literal-catalogs/<area>.json` (one file per census area, D-064 a) lists every catalog file: its path, its domain and one sentence on what it holds,
and `generatedFrom` for a generated file (`config/domain/theme/names.ts` ← `design/figma-tokens.snapshot.json`).
`ABSOLUTE_CATALOGS` and the D-050 path constants are read from it. Rules (test, no baseline):

| Rule | Fails when |
|---|---|
| catalog exists | a listed path is missing |
| catalog is data | a catalog holds a function, method or arrow body, or a statement other than declarations and imports (a catalog cannot hide logic) |
| catalog is documented | an exported declaration has no doc comment, or a key of an exported object has none (generated files: the generator writes them) |
| key is a meaning | a key's name is only its value or a synonym of it (`zero`, `one`, `true`, `false`, `yes`, `no`, `emptyString`, `none`) |

### The domains (amends D-050)

D-050's eight domains stay. D-063 adds the domains the audit found without a home (F4):

| Domain | Catalog | Holds |
|---|---|---|
| protocol | `kernel/protocol.ts` | HTTP methods, header names, MIME types, status codes, cookie attributes, URL schemes |
| storage | `platform/db/schema.ts`, a schema catalog (declared through its builders: Drizzle and the schema's check builders), and a kernel table-name catalog the schema and the domain rings both read (6.6b) | table, column, index, constraint and sequence names, column options, checks; the translators' SQL is template text; intents' `db.reads` / `db.writes` read the table names (6.6b) |
| intents | the eleven `*/domain/intents.ts` registries | intent ids, citations, meanings (they are already data) |
| context vocabulary | `<context>/domain/vocabulary.ts` | kinds, states, error codes, discriminants of one context; a literal type derives from it (`(typeof KINDS)[keyof typeof KINDS]`) |
| markup | `ui/markup.ts` | ARIA roles, button types, `data-*` words, image `sizes` |
| sheet | the theme (D-052 slots) | every sheet value that is not yet an identity value, including `0`, `100%` and grid lines |
| extent | `kernel/extent.ts` | empty, first, the floor of one, and other counting keys named for their job |

Cures that are not a new key: a predicate returns its expression instead of `if (…) return true`; a loop over indexes
becomes `for … of` or an array method; a literal type becomes a type derived from its catalog. A renamed literal
(`const ZERO = 0`) is blanking and fails "key is a meaning".

### The ratchet (fixes F1)

`ABSOLUTE_GATE = true`. `scripts/lib/absolute-literals-baseline/<area>.json` (the exception list, one file per census
area since D-064 a; the `-baseline` name keeps it out of the D-008 size budget like the repository's other generated
baselines) holds, per file, each remaining
offender value and its count, written by `pnpm literals:census --write`. The unit test fails when the census differs
from the list in either direction: a new literal fails with its file and line, and a removed literal fails until its
entry is deleted. `structure-check` (with `--base`, which the gate passes) fails when a value appears that the base's
list does not have, or is allowed more times across all files: the list only shrinks. The comparison is per value over
all files, not per file, so a file can move or be renamed with its literals (steps 7 and 8 move files) but no literal
can be added. Growing it needs a D-NNN decision. The step closes when the list is empty (done, PR 6.4).

## PRs

| PR | What | Root cause it closes | Enforcement added |
|---|---|---|---|
| 6.1 | This audit and plan, D-063, CAP-011 | — | D-063 entry (`test pending`) |
| 6.2 | The reading on the AST with line and role; scope `src/`, `next.config.ts`, `scripts/`, `fidelity/`; `pnpm literals:census` (done, #470): `src/` 11,802 → 12,218 on the new reading (strings on export lines and JSX text now count; regex digits and quoted `true` no longer double-count), all of `apps/web` 20,546 | F3 | the reading's tests (regex, JSX text, template booleans, roles, scope, census table) |
| 6.3 | The catalog manifest and its four rules; `ABSOLUTE_CATALOGS` and the D-050 lists read from it; the theme name table, `kernel/intents.ts` and nine intents registries declared; `fill` and the catalog field words (now `kernel/catalog-fields.ts`) leave the catalogs; `EXTENT.one` → `EXTENT.floor` (done, #471): `src/` 12,218 → 9,210, all 20,546 → 17,570. `config/domain/intents.ts` builds its routes with functions and waits for 6.14 | F2 | the catalog rules (`literal-catalogs.test.ts`) |
| 6.4 | The gate on: `ABSOLUTE_GATE = true`, `absolute-literals-baseline.json` equal to the census (17,587 offenders), `structure-check` shrink-only against the base per value; the "door stays off" test deleted (done, #473) | F1 | the exact-list test (`absolute-literals.test.ts`); `check_absolute_baseline` in `scripts/lib/structure.py` and `test_d063_refuses_an_absolute_exception_list_that_grows_against_the_base` |
| 6.5 | Protocol (done, #474): `kernel/protocol.ts` (`HTTP_METHOD`, `HTTP_HEADER`, `MEDIA_TYPE`, `HTTP_STATUS`); methods, headers, media types and statuses in `src/` and `next.config.ts` read it, outside the catalog context; the five header aliases deleted; client kernel modules may read a kernel catalog (`L1.kernel-pure`) and the site routing domain may read the kernel (`L2.site-route-domain`); 17,587 → 17,261 | F4 | the census: protocol words left in `src/` are the catalog context's 201 answers (6.16) |
| 6.6a | Storage, the schema (done, #475): `schema.ts` is the storage catalog, a new catalog form names its builder modules (calls into them and expression callbacks only); its one function moves to the media translator; 40 doc comments; 17,261 → 16,630 | F4 | the schema catalog rule (`literal-catalogs.test.ts`) |
| 6.6b | Storage, table names outside the schema (#476): the kernel table-name catalog `kernel/tables.ts` that `schema.ts`, the database translators, the intents registries, the Better Auth rate-limit model and the media migration tooling read (the catalog context's share waits for 6.16), and the checker's `pgTable(…)` readers follow it; 16,628 → 16,503 on its own commits (61 removed) | F4 | no table name spelled outside the two catalogs, except the catalog context's (6.16) |
| 6.6c | Storage, the translators' remaining literals (`media/records.ts`, `catalog/table-io.ts`, `admin/jobs.ts`, `operations/*`, …) | F4, F5 | the census for `platform/db/` outside the schema is 0 |
| 6.7 | `kernel` and `proxy.ts`: extent keys for every `0` and `1` with that job; the 82 `.length === 0` lines read `EXTENT.empty`, and the extent gate checks every site, not `EXTENT_CALLS` | F5 | the extent rule without a call list |
| 6.8 | `identity`: the rate-limit ceilings into `LIMITS`; Better Auth options read the identity vocabulary | F5, F7 | the census for `identity/` is 0 |
| 6.9a | `progress` (#477): the context vocabulary `progress/domain/vocabulary.ts`, the runtime type-name catalog `kernel/javascript.ts` and `FETCH_CREDENTIALS` in `kernel/protocol.ts`; the domain, viewer, client and handler read them; 16,628 → 16,564 | F4, F5 | 0 for `progress/` |
| 6.9b | `playback` (#479): the context vocabulary `playback/domain/vocabulary.ts`, `kernel/browser.ts` (lifecycle events, visibility, DOM elements) and `URL_SCHEME` in `kernel/protocol.ts`; the player's copy in the reader copy; 16,564 → 16,340 | F4, F5 | 0 for `playback/` |
| 6.10 | `release` | F4, F5 | 0 |
| 6.11 | `site` | F4, F5 | 0 |
| 6.12 | `factory`, including the 51 schema arguments | F4, F7 | 0 |
| 6.13a–b | `media` (about 520 outside the registry) | F4, F5, F7 | 0 |
| 6.14 | `config` outside the generated names | F4 | 0 |
| 6.15a–c | `admin`: route specs, catalog routes, lifecycle and job handlers | F4, F5 | 0 |
| 6.16a–e | `catalog` (about 2,300 outside the registry): contracts and request schemas, rules, the compiler, the server modules, `lesson-address.ts` | F4, F5, F7 | 0 |
| 6.17a–c | Sheets: every CSS module value into a theme slot (D-052); pixels proven by the fidelity and screen-measure reports | F6 | the sheet rule extended to every value; 0 for `.css` |
| 6.18a–b | Markup and text in `ui/` and `app/`: `ui/markup.ts`, the reader catalog for words, numbers in strings | F6 | 0 for `ui/` and `app/` |
| 6.19a–e | Tooling: `apps/web/scripts` (6,577) and `apps/web/fidelity` (2,343) | F3 | 0 for tooling |
| 6.20 | Close: the exception list empty, D-063 proven, CAP-011 done, the step's metrics | — | the list is `{}` and the shrink rule keeps it so |

**Open item for 6.16 (found in 6.5).** The catalog context has a shrink-only line budget (D-060, `L3.context-size`, 9,076
lines after 6.5). Moving a literal to a catalog key keeps the line count, but the file gains an import line, so a
catalog PR grows the context and fails the budget. 6.5 left the catalog's 201 answers in place for that reason. 6.16
must either free the lines in the same PR (dead code, shorter structure) or ask for a decision on how a budget counts
import lines; it does not raise the override silently.

**Open item for the ratchet (found in 6.6a).** The shrink rule compares counts per value over all files, so a file can
move with its literals. The same tolerance lets a PR add a literal in one file while it removes the same value from
another; 6.6a's own checker code did that with a `true` and a `false`, caught only by reading the list's diff. Each PR
compares its tooling and production entries against the base by file before it is ready. A stricter rule (no growth
in a file present in both lists) refuses a function moved into an existing file; whether that trade is worth it is
decided at 6.20, with the step's experience.

Order: 6.2–6.4 first, so every later PR is measured by the ratchet. Areas then go from the leaves of the context graph
(kernel, platform) to the contexts that read them, so a catalog exists before its readers move to it. If a PR exceeds
the size budget it is split in place (6.13a, 6.13b) and recorded on this plan. If a literal has no honest catalog home
(the cure would be blanking), the PR stops and records it as a contract question for A Torre instead of adding a key.

## Metrics (step start → target → step end)

| Measure | Start (c76e1771) | Target | After step 6 |
|---|---|---|---|
| Absolute offenders, `apps/web/src` | 11,802 in 404 files (old reading); 12,218 on the AST reading (PR 6.2) | 0 | — |
| Absolute offenders, `next.config.ts` | 49 (unread); 51 on the AST reading | 0 | — |
| Absolute offenders, tooling (`scripts/`, `fidelity/`) | 8,920 (unread); 8,277 on the AST reading, with `literals-census.ts` | 0 | — |
| `ABSOLUTE_GATE` | `false`, test requires > 0 | `true`, exact list, shrink-only | `true` from PR 6.4: 17,587 offenders on the list |
| Catalog files declared in a manifest | 0 (10 hand-kept paths) | every catalog | 23 after PR 6.3 |
| Literal domains with a home | 8 (D-050) | 8 + the D-063 domains | — |
| `.length === 0` lines | 82 | 0 | — |
| Rate-limit values outside `LIMITS` (`identity/server/config.ts`) | 4 | 0 | — |
| PRs | — | about 35 | — |
