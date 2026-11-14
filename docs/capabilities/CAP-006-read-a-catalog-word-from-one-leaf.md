# CAP-006 — Read a catalog word from one leaf
requested: 2026-10-25T08:57-03:00
requested-by: Daniel (implement the three cuts in the productivity audit)
status: approved 2026-10-25
visual: no

## Concepts
No new visitor concept. Course, lesson, author, Home row, and release stay as in [CONTRACT.md](../domain/CONTRACT.md).
A catalog word (a text-field name, a course status, a lesson kind, a Home-row kind) is declared once.
The database check, the release schema, and the Home-row rules read that declaration.

## Contract
Input: the leaf that already names the word.
Output: the check, the release text object, and the Home-row behavior that today are written beside the leaf.
A stored row, a compiled release, and the Home a visitor sees stay the same.
Errors: a generated check whose SQL differs from the stored check is a failed schema gate, not a migration in the cut that introduces the generator.
Invariants: D-035 (one list, read by the check) and D-050 (a call site reads the key). INV-R1 (one release schema).

## Out of scope
A lesson summary and any new `TEXT_FIELDS.lesson` field. `RELEASE_SCHEMA_VERSION`. Open University's `content/catalog/*.json` (archived at `567176bb`).
Turning on `ABSOLUTE_GATE`. A migration in the cut that only generates today's four checks.
The checks this leaf does not own (jobs, sources, confidence, lesson part, course noun and rights, edition variant, media extension, Home-row shape).
`maxChars` inside `LIMITS`. Rails, portals, continue-from-progress, and covers the visitor already sees.
Home-row kinds inside the editorial document. The factory text generator. `insertLessonDisplayTitle`.
The 45-second doctor ceiling.

## PRs
1. The four checks read the kernel leaves. The generated SQL is the SQL already stored. No migration.
2. The release text schema and the course compiler read `TEXT_FIELDS`. The compiled text keys stay the same.
3. One Home-row sheet. Both compilers and the Home rules read it. The rows stay the same.

## Target
idea-to-prod: the three cuts in one delivery
marginal: the next word is a change to the leaf; the check, the schema, or the sheet follows it
