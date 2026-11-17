CREATE TABLE "course_assets" (
	"id" text PRIMARY KEY NOT NULL,
	"course_id" text NOT NULL,
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
	CONSTRAINT "course_assets_kind" CHECK ("course_assets"."kind" in ('poster_9x16', 'hero_desktop_16x9', 'hero_present', 'hero_mobile_9x16', 'still_16x9', 'thumb')),
	CONSTRAINT "course_assets_dimensions" CHECK ("course_assets"."width" > 0 and "course_assets"."height" > 0 and "course_assets"."version" > 0),
	CONSTRAINT "course_assets_sha256" CHECK ("course_assets"."sha256" ~ '^[a-f0-9]{64}$'),
	CONSTRAINT "course_assets_design_status" CHECK ("course_assets"."design_status" in ('approved', 'draft', 'legacy'))
);
--> statement-breakpoint
CREATE TABLE "lesson_assets" (
	"id" text PRIMARY KEY NOT NULL,
	"lesson_id" text NOT NULL,
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
	CONSTRAINT "lesson_assets_kind" CHECK ("lesson_assets"."kind" in ('cover_16x9', 'thumb')),
	CONSTRAINT "lesson_assets_dimensions" CHECK ("lesson_assets"."width" > 0 and "lesson_assets"."height" > 0 and "lesson_assets"."version" > 0),
	CONSTRAINT "lesson_assets_sha256" CHECK ("lesson_assets"."sha256" ~ '^[a-f0-9]{64}$'),
	CONSTRAINT "lesson_assets_design_status" CHECK ("lesson_assets"."design_status" in ('approved', 'draft', 'legacy'))
);
--> statement-breakpoint
CREATE UNIQUE INDEX "course_assets_one_active" ON "course_assets" USING btree ("course_id","kind","variant") WHERE "course_assets"."is_active";--> statement-breakpoint
CREATE UNIQUE INDEX "course_assets_version" ON "course_assets" USING btree ("course_id","kind","variant","version");--> statement-breakpoint
CREATE UNIQUE INDEX "lesson_assets_one_active" ON "lesson_assets" USING btree ("lesson_id","kind","variant") WHERE "lesson_assets"."is_active";--> statement-breakpoint
CREATE UNIQUE INDEX "lesson_assets_version" ON "lesson_assets" USING btree ("lesson_id","kind","variant","version");