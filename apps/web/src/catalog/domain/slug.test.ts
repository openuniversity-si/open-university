import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { fixtureSlugs, type SlugFixture } from "../testing/slug-fixture.ts";
import { baseLessonSlug, cleanLessonSlug, cleanTitle, LESSON_SLUG_MAX, looksLikeTrailer, SLUG_PATTERN, slugify, uniqueLessonSlug, uniqueSlug, type LessonSlugInput } from "./lesson-address.ts";

const fixture = JSON.parse(readFileSync(new URL("../testing/slug.fixtures.json", import.meta.url), "utf8")) as SlugFixture;
const none = new Set<string>();

function course(slug: string, extra: Partial<LessonSlugInput> = {}): (youtubeTitle: string, displayTitle?: string) => string {
  const row = fixture.lessons.find((lesson) => lesson.courseSlug === slug);
  const context = fixture.courses[slug];
  return (youtubeTitle, displayTitle) => cleanLessonSlug({
    youtubeTitle, displayTitle: displayTitle ?? null, courseTitle: context?.title ?? "", courseSlug: slug, institution: context?.institution ?? null,
    edition: row?.edition ?? null, position: 1, kind: "lecture", ...extra,
  }, none);
}

/** Every input of the fixture, through both sources: the approved display title and the raw YouTube title (as an import sees it). */
const inputs: LessonSlugInput[] = fixture.lessons.flatMap((row) => {
  const context = { ...row, courseTitle: fixture.courses[row.courseSlug]?.title ?? "", institution: fixture.courses[row.courseSlug]?.institution ?? null };
  return [context, { ...context, displayTitle: null }];
});

describe("cleanLessonSlug: real titles (BRIEF-P7 §1)", () => {
  it("drops the course, institution and channel names around the YouTube title", () => {
    const db = course("cmu-intro-to-database-systems");
    expect(db("#01 - Relational Model & Algebra (CMU Intro to Database Systems)")).toBe("lecture-01-relational-model-algebra");
    expect(db("#03 - Database Storage: Files & Pages ✸ Guest Database Talk (CMU Intro to Database Systems)")).toBe("lecture-03-database-storage-files-pages");
    const energy = course("stanford-understand-energy");
    expect(energy("Oil Lecture | Diana Gragg | Stanford Understand Energy")).toBe("oil");
    expect(energy("Transportation Lecture Part 1 | Diana Gragg | Stanford Understand Energy")).toBe("transportation-part-1");
    expect(course("stanford-economics-of-transformative-ai")("01 Task-based models theory (The Economics of Transformative AI, August 2025)")).toBe("lecture-01-task-based-models-theory");
    expect(course("stanford-lung-cancer-journey")("MED 275 | Week 1: Dr. Bryant Lin’s Diagnosis & The Road Ahead")).toBe("week-01-dr-bryant-lins-diagnosis-the-road-ahead");
    expect(course("harvard-cs50x")("CS50x 2025 - Artificial Intelligence")).toBe("artificial-intelligence");
    expect(course("yale-america-at-250")("America at 250: A History, DeVane Lecture, Class 1 – The Road to 250")).toBe("lecture-01-the-road-to-250");
  });

  it("drops edition markers and bracket tags", () => {
    const android = course("cornell-android-course");
    expect(android("[FA24] Intro to Android: Bonus Lecture 2: Industry Standards")).toBe("bonus-lecture-02-industry-standards");
    expect(android("[FA24] Intro to Android L1.5 - The Beauty of Kotlin")).toBe("lecture-01-5-the-beauty-of-kotlin");
    expect(android("[SP25] Intro to Android: D1 - EateryCard")).toBe("demo-01-eaterycard");
    expect(android("x", "Spring 2025 · Lecture 1: Kotlin & Basic UI")).toBe("lecture-01-kotlin-basic-ui");
    expect(course("cmu-advanced-database-systems")("S2024 #00 - Course Overview & Logistics (CMU Advanced Database Systems)")).toBe("lecture-00-course-overview-logistics");
    expect(course("cmu-introduction-to-deep-learning")("IDL Spring 2024 : Lecture 1")).toBe("lecture-01");
  });

  it("keeps the lecture number as lecture-NN and prefers the approved display title", () => {
    const deep = course("mit-deep-learning");
    expect(deep("Lec 09. Hacker's Guide to Deep Learning")).toBe("lecture-09-hackers-guide-to-deep-learning");
    expect(deep("Lec 15. Generative Models: Representation Learning Meets Generative Modeling", "15: Generative Models and Representation Learning"))
      .toBe("lecture-15-generative-models-and-representation-learning");
    expect(course("yale-can-it-happen-here-again")("Class10, “Mexico Will Poison Us”: War of Conquest, the Compromise, and Kansas-Nebraska")).toBe("lecture-10-mexico-will-poison-us-war-of-conquest");
    expect(course("mit-social-problems-of-nuclear-energy")("Lecture 7: Can Renewables Decarbonize the U.S. Electricity Sector?")).toBe("lecture-07-can-renewables-decarbonize-the-us-electricity");
    expect(course("mit-perception")("x", "1: Introduction to Perception")).toBe("lecture-01-introduction-to-perception");
    expect(course("harvard-cs50x")("x", "  ")).toBe("lecture-01");
  });

  it("cuts at a word boundary within 60 characters, without a trailing hyphen or stopword", () => {
    const slug = course("yale-america-at-250")("x", "16: The Gilded Age and the Aftermath of Reconstruction");
    expect(slug).toBe("lecture-16-the-gilded-age-and-the-aftermath");
    expect(course("mit-perception")("x", "a".repeat(80))).toBe("a".repeat(LESSON_SLUG_MAX));
  });

  it("falls back to <kind>-NN by position when fewer than 3 useful characters are left", () => {
    const short = (title: string, kind = "lecture") => baseLessonSlug({ youtubeTitle: title, courseTitle: "Perception (MIT 9.35)", courseSlug: "mit-perception", position: 7, kind });
    expect(short("!!")).toBe("lecture-07");
    expect(short("Ok", "trailer")).toBe("trailer-07");
    expect(short("Perception | MIT 9.35")).toBe("perception");
    expect(short("Lecture 3")).toBe("lecture-03");
    expect(short("3: C")).toBe("lecture-03-c");
    expect(short("", "")).toBe("lecture-07");
  });

  it("keeps words before the lecture number unless they are a series name", () => {
    const slug = (title: string) => baseLessonSlug({ youtubeTitle: title, courseTitle: "Perception (MIT 9.35)", courseSlug: "mit-perception", position: 1, kind: "lecture" });
    expect(slug("Review of Lecture 3 Material")).toBe("lecture-03-review-of-material");
    expect(slug("Perception Lecture 3 Color")).toBe("lecture-03-color");
    expect(slug("Week 2 (MIT 9.35)")).toBe("week-02");
  });
});

describe("cleanLessonSlug: properties over every real title, both sources", () => {
  it("is within 60 characters and matches the CHECK", () => {
    for (const input of inputs) {
      const slug = cleanLessonSlug(input, none);
      expect(slug.length, slug).toBeLessThanOrEqual(LESSON_SLUG_MAX);
      expect(slug).toMatch(SLUG_PATTERN);
    }
  });

  it("carries no edition tag, bracket tag or course/channel suffix", () => {
    for (const input of inputs) {
      const slug = cleanLessonSlug(input, none);
      expect(slug, input.youtubeTitle).not.toMatch(/(?:^|-)(?:fall|spring|summer|winter)-\d{2,4}(?:-|$)|(?:^|-)(?:fa|sp|s)\d{2,4}(?:-|$)/);
      expect(slug, input.youtubeTitle).not.toMatch(/stanford-understand-energy|cmu-(?:intro|advanced)|economics-of-transformative-ai|intro-to-database-systems$|med-275|cs50x-2025|idl/);
      expect(slug, input.youtubeTitle).not.toMatch(/-lecture$|-$|^-/);
    }
  });

  it("is deterministic and idempotent (a slug is its own slug)", () => {
    for (const input of inputs) {
      const slug = cleanLessonSlug(input, none);
      expect(cleanLessonSlug(input, none)).toBe(slug);
      expect(cleanLessonSlug({ ...input, displayTitle: slug }, none), input.youtubeTitle).toBe(slug);
    }
  });

  it("is unique and stable: it never returns a taken slug, suffixes -2, -3 and stays within 60", () => {
    for (const input of inputs.slice(0, 40)) {
      const base = cleanLessonSlug(input, none);
      const two = cleanLessonSlug(input, new Set([base]));
      const three = cleanLessonSlug(input, new Set([base, two]));
      expect(three).toMatch(/-3$/);
      for (const slug of [two, three]) {
        // Same words as the base, cut between words when the suffix needs the room.
        expect(`${base}-`.startsWith(`${slug.slice(0, -2)}-`), slug).toBe(true);
        expect(slug.length).toBeLessThanOrEqual(LESSON_SLUG_MAX);
        expect(slug).toMatch(SLUG_PATTERN);
      }
    }
    expect(uniqueLessonSlug("a".repeat(60), new Set(["a".repeat(60)]))).toBe(`${"a".repeat(58)}-2`);
  });
});

describe("lesson title and trailer suggestion", () => {
  it("cleans a lecture prefix and a channel suffix, and keeps the title when cleaning would leave nothing", () => {
    expect(cleanTitle("Lecture 3 – Freud | Yale")).toBe("Freud");
    expect(cleanTitle("Ep. 12: The Flood")).toBe("The Flood");
    expect(cleanTitle("07. Abraham")).toBe("Abraham");
    expect(cleanTitle("  Plain title  ")).toBe("Plain title");
    expect(cleanTitle("Lecture 1 - | Yale")).toBe("Lecture 1 - | Yale");
  });

  it("slugifies a suggested title and keeps it unique", () => {
    expect(slugify("Ça va, Éden & Égypte!")).toBe("ca-va-eden-egypte");
    expect(slugify("!!!")).toBe("lesson");
    expect(slugify("word ".repeat(60), 20)).toBe("word-word-word-word");
    expect(uniqueSlug("freud", new Set())).toBe("freud");
    expect(uniqueSlug("freud", new Set(["freud", "freud-2"]))).toBe("freud-3");
    expect(uniqueSlug("a".repeat(10), new Set(["a".repeat(10)]), 10)).toBe(`${"a".repeat(8)}-2`);
    expect(uniqueSlug("hello-", new Set(["hello-"]), 8)).toBe("hello-2");
  });

  it("suggests a trailer only for a short first item named like one", () => {
    expect(looksLikeTrailer("Course trailer", 120, 0)).toBe(true);
    expect(looksLikeTrailer("A short preview", 60, 0)).toBe(true);
    expect(looksLikeTrailer("Introduction", 1200, 0)).toBe(false);
    expect(looksLikeTrailer("Intro", 120, 1)).toBe(false);
    expect(looksLikeTrailer("Intro", null, 0)).toBe(false);
    expect(looksLikeTrailer("Freud", 120, 0)).toBe(false);
  });
});

describe("slug.fixtures.json: the production catalog", () => {
  it("holds the 386 imported lessons and lists the 126 legacy ones apart", () => {
    expect(fixture.lessons).toHaveLength(386);
    expect(fixture.legacyLessonIds).toHaveLength(126);
    const legacy = new Set(fixture.legacyLessonIds);
    expect(fixture.lessons.filter((row) => legacy.has(row.lessonId))).toEqual([]);
  });

  it("matches the rule: a rule change fails here until the fixture is regenerated (node scripts/lib/slug-fixtures.ts) and reviewed", () => {
    const slugs = fixtureSlugs(fixture);
    const drift = fixture.lessons.filter((row) => slugs.get(row.lessonId) !== row.expectedSlug).map((row) => `${row.lessonId}: ${row.expectedSlug} → ${slugs.get(row.lessonId) ?? ""}`);
    expect(drift).toEqual([]);
    const perCourse = new Map<string, string[]>();
    for (const row of fixture.lessons) perCourse.set(row.courseSlug, [...(perCourse.get(row.courseSlug) ?? []), row.expectedSlug]);
    for (const slugsOfCourse of perCourse.values()) expect(new Set(slugsOfCourse).size).toBe(slugsOfCourse.length);
  });
});
