-- 0009 (ADR-21): course editions. Additive and idempotent, in the migration's single transaction:
-- 1. create course_editions and the nullable lessons.edition_id/part; 2. backfill one edition per course (two for the
-- Cornell Android course, split by video) and point every lesson at it; 3. renumber positions per edition;
-- 4. only then SET NOT NULL, the composite foreign key and the per-edition order index.
CREATE SEQUENCE IF NOT EXISTS "public"."edition_seq" INCREMENT BY 1 MINVALUE 1 MAXVALUE 9223372036854775807 START WITH 1 CACHE 1;--> statement-breakpoint
CREATE TABLE IF NOT EXISTS "course_editions" (
	"id" text PRIMARY KEY DEFAULT ('edition-' || nextval('edition_seq')) NOT NULL,
	"course_id" text NOT NULL,
	"slug" text NOT NULL,
	"label" text NOT NULL,
	"term" text,
	"year" integer NOT NULL,
	"position" integer NOT NULL,
	"resolution" text,
	"source_playlist_ids" text[] DEFAULT '{}'::text[] NOT NULL,
	"revision" integer DEFAULT 1 NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "course_editions_slug" CHECK ("course_editions"."slug" ~ '^[a-z0-9]+(?:-[a-z0-9]+)*$' AND char_length("course_editions"."slug") <= 40),
	CONSTRAINT "course_editions_label" CHECK (char_length(btrim("course_editions"."label")) BETWEEN 1 AND 40),
	CONSTRAINT "course_editions_term" CHECK ("course_editions"."term" IS NULL OR "course_editions"."term" IN ('spring', 'summer', 'fall', 'winter')),
	CONSTRAINT "course_editions_year" CHECK ("course_editions"."year" BETWEEN 1990 AND 2100),
	CONSTRAINT "course_editions_position" CHECK ("course_editions"."position" > 0),
	CONSTRAINT "course_editions_course_id_courses_id_fk" FOREIGN KEY ("course_id") REFERENCES "public"."courses"("id") ON DELETE restrict ON UPDATE no action
);
--> statement-breakpoint
CREATE UNIQUE INDEX IF NOT EXISTS "course_editions_course_slug" ON "course_editions" USING btree ("course_id","slug");--> statement-breakpoint
CREATE UNIQUE INDEX IF NOT EXISTS "course_editions_course_position" ON "course_editions" USING btree ("course_id","position");--> statement-breakpoint
CREATE UNIQUE INDEX IF NOT EXISTS "course_editions_id_course" ON "course_editions" USING btree ("id","course_id");--> statement-breakpoint
ALTER TABLE "lessons" ADD COLUMN IF NOT EXISTS "edition_id" text;--> statement-breakpoint
ALTER TABLE "lessons" ADD COLUMN IF NOT EXISTS "part" text DEFAULT 'lectures' NOT NULL;--> statement-breakpoint
-- The published editions (RELATORIO-IMPORT-19; label = term + year only). Matched by slug: course ids differ per environment.
INSERT INTO "course_editions" ("course_id", "slug", "label", "term", "year", "position", "source_playlist_ids")
SELECT c."id", k."slug", k."label", k."term", k."year", k."position", k."playlists"
FROM (VALUES
  ('biblical-series-genesis', '2017', '2017', NULL, 2017, 1, ARRAY['PL22J3VaeABQD_IZs7y60I3lUrrFTzkpat']::text[]),
  ('maps-of-meaning', '2017', '2017', NULL, 2017, 1, ARRAY['PL22J3VaeABQCn5nTAx65NRlh1EsKD0UQD']::text[]),
  ('personality-and-its-transformations', '2017', '2017', NULL, 2017, 1, ARRAY['PL22J3VaeABQBlN8DUor7SKWCwSghcqlY5']::text[]),
  ('awakening-from-the-meaning-crisis', '2017', '2017', NULL, 2017, 1, ARRAY['PLND1JCRq8Vuh3f0P5qjrSdb5eC1ZfZwWJ']::text[]),
  ('after-socrates', '2017', '2017', NULL, 2017, 1, ARRAY['PLND1JCRq8Vuj6q5NP_fXjBzUT1p_qYSCC']::text[]),
  ('mit-perception', 'spring-2024', 'Spring 2024', 'spring', 2024, 1, ARRAY['PLUl4u3cNGP62-9RweyYBIpkqfo5dfcuS8']::text[]),
  ('mit-public-finance', 'fall-2024', 'Fall 2024', 'fall', 2024, 1, ARRAY['PLUl4u3cNGP62KS2YhlASvGBxxL8HgB11p']::text[]),
  ('mit-deep-learning', 'fall-2024', 'Fall 2024', 'fall', 2024, 1, ARRAY['PLUl4u3cNGP63URZnh5iqBzDTDYPUTQT-8']::text[]),
  ('mit-social-problems-of-nuclear-energy', 'fall-2025', 'Fall 2025', 'fall', 2025, 1, ARRAY['PLEd-FHe0va8k']::text[]),
  ('mit-game-theory', 'fall-2025', 'Fall 2025', 'fall', 2025, 1, ARRAY['PLUl4u3cNGP63quuKvMHCt3cmTmt0O2qpv']::text[]),
  ('yale-can-it-happen-here-again', '2024', '2024', NULL, 2024, 1, ARRAY['PLh9mgdi4rNexNlVLgo7Z6Zrbk_Otyz-w1']::text[]),
  ('yale-america-at-250', '2025', '2025', NULL, 2025, 1, ARRAY['PLh9mgdi4rNezTQrY_6XMNBWaZqLRdgpoq']::text[]),
  ('yale-marxs-capital', '2026', '2026', NULL, 2026, 1, ARRAY['PLh9mgdi4rNewd_0qe4c2lkzXZZQka_QnZ']::text[]),
  ('harvard-cs50x', '2025', '2025', NULL, 2025, 1, ARRAY['PLhQjrBD2T383q7Vn8QnTsVgSvyLpsqL_R']::text[]),
  ('harvard-cs50-for-business', '2026', '2026', NULL, 2026, 1, ARRAY['PLhQjrBD2T381d32c80DEQZOR-IWcINyP8']::text[]),
  ('harvard-cs50-2d-game-development', '2026', '2026', NULL, 2026, 1, ARRAY['PLhQjrBD2T382zb36OpsmBBYPMGvniSK1B']::text[]),
  ('harvard-deep-learning-theory', '2024', '2024', NULL, 2024, 1, ARRAY['PL0NRmB0fnLJSEXFQHGF0q5JcedxTqK4AJ']::text[]),
  ('stanford-understand-energy', '2026', '2026', NULL, 2026, 1, ARRAY['PLj03YfdUVX_AzBaq4hXe7MpKUwoZNxv8R']::text[]),
  ('stanford-economics-of-transformative-ai', 'summer-2025', 'Summer 2025', 'summer', 2025, 1, ARRAY['PLQ9F4IqcaHKoGfl6q7FKWXxTCxBnH8j4r']::text[]),
  ('stanford-lung-cancer-journey', '2025', '2025', NULL, 2025, 1, ARRAY['PLuP5qOnCjJ-5lMaHJsGAAIN2xtc-8R0DB']::text[]),
  ('cmu-introduction-to-deep-learning', 'spring-2024', 'Spring 2024', 'spring', 2024, 1, ARRAY['PLp-0K3kfddPxUJzAW0KxNNjGiK_hISFas']::text[]),
  ('cmu-intro-to-database-systems', 'fall-2024', 'Fall 2024', 'fall', 2024, 1, ARRAY['PLSE8ODhjZXjYDBpQnSymaectKjxCy6BYq']::text[]),
  ('cmu-advanced-database-systems', 'spring-2024', 'Spring 2024', 'spring', 2024, 1, ARRAY['PLSE8ODhjZXjYa_zX-KeMJui7pcN1rIaIJ']::text[]),
  ('cornell-android-course', 'spring-2025', 'Spring 2025', 'spring', 2025, 1, ARRAY['PLjf6nsEcF5KNIDPgf6GjDTv8FxYC8Z5hE']::text[]),
  ('cornell-android-course', 'fall-2024', 'Fall 2024', 'fall', 2024, 2, ARRAY['PLjf6nsEcF5KP7A-qXHV7m6XMO_KdgVK5f']::text[])
) AS k("course_slug", "slug", "label", "term", "year", "position", "playlists")
JOIN "courses" c ON c."slug" = k."course_slug"
WHERE NOT EXISTS (SELECT 1 FROM "course_editions" e WHERE e."course_id" = c."id")
   OR (c."slug" = 'cornell-android-course' AND NOT EXISTS (SELECT 1 FROM "course_editions" e WHERE e."course_id" = c."id" AND e."slug" = k."slug"))
ORDER BY coalesce(substring(c."id" FROM '\d+$')::bigint, 0), c."id", k."position"
ON CONFLICT DO NOTHING;--> statement-breakpoint
-- Any other course (a database created after the import) gets one edition named after the year it was created.
INSERT INTO "course_editions" ("course_id", "slug", "label", "term", "year", "position")
SELECT c."id", y."year"::text, y."year"::text, NULL, y."year", 1
FROM "courses" c CROSS JOIN LATERAL (SELECT least(greatest(extract(year FROM c."created_at")::int, 1990), 2100) AS "year") y
WHERE NOT EXISTS (SELECT 1 FROM "course_editions" e WHERE e."course_id" = c."id")
ORDER BY coalesce(substring(c."id" FROM '\d+$')::bigint, 0), c."id";--> statement-breakpoint
-- The Cornell Android lessons, by YouTube id, into the edition of their playlist.
UPDATE "lessons" l SET "edition_id" = e."id"
FROM (VALUES
  ('cornell-android-course', 'spring-2025', '3KuD7j-B2nA'),
  ('cornell-android-course', 'spring-2025', '7_yF4pMkrqU'),
  ('cornell-android-course', 'spring-2025', 'Ri6oLJTIj20'),
  ('cornell-android-course', 'spring-2025', 'dLSDcOnuYys'),
  ('cornell-android-course', 'spring-2025', 'osxlrcVAYaI'),
  ('cornell-android-course', 'spring-2025', 'p9JbsHTSeMU'),
  ('cornell-android-course', 'spring-2025', 'OlTXvLaEGE8'),
  ('cornell-android-course', 'spring-2025', 'co-8xgAI98c'),
  ('cornell-android-course', 'spring-2025', '9nAhBs6pdJM'),
  ('cornell-android-course', 'spring-2025', '-t67tvKghSQ'),
  ('cornell-android-course', 'spring-2025', '6sPTzvw8JNk'),
  ('cornell-android-course', 'spring-2025', 'LY9e7PvTZH0'),
  ('cornell-android-course', 'fall-2024', 'r2t59qN5uHM'),
  ('cornell-android-course', 'fall-2024', 'EKlThtzdSak'),
  ('cornell-android-course', 'fall-2024', 'bitltGz7_yM'),
  ('cornell-android-course', 'fall-2024', 'ncZYovxdDIA'),
  ('cornell-android-course', 'fall-2024', 'Su_-GcFpY18'),
  ('cornell-android-course', 'fall-2024', 'llTohaKL_7Y'),
  ('cornell-android-course', 'fall-2024', 'elfX3fMqTkA'),
  ('cornell-android-course', 'fall-2024', 'IILAuo8nZGY'),
  ('cornell-android-course', 'fall-2024', 'Bc2Hu8mA-44'),
  ('cornell-android-course', 'fall-2024', 'sLa4zDLIC10'),
  ('cornell-android-course', 'fall-2024', 'vbGMOYKulv8'),
  ('cornell-android-course', 'fall-2024', 'jz-mhdVnU2E'),
  ('cornell-android-course', 'fall-2024', 'NkMKEhXsYU4')
) AS v("course_slug", "edition_slug", "youtube_id")
JOIN "courses" c ON c."slug" = v."course_slug"
JOIN "course_editions" e ON e."course_id" = c."id" AND e."slug" = v."edition_slug"
JOIN "lesson_videos" lv ON lv."provider" = 'youtube' AND lv."external_id" = v."youtube_id"
WHERE l."id" = lv."lesson_id" AND l."course_id" = c."id" AND l."edition_id" IS NULL;--> statement-breakpoint
-- Every other lesson: its course's newest edition (the only one, except for Cornell).
UPDATE "lessons" l SET "edition_id" = e."id"
FROM "course_editions" e
WHERE l."edition_id" IS NULL AND e."course_id" = l."course_id" AND e."position" = 1;--> statement-breakpoint
-- Order is per edition now: renumber 1..N inside each edition, keeping the relative order (no-op where it already holds).
DROP INDEX IF EXISTS "lessons_course_position";--> statement-breakpoint
UPDATE "lessons" l SET "position" = r."position"
FROM (SELECT "id", row_number() OVER (PARTITION BY "edition_id" ORDER BY "position", "id")::int AS "position" FROM "lessons") r
WHERE l."id" = r."id" AND l."position" <> r."position";--> statement-breakpoint
ALTER TABLE "lessons" ALTER COLUMN "edition_id" SET NOT NULL;--> statement-breakpoint
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'lessons_edition_course_fk') THEN
    ALTER TABLE "lessons" ADD CONSTRAINT "lessons_edition_course_fk" FOREIGN KEY ("edition_id","course_id") REFERENCES "public"."course_editions"("id","course_id") ON DELETE restrict ON UPDATE no action;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'lessons_part') THEN
    ALTER TABLE "lessons" ADD CONSTRAINT "lessons_part" CHECK ("lessons"."part" IN ('lectures', 'labs'));
  END IF;
END $$;--> statement-breakpoint
CREATE UNIQUE INDEX IF NOT EXISTS "lessons_edition_position" ON "lessons" USING btree ("edition_id","position");