CREATE TABLE "subarea_assets" (
	"id" text PRIMARY KEY NOT NULL,
	"subarea_id" text NOT NULL,
	"kind" text NOT NULL,
	"variant" text DEFAULT 'default' NOT NULL,
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
	CONSTRAINT "subarea_assets_kind" CHECK ("subarea_assets"."kind" in ('poster_9x16', 'hero_desktop_16x9', 'hero_present', 'hero_mobile_9x16', 'og', 'lesson_default')),
	CONSTRAINT "subarea_assets_dimensions" CHECK ("subarea_assets"."width" > 0 and "subarea_assets"."height" > 0 and "subarea_assets"."version" > 0),
	CONSTRAINT "subarea_assets_sha256" CHECK ("subarea_assets"."sha256" ~ '^[a-f0-9]{64}$'),
	CONSTRAINT "subarea_assets_design_status" CHECK ("subarea_assets"."design_status" in ('approved', 'draft', 'legacy'))
);
--> statement-breakpoint
ALTER TABLE "course_assets" DROP CONSTRAINT "course_assets_kind";--> statement-breakpoint
ALTER TABLE "courses" ADD COLUMN "cover_provisional" boolean DEFAULT false NOT NULL;--> statement-breakpoint
ALTER TABLE "subarea_assets" ADD CONSTRAINT "subarea_assets_subarea_id_subject_subareas_id_fk" FOREIGN KEY ("subarea_id") REFERENCES "public"."subject_subareas"("id") ON DELETE restrict ON UPDATE no action;--> statement-breakpoint
CREATE UNIQUE INDEX "subarea_assets_one_active" ON "subarea_assets" USING btree ("subarea_id","kind","variant") WHERE "subarea_assets"."is_active";--> statement-breakpoint
CREATE UNIQUE INDEX "subarea_assets_version" ON "subarea_assets" USING btree ("subarea_id","kind","variant","version");--> statement-breakpoint
ALTER TABLE "course_assets" ADD CONSTRAINT "course_assets_kind" CHECK ("course_assets"."kind" in ('poster_9x16', 'hero_desktop_16x9', 'hero_present', 'hero_mobile_9x16', 'still_16x9', 'lesson_default', 'thumb'));