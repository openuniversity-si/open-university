# ADR-30: Resolve shared covers on read

Status: deprecated by D-111 (the Open University product left this repository; PADRAO-DEV F3a).

Date: 2026-10-18. Status: implementation; production acceptance pending.

Repeated lesson uploads store the same image once per lesson and grow both database and media caches.
The course's own art must continue to win and existing published pages must retain their appearance.

`src/media/resolve.ts` owns the pure rule: active lesson default 16:9 → course `still_16x9` → course
`lesson_default` → subarea `lesson_default` → existing placeholder. Course posters/heroes/OG inherit only
when explicitly marked `cover_provisional`; their own kind/variant always wins. Publication's
`covers.active` uses the same resolver. The flag is included in newly compiled releases; older releases
and snapshot fixtures omit it and behave as false. No content is republished by the migration.

Migration 0017 adds `subarea_assets` with the same version/active constraints and a restrictive subarea
foreign key, adds the course flag defaulting to false, and extends course kinds with `lesson_default`.
The media API/CLI supports subarea upload, list and rollback. Inheritance is resolved after cached reads:
shared descriptors are cached once per subarea; no inherited database rows or course cache copies are written.
Invalidation addresses the shared tag and affected courses/lists.

`prune-inherited` compares default lesson 16:9 versions with the active inherited sha256, records full row
metadata and fallback identity, and optionally deletes matching references under write locks. It never
deletes R2 bytes. Dry-run reports in preview/production, preview application and local PR-versus-main reference
parity are required operational evidence. Per the updated S3 acceptance, local initial/hydrated normalized HTML and screenshots
at 390/1440 use fixed data, fonts and images; production requires the merge commit's hard smoke through
`ship-verify`/`production-check`, without production parity captures. Pixel/screenshot differences are report-only,
never a merge blocker (Daniel, 2026-10-19 15:40 BRT); normalized initial/hydrated HTML and tests remain gates.
Apply production pruning only after that smoke.
The doctor warns on redundant rows and errors on unresolved published
course covers. Tests cover precedence, inactive/variant handling, shared asset constraints/rollback,
publication without own assets and idempotent pruning.

Rollback: promote the previous Vercel deployment and activate the prior catalog release when needed.
Keep prune reports for reference restoration; retain R2 objects for the later GC stage. NPTEL pipeline
changes, content publication and physical object collection remain outside E1.
