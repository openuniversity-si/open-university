# CAP-004 — Keep any outside service inside its adapter
requested: 2026-10-24T18:39-03:00
requested-by: Daniel (resolve the adapter audit)
status: approved 2026-10-24
visual: no

## Concepts
No new concept. Release, lesson, session and media stay as in [CONTRACT.md](../domain/CONTRACT.md).
The rings of ADR-36 already put a vendor in its adapter. This capability applies that rule to the
database, object storage, the session provider, playback, the command ports, and the lesson text fields.

## Contract
Input: one outside service that production code names outside its adapter.
Output: the name, the URL and the client library of that service exist only in its adapter.
The public release, the pages, and the stored rows stay the same.
Errors: a name that escapes the adapter fails the stage proof.
Invariants: ADR-36 (a context reaches another ring through a port or the adapter that owns the vendor).

## Out of scope
Visitor-visible behavior. Open University's `content/catalog/*.json` (archived at `567176bb`). A lesson summary. `RELEASE_SCHEMA_VERSION`.
A database migration. Renaming the public release key `youtubeId`. Test pools, fidelity, one-off scripts,
the applied migration, and legal copy that names a vendor for the visitor.

## PRs
1. The database URL and the `pg` import stay in `platform/db`.
2. The object store stays behind one storage port (R2 only since D-062; Blob is retired).
3. The session provider stays in the session adapter.
4. Playback and the factory source stay in their adapters.
5. Ports ask for an operation; SQL stays in the server. Replaced by D-056: SQL lives in the database package ([CAP-007](CAP-007-keep-sql-in-the-database-package.md)).
6. Lesson text follows `TEXT_FIELDS`.

## Target
idea-to-prod: 24h
marginal: 1h
Each stage's proof is a search: the vendor name is only in its adapter, and the release a visitor
already receives is unchanged. The next service uses the same cut.
