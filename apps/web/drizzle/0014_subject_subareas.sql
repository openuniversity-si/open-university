-- 0014 (ADR-26): optional subareas of a subject area and an optional subarea per course. Additive, idempotent.
-- Taxonomy: src/catalog/subareas.ts = docs/catalog/subareas.md = this seed (subareas.test.ts keeps them identical).
CREATE TABLE IF NOT EXISTS "subject_subareas" (
	"id" text PRIMARY KEY NOT NULL,
	"area_id" text NOT NULL,
	"title" text NOT NULL,
	"position" integer NOT NULL,
	CONSTRAINT "subject_subareas_id" CHECK ("subject_subareas"."id" ~ '^[a-z0-9]+(?:-[a-z0-9]+)*$'),
	CONSTRAINT "subject_subareas_position" CHECK ("subject_subareas"."position" > 0)
);
--> statement-breakpoint
ALTER TABLE "courses" ADD COLUMN IF NOT EXISTS "subarea_id" text;--> statement-breakpoint
DO $$ BEGIN
  ALTER TABLE "subject_subareas" ADD CONSTRAINT "subject_subareas_area_id_subject_areas_id_fk" FOREIGN KEY ("area_id") REFERENCES "public"."subject_areas"("id") ON DELETE restrict ON UPDATE no action;
EXCEPTION WHEN duplicate_object THEN NULL; END $$;--> statement-breakpoint
CREATE UNIQUE INDEX IF NOT EXISTS "subject_subareas_area_position_unique" ON "subject_subareas" USING btree ("area_id","position");--> statement-breakpoint
CREATE UNIQUE INDEX IF NOT EXISTS "subject_subareas_area_id_unique" ON "subject_subareas" USING btree ("area_id","id");--> statement-breakpoint
CREATE UNIQUE INDEX IF NOT EXISTS "subject_subareas_title_unique" ON "subject_subareas" USING btree ("title");--> statement-breakpoint
-- A course's subarea must belong to the course's own area (composite key) and needs an area at all (check).
DO $$ BEGIN
  ALTER TABLE "courses" ADD CONSTRAINT "courses_subarea_area_fk" FOREIGN KEY ("area_id","subarea_id") REFERENCES "public"."subject_subareas"("area_id","id") ON DELETE restrict ON UPDATE no action;
EXCEPTION WHEN duplicate_object THEN NULL; END $$;--> statement-breakpoint
DO $$ BEGIN
  ALTER TABLE "courses" ADD CONSTRAINT "courses_subarea_area" CHECK ("courses"."subarea_id" IS NULL OR "courses"."area_id" IS NOT NULL);
EXCEPTION WHEN duplicate_object THEN NULL; END $$;--> statement-breakpoint
-- The v1 taxonomy (SUBAREAS-v1), fixed order inside each area.
INSERT INTO "subject_subareas" ("id", "area_id", "title", "position") VALUES
  ('programming', 'computer-science', 'Programming', 1),
  ('algorithms', 'computer-science', 'Algorithms', 2),
  ('computer-systems', 'computer-science', 'Computer Systems', 3),
  ('databases', 'computer-science', 'Databases', 4),
  ('computer-networks', 'computer-science', 'Computer Networks', 5),
  ('computer-security', 'computer-science', 'Computer Security', 6),
  ('software-engineering', 'computer-science', 'Software Engineering', 7),
  ('computer-graphics', 'computer-science', 'Computer Graphics', 8),
  ('machine-learning', 'artificial-intelligence', 'Machine Learning', 1),
  ('deep-learning', 'artificial-intelligence', 'Deep Learning', 2),
  ('natural-language-processing', 'artificial-intelligence', 'Natural Language Processing', 3),
  ('computer-vision', 'artificial-intelligence', 'Computer Vision', 4),
  ('reinforcement-learning', 'artificial-intelligence', 'Reinforcement Learning', 5),
  ('calculus', 'mathematics', 'Calculus', 1),
  ('linear-algebra', 'mathematics', 'Linear Algebra', 2),
  ('differential-equations', 'mathematics', 'Differential Equations', 3),
  ('analysis', 'mathematics', 'Analysis', 4),
  ('algebra', 'mathematics', 'Algebra', 5),
  ('geometry', 'mathematics', 'Geometry', 6),
  ('discrete-mathematics', 'mathematics', 'Discrete Mathematics', 7),
  ('optimization', 'mathematics', 'Optimization', 8),
  ('numerical-analysis', 'mathematics', 'Numerical Analysis', 9),
  ('probability', 'statistics', 'Probability', 1),
  ('statistical-inference', 'statistics', 'Statistical Inference', 2),
  ('data-analysis', 'statistics', 'Data Analysis', 3),
  ('classical-mechanics', 'physics', 'Classical Mechanics', 1),
  ('electromagnetism', 'physics', 'Electromagnetism', 2),
  ('quantum-mechanics', 'physics', 'Quantum Mechanics', 3),
  ('statistical-mechanics', 'physics', 'Statistical Mechanics', 4),
  ('relativity', 'physics', 'Relativity', 5),
  ('condensed-matter-physics', 'physics', 'Condensed Matter Physics', 6),
  ('particle-physics', 'physics', 'Particle Physics', 7),
  ('optics', 'physics', 'Optics', 8),
  ('organic-chemistry', 'chemistry', 'Organic Chemistry', 1),
  ('inorganic-chemistry', 'chemistry', 'Inorganic Chemistry', 2),
  ('physical-chemistry', 'chemistry', 'Physical Chemistry', 3),
  ('analytical-chemistry', 'chemistry', 'Analytical Chemistry', 4),
  ('biochemistry', 'chemistry', 'Biochemistry', 5),
  ('mechanical-engineering', 'engineering', 'Mechanical Engineering', 1),
  ('electrical-engineering', 'engineering', 'Electrical Engineering', 2),
  ('electronics-engineering', 'engineering', 'Electronics Engineering', 3),
  ('communications-engineering', 'engineering', 'Communications Engineering', 4),
  ('signal-processing', 'engineering', 'Signal Processing', 5),
  ('control-engineering', 'engineering', 'Control Engineering', 6),
  ('robotics', 'engineering', 'Robotics', 7),
  ('civil-engineering', 'engineering', 'Civil Engineering', 8),
  ('environmental-engineering', 'engineering', 'Environmental Engineering', 9),
  ('chemical-engineering', 'engineering', 'Chemical Engineering', 10),
  ('materials-engineering', 'engineering', 'Materials Engineering', 11),
  ('manufacturing-engineering', 'engineering', 'Manufacturing Engineering', 12),
  ('aerospace-engineering', 'engineering', 'Aerospace Engineering', 13),
  ('ocean-engineering', 'engineering', 'Ocean Engineering', 14),
  ('biomedical-engineering', 'engineering', 'Biomedical Engineering', 15),
  ('engineering-design', 'engineering', 'Engineering Design', 16),
  ('molecular-biology', 'biology', 'Molecular Biology', 1),
  ('cell-biology', 'biology', 'Cell Biology', 2),
  ('genetics', 'biology', 'Genetics', 3),
  ('microbiology', 'biology', 'Microbiology', 4),
  ('immunology', 'biology', 'Immunology', 5),
  ('evolution', 'biology', 'Evolution', 6),
  ('ecology', 'biology', 'Ecology', 7),
  ('biotechnology', 'biology', 'Biotechnology', 8),
  ('microeconomics', 'economics', 'Microeconomics', 1),
  ('macroeconomics', 'economics', 'Macroeconomics', 2),
  ('econometrics', 'economics', 'Econometrics', 3),
  ('game-theory', 'economics', 'Game Theory', 4),
  ('development-economics', 'economics', 'Development Economics', 5),
  ('public-economics', 'economics', 'Public Economics', 6),
  ('management', 'business', 'Management', 1),
  ('marketing', 'business', 'Marketing', 2),
  ('operations-management', 'business', 'Operations Management', 3),
  ('human-resources', 'business', 'Human Resources', 4),
  ('ancient-history', 'history', 'Ancient History', 1),
  ('european-history', 'history', 'European History', 2),
  ('american-history', 'history', 'American History', 3),
  ('history-of-science', 'history', 'History of Science', 4),
  ('geology', 'earth-sciences', 'Geology', 1),
  ('oceanography', 'earth-sciences', 'Oceanography', 2),
  ('atmospheric-science', 'earth-sciences', 'Atmospheric Science', 3),
  ('hydrology', 'earth-sciences', 'Hydrology', 4)
ON CONFLICT ("id") DO NOTHING;
