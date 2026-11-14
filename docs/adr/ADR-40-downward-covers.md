# ADR-40 — Covers inherit only downward

Date: 2026-10-22. Status: accepted.

A cover may be inherited only downward in the catalog: a lesson from its course, a course from its subarea when `cover_provisional` is set (ADR-30). A university (a curated Home row) and an author on the Authors tab are upper levels. They never borrow a course poster or hero. Each one that is visible and publishes a course must have its own cover.

The read path keeps that field optional. An old release still parses. Where the cover is missing, the page renders a neutral plate and no course image. The doctor lists every visible row that is still missing one (`home.cover.missing`, warning).

PUT `/home`, bundle apply, bulk ship (`POST /bundles/ship`, including a draft batch) and the admin release cutter reject the missing cover with 422 and name the row. Bulk ship publishes through `publishRelease`, and it also checks the target row before appending a course. `compileRelease` enforces universities only, so the frozen v1 snapshot (author rows, no covers, no curated rows) still recompiles to the same bytes. The admin cutter also enforces author rows. Clearing a cover that a visible row still needs is refused.

No migration. The columns already exist. Production rows that lacked a cover are given one through the admin API; the placeholder is the safety net for a release cut before that.
