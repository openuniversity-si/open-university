import { describe, expect, it } from "vitest";
import { canonicalJson, sha256Hex } from "../../kernel/canonical.ts";
import { syntheticCatalog, syntheticTables } from "../testing/synthetic.ts";
import { compileRelease } from "./compile.ts";
import { TEXT_FIELDS } from "./fields.ts";
import { courseReleaseTextSchema, lessonReleaseTextSchema, RELEASE_SCHEMA_VERSION } from "./release.ts";

const COURSE_TEXT_ORDER = [
  "displayTitle", "shelfTitle", "subtitle", "billboardDescription", "billboardDescriptionMobile",
  "description", "descriptionMobile", "about", "level", "format",
] as const;

function textProjection(release: typeof syntheticCatalog) {
  const courseNames = Object.keys(TEXT_FIELDS.course);
  const lessonNames = Object.keys(TEXT_FIELDS.lesson);
  const pick = (entity: object, names: readonly string[]) => {
    const record = entity as Record<string, unknown>;
    const order = Object.keys(record).filter((key) => names.includes(key));
    return { order, values: Object.fromEntries(order.map((key) => [key, record[key]])) };
  };
  return {
    courses: release.courses.map((course) => pick(course, courseNames)),
    lessons: release.lessons.map((lesson) => pick(lesson, lessonNames)),
  };
}

describe("release text reads the leaf", () => {
  it("compiles the same text keys, in the same order, as the release already stored for the test catalog", () => {
    const compiled = compileRelease(syntheticTables(), { number: syntheticCatalog.number, publishedAt: syntheticCatalog.publishedAt });
    const projection = textProjection(compiled);
    expect(sha256Hex(canonicalJson(projection))).toBe("f53595d0b1292accb7018898b66917e17ed79f20c4252e20108b95174ed2af3f");
    expect(projection.courses[0]?.order).toEqual([...COURSE_TEXT_ORDER]);
    expect(projection.lessons[0]?.order).toEqual(["displayTitle", "about"]);
    expect(compiled.schemaVersion).toBe(RELEASE_SCHEMA_VERSION);
  });

  it("rejects a text key the leaf does not have and accepts a null about", () => {
    const course = {
      displayTitle: "Title", shelfTitle: "Shelf", subtitle: "Subtitle", billboardDescription: "Billboard",
      billboardDescriptionMobile: "Mobile", description: "Description", descriptionMobile: "Mobile description",
      about: null, level: "Intro", format: "Lecture",
    };
    expect(courseReleaseTextSchema.safeParse(course).success).toBe(true);
    expect(courseReleaseTextSchema.safeParse({ ...course, summary: "Later" }).success).toBe(false);
    expect(lessonReleaseTextSchema.safeParse({ displayTitle: "Title", about: null }).success).toBe(true);
    expect(lessonReleaseTextSchema.safeParse({ displayTitle: "Title" }).success).toBe(false);
    expect(lessonReleaseTextSchema.safeParse({ displayTitle: "Title", about: null, summary: "Later" }).success).toBe(false);
  });
});
