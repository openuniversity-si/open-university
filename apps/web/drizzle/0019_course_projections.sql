CREATE TABLE IF NOT EXISTS "catalog_course_projections" (
	"course_id" text NOT NULL,
	"projection_sha256" text NOT NULL,
	"source_revision" integer NOT NULL,
	"summary_json" jsonb NOT NULL,
	"detail_json" jsonb NOT NULL,
	CONSTRAINT "catalog_course_projections_course_id_projection_sha256_pk" PRIMARY KEY("course_id","projection_sha256"),
	CONSTRAINT "catalog_course_projections_sha" CHECK ("catalog_course_projections"."projection_sha256" ~ '^[a-f0-9]{64}$')
);
--> statement-breakpoint
CREATE TABLE IF NOT EXISTS "catalog_release_index" (
	"release_number" integer PRIMARY KEY NOT NULL,
	"manifest_sha256" text NOT NULL,
	"index_json" jsonb NOT NULL,
	"format_version" integer NOT NULL,
	CONSTRAINT "catalog_release_index_sha" CHECK ("catalog_release_index"."manifest_sha256" ~ '^[a-f0-9]{64}$'),
	CONSTRAINT "catalog_release_index_format" CHECK ("catalog_release_index"."format_version" > 0)
);
--> statement-breakpoint
CREATE TABLE IF NOT EXISTS "catalog_redirects" (
	"release_number" integer NOT NULL,
	"from_path" text NOT NULL,
	"to_path" text NOT NULL,
	"status_code" integer NOT NULL,
	CONSTRAINT "catalog_redirects_release_number_from_path_pk" PRIMARY KEY("release_number","from_path"),
	CONSTRAINT "catalog_redirects_status" CHECK ("catalog_redirects"."status_code" IN (301, 308))
);
--> statement-breakpoint
DO $$ BEGIN
	ALTER TABLE "catalog_release_index" ADD CONSTRAINT "catalog_release_index_release_number_catalog_releases_number_fk" FOREIGN KEY ("release_number") REFERENCES "public"."catalog_releases"("number") ON DELETE no action ON UPDATE no action;
EXCEPTION
	WHEN duplicate_object THEN NULL;
END $$;
--> statement-breakpoint
DO $$ BEGIN
	ALTER TABLE "catalog_redirects" ADD CONSTRAINT "catalog_redirects_release_number_catalog_releases_number_fk" FOREIGN KEY ("release_number") REFERENCES "public"."catalog_releases"("number") ON DELETE no action ON UPDATE no action;
EXCEPTION
	WHEN duplicate_object THEN NULL;
END $$;
--> statement-breakpoint
CREATE INDEX IF NOT EXISTS "catalog_redirects_release" ON "catalog_redirects" USING btree ("release_number");
