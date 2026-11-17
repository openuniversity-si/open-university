import { describe, expect, it, vi } from "vitest";

vi.mock("next/headers", () => ({ draftMode: () => Promise.resolve({ isEnabled: false }), cookies: () => Promise.resolve({ get: () => undefined }) }));
import { fakeCatalog as catalog, TEST_EDITIONS_COURSE } from "@/catalog/testing/fake";
import { homeCourses } from "@/catalog/domain/home";
import { courseBySlug, lessonBySlug } from "@/catalog/domain/queries";
import { PUBLIC_STATIC_ROUTES } from "@/site/domain/route-registry";
import sitemap, { revalidate } from "./sitemap.ts";

const ORIGIN = "https://openuniversity.si";

/** Static pages, plus mirrors of the notFound() safety nets of the course and lesson pages, so every URL renders 200. */
function servedPath(path: string): boolean {
  if ((PUBLIC_STATIC_ROUTES as readonly string[]).includes(path)) return true;
  const [, c, courseSlug, lessonSlug, ...rest] = path.split("/");
  if (c !== "c" || courseSlug === undefined || rest.length > 0) return false;
  const course = courseBySlug(catalog, courseSlug);
  if (!course || !catalog.authors.some((author) => author.id === course.authorId)) return false;
  if (lessonSlug === undefined) return homeCourses(catalog).has(course.id);
  const lesson = lessonBySlug(catalog, course.id, lessonSlug);
  return lesson !== undefined;
}

// vitest maps @tower/catalog to the fake: the snapshot release plus the two-edition test course.
const urls = (await sitemap()).map((entry) => entry.url);

describe("sitemap", () => {
  it("is cached for an hour (purged by releases too), not rendered per crawler request", () => {
    expect(revalidate).toBe(3600);
  });

  it("lists the home, the static pages, every course and every lesson exactly once", () => {
    expect(urls).toHaveLength(PUBLIC_STATIC_ROUTES.length + catalog.courses.length + catalog.lessons.length);
    expect(urls).toHaveLength(1 + 2 + 5 + 6 + 131); // Home, the two tabs, five static pages, courses, lessons
    expect(urls).toContain(`${ORIGIN}/universities`);
    expect(urls).toContain(`${ORIGIN}/authors`);
    // A course with editions is one page and one entry; its lessons keep /c/<course>/<lesson> (ADR-21).
    expect(urls.filter((url) => url === `${ORIGIN}/c/${TEST_EDITIONS_COURSE.slug}`)).toHaveLength(1);
    expect(new Set(urls).size).toBe(urls.length);
    expect(urls.slice(0, 7)).toEqual(["/", "/universities", "/authors", "/privacy", "/terms", "/contact", "/about"].map((path) => `${ORIGIN}${path}`));
    for (const course of catalog.courses) expect(urls).toContain(`${ORIGIN}/c/${course.slug}`);
    for (const lesson of catalog.lessons) {
      const course = catalog.courses.find((entry) => entry.id === lesson.courseId);
      expect(urls).toContain(`${ORIGIN}/c/${course?.slug ?? ""}/${lesson.slug}`);
    }
  });

  it("only has absolute openuniversity.si URLs that the app routes serve", () => {
    for (const url of urls) {
      expect(url.startsWith(`${ORIGIN}/`), url).toBe(true);
      expect(servedPath(url.slice(ORIGIN.length)), url).toBe(true);
    }
  });
});
