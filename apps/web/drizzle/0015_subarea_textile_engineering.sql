-- 0015 (ADR-26, append-only): Textile Engineering subarea, needed by the NPTEL courses (17/10/2026). Idempotent.
INSERT INTO "subject_subareas" ("id", "area_id", "title", "position") VALUES
  ('textile-engineering', 'engineering', 'Textile Engineering', 17)
ON CONFLICT ("id") DO NOTHING;
