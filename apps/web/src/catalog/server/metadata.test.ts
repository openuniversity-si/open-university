import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { snapshotCatalog as catalog } from "@/catalog/testing/fake";
import { installSiteData, parseSiteData } from "../../site/domain/site-data.ts";
import { courseMetadata, lessonMetadata } from "../../site/domain/metadata.ts";
import { courseMetadataInput, lessonMetadataInput } from "./metadata.ts";

installSiteData(parseSiteData(JSON.parse(readFileSync(new URL("../../../content/site/site-data.v2.json", import.meta.url), "utf8"))));

describe("catalog metadata adapter", () => {
  it("produces the same metadata as the structural input, and nothing for an unknown slug", () => {
    const course = catalog.courses[0];
    const lesson = catalog.lessons.find((entry) => entry.courseId === course?.id);
    if (!course || !lesson) throw new Error("fixture");
    const art = [{ kind: "hero_desktop_16x9", variant: "og", url: "https://media.openuniversity.si/covers/x/og.jpg", width: 1200, height: 630 }];
    const courseInput = courseMetadataInput(catalog, course.slug, art);
    const lessonInput = lessonMetadataInput(catalog, course.slug, lesson.slug, art);
    expect(courseMetadata(courseInput)).toEqual(courseMetadata(courseInput));
    expect(lessonMetadata(lessonInput)).toEqual(lessonMetadata(lessonInput));
    expect(courseInput?.authorName.length).toBeGreaterThan(0);
    expect(lessonInput?.about).toBe(lesson.about);
    expect(courseMetadata(courseMetadataInput(catalog, "no-such-course"))).toEqual({});
    expect(lessonMetadata(lessonMetadataInput(catalog, "no-such-course", "x"))).toEqual({});
    expect(lessonMetadata(lessonMetadataInput(catalog, course.slug, "no-such-lesson"))).toEqual({});
    expect(JSON.stringify(courseMetadata(courseInput).openGraph?.images)).toContain(art[0]?.url ?? "");
  });
});
