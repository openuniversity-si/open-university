CREATE TABLE "media_objects" (
	"sha256" text PRIMARY KEY NOT NULL,
	"ext" text NOT NULL,
	"content_type" text NOT NULL,
	"bytes" bigint NOT NULL,
	"width" integer NOT NULL,
	"height" integer NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "media_objects_sha256" CHECK ("media_objects"."sha256" ~ '^[a-f0-9]{64}$'),
	CONSTRAINT "media_objects_ext" CHECK ("media_objects"."ext" IN ('jpg','png','webp','avif')),
	CONSTRAINT "media_objects_type" CHECK ("media_objects"."content_type" = 'image/' || CASE WHEN "media_objects"."ext" = 'jpg' THEN 'jpeg' ELSE "media_objects"."ext" END),
	CONSTRAINT "media_objects_dimensions" CHECK ("media_objects"."bytes" > 0 AND "media_objects"."width" > 0 AND "media_objects"."height" > 0)
);
--> statement-breakpoint
ALTER TABLE "authors" ADD COLUMN "media_sha256" text;--> statement-breakpoint
ALTER TABLE "course_assets" ADD COLUMN "media_sha256" text;--> statement-breakpoint
ALTER TABLE "home_rows" ADD COLUMN "media_sha256" text;--> statement-breakpoint
ALTER TABLE "home_rows" ADD COLUMN "og_media_sha256" text;--> statement-breakpoint
ALTER TABLE "lesson_assets" ADD COLUMN "media_sha256" text;--> statement-breakpoint
ALTER TABLE "subarea_assets" ADD COLUMN "media_sha256" text;--> statement-breakpoint
ALTER TABLE "authors" ADD CONSTRAINT "authors_media_sha256_media_objects_sha256_fk" FOREIGN KEY ("media_sha256") REFERENCES "public"."media_objects"("sha256") ON DELETE restrict ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "course_assets" ADD CONSTRAINT "course_assets_media_sha256_media_objects_sha256_fk" FOREIGN KEY ("media_sha256") REFERENCES "public"."media_objects"("sha256") ON DELETE restrict ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "home_rows" ADD CONSTRAINT "home_rows_media_sha256_media_objects_sha256_fk" FOREIGN KEY ("media_sha256") REFERENCES "public"."media_objects"("sha256") ON DELETE restrict ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "home_rows" ADD CONSTRAINT "home_rows_og_media_sha256_media_objects_sha256_fk" FOREIGN KEY ("og_media_sha256") REFERENCES "public"."media_objects"("sha256") ON DELETE restrict ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "lesson_assets" ADD CONSTRAINT "lesson_assets_media_sha256_media_objects_sha256_fk" FOREIGN KEY ("media_sha256") REFERENCES "public"."media_objects"("sha256") ON DELETE restrict ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "subarea_assets" ADD CONSTRAINT "subarea_assets_media_sha256_media_objects_sha256_fk" FOREIGN KEY ("media_sha256") REFERENCES "public"."media_objects"("sha256") ON DELETE restrict ON UPDATE no action;