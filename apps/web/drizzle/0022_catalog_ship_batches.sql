CREATE TABLE "catalog_ship_batches" (
	"content_hash" text PRIMARY KEY NOT NULL,
	"status" text NOT NULL,
	"draft" boolean NOT NULL,
	"allow_orphan" boolean NOT NULL,
	"note" text,
	"chunk_count" integer NOT NULL,
	"result" jsonb,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "catalog_ship_batches_hash" CHECK ("catalog_ship_batches"."content_hash" ~ '^[a-f0-9]{64}$'),
	CONSTRAINT "catalog_ship_batches_status" CHECK ("catalog_ship_batches"."status" IN ('open', 'committed')),
	CONSTRAINT "catalog_ship_batches_chunks" CHECK ("catalog_ship_batches"."chunk_count" BETWEEN 1 AND 100)
);
--> statement-breakpoint
CREATE TABLE "catalog_ship_chunks" (
	"content_hash" text NOT NULL,
	"chunk_index" integer NOT NULL,
	"bundles" jsonb NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "catalog_ship_chunks_content_hash_chunk_index_pk" PRIMARY KEY("content_hash","chunk_index"),
	CONSTRAINT "catalog_ship_chunks_index" CHECK ("catalog_ship_chunks"."chunk_index" >= 0)
);
--> statement-breakpoint
ALTER TABLE "catalog_ship_chunks" ADD CONSTRAINT "catalog_ship_chunks_content_hash_catalog_ship_batches_content_hash_fk" FOREIGN KEY ("content_hash") REFERENCES "public"."catalog_ship_batches"("content_hash") ON DELETE cascade ON UPDATE no action;