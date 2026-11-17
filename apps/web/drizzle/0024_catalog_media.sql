CREATE TABLE "catalog_media" (
	"id" text PRIMARY KEY NOT NULL,
	"owner_kind" text NOT NULL,
	"owner_id" text NOT NULL,
	"kind" text NOT NULL,
	"variant" text DEFAULT 'default' NOT NULL,
	"media_sha256" text,
	"url" text NOT NULL,
	"pathname" text NOT NULL,
	"width" integer NOT NULL,
	"height" integer NOT NULL,
	"sha256" text NOT NULL,
	"alt" text NOT NULL,
	"transform" jsonb,
	"design_status" text NOT NULL,
	"version" integer NOT NULL,
	"is_active" boolean DEFAULT true NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "catalog_media_owner_kind" CHECK ("catalog_media"."owner_kind" in ('institution', 'area', 'subarea', 'course', 'lesson')),
	CONSTRAINT "catalog_media_kind" CHECK ("catalog_media"."kind" in ('poster_9x16', 'hero_desktop_16x9', 'hero_present', 'hero_mobile_9x16', 'still_16x9', 'lesson_default', 'thumb', 'cover_16x9', 'cover_9x16', 'og', 'author_cover_9x16', 'university_cover_9x16')),
	CONSTRAINT "catalog_media_dimensions" CHECK ("catalog_media"."width" > 0 and "catalog_media"."height" > 0 and "catalog_media"."version" > 0),
	CONSTRAINT "catalog_media_sha256" CHECK ("catalog_media"."sha256" ~ '^[a-f0-9]{64}$'),
	CONSTRAINT "catalog_media_design_status" CHECK ("catalog_media"."design_status" in ('approved', 'draft', 'legacy'))
);
--> statement-breakpoint
ALTER TABLE "catalog_media" ADD CONSTRAINT "catalog_media_media_sha256_media_objects_sha256_fk" FOREIGN KEY ("media_sha256") REFERENCES "public"."media_objects"("sha256") ON DELETE restrict ON UPDATE no action;--> statement-breakpoint
CREATE UNIQUE INDEX "catalog_media_one_active" ON "catalog_media" USING btree ("owner_kind","owner_id","kind","variant") WHERE "catalog_media"."is_active";--> statement-breakpoint
CREATE UNIQUE INDEX "catalog_media_version" ON "catalog_media" USING btree ("owner_kind","owner_id","kind","variant","version");--> statement-breakpoint
INSERT INTO "catalog_media" ("id", "owner_kind", "owner_id", "kind", "variant", "url", "pathname", "width", "height", "sha256", "alt", "transform", "design_status", "version", "is_active", "created_at", "updated_at", "media_sha256")
SELECT "id", 'course', "course_id", "kind", "variant", "url", "pathname", "width", "height", "sha256", "alt", "transform", "design_status", "version", "is_active", "created_at", "updated_at", "media_sha256" FROM "course_assets";--> statement-breakpoint
INSERT INTO "catalog_media" ("id", "owner_kind", "owner_id", "kind", "variant", "url", "pathname", "width", "height", "sha256", "alt", "transform", "design_status", "version", "is_active", "created_at", "updated_at", "media_sha256")
SELECT "id", 'lesson', "lesson_id", "kind", "variant", "url", "pathname", "width", "height", "sha256", "alt", "transform", "design_status", "version", "is_active", "created_at", "updated_at", "media_sha256" FROM "lesson_assets";--> statement-breakpoint
INSERT INTO "catalog_media" ("id", "owner_kind", "owner_id", "kind", "variant", "url", "pathname", "width", "height", "sha256", "alt", "transform", "design_status", "version", "is_active", "created_at", "updated_at", "media_sha256")
SELECT "id", 'subarea', "subarea_id", "kind", "variant", "url", "pathname", "width", "height", "sha256", "alt", "transform", "design_status", "version", "is_active", "created_at", "updated_at", "media_sha256" FROM "subarea_assets";--> statement-breakpoint
INSERT INTO "catalog_media" ("id", "owner_kind", "owner_id", "kind", "variant", "url", "pathname", "width", "height", "sha256", "alt", "design_status", "version", "is_active", "media_sha256")
SELECT 'legacy-author:' || a."id", 'institution', a."id", 'author_cover_9x16', 'default',
  COALESCE(a."cover"->>'url', 'https://media.openuniversity.si/m/' || o."sha256" || '.' || o."ext"),
  COALESCE(regexp_replace(a."cover"->>'url', '^https://[^/]+/', ''), 'm/' || o."sha256" || '.' || o."ext"),
  COALESCE((a."cover"->>'width')::int, o."width"),
  COALESCE((a."cover"->>'height')::int, o."height"),
  COALESCE(a."cover"->>'sha256', a."media_sha256"),
  COALESCE(NULLIF(a."cover"->>'alt', ''), a."name"),
  'approved', 1, true,
  COALESCE(a."media_sha256", NULLIF(a."cover"->>'mediaSha256', ''))
FROM "authors" a
LEFT JOIN "media_objects" o ON o."sha256" = COALESCE(a."media_sha256", a."cover"->>'sha256')
WHERE a."cover" IS NOT NULL OR a."media_sha256" IS NOT NULL;--> statement-breakpoint
INSERT INTO "catalog_media" ("id", "owner_kind", "owner_id", "kind", "variant", "url", "pathname", "width", "height", "sha256", "alt", "design_status", "version", "is_active", "media_sha256")
SELECT 'legacy-home:' || r."id", 'institution', r."id", 'university_cover_9x16', 'default',
  COALESCE(r."cover"->>'url', 'https://media.openuniversity.si/m/' || o."sha256" || '.' || o."ext"),
  COALESCE(regexp_replace(r."cover"->>'url', '^https://[^/]+/', ''), 'm/' || o."sha256" || '.' || o."ext"),
  COALESCE((r."cover"->>'width')::int, o."width"),
  COALESCE((r."cover"->>'height')::int, o."height"),
  COALESCE(r."cover"->>'sha256', r."media_sha256"),
  COALESCE(NULLIF(r."cover"->>'alt', ''), r."title", r."id"),
  'approved', 1, true,
  COALESCE(r."media_sha256", NULLIF(r."cover"->>'mediaSha256', ''))
FROM "home_rows" r
LEFT JOIN "media_objects" o ON o."sha256" = COALESCE(r."media_sha256", r."cover"->>'sha256')
WHERE r."cover" IS NOT NULL OR r."media_sha256" IS NOT NULL;--> statement-breakpoint
INSERT INTO "catalog_media" ("id", "owner_kind", "owner_id", "kind", "variant", "url", "pathname", "width", "height", "sha256", "alt", "design_status", "version", "is_active", "media_sha256")
SELECT 'legacy-home-og:' || r."id", 'institution', r."id", 'og', 'default',
  COALESCE(r."cover"->'og'->>'url', 'https://media.openuniversity.si/m/' || o."sha256" || '.' || o."ext"),
  COALESCE(regexp_replace(r."cover"->'og'->>'url', '^https://[^/]+/', ''), 'm/' || o."sha256" || '.' || o."ext"),
  COALESCE((r."cover"->'og'->>'width')::int, o."width"),
  COALESCE((r."cover"->'og'->>'height')::int, o."height"),
  COALESCE(r."cover"->'og'->>'sha256', r."og_media_sha256"),
  COALESCE(NULLIF(r."title", ''), r."id"),
  'approved', 1, true,
  COALESCE(r."og_media_sha256", NULLIF(r."cover"->'og'->>'mediaSha256', ''))
FROM "home_rows" r
LEFT JOIN "media_objects" o ON o."sha256" = COALESCE(r."og_media_sha256", r."cover"->'og'->>'sha256')
WHERE r."cover"->'og' IS NOT NULL OR r."og_media_sha256" IS NOT NULL;--> statement-breakpoint
CREATE FUNCTION "public"."catalog_media_legacy_frozen"() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'legacy media table % is frozen; write catalog_media', TG_TABLE_NAME USING ERRCODE = '55000';
END $$;--> statement-breakpoint
CREATE TRIGGER "course_assets_frozen" BEFORE INSERT OR UPDATE OR DELETE ON "course_assets" FOR EACH ROW EXECUTE FUNCTION "public"."catalog_media_legacy_frozen"();--> statement-breakpoint
CREATE TRIGGER "lesson_assets_frozen" BEFORE INSERT OR UPDATE OR DELETE ON "lesson_assets" FOR EACH ROW EXECUTE FUNCTION "public"."catalog_media_legacy_frozen"();--> statement-breakpoint
CREATE TRIGGER "subarea_assets_frozen" BEFORE INSERT OR UPDATE OR DELETE ON "subarea_assets" FOR EACH ROW EXECUTE FUNCTION "public"."catalog_media_legacy_frozen"();