import type { MediaAsset } from "../../media/domain/types.ts";
import type { CourseProgressView } from "../../progress/domain/view.ts";
import { groupByCountry, type Country } from "./countries.ts";
import { homePortals, rowTab, signedInHome, signedOutHome, tabHome, type HomeCourse } from "./home.ts";
import type { PublicCatalog } from "./release.ts";
import { universities, universityCourseCount, universityRails, type University, type UniversityCoverArt } from "./universities.ts";

/** Pixels of one image the client actually paints. */
export interface ArtSize {
  readonly url: string;
  readonly width: number;
  readonly height: number;
}

export interface HeroArt extends ArtSize {
  readonly transform: MediaAsset["transform"];
}

/** The progress fields the billboard and a Continue Watching card paint. Watched ids stay on the server. */
export interface BillboardProgress {
  readonly cta: CourseProgressView["cta"];
  readonly card: CourseProgressView["card"];
}

/** Fields `Billboard` reads. Nothing else crosses into that client tree. */
export interface BillboardView {
  readonly id: string;
  readonly slug: string;
  readonly title: string;
  readonly displayTitle: string;
  readonly billboardDescription: string;
  readonly billboardDescriptionMobile: string;
  readonly author: string;
  readonly featured: boolean;
  readonly meta: string;
  readonly metaMobile: string;
  readonly startHref: string;
  readonly assets: {
    readonly poster?: HeroArt;
    readonly heroDesktop?: HeroArt;
    readonly heroMobile?: HeroArt;
  };
  readonly progress?: BillboardProgress;
}

/** Fields `CourseCard` reads. */
export interface CardView {
  readonly id: string;
  readonly slug: string;
  readonly title: string;
  readonly assets: { readonly poster?: ArtSize };
}

function heroArt(value: HomeCourse["assets"]["poster"]): HeroArt | undefined {
  if (!value) return undefined;
  return { url: value.url, width: value.width, height: value.height, transform: value.transform };
}

/** Copy of the billboard fields. Call this at the server/client boundary so extra catalog fields are not serialized. */
export function billboardView(course: HomeCourse): BillboardView {
  const poster = heroArt(course.assets.poster);
  const heroDesktop = heroArt(course.assets.heroDesktop);
  const heroMobile = heroArt(course.assets.heroMobile);
  return {
    id: course.id, slug: course.slug, title: course.title, displayTitle: course.displayTitle,
    billboardDescription: course.billboardDescription, billboardDescriptionMobile: course.billboardDescriptionMobile,
    author: course.author, featured: course.featured, meta: course.meta, metaMobile: course.metaMobile, startHref: course.startHref,
    assets: { ...(poster ? { poster } : {}), ...(heroDesktop ? { heroDesktop } : {}), ...(heroMobile ? { heroMobile } : {}) },
    ...(course.progress ? { progress: { cta: course.progress.cta, card: course.progress.card } } : {}),
  };
}

/** Copy of the card fields. A poster keeps url, width and height. */
export function cardView(course: Pick<HomeCourse, "id" | "slug" | "title" | "assets">): CardView {
  const poster = course.assets.poster;
  return {
    id: course.id, slug: course.slug, title: course.title,
    assets: poster ? { poster: { url: poster.url, width: poster.width, height: poster.height } } : {},
  };
}

/** One university on `/universities`. `courseCount` replaces the course list. */
export interface UniversityCard {
  readonly slug: string;
  readonly name: string;
  readonly fullName: string;
  readonly place: string;
  readonly cover: UniversityCoverArt | null;
  readonly courseCount: number;
  readonly areaCount: number;
  readonly areasNamed: boolean;
}

export interface UniversityGroupView {
  readonly country: Country | null;
  readonly universityCount: number;
  readonly courseCount: number;
  readonly universities: readonly UniversityCard[];
}

export interface UniversityIndexView {
  readonly courseCount: number;
  readonly groups: readonly UniversityGroupView[];
}

function universityCard(entry: University): UniversityCard {
  return {
    slug: entry.slug, name: entry.name, fullName: entry.fullName, place: entry.place, cover: entry.cover,
    courseCount: entry.courses.length, areaCount: entry.areaCount, areasNamed: entry.areasNamed,
  };
}

/** The universities index. Course identity is still known here, so the counts are final and the course list is dropped. */
export function universityIndexView(catalog: PublicCatalog, countries: readonly Country[]): UniversityIndexView {
  const entries = universities(catalog);
  return {
    courseCount: universityCourseCount(entries),
    groups: groupByCountry(entries, countries).map((group) => ({
      country: group.country, universityCount: group.universityCount, courseCount: group.courseCount, universities: group.universities.map(universityCard),
    })),
  };
}

export interface RailView {
  readonly id: string;
  readonly title: string;
  readonly courses: readonly BillboardView[];
}

/** Home client props: the featured billboard and the portals. Rails are not on this page. */
export function homeClient(catalog: PublicCatalog, media: ReadonlyMap<string, readonly MediaAsset[]> = new Map()) {
  const home = signedOutHome(catalog, media);
  return { featured: home.featured ? billboardView(home.featured) : undefined, portals: homePortals(catalog) };
}

/** Authors client props: one billboard view per course the tab can select. */
export function authorsClient(catalog: PublicCatalog, media: ReadonlyMap<string, readonly MediaAsset[]> = new Map()) {
  const tab = tabHome(catalog, "authors", media);
  return {
    featured: tab.featured ? billboardView(tab.featured) : undefined,
    rails: tab.rails.map((rail): RailView => ({ id: rail.id, title: rail.title, courses: rail.courses.map(billboardView) })),
  };
}

/** Course ids whose posters or heroes the authors tab paints. */
export function authorMediaIds(catalog: PublicCatalog): string[] {
  const ids = catalog.home.rows.filter((row) => rowTab(row) === "authors").flatMap((row) => [...row.courseIds]);
  const featured = catalog.home.featuredCourseId;
  return [...new Set(featured ? [...ids, featured] : ids)];
}

/** The one course whose hero the signed-out Home paints. */
export function featuredMediaIds(catalog: PublicCatalog): readonly string[] {
  return catalog.home.featuredCourseId ? [catalog.home.featuredCourseId] : [];
}

/** One rail on a university page. Courses are cards; the course body stays on the server. */
export interface UniversityRailView {
  readonly id: string;
  readonly areaId: string;
  readonly kind: "area" | "subarea" | "rest";
  readonly title: string;
  readonly href: string;
  readonly courses: readonly CardView[];
}

/** Rails of a university page, each course reduced to a card. */
export function universityDetailRails(catalog: PublicCatalog, slug: string, courses: readonly HomeCourse[]): UniversityRailView[] {
  return universityRails(catalog, slug, courses).map((rail) => ({
    id: rail.id, areaId: rail.areaId, kind: rail.kind, title: rail.title, href: rail.href, courses: rail.courses.map(cardView),
  }));
}

/** Course ids whose posters the signed-in Home paints: the featured course, plus Continue Watching. */
export function signedInMediaIds(catalog: PublicCatalog, views: ReadonlyMap<string, CourseProgressView>): string[] {
  const ids = new Set<string>(featuredMediaIds(catalog));
  for (const row of catalog.home.rows) {
    if (row.kind === "continue") continue;
    for (const id of row.courseIds) if (views.get(id)?.card) ids.add(id);
  }
  return [...ids];
}

/** Signed-in Home client props. Rails stay on the server; Continue Watching is a billboard view per started course. */
export function signedInHomeClient(catalog: PublicCatalog, media: ReadonlyMap<string, readonly MediaAsset[]>, views: ReadonlyMap<string, CourseProgressView>) {
  const home = signedInHome(catalog, media, views);
  return {
    featured: home.featured ? billboardView(home.featured) : undefined,
    continueWatching: home.continueWatching.map(billboardView),
    portals: homePortals(catalog),
  };
}
