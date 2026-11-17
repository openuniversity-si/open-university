-- 0010: authors.cover, the author cover (src/catalog/author-cover.ts; docs/catalog/author-covers.md). Additive, idempotent.
ALTER TABLE "authors" ADD COLUMN IF NOT EXISTS "cover" jsonb;
