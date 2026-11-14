# ADR-39 — Data ownership and retention

Status: accepted for the structural audit (states 2.1 and 5.4).

Each application table has one owning context. SQL for that table stays in that context's adapter, plus the shared schema and migrations.
Media bytes outlive a swap. An object may be marked orphaned only after a complete inventory shows no reference in prod, preview or a retained release.
Physical deletion of an orphaned object happens once an inventory shows no reference, under a write barrier that covers every environment using the bucket, and only after a recoverable copy and a receipt. No calendar wait keeps a retired table, column or reader (D-029): `0027_retire_legacy_media` drops the frozen asset tables and the legacy cover columns.
Preview reset requires a verified snapshot and is rejected for production. A failed reset restores that snapshot before writers resume.
The nullable marker is additive. Reverting the code does not drop the column or the receipts.
