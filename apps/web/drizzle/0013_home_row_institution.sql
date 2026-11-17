-- 0013: full name and place of a curated (university) row. Additive, idempotent.
ALTER TABLE "home_rows" ADD COLUMN IF NOT EXISTS "full_name" text;--> statement-breakpoint
ALTER TABLE "home_rows" ADD COLUMN IF NOT EXISTS "place" text;
