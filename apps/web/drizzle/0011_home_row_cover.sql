-- 0011: home_rows.cover, the cover of a curated (university) row (src/catalog/university-cover.ts; docs/catalog/university-covers.md). Additive, idempotent.
ALTER TABLE "home_rows" ADD COLUMN IF NOT EXISTS "cover" jsonb;
