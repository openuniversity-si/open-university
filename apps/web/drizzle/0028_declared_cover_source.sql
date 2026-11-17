ALTER TABLE "courses" ADD COLUMN "cover_from" text;--> statement-breakpoint
-- D-031. The old provisional flag is the declaration, not a walk: a subarea when one is set, otherwise the area, otherwise own.
-- A published course whose declared owner lacks a required kind is held. Institution media is never an input.
WITH kinds AS (
  SELECT owner_kind, owner_id, array_agg(DISTINCT kind) AS kinds
  FROM catalog_media
  WHERE is_active AND variant = 'default' AND owner_kind IN ('course', 'subarea', 'area')
  GROUP BY owner_kind, owner_id
),
declared AS (
  SELECT c.id, c.status AS old_status, c.cover_provisional,
    CASE
      WHEN c.cover_provisional AND c.subarea_id IS NOT NULL THEN 'subarea:' || c.subarea_id
      WHEN c.cover_provisional AND c.area_id IS NOT NULL THEN 'area:' || c.area_id
      ELSE 'own'
    END AS cover_from,
    CASE
      WHEN c.cover_provisional AND c.subarea_id IS NOT NULL THEN COALESCE((SELECT k.kinds FROM kinds k WHERE k.owner_kind = 'subarea' AND k.owner_id = c.subarea_id), ARRAY[]::text[])
      WHEN c.cover_provisional AND c.area_id IS NOT NULL THEN COALESCE((SELECT k.kinds FROM kinds k WHERE k.owner_kind = 'area' AND k.owner_id = c.area_id), ARRAY[]::text[])
      ELSE COALESCE((SELECT k.kinds FROM kinds k WHERE k.owner_kind = 'course' AND k.owner_id = c.id), ARRAY[]::text[])
    END AS owner_kinds
  FROM courses c
),
missing AS (
  SELECT id, old_status, cover_provisional, cover_from,
    ARRAY(
      SELECT required FROM unnest(ARRAY['poster_9x16', 'hero_desktop_16x9', 'hero_present', 'hero_mobile_9x16']) AS required
      WHERE NOT (required = ANY (owner_kinds))
    ) AS missing
  FROM declared
),
updated AS (
  UPDATE courses AS c
  SET cover_from = m.cover_from,
      status = CASE WHEN m.old_status = 'published' AND cardinality(m.missing) > 0 THEN 'draft' ELSE c.status END,
      published_at = CASE WHEN m.old_status = 'published' AND cardinality(m.missing) > 0 THEN NULL ELSE c.published_at END,
      revision = CASE WHEN m.old_status = 'published' AND cardinality(m.missing) > 0 THEN c.revision + 1 ELSE c.revision END
  FROM missing AS m
  WHERE c.id = m.id
  RETURNING c.id, m.old_status, m.cover_provisional, m.cover_from, m.missing
)
INSERT INTO catalog_audit (actor, request_id, action, entity_kind, entity_id, before, after)
SELECT 'migration-0028', 'migration-0028', 'cover.backfill', 'course', id,
  jsonb_build_object('status', old_status, 'coverProvisional', cover_provisional),
  jsonb_build_object(
    'coverFrom', cover_from,
    'status', CASE WHEN old_status = 'published' THEN 'draft' ELSE old_status END,
    'reason', 'missing ' || array_to_string(missing, ',')
  )
FROM updated
WHERE cardinality(missing) > 0;--> statement-breakpoint
-- The deferred institution-cover trigger is still pending; ALTER TABLE refuses until it runs.
SET CONSTRAINTS ALL IMMEDIATE;--> statement-breakpoint
ALTER TABLE "courses" ALTER COLUMN "cover_from" SET NOT NULL;--> statement-breakpoint
ALTER TABLE "courses" ADD CONSTRAINT "courses_cover_from" CHECK ("courses"."cover_from" ~ '^(own|subarea:[a-z0-9]+(?:-[a-z0-9]+)*|area:[a-z0-9]+(?:-[a-z0-9]+)*)$');--> statement-breakpoint
CREATE FUNCTION "public"."courses_cover_from_owner"() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.cover_from = 'own' THEN
    RETURN NEW;
  END IF;
  IF NEW.cover_from LIKE 'subarea:%' THEN
    IF NEW.subarea_id IS DISTINCT FROM substr(NEW.cover_from, 9) THEN
      RAISE EXCEPTION 'coverFrom % is not the course subarea', NEW.cover_from USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
  END IF;
  IF NEW.cover_from LIKE 'area:%' THEN
    IF NEW.subarea_id IS NOT NULL OR NEW.area_id IS DISTINCT FROM substr(NEW.cover_from, 6) THEN
      RAISE EXCEPTION 'coverFrom % is not the course area', NEW.cover_from USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
  END IF;
  RAISE EXCEPTION 'coverFrom % is not own, subarea or area', NEW.cover_from USING ERRCODE = '23514';
END $$;--> statement-breakpoint
CREATE TRIGGER "courses_cover_from_owner" BEFORE INSERT OR UPDATE OF cover_from, area_id, subarea_id ON "courses" FOR EACH ROW EXECUTE FUNCTION "public"."courses_cover_from_owner"();--> statement-breakpoint
ALTER TABLE "courses" DROP COLUMN "cover_provisional";
