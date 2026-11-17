ALTER TABLE "authors" ALTER COLUMN "kind" DROP DEFAULT;--> statement-breakpoint
ALTER TABLE "courses" ADD COLUMN "institution_id" text;--> statement-breakpoint
ALTER TABLE "home_rows" ADD COLUMN "institution_id" text;--> statement-breakpoint
-- D-024: each University row is the fact for its institution (slug = row id, name = row title). An existing
-- institution with that slug is reused; a person or channel holding the slug leaves the row unlinked and the CHECK stops.
INSERT INTO authors (id, slug, name, monogram, kind)
SELECT r.id, r.id, r.title, upper(left(coalesce(nullif(array_to_string(ARRAY(
         SELECT left(w, 1) FROM regexp_split_to_table(coalesce(r.full_name, r.title), '[^A-Za-z]+') AS w WHERE w ~ '^[A-Z]'), ''), ''), r.title), 3)),
       'institution'
FROM home_rows r WHERE r.kind = 'curated' AND NOT EXISTS (SELECT 1 FROM authors a WHERE a.slug = r.id);
--> statement-breakpoint
UPDATE home_rows r SET institution_id = a.id FROM authors a
WHERE r.kind = 'curated' AND a.slug = r.id AND a.kind = 'institution';
--> statement-breakpoint
-- A course takes the institution of its one University row; author_id stays its lecturer. A course in two rows is
-- left unset and the final check below stops the migration instead of guessing.
UPDATE courses c SET institution_id = r.institution_id
FROM home_row_items i JOIN home_rows r ON r.id = i.row_id AND r.kind = 'curated'
WHERE i.course_id = c.id AND NOT EXISTS (
  SELECT 1 FROM home_row_items other JOIN home_rows o ON o.id = other.row_id AND o.kind = 'curated'
  WHERE other.course_id = c.id AND o.id <> r.id
);
--> statement-breakpoint
ALTER TABLE "courses" ADD CONSTRAINT "courses_institution_id_authors_id_fk" FOREIGN KEY ("institution_id") REFERENCES "public"."authors"("id") ON DELETE restrict ON UPDATE no action;--> statement-breakpoint
CREATE INDEX "courses_institution" ON "courses" USING btree ("institution_id");--> statement-breakpoint
ALTER TABLE "home_rows" ADD CONSTRAINT "home_rows_institution_id_authors_id_fk" FOREIGN KEY ("institution_id") REFERENCES "public"."authors"("id") ON DELETE restrict ON UPDATE no action;--> statement-breakpoint
CREATE UNIQUE INDEX "home_rows_institution_unique" ON "home_rows" USING btree ("institution_id") WHERE "home_rows"."kind" = 'curated';--> statement-breakpoint
ALTER TABLE "courses" ADD CONSTRAINT "courses_published_area" CHECK ("courses"."status" <> 'published' OR "courses"."area_id" IS NOT NULL);--> statement-breakpoint
ALTER TABLE "home_rows" ADD CONSTRAINT "home_rows_institution" CHECK (("home_rows"."kind" = 'curated') = ("home_rows"."institution_id" IS NOT NULL));
--> statement-breakpoint
-- Institutions and their own university rows can share bytes, but each owns its attachment.
INSERT INTO catalog_media (id, owner_kind, owner_id, kind, variant, media_sha256, url, pathname, width, height, sha256, alt, transform, design_status, version, is_active)
SELECT 'hierarchy:' || r.institution_id, 'institution', r.institution_id, 'poster_9x16', 'default', m.media_sha256,
       m.url, m.pathname, m.width, m.height, m.sha256, m.alt, m.transform, m.design_status,
       coalesce((SELECT max(previous.version) FROM catalog_media previous WHERE previous.owner_kind = 'institution' AND previous.owner_id = r.institution_id AND previous.kind = 'poster_9x16' AND previous.variant = 'default'), 0) + 1, true
FROM home_rows r JOIN catalog_media m ON m.owner_kind = 'institution' AND m.owner_id = r.id
  AND m.kind = 'university_cover_9x16' AND m.variant = 'default' AND m.is_active
WHERE r.kind = 'curated' AND NOT EXISTS (
  SELECT 1 FROM catalog_media own WHERE own.owner_kind = 'institution' AND own.owner_id = r.institution_id
    AND own.kind IN ('poster_9x16', 'author_cover_9x16') AND own.variant = 'default' AND own.is_active
);
--> statement-breakpoint
CREATE OR REPLACE FUNCTION catalog_assert_institution_cover(institution text) RETURNS void LANGUAGE plpgsql AS $$
BEGIN
  -- Serialize checks on this institution, including concurrent publish and cover removal.
  PERFORM 1 FROM authors WHERE id = institution FOR NO KEY UPDATE;
  -- D-024: a University row and a course point at an institution, never at a lecturer.
  IF EXISTS (SELECT 1 FROM authors WHERE id = institution AND kind <> 'institution') AND (
    EXISTS (SELECT 1 FROM home_rows WHERE kind = 'curated' AND institution_id = institution)
    OR EXISTS (SELECT 1 FROM courses WHERE institution_id = institution)
  ) THEN
    RAISE EXCEPTION 'Only an institution can own a University row or offer a course: %', institution
      USING ERRCODE = '23514', CONSTRAINT = 'catalog_institution_kind';
  END IF;
  IF EXISTS (
    SELECT 1 FROM home_rows r JOIN home_row_items i ON i.row_id = r.id JOIN courses c ON c.id = i.course_id
    WHERE r.kind = 'curated' AND r.institution_id = institution AND c.institution_id IS DISTINCT FROM institution
  ) THEN
    RAISE EXCEPTION 'A university row cannot group institutions: %', institution
      USING ERRCODE = '23514', CONSTRAINT = 'home_rows_institution_courses';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM courses WHERE institution IN (author_id, institution_id) AND status = 'published') THEN RETURN; END IF;
  IF EXISTS (
    SELECT 1 FROM home_rows r WHERE r.visible AND coalesce(r.institution_id, r.author_id) = institution
    AND (
      NOT EXISTS (SELECT 1 FROM catalog_media m WHERE m.owner_kind = 'institution' AND m.owner_id = institution
        AND m.kind IN ('poster_9x16', 'author_cover_9x16') AND m.variant = 'default' AND m.is_active)
      OR (r.kind = 'curated' AND NOT EXISTS (
        SELECT 1 FROM catalog_media m WHERE m.owner_kind = 'institution' AND m.owner_id = r.id
          AND m.kind = 'university_cover_9x16' AND m.variant = 'default' AND m.is_active))
    )
  ) THEN
    RAISE EXCEPTION 'Visible institution and university row need their own active cover: %', institution
      USING ERRCODE = '23514', CONSTRAINT = 'catalog_institution_cover';
  END IF;
END;
$$;
--> statement-breakpoint
CREATE OR REPLACE FUNCTION catalog_institution_cover() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE owner text;
BEGIN
  IF TG_TABLE_NAME = 'authors' THEN
    IF TG_OP <> 'INSERT' THEN PERFORM catalog_assert_institution_cover(OLD.id); END IF;
    IF TG_OP <> 'DELETE' THEN PERFORM catalog_assert_institution_cover(NEW.id); END IF;
  ELSIF TG_TABLE_NAME = 'courses' THEN
    IF TG_OP <> 'INSERT' THEN
      PERFORM catalog_assert_institution_cover(OLD.author_id);
      PERFORM catalog_assert_institution_cover(OLD.institution_id);
    END IF;
    IF TG_OP <> 'DELETE' THEN
      PERFORM catalog_assert_institution_cover(NEW.author_id);
      PERFORM catalog_assert_institution_cover(NEW.institution_id);
    END IF;
  ELSIF TG_TABLE_NAME = 'home_rows' THEN
    IF TG_OP <> 'INSERT' THEN PERFORM catalog_assert_institution_cover(coalesce(OLD.institution_id, OLD.author_id)); END IF;
    IF TG_OP <> 'DELETE' THEN PERFORM catalog_assert_institution_cover(coalesce(NEW.institution_id, NEW.author_id)); END IF;
  ELSIF TG_TABLE_NAME = 'home_row_items' THEN
    IF TG_OP <> 'INSERT' THEN
      SELECT coalesce(institution_id, author_id) INTO owner FROM home_rows WHERE id = OLD.row_id;
      PERFORM catalog_assert_institution_cover(owner);
    END IF;
    IF TG_OP <> 'DELETE' THEN
      SELECT coalesce(institution_id, author_id) INTO owner FROM home_rows WHERE id = NEW.row_id;
      PERFORM catalog_assert_institution_cover(owner);
    END IF;
  ELSIF TG_TABLE_NAME = 'catalog_media' THEN
    IF TG_OP <> 'INSERT' AND OLD.owner_kind = 'institution' THEN
      FOR owner IN SELECT id FROM authors WHERE id = OLD.owner_id UNION SELECT coalesce(institution_id, author_id) FROM home_rows WHERE id = OLD.owner_id LOOP
        PERFORM catalog_assert_institution_cover(owner);
      END LOOP;
    END IF;
    IF TG_OP <> 'DELETE' AND NEW.owner_kind = 'institution' THEN
      FOR owner IN SELECT id FROM authors WHERE id = NEW.owner_id UNION SELECT coalesce(institution_id, author_id) FROM home_rows WHERE id = NEW.owner_id LOOP
        PERFORM catalog_assert_institution_cover(owner);
      END LOOP;
    END IF;
  END IF;
  RETURN NULL;
END;
$$;
--> statement-breakpoint
CREATE CONSTRAINT TRIGGER catalog_institution_cover AFTER INSERT OR UPDATE OR DELETE ON authors DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION catalog_institution_cover();
--> statement-breakpoint
CREATE CONSTRAINT TRIGGER catalog_institution_cover AFTER INSERT OR UPDATE OR DELETE ON courses DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION catalog_institution_cover();
--> statement-breakpoint
CREATE CONSTRAINT TRIGGER catalog_institution_cover AFTER INSERT OR UPDATE OR DELETE ON home_rows DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION catalog_institution_cover();
--> statement-breakpoint
CREATE CONSTRAINT TRIGGER catalog_institution_cover AFTER INSERT OR UPDATE OR DELETE ON home_row_items DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION catalog_institution_cover();
--> statement-breakpoint
CREATE CONSTRAINT TRIGGER catalog_institution_cover AFTER INSERT OR UPDATE OR DELETE ON catalog_media DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION catalog_institution_cover();
--> statement-breakpoint
-- Verify current data as well as future transactions. Never invent areas or silently unpublish a course.
SELECT catalog_assert_institution_cover(id) FROM authors;
