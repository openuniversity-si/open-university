CREATE TABLE "admin_rate_limits" (
	"secret_hash" text PRIMARY KEY NOT NULL,
	"minute" bigint NOT NULL,
	"requests" integer NOT NULL
);
