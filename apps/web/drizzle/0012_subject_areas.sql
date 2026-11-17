-- 0012 (ADR-25): the global subject areas (src/catalog/areas.ts, docs/catalog/areas.md) and one area per course. Additive, idempotent.
CREATE TABLE IF NOT EXISTS "subject_areas" (
	"id" text PRIMARY KEY NOT NULL,
	"title" text NOT NULL,
	"position" integer NOT NULL,
	CONSTRAINT "subject_areas_id" CHECK ("subject_areas"."id" ~ '^[a-z0-9]+(?:-[a-z0-9]+)*$'),
	CONSTRAINT "subject_areas_position" CHECK ("subject_areas"."position" > 0)
);
--> statement-breakpoint
ALTER TABLE "courses" ADD COLUMN IF NOT EXISTS "area_id" text;--> statement-breakpoint
CREATE UNIQUE INDEX IF NOT EXISTS "subject_areas_position_unique" ON "subject_areas" USING btree ("position");--> statement-breakpoint
CREATE UNIQUE INDEX IF NOT EXISTS "subject_areas_title_unique" ON "subject_areas" USING btree ("title");--> statement-breakpoint
DO $$ BEGIN
  ALTER TABLE "courses" ADD CONSTRAINT "courses_area_id_subject_areas_id_fk" FOREIGN KEY ("area_id") REFERENCES "public"."subject_areas"("id") ON DELETE restrict ON UPDATE no action;
EXCEPTION WHEN duplicate_object THEN NULL; END $$;--> statement-breakpoint
-- The 30 areas in their fixed order (areas.test.ts keeps this list, areas.ts and the doc identical).
INSERT INTO "subject_areas" ("id", "title", "position") VALUES
  ('computer-science', 'Computer Science', 1),
  ('artificial-intelligence', 'Artificial Intelligence', 2),
  ('mathematics', 'Mathematics', 3),
  ('statistics', 'Statistics', 4),
  ('physics', 'Physics', 5),
  ('chemistry', 'Chemistry', 6),
  ('astronomy', 'Astronomy', 7),
  ('earth-sciences', 'Earth Sciences', 8),
  ('engineering', 'Engineering', 9),
  ('energy', 'Energy', 10),
  ('biology', 'Biology', 11),
  ('medicine', 'Medicine', 12),
  ('psychology', 'Psychology', 13),
  ('neuroscience', 'Neuroscience', 14),
  ('economics', 'Economics', 15),
  ('finance', 'Finance', 16),
  ('business', 'Business', 17),
  ('entrepreneurship', 'Entrepreneurship', 18),
  ('political-science', 'Political Science', 19),
  ('law', 'Law', 20),
  ('urban-planning', 'Urban Planning', 21),
  ('sociology', 'Sociology', 22),
  ('history', 'History', 23),
  ('philosophy', 'Philosophy', 24),
  ('religion', 'Religion', 25),
  ('literature', 'Literature', 26),
  ('linguistics', 'Linguistics', 27),
  ('music', 'Music', 28),
  ('art', 'Art', 29),
  ('film-and-media', 'Film & Media', 30)
ON CONFLICT ("id") DO NOTHING;
