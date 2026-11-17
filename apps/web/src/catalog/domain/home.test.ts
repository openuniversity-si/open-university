import { describe, expect, it } from "vitest";
import { snapshotCatalog as catalog } from "../testing/fake.ts";
import type { MediaAsset } from "../../media/domain/types.ts";
import { releaseFixture } from "../../../test/fixtures/release.ts";
import { imageCredits } from "./credits.ts";
import { namesLabel } from "./home.ts";
import { authorCourses, cardFigures, homeCourses, homeImages, homePortals, PORTAL_AUTHOR_COVER_CAP, PORTAL_UNIVERSITY_COVER_CAP, rowTab, signedOutHome, tabHome } from "./home.ts";

describe("signed-out Home projection", () => {
  it("keeps only populated author rails in catalog order, without Continue or its space", () => {
    const home = signedOutHome(catalog);
    expect(home.rails.map((rail) => [rail.title, rail.courses.map((course) => course.id)])).toEqual([
      ["Fixture Lecturer 1", ["course-1", "course-2", "course-3"]],
      ["Fixture Lecturer 2", ["course-4", "course-5"]],
    ]);
    expect(home.featured?.displayTitle).toBe("Fixture Course 1");
  });
  it("starts the first catalog lesson and computes the approved Fixture Course 1 labels", () => {
    const course = signedOutHome(catalog).featured;
    expect(course?.startHref).toBe("/c/fixture-course-1/fixture-lesson-1");
    expect(course?.featured).toBe(true);
    expect(course?.metaMobile).toBe("17 lectures  ·  17h");
    expect(course?.meta).toBe("17 lectures  ·  17h  ·  Intermediate  ·  English");
  });
  it("projects active default media and never falls back to local catalog image paths", () => {
    const asset = { kind: "poster_9x16", variant: "default", isActive: true, url: "https://example.test/poster.jpg", width: 540, height: 960, transform: null } as MediaAsset;
    const home = signedOutHome(catalog, new Map([["course-1", [asset]]]));
    expect(home.featured?.assets.poster).toEqual({ url: asset.url, width: 540, height: 960, transform: null });
    expect(homeImages(cardFigures([{ ...asset, isActive: false }, { ...asset, variant: "alternate" }]))).toEqual({});
    expect(homeImages({ poster: asset })).toEqual({ poster: { url: asset.url, width: 540, height: 960, transform: null } });
    expect(JSON.stringify(home)).not.toContain("/media/");
  });
  it("excludes empty rails and handles an empty catalog", () => {
    expect(signedOutHome({ ...catalog, courses: [] })).toEqual({ featured: undefined, rails: [] });
  });
  it("does not serialize video credentials, editorial provenance or lesson inventories", () => {
    const home = JSON.stringify(signedOutHome(catalog));
    for (const key of ["playbackId", "assetId", "editorial", "youtubeId", "durationSeconds", "aboutApproved"]) expect(home).not.toContain(key);
  });
});

describe("release Home rows", () => {
  it("renders curated rows with their own title, in release order, beside author rows", () => {
    const release = releaseFixture();
    release.home.rows.splice(1, 0, { id: "start-here", kind: "curated", title: "Start here", courseIds: ["course-2"] });
    expect(signedOutHome(release).rails.map((rail) => [rail.id, rail.title, rail.courses.map((course) => course.id)])).toEqual([
      ["start-here", "Start here", ["course-2"]],
      ["test-lecturer", "Test Lecturer", ["course-1", "course-2"]],
    ]);
  });
  it("takes the Billboard from home.featuredCourseId and allows none", () => {
    expect(signedOutHome(releaseFixture()).featured?.id).toBe("course-1");
    const none = releaseFixture();
    none.home.featuredCourseId = null;
    for (const course of none.courses) course.featured = false;
    expect(signedOutHome(none).featured).toBeUndefined();
  });
  it("projects a course that is on no row, and finds More from its author", () => {
    const release = releaseFixture();
    release.home.rows = release.home.rows.filter((row) => row.kind !== "author");
    const courses = homeCourses(release);
    expect(courses.get("course-2")?.startHref).toBe("/c/second-course/intro");
    expect(authorCourses(release, "course-2", courses).map((course) => course.id)).toEqual(["course-1", "course-2"]);
    expect(authorCourses(catalog, "course-4", homeCourses(catalog)).map((course) => course.id)).toEqual(["course-4", "course-5"]);
  });
});

describe("Home tabs (Universities, Authors)", () => {
  const withUniversity = () => {
    const release = releaseFixture();
    release.home.rows.push({ id: "mit", kind: "curated", title: "MIT", courseIds: ["course-2"] });
    return release;
  };
  it("derives the tab from the row kind, never from names", () => {
    expect(rowTab({ kind: "curated" })).toBe("universities");
    expect(rowTab({ kind: "author" })).toBe("authors");
    expect(rowTab({ kind: "continue" })).toBeNull();
  });
  it("keeps only the tab's rows, in release order", () => {
    const release = withUniversity();
    expect(tabHome(release, "universities").rails.map((rail) => rail.id)).toEqual(["mit"]);
    expect(tabHome(release, "authors").rails.map((rail) => rail.id)).toEqual(["test-lecturer"]);
    expect(tabHome(catalog, "universities").rails).toEqual([]);
  });
  it("uses the Home Billboard when it is on the tab, else the first course of the first row", () => {
    const release = withUniversity();
    expect(tabHome(release, "authors").featured?.id).toBe("course-1");
    expect(tabHome(release, "universities").featured?.id).toBe("course-2");
    expect(tabHome(catalog, "universities").featured).toBeUndefined();
  });
});

describe("Home Portais (concept 01)", () => {
  const poster = (url: string) => ({ kind: "poster_9x16", variant: "default", isActive: true, url, width: 540, height: 960, transform: null }) as MediaAsset;
  it("derives one portal per populated tab from the release rows: names, count, own covers, link", () => {
    const release = releaseFixture();
    release.home.rows.push({ id: "mit", kind: "curated", title: "MIT", courseIds: ["course-2"] });
    const media = new Map([["course-1", [poster("https://m.test/1.webp")]], ["course-2", [poster("https://m.test/2.webp")]]]);
    const portals = homePortals(release, media);
    expect(portals.map((p) => p.tab)).toEqual(["universities", "authors"]);
    const [universities, authors] = portals;
    expect(universities).toMatchObject({ href: "/universities", title: "Universities", names: ["MIT"], countLabel: "1 institution" });
    expect(universities?.covers).toEqual([{ url: "", width: 1080, height: 1920, alt: "", placeholder: true }]);
    expect(authors).toMatchObject({ href: "/authors", title: "Authors", countLabel: "1 author" });
    expect(authors?.covers).toEqual([{ url: "", width: 1080, height: 1920, alt: "", placeholder: true }]);
    expect(JSON.stringify(portals)).not.toContain("m.test");
  });
  it("Authors portal: one cover per author from authors[].cover, capped with +N, credits for the Authors tab", () => {
    const release = structuredClone(catalog);
    const cover = (id: string) => ({ url: `https://media.openuniversity.si/covers/${id}/author_cover_9x16/${"a".repeat(40)}.webp`, width: 1080, height: 1920, sha256: "b".repeat(64), alt: id, credit: `Photo: ${id}`, sourceUrl: "https://example.org", license: "CC BY-SA 3.0", note: null });
    release.authors = release.authors.map((author) => ({ ...author, cover: cover(author.id) }));
    const authors = homePortals(release).find((p) => p.tab === "authors");
    expect(authors?.covers.map((c) => c.alt)).toEqual(release.home.rows.filter((r) => r.kind === "author").map((r) => r.authorId));
    expect(authors?.more).toBe(0);
    expect(imageCredits(release).filter((c) => c.kind === "author").map((c) => c.credit)).toEqual(authors?.covers.map((c) => `Photo: ${c.alt}`));
    // Six authors: the cap, then "+N".
    for (let index = 3; index <= 8; index += 1) {
      release.authors.push({ ...(release.authors[0] as (typeof release.authors)[number]), id: `author-${String(index)}`, slug: `a-${String(index)}`, cover: cover(`author-${String(index)}`) });
      release.home.rows.push({ id: `a-${String(index)}`, kind: "author", title: `A${String(index)}`, authorId: `author-${String(index)}`, courseIds: ["course-1"] });
    }
    const many = homePortals(release).find((p) => p.tab === "authors");
    expect(many?.covers).toHaveLength(PORTAL_AUTHOR_COVER_CAP);
    expect(many?.more).toBe(8 - PORTAL_AUTHOR_COVER_CAP);
  });
  it("Universities portal: one cover per university from home.rows[].cover, capped with +N, credits", () => {
    const release = releaseFixture();
    const cover = (id: string) => ({ url: `https://media.openuniversity.si/covers/${id}/university_cover_9x16/${"a".repeat(40)}.webp`, width: 1080, height: 1920, sha256: "b".repeat(64), alt: id, credit: `Photo: ${id}`, sourceUrl: "https://example.org", license: "CC BY 4.0", note: null });
    const media = new Map([["course-2", [poster("https://m.test/2.webp")]]]);
    for (const id of ["mit", "yale", "harvard", "stanford", "cmu"]) release.home.rows.push({ id, kind: "curated", title: id.toUpperCase(), courseIds: ["course-2"], cover: cover(id) });
    release.home.rows.push({ id: "cornell", kind: "curated", title: "CORNELL", courseIds: ["course-2"] });
    const universities = homePortals(release, media).find((p) => p.tab === "universities");
    expect(universities?.covers.map((c) => c.alt)).toEqual(["mit", "yale", "harvard", "stanford"]);
    expect(universities?.covers).toHaveLength(PORTAL_UNIVERSITY_COVER_CAP);
    expect(universities?.more).toBe(2);
    expect(imageCredits(release).filter((c) => c.kind === "university").map((c) => [c.subject, c.credit])).toEqual(["mit", "yale", "harvard", "stanford", "cmu"].map((id) => [id.toUpperCase(), `Photo: ${id}`]));
    release.home.rows = release.home.rows.filter((r) => r.id === "cornell" || r.kind !== "curated");
    const cornell = homePortals(release, media).find((p) => p.tab === "universities");
    expect(cornell?.covers).toEqual([{ url: "", width: 1080, height: 1920, alt: "", placeholder: true }]);
    expect(JSON.stringify(cornell)).not.toContain("m.test");
  });
  it("omits a tab without rows and counts in plural", () => {
    const portals = homePortals(catalog);
    expect(portals.map((p) => [p.tab, p.countLabel, p.names])).toEqual([["authors", "2 authors", ["Fixture Lecturer 1", "Fixture Lecturer 2"]]]);
    expect(portals[0]?.covers).toEqual([
      { url: "", width: 1080, height: 1920, alt: "", placeholder: true },
      { url: "", width: 1080, height: 1920, alt: "", placeholder: true },
    ]);
  });
});

describe("portal names label", () => {
  it("shows the first names then +N, never a cut word", () => {
    expect(namesLabel(["MIT", "Yale"])).toBe("MIT · Yale");
    expect(namesLabel(["MIT", "Yale", "Harvard", "Stanford", "Carnegie Mellon", "Cornell", "UC Berkeley"])).toBe("MIT · Yale · Harvard · Stanford  +3");
  });
});
