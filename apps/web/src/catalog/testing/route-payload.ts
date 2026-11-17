import type { Country } from "../domain/countries.ts";
import type { PublicCatalog } from "../domain/release.ts";
import { universities } from "../domain/universities.ts";
import { authorsClient, cardView, homeClient, signedInHomeClient, universityDetailRails, universityIndexView } from "../domain/view-model.ts";
import { htmlBytes, SITE_HEALTH_ROUTES, type Audience, type SiteHealthMeasurement, type SiteHealthRoute } from "../../site/domain/site-health.ts";
import { fullSizeRelease } from "./full-release.ts";

const countries: readonly Country[] = [
  { id: "us", name: "United States", rank: 1, placeEndings: ["MA"] },
  { id: "uk", name: "United Kingdom", rank: 2, placeEndings: ["United Kingdom"] },
  { id: "in", name: "India", rank: 3, placeEndings: ["India"] },
  { id: "br", name: "Brazil", rank: 4, placeEndings: ["Brazil"] },
];

const bytes = (value: unknown) => Buffer.byteLength(JSON.stringify(value), "utf8");

function lessonPayload(catalog: PublicCatalog, signedIn: boolean): unknown {
  const course = catalog.courses.find((entry) => entry.slug === "course-0") ?? catalog.courses[0];
  const lessons = course === undefined ? [] : catalog.lessons.filter((entry) => entry.courseId === course.id);
  const lesson = lessons[0];
  return {
    signedIn,
    youtubeId: lesson?.youtubeId ?? "",
    about: lesson?.about ?? null,
    title: lesson?.displayTitle ?? "",
    rows: lessons.map((entry) => ({
      id: entry.id,
      href: `/c/${course?.slug ?? "missing"}/${entry.slug}`,
      title: entry.displayTitle,
      duration: entry.durationSeconds,
      ...(signedIn ? { completed: false } : {}),
    })),
  };
}

function payloads(catalog: PublicCatalog): Record<SiteHealthRoute, { readonly anonymous: unknown; readonly signedIn: unknown }> {
  const index = universityIndexView(catalog, countries);
  const home = homeClient(catalog);
  const signedInHome = signedInHomeClient(catalog, new Map(), new Map());
  const authors = authorsClient(catalog);
  const listed = universities(catalog);
  const university = listed.find((entry) => entry.slug === "university-0") ?? listed[0];
  const rails = university ? universityDetailRails(catalog, university.slug, university.courses) : [];
  const authorCourses = authors.rails[0]?.courses ?? [];
  const course = { hero: authors.featured, cards: authorCourses.map((entry) => cardView(entry)) };
  return {
    "/": { anonymous: home, signedIn: signedInHome },
    "/universities": { anonymous: index, signedIn: index },
    "/authors": { anonymous: authors, signedIn: authors },
    "/universities/[slug]": { anonymous: rails, signedIn: rails },
    "/c/[courseSlug]": { anonymous: course, signedIn: course },
    "/c/[courseSlug]/[lessonSlug]": { anonymous: lessonPayload(catalog, false), signedIn: lessonPayload(catalog, true) },
  };
}

function queriesFor(route: SiteHealthRoute): number {
  return route.startsWith("/c/") ? 7 : 4;
}

/** RSC bytes and the shared read cost of every site-health route, both audiences, on a release-133-sized fixture. */
export function fixtureMeasurements(catalog: PublicCatalog = fullSizeRelease(), serverMs = 1): SiteHealthMeasurement[] {
  const built = payloads(catalog);
  return SITE_HEALTH_ROUTES.flatMap((route) => (["anonymous", "signedIn"] as const).map((key) => {
    const audience: Audience = key === "signedIn" ? "signed-in" : "anonymous";
    const rscBytes = bytes(built[route][key]);
    return { route, audience, rscBytes, queries: queriesFor(route), serverMs, cacheEntryBytes: rscBytes };
  }));
}

/** Anonymous RSC bytes, for the route script that prints one line per path. */
export function fixtureRouteBytes(catalog: PublicCatalog = fullSizeRelease()): Record<SiteHealthRoute, number> {
  const measurements = fixtureMeasurements(catalog);
  const out = {} as Record<SiteHealthRoute, number>;
  for (const measurement of measurements) {
    if (measurement.audience === "anonymous") out[measurement.route] = measurement.rscBytes;
  }
  return out;
}

export { htmlBytes };
