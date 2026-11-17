DROP INDEX "lesson_videos_external";--> statement-breakpoint
ALTER TABLE "lesson_videos" ADD COLUMN "course_id" text;--> statement-breakpoint
UPDATE "lesson_videos" AS v SET "course_id" = l."course_id" FROM "lessons" AS l WHERE l."id" = v."lesson_id";--> statement-breakpoint
ALTER TABLE "lesson_videos" ALTER COLUMN "course_id" SET NOT NULL;--> statement-breakpoint
ALTER TABLE "lesson_videos" ADD CONSTRAINT "lesson_videos_course_id_courses_id_fk" FOREIGN KEY ("course_id") REFERENCES "public"."courses"("id") ON DELETE restrict ON UPDATE no action;--> statement-breakpoint
CREATE UNIQUE INDEX "lesson_videos_youtube_course" ON "lesson_videos" USING btree ("course_id","external_id") WHERE "lesson_videos"."provider" = 'youtube';--> statement-breakpoint
CREATE UNIQUE INDEX "lesson_videos_mux_external" ON "lesson_videos" USING btree ("provider","external_id") WHERE "lesson_videos"."provider" <> 'youtube';--> statement-breakpoint
CREATE FUNCTION "public"."lesson_videos_course_id"() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  SELECT course_id INTO NEW.course_id FROM lessons WHERE id = NEW.lesson_id;
  IF NEW.course_id IS NULL THEN
    RAISE EXCEPTION 'lesson_videos.lesson_id % has no course', NEW.lesson_id USING ERRCODE = '23503';
  END IF;
  RETURN NEW;
END $$;--> statement-breakpoint
CREATE TRIGGER "lesson_videos_course_id" BEFORE INSERT OR UPDATE ON "lesson_videos" FOR EACH ROW EXECUTE FUNCTION "public"."lesson_videos_course_id"();
