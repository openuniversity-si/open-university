CREATE TABLE "catalog_home" (
	"singleton" boolean PRIMARY KEY DEFAULT true NOT NULL,
	"revision" integer DEFAULT 1 NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "catalog_home_singleton" CHECK ("catalog_home"."singleton")
);
--> statement-breakpoint
CREATE TABLE "r2_pending_deletions" (
	"key" text PRIMARY KEY NOT NULL,
	"owner_kind" text NOT NULL,
	"owner_id" text NOT NULL,
	"course_id" text NOT NULL,
	"request_id" text NOT NULL,
	"attempts" integer DEFAULT 0 NOT NULL,
	"last_error" text,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "r2_pending_deletions_owner_kind" CHECK ("r2_pending_deletions"."owner_kind" IN ('course', 'lesson'))
);
--> statement-breakpoint
ALTER TABLE "catalog_imports" DROP CONSTRAINT "catalog_imports_status";--> statement-breakpoint
ALTER TABLE "catalog_imports" ALTER COLUMN "status" SET DEFAULT 'received';--> statement-breakpoint
ALTER TABLE "content_sources" ADD COLUMN "revision" integer DEFAULT 1 NOT NULL;--> statement-breakpoint
ALTER TABLE "content_sources" ADD COLUMN "updated_at" timestamp with time zone DEFAULT now() NOT NULL;--> statement-breakpoint
CREATE INDEX "r2_pending_deletions_course" ON "r2_pending_deletions" USING btree ("course_id");--> statement-breakpoint
CREATE INDEX "lesson_progress_lesson" ON "lesson_progress" USING btree ("lesson_id");--> statement-breakpoint
ALTER TABLE "catalog_imports" ADD CONSTRAINT "catalog_imports_status" CHECK ("catalog_imports"."status" IN ('received', 'drafted', 'discarded'));--> statement-breakpoint
INSERT INTO "catalog_home" ("singleton") VALUES (true) ON CONFLICT DO NOTHING;--> statement-breakpoint
CREATE FUNCTION "public"."catalog_releases_immutable"() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' OR (NEW.number, NEW.schema_version, NEW.payload, NEW.payload_sha256, NEW.counts, NEW.note, NEW.created_by, NEW.created_at)
      IS DISTINCT FROM (OLD.number, OLD.schema_version, OLD.payload, OLD.payload_sha256, OLD.counts, OLD.note, OLD.created_by, OLD.created_at) THEN
    RAISE EXCEPTION 'catalog_releases rows are immutable; only is_active and activated_at change' USING ERRCODE = '55000';
  END IF;
  RETURN NEW;
END $$;--> statement-breakpoint
CREATE TRIGGER "catalog_releases_immutable" BEFORE UPDATE OR DELETE ON "catalog_releases" FOR EACH ROW EXECUTE FUNCTION "public"."catalog_releases_immutable"();
