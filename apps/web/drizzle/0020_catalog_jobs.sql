CREATE TABLE IF NOT EXISTS "catalog_jobs" (
	"job_id" text PRIMARY KEY NOT NULL,
	"idempotency_key" text NOT NULL,
	"bundle_sha256" text NOT NULL,
	"target_env" text NOT NULL,
	"actor_id" text NOT NULL,
	"stage" text NOT NULL,
	"lease_until" timestamp with time zone,
	"lease_token" integer DEFAULT 0 NOT NULL,
	"attempt_count" integer DEFAULT 0 NOT NULL,
	"checkpoint_json" jsonb,
	"stage_timings_json" jsonb DEFAULT '[]'::jsonb NOT NULL,
	"last_error" text,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "catalog_jobs_env" CHECK ("catalog_jobs"."target_env" IN ('preview', 'prod')),
	CONSTRAINT "catalog_jobs_sha" CHECK ("catalog_jobs"."bundle_sha256" ~ '^[a-f0-9]{64}$'),
	CONSTRAINT "catalog_jobs_stage" CHECK ("catalog_jobs"."stage" IN ('VALIDATED', 'MEDIA_CHECKED', 'MEDIA_UPLOADED', 'BUNDLE_APPLIED', 'PUBLISHED', 'DRAFT_READY', 'VERIFIED', 'FAILED', 'PAUSED'))
);
--> statement-breakpoint
CREATE UNIQUE INDEX IF NOT EXISTS "catalog_jobs_identity" ON "catalog_jobs" USING btree ("target_env","actor_id","idempotency_key");
--> statement-breakpoint
CREATE INDEX IF NOT EXISTS "catalog_jobs_lease" ON "catalog_jobs" USING btree ("lease_until");
--> statement-breakpoint
CREATE INDEX IF NOT EXISTS "catalog_jobs_stage" ON "catalog_jobs" USING btree ("stage");
