CREATE TABLE "config_document_revisions" (
	"kind" text NOT NULL,
	"revision" integer NOT NULL,
	"body" jsonb NOT NULL,
	"actor" text NOT NULL,
	"note" text,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "config_document_revisions_kind_revision_pk" PRIMARY KEY("kind","revision"),
	CONSTRAINT "config_document_revisions_kind" CHECK ("config_document_revisions"."kind" IN ('theme', 'copy', 'limits', 'editorial')),
	CONSTRAINT "config_document_revisions_revision" CHECK ("config_document_revisions"."revision" >= 1)
);
--> statement-breakpoint
CREATE TABLE "config_documents" (
	"kind" text PRIMARY KEY NOT NULL,
	"revision" integer NOT NULL,
	"body" jsonb NOT NULL,
	"actor" text NOT NULL,
	"note" text,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "config_documents_kind" CHECK ("config_documents"."kind" IN ('theme', 'copy', 'limits', 'editorial')),
	CONSTRAINT "config_documents_revision" CHECK ("config_documents"."revision" >= 1)
);
