ALTER TABLE "courses" ADD COLUMN "shared_with" text[];--> statement-breakpoint
-- D-032. A video already used by two courses is an explicit mutual share. Courses whose videos do not overlap declare none.
WITH pairs AS (
  SELECT DISTINCT la.course_id AS left_id, lb.course_id AS right_id
  FROM lesson_videos va
  JOIN lessons la ON la.id = va.lesson_id
  JOIN lesson_videos vb ON vb.provider = 'youtube' AND vb.external_id = va.external_id
  JOIN lessons lb ON lb.id = vb.lesson_id
  WHERE va.provider = 'youtube' AND la.course_id < lb.course_id
),
lists AS (
  SELECT id, array_agg(other ORDER BY other) AS shared_with
  FROM (
    SELECT left_id AS id, right_id AS other FROM pairs
    UNION ALL
    SELECT right_id AS id, left_id AS other FROM pairs
  ) side
  GROUP BY id
),
updated AS (
  UPDATE courses AS c
  SET shared_with = filled.shared_with
  FROM (
    SELECT every.id, coalesce(l.shared_with, ARRAY[]::text[]) AS shared_with
    FROM courses AS every
    LEFT JOIN lists l ON l.id = every.id
  ) AS filled
  WHERE c.id = filled.id
  RETURNING c.id, c.shared_with
)
INSERT INTO catalog_audit (actor, request_id, action, entity_kind, entity_id, before, after)
SELECT 'migration-0029', 'migration-0029', 'video.share.backfill', 'course', id,
  jsonb_build_object('sharedWith', '[]'::jsonb),
  jsonb_build_object('sharedWith', to_jsonb(shared_with))
FROM updated
WHERE cardinality(shared_with) > 0;--> statement-breakpoint
-- A deferred trigger from an earlier migration can still be pending; ALTER TABLE refuses until it runs.
SET CONSTRAINTS ALL IMMEDIATE;--> statement-breakpoint
ALTER TABLE "courses" ALTER COLUMN "shared_with" SET NOT NULL;--> statement-breakpoint
CREATE FUNCTION "public"."courses_shared_with_mutual"() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  other text;
  theirs text[];
BEGIN
  IF NEW.id = ANY (NEW.shared_with) THEN
    RAISE EXCEPTION 'A course does not declare a share with itself' USING ERRCODE = '23514';
  END IF;
  IF (SELECT count(*) FROM unnest(NEW.shared_with) AS item) <> (SELECT count(DISTINCT item) FROM unnest(NEW.shared_with) AS item) THEN
    RAISE EXCEPTION 'A share is declared once' USING ERRCODE = '23514';
  END IF;
  FOREACH other IN ARRAY NEW.shared_with LOOP
    SELECT shared_with INTO theirs FROM courses WHERE id = other;
    IF NOT FOUND OR NOT (NEW.id = ANY (theirs)) THEN
      RAISE EXCEPTION 'Course % does not declare the share with %', other, NEW.id USING ERRCODE = '23514';
    END IF;
  END LOOP;
  IF EXISTS (
    SELECT 1 FROM courses AS other
    WHERE other.id <> NEW.id AND NEW.id = ANY (other.shared_with) AND NOT (other.id = ANY (NEW.shared_with))
  ) THEN
    RAISE EXCEPTION 'A share with % is still declared by the other course', NEW.id USING ERRCODE = '23514';
  END IF;
  RETURN NULL;
END $$;--> statement-breakpoint
CREATE CONSTRAINT TRIGGER "courses_shared_with_mutual"
  AFTER INSERT OR UPDATE OF shared_with ON "courses"
  DEFERRABLE INITIALLY DEFERRED
  FOR EACH ROW EXECUTE FUNCTION "public"."courses_shared_with_mutual"();
