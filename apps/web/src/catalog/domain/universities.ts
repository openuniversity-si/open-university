import type { MediaAsset } from "../../media/domain/types.ts";
import { homeCourses, rowTab, type HomeCourse } from "./home.ts";
import type { PublicCatalog } from "./release.ts";

/**
 * The Universities showcase (Daniel, 14/10/2026; Figma 556:3, ADR-25):
 * - /universities: one 9:16 cover per university (a `curated` Home row) in a grid, under a hero of the selected one;
 * - /universities/[slug]: the university's courses in one rail per subject area (release `areas` order, only the areas it
 *   has published courses in). Every live course is listed; "See all N" links to the area page.
 * - /universities/[slug]/[area]: every course of that university in that area.
 * Everything comes from the release: title, fullName and place of the curated row (0013), and that row's own cover.
 * A university never borrows a course poster (ADR-40). A legacy release with no cover renders a neutral placeholder.
 */

export interface UniversityCoverArt { readonly url: string; readonly width: number; readonly height: number; readonly alt: string }

export interface University {
  readonly slug: string;
  readonly name: string;
  readonly fullName: string;
  /** "" when unknown. */
  readonly place: string;
  readonly cover: UniversityCoverArt | null;
  /** The 1200×630 link preview (university-cover.ts `og`), when one was made. */
  readonly og: { readonly url: string; readonly width: number; readonly height: number } | null;
  readonly courses: readonly HomeCourse[];
  /** Non-empty areas this university publishes, in release order. */
  readonly areaCount: number;
  /** The release names areas, so the shelf can count them. */
  readonly areasNamed: boolean;
}

export interface UniversityArea {
  readonly id: string;
  readonly title: string;
  readonly courses: readonly HomeCourse[];
}

/** Every university with at least one published course, in Home row order. */
export function universities(catalog: PublicCatalog, media: ReadonlyMap<string, readonly MediaAsset[]> = new Map()): University[] {
  const courses = homeCourses(catalog, media);
  return catalog.home.rows.filter((row) => rowTab(row) === "universities").flatMap((row) => {
    const entries = row.courseIds.flatMap((id) => { const course = courses.get(id); return course ? [course] : []; });
    if (entries.length === 0) return [];
    const fullName = row.fullName ?? row.title;
    const place = row.place ?? "";
    const cover = row.cover ? { url: row.cover.url, width: row.cover.width, height: row.cover.height, alt: row.cover.alt } : null;
    const og = row.cover?.og ? { url: row.cover.og.url, width: row.cover.og.width, height: row.cover.og.height } : null;
    return [{
      slug: row.id, name: row.title, fullName, place, cover, og, courses: entries,
      areaCount: universityAreas(catalog, entries).length, areasNamed: Boolean(catalog.areas),
    }];
  });
}

export function findUniversity(catalog: PublicCatalog, slug: string, media?: ReadonlyMap<string, readonly MediaAsset[]>): University | undefined {
  return universities(catalog, media).find((entry) => entry.slug === slug);
}

/** The areas a set of courses falls in: release order, only non-empty ones, courses in their given (row) order. */
export function universityAreas(catalog: PublicCatalog, courses: readonly HomeCourse[]): UniversityArea[] {
  const areaOf = new Map(catalog.courses.map((course) => [course.id, course.areaId]));
  const groups = (catalog.areas ?? []).map((area) => ({
    id: area.id, title: area.title,
    courses: courses.filter((course) => areaOf.get(course.id) === area.id),
  }));
  return groups.filter((group) => group.courses.length > 0);
}

/**
 * Subarea rails (ADR-26, Daniel 17/10/2026; Figma 622:2488 / 622:2907, page "Proto — Dynamic"). Decided per page from
 * the courses that page shows, never by a click: an area with at least SUBAREA_SPLIT_AT courses is shown as one rail per
 * subarea that has at least SUBAREA_MIN_RAIL of them (taxonomy order), followed by one rail titled with the area for
 * the rest (no subarea, or a subarea below the minimum). If that leaves a single rail, the area is shown unsplit.
 */
export const SUBAREA_SPLIT_AT = 12;
export const SUBAREA_MIN_RAIL = 4;

export interface AreaGroup {
  /** Anchor: the subarea id, the area id for an unsplit area, or `<area>-other` for the leftovers of a split area. */
  readonly id: string;
  readonly kind: "area" | "subarea" | "rest";
  readonly title: string;
  readonly courses: readonly HomeCourse[];
}

/** One area's courses as rails/sections: [the whole area] when it stays unsplit, else the subarea groups then the rest. */
export function splitArea(catalog: PublicCatalog, area: UniversityArea): AreaGroup[] {
  const whole: AreaGroup[] = [{ id: area.id, kind: "area", title: area.title, courses: area.courses }];
  if (area.courses.length < SUBAREA_SPLIT_AT) return whole;
  const subareaOf = new Map(catalog.courses.map((course) => [course.id, course.subareaId]));
  const subareas = (catalog.subareas ?? []).filter((subarea) => subarea.areaId === area.id);
  const groups = subareas.map((subarea) => ({ id: subarea.id, kind: "subarea" as const, title: subarea.title, courses: area.courses.filter((course) => subareaOf.get(course.id) === subarea.id) }))
    .filter((group) => group.courses.length >= SUBAREA_MIN_RAIL);
  const placed = new Set(groups.flatMap((group) => group.courses.map((course) => course.id)));
  const rest = area.courses.filter((course) => !placed.has(course.id));
  const split: AreaGroup[] = [...groups, ...(rest.length > 0 ? [{ id: `${area.id}-other`, kind: "rest" as const, title: area.title, courses: rest }] : [])];
  return split.length > 1 ? split : whole;
}

export interface UniversityRail extends AreaGroup {
  readonly areaId: string;
  /** "See all N": the area page, at this rail's section when the area is split. */
  readonly href: string;
}

/** Every rail of a university page, in area order, each area's rails together in its place (ADR-25 + ADR-26). */
export function universityRails(catalog: PublicCatalog, slug: string, courses: readonly HomeCourse[]): UniversityRail[] {
  return universityAreas(catalog, courses).flatMap((area) => splitArea(catalog, area).map((group) => ({
    ...group, areaId: area.id, href: `/universities/${slug}/${area.id}${group.kind === "area" ? "" : `#${group.id}`}`,
  })));
}

/** Cards one rail lists. A long rail scrolls; courses are not dropped to fit a cap. */
export function railCards(rail: Pick<UniversityRail, "courses">): readonly HomeCourse[] {
  return rail.courses;
}

/** Every course the university page lists, once, in rail order. Matches the university's live courses. */
export function coursesOnUniversityPage(catalog: PublicCatalog, slug: string, courses: readonly HomeCourse[]): readonly HomeCourse[] {
  const seen = new Set<string>();
  const listed: HomeCourse[] = [];
  for (const course of universityRails(catalog, slug, courses).flatMap((rail) => railCards(rail))) {
    if (seen.has(course.id)) continue;
    seen.add(course.id);
    listed.push(course);
  }
  return listed;
}

/** Total published courses on the universities tab (each course counted once). */
export function universityCourseCount(entries: readonly University[]): number {
  return new Set(entries.flatMap((entry) => entry.courses.map((course) => course.id))).size;
}
