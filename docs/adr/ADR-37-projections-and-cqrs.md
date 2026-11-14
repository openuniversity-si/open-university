# ADR-37 — Course projections and CQRS

Status: accepted for the structural audit (states 4.1 and 5.2).

Publishing writes `catalog_course_projections`, `catalog_release_index` and `catalog_redirects` in the same transaction as the release.
Public pages read those projections through `CatalogQueriesPort`. The full catalog remains the fallback when the index or a stitch is missing.
Drift between the active index and the stored projections is an error in the doctor. Health does not scan those tables.
The last publish duration is recorded only after commit and is null until a sample exists. Its scope is the current process.
