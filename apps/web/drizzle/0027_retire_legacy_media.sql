ALTER TABLE "course_assets" DISABLE ROW LEVEL SECURITY;--> statement-breakpoint
ALTER TABLE "lesson_assets" DISABLE ROW LEVEL SECURITY;--> statement-breakpoint
ALTER TABLE "subarea_assets" DISABLE ROW LEVEL SECURITY;--> statement-breakpoint
DROP TABLE "course_assets" CASCADE;--> statement-breakpoint
DROP TABLE "lesson_assets" CASCADE;--> statement-breakpoint
DROP TABLE "subarea_assets" CASCADE;--> statement-breakpoint
ALTER TABLE "authors" DROP CONSTRAINT "authors_media_sha256_media_objects_sha256_fk";
--> statement-breakpoint
ALTER TABLE "home_rows" DROP CONSTRAINT "home_rows_media_sha256_media_objects_sha256_fk";
--> statement-breakpoint
ALTER TABLE "home_rows" DROP CONSTRAINT "home_rows_og_media_sha256_media_objects_sha256_fk";
--> statement-breakpoint
ALTER TABLE "authors" DROP COLUMN "media_sha256";--> statement-breakpoint
ALTER TABLE "home_rows" DROP COLUMN "media_sha256";--> statement-breakpoint
ALTER TABLE "home_rows" DROP COLUMN "og_media_sha256";--> statement-breakpoint
DROP FUNCTION IF EXISTS "catalog_media_legacy_frozen"();