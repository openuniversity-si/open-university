# Step 6 audit: literals and the absolute gate

Roadmap step 6 of 8 (D-054). Audited on `mod/roadmap-integration` c76e1771 (step 5 closed, #468), 2026-10-26, by the
roadmap implementer session. A Torre's baseline audit (main 198aa130) was the starting hypothesis. Each finding is
verified, corrected or extended below with exact counts and file lists.

## How the counts were taken

- **The absolute reading** is `absoluteOffenders(absoluteSources(repo))` of `apps/web/scripts/lib/absolute-literals.ts`,
  run unchanged, with the options its test uses (the Figma token snapshot values and `readerPhrases`). It reads every
  production `.ts`, `.tsx` and `.css` file under `apps/web/src` (tests and `testing/` excluded, `(test)` routes
  included), drops comments, and counts each quoted string, each number (also inside a string and before a CSS unit)
  and each `true` or `false`, except in the catalog files (`ABSOLUTE_CATALOGS`) and the D-050 structural exceptions. A
  template literal's text is not counted; its `${…}` holes are code.
- **An offender** is one counted literal. The same value twice in a file is two offenders.
- **Syntactic role** (this audit only): each offender's TypeScript AST node, read with the `typescript` compiler of
  `apps/web`: a literal *type* (inside a type node), an object *key*, a *JSX attribute* value, a `z.…` *schema*
  argument, a *comparison* operand (`===`, `!==`), a bare `0`, `1`, `true` or `false` in code, a number inside a
  *string*, a literal in a *data-only file* (a file with no function, method or arrow body), and the rest of *logic*.
  CSS offenders are their own role.
- Counts outside the reading's scope use the same function over the named files.

## Baseline

| Measure | A Torre (main 198aa130) | Verified (c76e1771) |
|---|---|---|
| Absolute offenders, `apps/web/src` | 9,792 | 9,792 on main (reproduced); **11,802** on the integration branch, in **404** files: 8,326 strings, 2,684 numbers, 792 booleans |
| `ABSOLUTE_GATE` | `false` at `absolute-literals.ts:127`, a test asserts it is off | `false` (line 127); the test asserts `ABSOLUTE_GATE === false` **and** `offenders.length > 0`: it fails at zero and passes at any growth |
| The absolute reading in a gate | — | only that unit test; `check-architecture` does not run it; no stage reports the count |
| Production files outside the reading | — | `apps/web/next.config.ts` (49 offenders, the CSP and headers); tooling `apps/web/scripts` (102 files, 6,577) and `apps/web/fidelity` (20 files, 2,343). `e2e/` and `test/` are tests |
| Old-series domains still open | editorial rules, bare 0/1/booleans, `rows.length === 0`, `expire: 0`, rate-limit ceiling, ui, catalog, admin/route-specs | `expire: 0` is gone from code (a comment in `kernel/cache.ts` names it). `.length === 0` is on **82** lines in 50 files (`EXTENT.empty` exists, but the extent gate checks only the calls named in `EXTENT_CALLS`). The rate-limit ceiling is still `window: 60, max: 100` and `{ window: 60, max: 10 }` in `identity/server/config.ts:98-101`. Bare `0` 818, `1` 377, booleans 792. `admin/domain/route-specs.ts` 499 |

### Where the 2,010 new offenders came from (main → integration)

Steps 2–5 moved and added files while the gate was off. The growth is almost all new declaration files:

| Source | main | integration | Why |
|---|---|---|---|
| The eleven intents registries (`*/domain/intents.ts`, `kernel/intents.ts`) | 0 | **1,928** | step 4 (D-060) registered 108 intents as data: `catalog/domain/intents.ts` 1,219, `media` 266, `admin` 102, `release` 91, `config` 85, `site` 45, `playback` 44, `progress` 33, `identity` 23, `factory` 12, `kernel` 8 |
| Everything else | 9,792 | 9,874 | +82 net: files moved between rings and folders and carried their literals (`catalog/server` 1,708 → 1,062 and `catalog/domain` +1,096 without the registry; `admin/route-specs.ts` 485 → `admin/domain/route-specs.ts` 499; `platform/db` 656 → 1,273 as SQL and table shapes moved into the database package in step 2) |

The generated theme name table moved from `ui/tokens/names.ts` to `config/domain/theme/names.ts` (ee38a677, D-058)
with the same 1,139 offenders: it was never in `ABSOLUTE_CATALOGS`, before or after the move.

### By area and syntactic role (c76e1771)

| Area | Files | Total | Data-only file | Logic | Bare 0/1/bool | Comparison | CSS | Number in string | Type | JSX attribute | Schema (`z.`) | Key | Index |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| catalog | 74 | 3,527 | 1,145 | 1,123 | 508 | 263 | 0 | 96 | 188 | 0 | 133 | 61 | 10 |
| ui | 88 | 1,408 | 7 | 132 | 106 | 37 | 562 | 132 | 38 | 378 | 0 | 10 | 6 |
| platform | 57 | 1,360 | 13 | 842 | 301 | 82 | 0 | 84 | 34 | 0 | 0 | 0 | 4 |
| admin | 17 | 1,330 | 98 | 932 | 92 | 50 | 0 | 25 | 42 | 0 | 20 | 10 | 61 |
| config | 6 | 1,268 | 976 | 95 | 11 | 14 | 0 | 172 | 0 | 0 | 0 | 0 | 0 |
| media | 32 | 780 | 238 | 264 | 96 | 45 | 0 | 40 | 30 | 1 | 57 | 7 | 2 |
| site | 14 | 383 | 44 | 210 | 52 | 21 | 0 | 9 | 28 | 0 | 11 | 8 | 0 |
| factory | 9 | 344 | 11 | 156 | 58 | 29 | 0 | 14 | 19 | 0 | 51 | 2 | 4 |
| release | 17 | 332 | 83 | 113 | 42 | 34 | 0 | 10 | 43 | 0 | 4 | 2 | 1 |
| app | 42 | 287 | 4 | 65 | 26 | 10 | 96 | 5 | 0 | 76 | 0 | 5 | 0 |
| playback | 18 | 253 | 34 | 85 | 57 | 42 | 0 | 14 | 19 | 0 | 2 | 0 | 0 |
| identity | 10 | 208 | 23 | 110 | 49 | 19 | 0 | 2 | 1 | 0 | 0 | 4 | 0 |
| kernel | 13 | 199 | 11 | 130 | 42 | 5 | 0 | 0 | 11 | 0 | 0 | 0 | 0 |
| progress | 6 | 110 | 30 | 45 | 20 | 5 | 0 | 4 | 4 | 0 | 0 | 2 | 0 |
| `proxy.ts` | 1 | 13 | 0 | 8 | 0 | 3 | 0 | 2 | 0 | 0 | 0 | 0 | 0 |
| **total** | **404** | **11,802** | **2,717** | **4,310** | **1,460** | **659** | **658** | **609** | **457** | **455** | **278** | **111** | **88** |

The 3,687 distinct values repeat: `0` ×818, `true` ×496, `1` ×377, `false` ×296, `"none"` ×255, `""` ×214, `2` ×148,
`"string"` ×130, `"catalog"` ×127, `"course"` ×125.

Largest files: `catalog/domain/intents.ts` 1,219; `config/domain/theme/names.ts` 1,139; `platform/db/schema.ts` 594;
`admin/domain/route-specs.ts` 499; `admin/server/catalog-routes.ts` 302; `media/domain/intents.ts` 266;
`catalog/domain/lesson-address.ts` 152; `catalog/server/courses.ts` 127; `ui/lesson-row/PlaylistItem.tsx` 122.

## Findings

### F1. The count grows while the gate is off, and no check sees it

Verified and extended. 9,792 on main, 11,802 on the integration branch: steps 2–5 added **2,010** (+20.5%) without a
failing check. The only test of the reading asserts the gate is off and the count is above zero, so it would fail on
the day the count reaches zero and passes at any growth.

Why-chain:
1. 11,802 production literals sit outside a catalog, 2,010 more than two days ago.
2. Each step moved or added code with literals in it, and nothing failed.
3. The absolute reading runs only in a test that asserts `ABSOLUTE_GATE === false` and `offenders.length > 0`.
4. D-050 turns a domain on only at zero and has no state between "off" and "zero": a count that is not zero has no
   ceiling.
5. **Root cause: no ratchet.** The rule has no recorded baseline that may only shrink, so off means unbounded.

### F2. The catalogs are a hand-kept path list, and declarations are not catalogs

Verified and extended. `ABSOLUTE_CATALOGS` is ten path constants spread over `domain-literals.ts`. The generated theme
name table (`config/domain/theme/names.ts`, 1,139 offenders, generated from the Figma snapshot by
`pnpm tokens:generate`) is not on it, although its sibling `values.ts` is. The intents registries (1,928 offenders), the
route specs and the database schema are declarations whose literals are the documented value, but nothing says so:
2,717 offenders sit in 23 files that hold no function at all.

Why-chain:
1. 2,717 literals in data-only files count as offenders, 1,139 of them generated from the Figma snapshot.
2. A file is a catalog only if its path is in `ABSOLUTE_CATALOGS`.
3. The list is code in a script, maintained by hand, and no test fails when a generated or declaration file is missing
   from it, or when a listed file moves.
4. "Catalog" has no definition the checker can test: no manifest names a catalog's domain and description, and nothing
   requires a catalog to hold only documented data (a catalog with logic in it could hide literals).
5. **Root cause: catalogs are not declared data.** There is no catalog manifest with rules (exists, data only, every
   export documented), the literal equivalent of step 4's context map and step 5's vendor map.

### F3. The reading is a hand lexer with no roles and a narrow scope

Verified and extended. `valueLiterals` is a character scanner: it does not know regular expression literals
(`catalog/domain/lesson-address.ts` produces two offenders that span several lines, a quote inside a regex opening a
"string"), JSX text, or types. It reports `path: kind value` with no line and no role, so 11,802 lines cannot be sorted
into the work each needs. It reads `apps/web/src` only: `next.config.ts` (the CSP and the response headers, 49 literals)
is production and unread; `apps/web/scripts` (6,577) and `apps/web/fidelity` (2,343) are unread.

Why-chain:
1. The census cannot say which offender is a type, a table name, a UI word or a bare zero, and misses 49 production
   literals.
2. The reading was written as the M10 audit's quick count and promoted to a check unchanged.
3. The checker has the TypeScript compiler available but the literal rules never used it.
4. The rule was not expected to turn on soon (F1), so its precision and scope did not matter.
5. **Root cause: the reading is not a maintained rule.** It has no owner rule id, no line numbers, no roles and a scope
   that is a folder name instead of "every production file".

### F4. Domain vocabulary has no catalog

Verified. Table names are spelled **736** times in **45** files besides the schema (intents' `db.reads` and `db.writes`,
the translators, doctor, deletion, lifecycle). HTTP methods 166 times in 8 files, header names 23, MIME types 10.
Discriminants are spelled at the use site and again in a literal type (457 type literals, 659 comparison operands):
`"course"` ×125, `"lesson"` ×55, `"published"` ×34. D-050 says "a mechanical id is not a key", so no catalog exists for
these, and the absolute reading counts them all.

Why-chain:
1. The same table name, status or method is written in dozens of files.
2. Each module spells the word it needs; a type union is written next to it with the same words.
3. D-050 made the eight domains (colors, spacing, typography, UI text, limits, pagination, cache, editorial) and
   exempted "mechanical ids" without saying where they live.
4. The domain list is closed: protocol vocabulary (HTTP, headers, MIME), storage names (tables, columns) and context
   vocabularies (kinds, states, error codes) have no domain, so they cannot be "in a catalog".
5. **Root cause: missing domains.** The rule names where eight kinds of value live and leaves the rest without a home,
   which makes zero unreachable by construction.

### F5. Bare 0, 1 and booleans are deferred with no owner

Verified. 818 `0`, 377 `1`, 792 booleans, 82 `.length === 0` lines. `kernel/extent.ts` has `EXTENT.empty`, `first` and
`one`, but `extentOffenders` only checks the call sites named in `EXTENT_CALLS`. Booleans have no catalog at all:
option objects (`{ httpOnly: true }`, `disableCSRFCheck: false`), initial state, `return true` in predicates.

Why-chain:
1. Bare 0/1/booleans are 2,069 offenders, 17.5% of the census.
2. D-050 deferred them to "the remainder domain".
3. The remainder domain was never created: no file, no owner, no rule.
4. A bare boolean has two cures (a meaning-named option key, or an expression instead of `if … return true`) and no
   rule says which, so every attempt stalls.
5. **Root cause: unclear ownership.** The remainder belongs to nobody, and there is no anti-blanking rule that tells a
   meaning-named key (`EXTENT.empty`) from a renamed literal (`ZERO`).

### F6. UI literals sit in sheets, attributes and markup

Verified. `ui` and `app` hold 1,695 offenders: 658 in CSS modules (`0` ×214, `true` ×49 in attribute selectors, `100`,
grid lines, durations; `app/c/[courseSlug]/[lessonSlug]/page.module.css` 74, `ui/playback/PlayerRail.module.css` 66),
455 JSX attribute values (`type="button"`, `role`, `aria-*`, `data-*`, `sizes`), 137 numbers inside strings. D-052's
sheet check (`sheet-literals.test.ts`) only refuses identity literals (lengths and colors), so `0`, `100%` and
selector words pass it.

Why-chain:
1. 1,695 UI literals outside the theme and the reader catalog.
2. D-052 moved every identity value (color, type, space, radius) to the theme and stopped there.
3. A sheet literal that is not an identity value (`0`, a grid line, `true` in `[data-open="true"]`) has no theme slot.
4. ARIA roles, button types and data attribute words are markup vocabulary with no catalog (F4).
5. **Root cause: the theme's slot set covers identity, not the sheet.** Nothing gives a non-identity sheet value or a
   markup word one place.

### F7. Limits and contracts still spell their bounds

Verified. 278 offenders are `z.…` arguments (`.max(200)`, `z.literal("course")`, `z.enum([...])`), 133 in catalog and
51 in factory. The auth rate-limit ceiling (`window: 60, max: 100`; sign-in `10`) is in `identity/server/config.ts`,
not `kernel/limits.ts`. `limitOffenders` checks named patterns (`.max(`, timeouts) only where its rules say.

Why-chain:
1. Request schemas and the auth config hold bounds the limits catalog does not have.
2. They were written before D-050, or by a vendor's config shape (Better Auth).
3. The limit gate reads patterns, so a bound passed through a vendor option name is not seen.
4. D-051 makes limits a versioned document with code ceilings, but only for the keys already in `LIMITS`.
5. **Root cause: the limit domain is defined by patterns, not by the values the app enforces.**

## Root causes → enforcement (summary)

| Root cause | Enforcement (plan) |
|---|---|
| No ratchet (F1) | `ABSOLUTE_GATE = true` with an exception list (`scripts/lib/absolute-literals-baseline.json`, PR 6.4): the census must equal the list exactly (test), and the list may only shrink against the PR's base (`structure-check`, `--base`) |
| Catalogs are not declared data (F2) | `scripts/lib/literal-catalogs.json`: every catalog file with its domain and description; the reading's catalogs come from it; a catalog must exist, hold only data (no function bodies) and document every export |
| The reading is not a maintained rule (F3) | the reading on the TypeScript AST, with line and role, over every production file of `apps/web` (`src/`, `next.config.ts`, then `scripts/` and `fidelity/`) |
| Missing domains (F4) | D-063: protocol, storage and context vocabularies are catalog domains; a literal type derives from its catalog (`(typeof X)[keyof typeof X]`) |
| Unclear ownership of the remainder (F5) | D-063 names the cures for 0, 1 and booleans; the catalog rule refuses a key named after its value (`zero`, `true`, `empty_string`) |
| Theme slots cover identity only (F6) | sheet values get theme slots (D-052's mechanism), markup words a UI vocabulary catalog; pixels proven unchanged |
| Limits defined by patterns (F7) | every enforced bound is a `LIMITS` key; request schemas and the auth config read it |
