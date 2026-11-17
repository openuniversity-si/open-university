CREATE FUNCTION "public"."catalog_text_sha256"(value text) RETURNS text LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE AS $$ SELECT pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(value, 'UTF8')), 'hex') $$;--> statement-breakpoint
CREATE SEQUENCE "public"."author_seq" INCREMENT BY 1 MINVALUE 1 MAXVALUE 9223372036854775807 START WITH 3 CACHE 1;--> statement-breakpoint
CREATE SEQUENCE "public"."course_seq" INCREMENT BY 1 MINVALUE 1 MAXVALUE 9223372036854775807 START WITH 6 CACHE 1;--> statement-breakpoint
CREATE SEQUENCE "public"."lesson_seq" INCREMENT BY 1 MINVALUE 1 MAXVALUE 9223372036854775807 START WITH 127 CACHE 1;--> statement-breakpoint
CREATE TABLE "admin_idempotency" (
	"key" text PRIMARY KEY NOT NULL,
	"route" text NOT NULL,
	"request_sha256" text NOT NULL,
	"status" integer NOT NULL,
	"response" jsonb NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "authors" (
	"id" text PRIMARY KEY DEFAULT ('author-' || nextval('author_seq')) NOT NULL,
	"slug" text NOT NULL,
	"name" text NOT NULL,
	"monogram" text NOT NULL,
	"role" text DEFAULT 'Lecturer' NOT NULL,
	"kind" text DEFAULT 'person' NOT NULL,
	"revision" integer DEFAULT 1 NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "authors_slug_unique" UNIQUE("slug"),
	CONSTRAINT "authors_slug" CHECK ("authors"."slug" ~ '^[a-z0-9]+(?:-[a-z0-9]+)*$'),
	CONSTRAINT "authors_monogram" CHECK (char_length("authors"."monogram") BETWEEN 1 AND 3),
	CONSTRAINT "authors_kind" CHECK ("authors"."kind" IN ('person', 'institution', 'channel'))
);
--> statement-breakpoint
CREATE TABLE "catalog_audit" (
	"id" bigserial PRIMARY KEY NOT NULL,
	"at" timestamp with time zone DEFAULT now() NOT NULL,
	"actor" text NOT NULL,
	"request_id" text NOT NULL,
	"action" text NOT NULL,
	"entity_kind" text NOT NULL,
	"entity_id" text NOT NULL,
	"before" jsonb,
	"after" jsonb,
	"release_number" integer
);
--> statement-breakpoint
CREATE TABLE "catalog_imports" (
	"id" text PRIMARY KEY NOT NULL,
	"playlist_id" text NOT NULL,
	"source_url" text NOT NULL,
	"tool" text NOT NULL,
	"fetched_at" timestamp with time zone NOT NULL,
	"items" jsonb NOT NULL,
	"report" jsonb NOT NULL,
	"course_id" text,
	"status" text DEFAULT 'drafted' NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "catalog_imports_status" CHECK ("catalog_imports"."status" IN ('drafted', 'discarded'))
);
--> statement-breakpoint
CREATE TABLE "catalog_releases" (
	"number" integer PRIMARY KEY NOT NULL,
	"schema_version" integer NOT NULL,
	"payload" jsonb NOT NULL,
	"payload_sha256" text NOT NULL,
	"counts" jsonb NOT NULL,
	"note" text NOT NULL,
	"created_by" text NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"is_active" boolean DEFAULT false NOT NULL,
	"activated_at" timestamp with time zone,
	CONSTRAINT "catalog_releases_sha" CHECK ("catalog_releases"."payload_sha256" ~ '^[a-f0-9]{64}$')
);
--> statement-breakpoint
CREATE TABLE "catalog_texts" (
	"entity_kind" text NOT NULL,
	"entity_id" text NOT NULL,
	"field" text NOT NULL,
	"locale" text DEFAULT 'en' NOT NULL,
	"text" text NOT NULL,
	"text_sha256" text GENERATED ALWAYS AS (catalog_text_sha256("text")) STORED,
	"source" text NOT NULL,
	"source_ref" text NOT NULL,
	"confidence" text NOT NULL,
	"status" text DEFAULT 'draft' NOT NULL,
	"approved_by" text,
	"approved_at" timestamp with time zone,
	"approved_sha256" text,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "catalog_texts_entity_kind_entity_id_field_locale_pk" PRIMARY KEY("entity_kind","entity_id","field","locale"),
	CONSTRAINT "catalog_texts_kind" CHECK ("catalog_texts"."entity_kind" IN ('course', 'lesson', 'author')),
	CONSTRAINT "catalog_texts_field" CHECK (("catalog_texts"."entity_kind" = 'course' AND "catalog_texts"."field" IN ('displayTitle', 'shelfTitle', 'subtitle', 'billboardDescription', 'billboardDescriptionMobile', 'description', 'descriptionMobile', 'about', 'level', 'format')) OR ("catalog_texts"."entity_kind" = 'lesson' AND "catalog_texts"."field" IN ('displayTitle', 'about')) OR ("catalog_texts"."entity_kind" = 'author' AND "catalog_texts"."field" IN ('bio'))),
	CONSTRAINT "catalog_texts_source" CHECK ("catalog_texts"."source" IN ('figma', 'dossier/catalog', 'youtube', 'llm', 'manual')),
	CONSTRAINT "catalog_texts_confidence" CHECK ("catalog_texts"."confidence" IN ('figma-approved', 'high', 'medium', 'low')),
	CONSTRAINT "catalog_texts_approval" CHECK (("catalog_texts"."status" = 'approved' AND "catalog_texts"."approved_by" IS NOT NULL AND "catalog_texts"."approved_at" IS NOT NULL AND "catalog_texts"."approved_sha256" = "catalog_texts"."text_sha256") OR ("catalog_texts"."status" = 'draft' AND "catalog_texts"."approved_by" IS NULL AND "catalog_texts"."approved_at" IS NULL AND "catalog_texts"."approved_sha256" IS NULL)),
	CONSTRAINT "catalog_texts_approved_by" CHECK ("catalog_texts"."approved_by" IS NULL OR char_length(btrim("catalog_texts"."approved_by")) BETWEEN 1 AND 64),
	CONSTRAINT "catalog_texts_nonempty" CHECK (char_length(btrim("catalog_texts"."text")) > 0)
);
--> statement-breakpoint
CREATE TABLE "content_sources" (
	"id" text PRIMARY KEY NOT NULL,
	"kind" text NOT NULL,
	"title" text NOT NULL,
	"publisher" text NOT NULL,
	"url" text NOT NULL,
	"youtube_channel_id" text,
	"youtube_playlist_id" text,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "content_sources_kind" CHECK ("content_sources"."kind" IN ('youtube-playlist', 'youtube-channel', 'institution-site')),
	CONSTRAINT "content_sources_url" CHECK ("content_sources"."url" ~ '^https://')
);
--> statement-breakpoint
CREATE TABLE "courses" (
	"id" text PRIMARY KEY DEFAULT ('course-' || nextval('course_seq')) NOT NULL,
	"slug" text NOT NULL,
	"author_id" text NOT NULL,
	"title" text NOT NULL,
	"language_label" text DEFAULT 'English' NOT NULL,
	"lesson_noun" text DEFAULT 'Lecture' NOT NULL,
	"status" text DEFAULT 'draft' NOT NULL,
	"featured" boolean DEFAULT false NOT NULL,
	"source_id" text,
	"license_code" text,
	"attribution_text" text,
	"canonical_url" text,
	"rights_status" text DEFAULT 'unverified' NOT NULL,
	"rights_notes" text,
	"rights_checked_by" text,
	"rights_checked_at" timestamp with time zone,
	"legacy" jsonb,
	"revision" integer DEFAULT 1 NOT NULL,
	"published_at" timestamp with time zone,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "courses_slug_unique" UNIQUE("slug"),
	CONSTRAINT "courses_slug" CHECK ("courses"."slug" ~ '^[a-z0-9]+(?:-[a-z0-9]+)*$' AND char_length("courses"."slug") <= 120),
	CONSTRAINT "courses_status" CHECK ("courses"."status" IN ('draft', 'review', 'published', 'archived')),
	CONSTRAINT "courses_noun" CHECK ("courses"."lesson_noun" IN ('Lecture', 'Episode')),
	CONSTRAINT "courses_rights" CHECK ("courses"."rights_status" IN ('unverified', 'cleared', 'permission-requested', 'accepted-risk', 'restricted')),
	CONSTRAINT "courses_canonical" CHECK ("courses"."canonical_url" IS NULL OR "courses"."canonical_url" ~ '^https://'),
	CONSTRAINT "courses_published_rights" CHECK ("courses"."status" <> 'published' OR ("courses"."license_code" IS NOT NULL AND "courses"."source_id" IS NOT NULL AND "courses"."canonical_url" IS NOT NULL AND "courses"."rights_status" IN ('cleared', 'accepted-risk')))
);
--> statement-breakpoint
CREATE TABLE "home_row_items" (
	"row_id" text NOT NULL,
	"course_id" text NOT NULL,
	"position" integer NOT NULL,
	CONSTRAINT "home_row_items_row_id_course_id_pk" PRIMARY KEY("row_id","course_id"),
	CONSTRAINT "home_row_items_position" CHECK ("home_row_items"."position" <> 0)
);
--> statement-breakpoint
CREATE TABLE "home_rows" (
	"id" text PRIMARY KEY NOT NULL,
	"kind" text NOT NULL,
	"author_id" text,
	"title" text,
	"position" integer NOT NULL,
	"visible" boolean DEFAULT true NOT NULL,
	"revision" integer DEFAULT 1 NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "home_rows_id" CHECK ("home_rows"."id" ~ '^[a-z0-9]+(?:-[a-z0-9]+)*$'),
	CONSTRAINT "home_rows_kind" CHECK ("home_rows"."kind" IN ('continue', 'author', 'curated')),
	CONSTRAINT "home_rows_shape" CHECK (("home_rows"."kind" = 'author' AND "home_rows"."author_id" IS NOT NULL) OR ("home_rows"."kind" = 'curated' AND "home_rows"."title" IS NOT NULL AND "home_rows"."author_id" IS NULL) OR ("home_rows"."kind" = 'continue' AND "home_rows"."author_id" IS NULL)),
	CONSTRAINT "home_rows_position" CHECK ("home_rows"."position" <> 0)
);
--> statement-breakpoint
CREATE TABLE "lesson_videos" (
	"lesson_id" text NOT NULL,
	"provider" text NOT NULL,
	"external_id" text NOT NULL,
	"playback_id" text,
	"playback_policy" text,
	"resolution_tier" text,
	"status" text NOT NULL,
	"duration_seconds" numeric(10, 3),
	"youtube_license" text,
	"channel_id" text,
	"checked_at" timestamp with time zone NOT NULL,
	"checked_by" text NOT NULL,
	CONSTRAINT "lesson_videos_lesson_id_provider_pk" PRIMARY KEY("lesson_id","provider"),
	CONSTRAINT "lesson_videos_provider" CHECK ("lesson_videos"."provider" IN ('youtube', 'mux')),
	CONSTRAINT "lesson_videos_youtube_id" CHECK ("lesson_videos"."provider" <> 'youtube' OR "lesson_videos"."external_id" ~ '^[A-Za-z0-9_-]{11}$')
);
--> statement-breakpoint
CREATE TABLE "lessons" (
	"id" text PRIMARY KEY DEFAULT ('lesson-' || nextval('lesson_seq')) NOT NULL,
	"course_id" text NOT NULL,
	"slug" text NOT NULL,
	"position" integer NOT NULL,
	"kind" text DEFAULT 'lecture' NOT NULL,
	"youtube_title" text NOT NULL,
	"duration_seconds" integer NOT NULL,
	"visible" boolean DEFAULT true NOT NULL,
	"license_code" text,
	"attribution_text" text,
	"revision" integer DEFAULT 1 NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "lessons_slug" CHECK ("lessons"."slug" ~ '^[a-z0-9]+(?:-[a-z0-9]+)*$' AND char_length("lessons"."slug") <= 160),
	CONSTRAINT "lessons_kind" CHECK ("lessons"."kind" IN ('lecture', 'background', 'compilation', 'trailer')),
	CONSTRAINT "lessons_position" CHECK ("lessons"."position" <> 0),
	CONSTRAINT "lessons_duration" CHECK ("lessons"."duration_seconds" > 0)
);
--> statement-breakpoint
CREATE TABLE "licenses" (
	"code" text PRIMARY KEY NOT NULL,
	"name" text NOT NULL,
	"url" text,
	"requires_attribution" boolean NOT NULL,
	"non_commercial" boolean DEFAULT false NOT NULL,
	"share_alike" boolean DEFAULT false NOT NULL,
	"embed_only" boolean DEFAULT true NOT NULL,
	"attribution_template" text,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "licenses_code" CHECK ("licenses"."code" ~ '^[a-z0-9]+(?:[-.][a-z0-9]+)*$')
);
--> statement-breakpoint
CREATE TABLE "slug_redirects" (
	"from_path" text PRIMARY KEY NOT NULL,
	"to_path" text NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "slug_redirects_paths" CHECK ("slug_redirects"."from_path" ~ '^/c/' AND "slug_redirects"."to_path" ~ '^/c/' AND "slug_redirects"."from_path" <> "slug_redirects"."to_path")
);
--> statement-breakpoint
ALTER TABLE "catalog_audit" ADD CONSTRAINT "catalog_audit_release_number_catalog_releases_number_fk" FOREIGN KEY ("release_number") REFERENCES "public"."catalog_releases"("number") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "catalog_imports" ADD CONSTRAINT "catalog_imports_course_id_courses_id_fk" FOREIGN KEY ("course_id") REFERENCES "public"."courses"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "courses" ADD CONSTRAINT "courses_author_id_authors_id_fk" FOREIGN KEY ("author_id") REFERENCES "public"."authors"("id") ON DELETE restrict ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "courses" ADD CONSTRAINT "courses_source_id_content_sources_id_fk" FOREIGN KEY ("source_id") REFERENCES "public"."content_sources"("id") ON DELETE restrict ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "courses" ADD CONSTRAINT "courses_license_code_licenses_code_fk" FOREIGN KEY ("license_code") REFERENCES "public"."licenses"("code") ON DELETE restrict ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "home_row_items" ADD CONSTRAINT "home_row_items_row_id_home_rows_id_fk" FOREIGN KEY ("row_id") REFERENCES "public"."home_rows"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "home_row_items" ADD CONSTRAINT "home_row_items_course_id_courses_id_fk" FOREIGN KEY ("course_id") REFERENCES "public"."courses"("id") ON DELETE restrict ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "home_rows" ADD CONSTRAINT "home_rows_author_id_authors_id_fk" FOREIGN KEY ("author_id") REFERENCES "public"."authors"("id") ON DELETE restrict ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "lesson_videos" ADD CONSTRAINT "lesson_videos_lesson_id_lessons_id_fk" FOREIGN KEY ("lesson_id") REFERENCES "public"."lessons"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "lessons" ADD CONSTRAINT "lessons_course_id_courses_id_fk" FOREIGN KEY ("course_id") REFERENCES "public"."courses"("id") ON DELETE restrict ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "lessons" ADD CONSTRAINT "lessons_license_code_licenses_code_fk" FOREIGN KEY ("license_code") REFERENCES "public"."licenses"("code") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
CREATE INDEX "catalog_audit_entity" ON "catalog_audit" USING btree ("entity_kind","entity_id","at" DESC NULLS FIRST);--> statement-breakpoint
CREATE UNIQUE INDEX "catalog_releases_one_active" ON "catalog_releases" USING btree ((true)) WHERE "catalog_releases"."is_active";--> statement-breakpoint
CREATE INDEX "catalog_texts_pending" ON "catalog_texts" USING btree ("entity_kind","entity_id") WHERE "catalog_texts"."status" = 'draft';--> statement-breakpoint
CREATE UNIQUE INDEX "content_sources_playlist" ON "content_sources" USING btree ("youtube_playlist_id") WHERE "content_sources"."youtube_playlist_id" IS NOT NULL;--> statement-breakpoint
CREATE UNIQUE INDEX "courses_one_featured" ON "courses" USING btree ((true)) WHERE "courses"."featured" AND "courses"."status" = 'published';--> statement-breakpoint
CREATE INDEX "courses_author" ON "courses" USING btree ("author_id");--> statement-breakpoint
CREATE INDEX "courses_status" ON "courses" USING btree ("status");--> statement-breakpoint
CREATE UNIQUE INDEX "home_row_items_position_unique" ON "home_row_items" USING btree ("row_id","position");--> statement-breakpoint
CREATE UNIQUE INDEX "home_rows_position_unique" ON "home_rows" USING btree ("position");--> statement-breakpoint
CREATE UNIQUE INDEX "home_rows_one_continue" ON "home_rows" USING btree ((true)) WHERE "home_rows"."kind" = 'continue';--> statement-breakpoint
CREATE UNIQUE INDEX "lesson_videos_external" ON "lesson_videos" USING btree ("provider","external_id");--> statement-breakpoint
CREATE UNIQUE INDEX "lessons_course_slug" ON "lessons" USING btree ("course_id","slug");--> statement-breakpoint
CREATE UNIQUE INDEX "lessons_course_position" ON "lessons" USING btree ("course_id","position");