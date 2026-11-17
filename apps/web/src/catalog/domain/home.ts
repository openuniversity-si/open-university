import type { MediaAsset } from "../../media/domain/types.ts";
import { authorNoun, authorNounMany, authorsTitle, fill, hourMark, institutionNoun, institutionNounMany, metaDot, metaGap, morePrefix, nounPluralTemplate, universitiesTitle } from "../../site/domain/reader-copy.ts";
import type { CourseProgressView } from "../../progress/domain/view.ts";
import { defaultEdition, lessonsForEdition, type Course } from "./queries.ts";
import { homeRowSpec } from "./home-row-kind.ts";
import type { PublicCatalog } from "./release.ts";

/** A public UI projection; video assets and editorial provenance never enter the Home client. */
export type HomeCourse = Pick<Course, "id" | "slug" | "title" | "displayTitle" | "billboardDescription" | "billboardDescriptionMobile"> & {
  readonly assets: Partial<Record<"poster" | "heroDesktop" | "heroPresent" | "heroMobile", Pick<MediaAsset, "url" | "width" | "height" | "transform">>>;
  readonly author: string;
  readonly featured: boolean;
  /** Meta without its status, which depends on the Billboard selection (see `ui/Billboard/meta.ts`). */
  readonly meta: string;
  readonly metaMobile: string;
  readonly startHref: string;
  /** Signed in only (F11). */
  readonly progress?: CourseProgressView;
};

export interface HomeRail {
  readonly id: string;
  readonly title: string;
  readonly courses: readonly HomeCourse[];
}

/** ADR-07/ADR-17: the signed-out Home is projected only from the active, validated release. */
export function signedOutHome(catalog: PublicCatalog, media: ReadonlyMap<string, readonly MediaAsset[]> = new Map()): { featured: HomeCourse | undefined; rails: HomeRail[] } {
  const courses = homeCourses(catalog, media);
  const { featuredCourseId } = catalog.home;
  // Author and curated rows, in release order; Continue Watching is derived from progress (signedInHome).
  const rails = catalog.home.rows.filter((row) => row.kind !== "continue").flatMap((row) => {
    const entries = row.courseIds.flatMap((id) => { const course = courses.get(id); return course ? [course] : []; });
    return entries.length === 0 ? [] : [{ id: row.id, title: row.title, courses: entries }];
  });
  return { featured: featuredCourseId === null ? undefined : courses.get(featuredCourseId), rails };
}

/**
 * The Home tabs (Daniel, 14/10/2026). The section of a release row is derived from its kind, never from a list of names:
 * `curated` rows group institution courses (MIT, Yale, …) and are the Universities tab; `author` rows are one lecturer's
 * courses and are the Authors tab; `continue` belongs to no tab (progress lives on Home only).
 */
export type HomeTab = "universities" | "authors";
export const HOME_TABS: readonly HomeTab[] = ["universities", "authors"];

export function rowTab(row: Pick<PublicCatalog["home"]["rows"][number], "kind">): HomeTab | null {
  return homeRowSpec(row.kind).tab;
}

/**
 * A tab is the Home filtered to its rows, in release order. Billboard: the Home's featured course when it is on one of the
 * tab's rows, else the first course of the tab's first row.
 */
export function tabHome(catalog: PublicCatalog, tab: HomeTab, media: ReadonlyMap<string, readonly MediaAsset[]> = new Map()): { featured: HomeCourse | undefined; rails: HomeRail[] } {
  const home = signedOutHome(catalog, media);
  const ids = new Set(catalog.home.rows.filter((row) => rowTab(row) === tab).map((row) => row.id));
  const rails = home.rails.filter((rail) => ids.has(rail.id));
  const onTab = home.featured && rails.some((rail) => rail.courses.some((course) => course.id === home.featured?.id));
  return { featured: onTab ? home.featured : rails[0]?.courses[0], rails };
}

/**
 * Home "Portais" (Daniel, 14/10/2026; Figma Home 562:55931 / 563:949 / 563:57913, concept 01): the Home no longer lists
 * every rail; it shows one portal per tab. Everything is derived from the release rows (`rowTab`): the names are the
 * tab's row titles, the count is its row count, and the collage is that row's own cover (never a course poster).
 */
export interface HomePortal {
  readonly tab: HomeTab;
  readonly href: `/${HomeTab}`;
  readonly title: string;
  readonly names: readonly string[];
  /** Desktop subtitle: the first PORTAL_NAME_CAP names, then "+N" (never cut mid-word). */
  readonly namesLabel: string;
  /** "6 institutions" / "2 authors" (mobile subtitle). */
  readonly countLabel: string;
  readonly covers: readonly PortalCover[];
  /** Entries beyond the collage cap ("+N"). */
  readonly more: number;
}

export interface PortalCover {
  readonly url: string;
  readonly width: number;
  readonly height: number;
  readonly alt: string;
  /** A legacy release whose row has no cover of its own. Not course art. */
  readonly placeholder?: true;
}

const PORTAL_PLACEHOLDER: PortalCover = { url: "", width: 1080, height: 1920, alt: "", placeholder: true };

/** The Authors collage shows at most this many covers, then "+N" (Daniel, 14/10/2026). */
export const PORTAL_AUTHOR_COVER_CAP = 4;
/** Likewise the Universities collage, one cover per university (Daniel, 14/10/2026; docs/catalog/university-covers.md). */
export const PORTAL_UNIVERSITY_COVER_CAP = 4;
/** Names in a portal's desktop subtitle before "+N" (Daniel, 14/10/2026: "… UC Berkele" was cut mid-word). */
export const PORTAL_NAME_CAP = 4;

export function namesLabel(names: readonly string[], cap = PORTAL_NAME_CAP): string {
  const shown = names.slice(0, cap).join(metaDot);
  return names.length > cap ? `${shown}${morePrefix}${String(names.length - cap)}` : shown;
}

const PORTAL_COPY: Record<HomeTab, { title: string; one: string; many: string }> = {
  universities: { title: universitiesTitle, one: institutionNoun, many: institutionNounMany },
  authors: { title: authorsTitle, one: authorNoun, many: authorNounMany },
};

export function homePortals(catalog: PublicCatalog, media: ReadonlyMap<string, readonly MediaAsset[]> = new Map()): HomePortal[] {
  const { rails } = signedOutHome(catalog, media);
  const rowsById = new Map(catalog.home.rows.map((row) => [row.id, row]));
  return HOME_TABS.flatMap((tab) => {
    const tabRails = rails.filter((rail) => { const row = rowsById.get(rail.id); return row !== undefined && rowTab(row) === tab; });
    if (tabRails.length === 0) return [];
    const copy = PORTAL_COPY[tab];
    // One slot per row that publishes a course: its own cover, or a neutral placeholder. Never a course poster (ADR-40).
    const all = tabRails.map((rail) => {
      const row = rowsById.get(rail.id);
      const cover = tab === "authors" ? catalog.authors.find((author) => author.id === row?.authorId)?.cover : row?.cover;
      return cover ? { url: cover.url, width: cover.width, height: cover.height, alt: cover.alt } : PORTAL_PLACEHOLDER;
    });
    const covers = all.slice(0, tab === "authors" ? PORTAL_AUTHOR_COVER_CAP : PORTAL_UNIVERSITY_COVER_CAP);
    const n = tabRails.length;
    return [{ tab, href: `/${tab}` as const, title: copy.title, names: tabRails.map((rail) => rail.title), namesLabel: namesLabel(tabRails.map((rail) => rail.title)), countLabel: `${String(n)} ${n === 1 ? copy.one : copy.many}`, covers, more: Math.max(0, n - covers.length) }];
  });
}

/** Every published course's card/Billboard projection, by id (a course need not be on a Home row to have a page). */
export function homeCourses(catalog: PublicCatalog, media: ReadonlyMap<string, readonly MediaAsset[]> = new Map()): ReadonlyMap<string, HomeCourse> {
  return new Map(catalog.courses.map((course) => {
    const author = catalog.authors.find((entry) => entry.id === course.authorId);
    // Cards and the Billboard describe the default edition (position 1), where the course opens (ADR-21).
    const lessons = lessonsForEdition(catalog, defaultEdition(course).id);
    const first = lessons[0];
    if (!author || !first) throw new Error(`Published course ${course.id} must have an author and a first lesson.`);
    const hours = Math.round(lessons.reduce((sum, lesson) => sum + lesson.durationSeconds, 0) / 3600);
    const metaMobile = `${String(lessons.length)} ${fill(nounPluralTemplate, { noun: course.lessonNoun.toLowerCase() })}${metaGap}${String(hours)}${hourMark}`;
    const projection: HomeCourse = {
      id: course.id, slug: course.slug, title: course.title, displayTitle: course.displayTitle,
      billboardDescription: course.billboardDescription, billboardDescriptionMobile: course.billboardDescriptionMobile,
      assets: homeImages(cardFigures(media.get(course.id) ?? [])), author: author.name, featured: course.featured, metaMobile,
      meta: `${metaMobile}${metaGap}${course.level}${metaGap}${course.languageLabel}`,
      startHref: `/c/${course.slug}/${first.slug}`,
    };
    return [course.id, projection] as const;
  }));
}

/** "More from <author>": the author's Home row when it lists the course, else every course by the author in release order. */
export function authorCourses(catalog: PublicCatalog, courseId: string, courses: ReadonlyMap<string, HomeCourse>): HomeCourse[] {
  const authorId = catalog.courses.find((course) => course.id === courseId)?.authorId;
  const row = catalog.home.rows.find((entry) => homeRowSpec(entry.kind).author && entry.authorId === authorId && entry.courseIds.includes(courseId));
  const ids = row?.courseIds ?? catalog.courses.filter((course) => course.authorId === authorId).map((course) => course.id);
  return ids.flatMap((id) => { const course = courses.get(id); return course ? [course] : []; });
}

/** F11 signed-in Home: the same rails with each course's progress, plus Continue Watching (most recent first). */
export function signedInHome(catalog: PublicCatalog, media: ReadonlyMap<string, readonly MediaAsset[]>, views: ReadonlyMap<string, CourseProgressView>): { featured: HomeCourse | undefined; continueWatching: HomeCourse[]; rails: HomeRail[] } {
  const home = signedOutHome(catalog, media);
  const attach = (course: HomeCourse): HomeCourse => {
    const progress = views.get(course.id);
    return progress ? { ...course, progress } : course;
  };
  const rails = home.rails.map((rail) => ({ ...rail, courses: rail.courses.map(attach) }));
  const courses = [...new Map(rails.flatMap((rail) => rail.courses).map((course) => [course.id, course])).values()];
  const continueWatching = courses.filter((course) => course.progress?.card).sort((a, b) => (b.progress?.lastActivity ?? 0) - (a.progress?.lastActivity ?? 0));
  return { featured: home.featured && attach(home.featured), continueWatching, rails };
}

export interface HomeCardFigures {
  readonly poster?: MediaAsset;
  readonly heroDesktop?: MediaAsset;
  readonly heroPresent?: MediaAsset;
  readonly heroMobile?: MediaAsset;
}

const cardKinds = { poster_9x16: "poster", hero_desktop_16x9: "heroDesktop", hero_present: "heroPresent", hero_mobile_9x16: "heroMobile" } as const;

/** Names the figures the read already resolved. It does not walk to another owner. */
export function cardFigures(media: readonly MediaAsset[]): HomeCardFigures {
  const figures: { -readonly [Name in keyof HomeCardFigures]?: MediaAsset } = {};
  for (const asset of media) {
    if (asset.variant !== "default" || !asset.isActive || !(asset.kind in cardKinds)) continue;
    figures[cardKinds[asset.kind as keyof typeof cardKinds]] = asset;
  }
  return figures;
}

/** Only public rendering fields cross the server/client boundary; no Blob/database metadata. */
export function homeImages(figures: HomeCardFigures): HomeCourse["assets"] {
  const result: HomeCourse["assets"] = {};
  for (const name of ["poster", "heroDesktop", "heroPresent", "heroMobile"] as const) {
    const asset = figures[name];
    if (!asset) continue;
    result[name] = { url: asset.url, width: asset.width, height: asset.height, transform: asset.transform };
  }
  return result;
}
