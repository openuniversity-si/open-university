import { CACHE_ENTRY_BUDGET_BYTES } from "../../kernel/cache-budget.ts";

/**
 * The one definition of a working site (D-038). Byte, query, time and cache ceilings live here.
 * `kernel/cache-budget.ts` enforces the cache cap; this module is the number every route uses.
 */

/** Bytes of the document around a route's RSC payload. Fixture HTML is this plus the payload. */
export const DOCUMENT_SHELL_BYTES = 32 * 1024;

/** Courses in the release that defined a working site (release 133). */
export const FULL_CATALOG_COURSES = 2363;

export const SITE_HEALTH_ROUTES = [
  "/",
  "/universities",
  "/universities/[slug]",
  "/authors",
  "/c/[courseSlug]",
  "/c/[courseSlug]/[lessonSlug]",
] as const;

export type SiteHealthRoute = (typeof SITE_HEALTH_ROUTES)[number];
export type Audience = "anonymous" | "signed-in";
export type Rendering = "isr" | "per-user";

export interface RouteCeiling {
  readonly rendering: Rendering;
  readonly rscBytes: number;
  readonly htmlBytes: number;
  readonly queries: number;
  readonly serverMs: number;
  readonly cacheEntryBytes: number;
}

const ISR_QUERIES = 8;
const PER_USER_QUERIES = 12;
const ISR_SERVER_MS = 5_000;
const PER_USER_SERVER_MS = 8_000;

const smallPage = { rscBytes: 100 * 1024, htmlBytes: 150 * 1024 };
const universityPage = { rscBytes: 200 * 1024, htmlBytes: 250 * 1024 };
const authorsPage = {
  rscBytes: CACHE_ENTRY_BUDGET_BYTES,
  htmlBytes: CACHE_ENTRY_BUDGET_BYTES + DOCUMENT_SHELL_BYTES,
};

function ceiling(rendering: Rendering, bytes: { readonly rscBytes: number; readonly htmlBytes: number }): RouteCeiling {
  const perUser = rendering === "per-user";
  return {
    rendering,
    rscBytes: bytes.rscBytes,
    htmlBytes: bytes.htmlBytes,
    queries: perUser ? PER_USER_QUERIES : ISR_QUERIES,
    serverMs: perUser ? PER_USER_SERVER_MS : ISR_SERVER_MS,
    cacheEntryBytes: CACHE_ENTRY_BUDGET_BYTES,
  };
}

export interface SiteHealthRouteSpec {
  readonly route: SiteHealthRoute;
  readonly anonymous: RouteCeiling;
  readonly signedIn: RouteCeiling;
}

/** Main routes, both audiences, at full catalog size. A page with no per-user state stays ISR for a signed-in visitor. */
export const SITE_HEALTH: readonly SiteHealthRouteSpec[] = [
  { route: "/", anonymous: ceiling("isr", smallPage), signedIn: ceiling("per-user", smallPage) },
  { route: "/universities", anonymous: ceiling("isr", smallPage), signedIn: ceiling("isr", smallPage) },
  { route: "/universities/[slug]", anonymous: ceiling("isr", universityPage), signedIn: ceiling("isr", universityPage) },
  { route: "/authors", anonymous: ceiling("isr", authorsPage), signedIn: ceiling("isr", authorsPage) },
  { route: "/c/[courseSlug]", anonymous: ceiling("isr", smallPage), signedIn: ceiling("per-user", smallPage) },
  { route: "/c/[courseSlug]/[lessonSlug]", anonymous: ceiling("isr", smallPage), signedIn: ceiling("per-user", smallPage) },
];

export function siteHealthRoute(route: SiteHealthRoute): SiteHealthRouteSpec {
  const found = SITE_HEALTH.find((entry) => entry.route === route);
  if (!found) throw new Error(`No site-health definition for ${route}.`);
  return found;
}

export function siteHealthCeiling(route: SiteHealthRoute, audience: Audience): RouteCeiling {
  const spec = siteHealthRoute(route);
  return audience === "signed-in" ? spec.signedIn : spec.anonymous;
}

/** Anonymous ceiling. Page reads compare their query count with this. */
export function routeBudget(route: SiteHealthRoute): RouteCeiling {
  return siteHealthCeiling(route, "anonymous");
}

export function htmlBytes(rscBytes: number): number {
  return rscBytes + DOCUMENT_SHELL_BYTES;
}

export interface SiteHealthMeasurement {
  readonly route: SiteHealthRoute;
  readonly audience: Audience;
  readonly rscBytes: number;
  readonly queries: number;
  readonly serverMs: number;
  readonly cacheEntryBytes: number;
}

/** Failures for the measurements provided. A missing route is reported only by `siteHealthFailures`. */
export function measurementFailures(measurements: readonly SiteHealthMeasurement[]): string[] {
  return measurements.flatMap((measurement) => {
    const budget = siteHealthCeiling(measurement.route, measurement.audience);
    const html = htmlBytes(measurement.rscBytes);
    const failures: string[] = [];
    if (measurement.rscBytes <= 0) failures.push(`${measurement.route} ${measurement.audience} RSC was not measured`);
    else if (measurement.rscBytes > budget.rscBytes) failures.push(`${measurement.route} ${measurement.audience} RSC ${String(measurement.rscBytes)} bytes over ${String(budget.rscBytes)}`);
    if (html > budget.htmlBytes) failures.push(`${measurement.route} ${measurement.audience} HTML ${String(html)} bytes over ${String(budget.htmlBytes)}`);
    if (measurement.queries > budget.queries) failures.push(`${measurement.route} ${measurement.audience} ${String(measurement.queries)} queries over ${String(budget.queries)}`);
    if (measurement.serverMs > budget.serverMs) failures.push(`${measurement.route} ${measurement.audience} ${String(measurement.serverMs)} ms over ${String(budget.serverMs)}`);
    if (measurement.cacheEntryBytes > budget.cacheEntryBytes) failures.push(`${measurement.route} ${measurement.audience} cache entry ${String(measurement.cacheEntryBytes)} bytes over ${String(budget.cacheEntryBytes)}`);
    return failures;
  });
}

/** Empty when every route and both audiences were measured and are inside the definition. */
export function siteHealthFailures(measurements: readonly SiteHealthMeasurement[]): string[] {
  const missing = SITE_HEALTH.flatMap((spec) => (["anonymous", "signed-in"] as const).flatMap((audience) => (
    measurements.some((entry) => entry.route === spec.route && entry.audience === audience) ? [] : [`${spec.route} ${audience} was not measured`]
  )));
  return [...missing, ...measurementFailures(measurements)];
}

const BATCH_SHA = /^[a-f0-9]{64}$/;

export interface SiteHealthReport {
  readonly batchSha: string;
  readonly passed: boolean;
  readonly failures: readonly string[];
  readonly routes: readonly SiteHealthMeasurement[];
}

export function siteHealthReport(batchSha: string, measurements: readonly SiteHealthMeasurement[]): SiteHealthReport {
  if (!BATCH_SHA.test(batchSha)) throw new Error("batch sha must be 64 hex characters.");
  const failures = siteHealthFailures(measurements);
  return { batchSha, passed: failures.length === 0, failures, routes: measurements };
}

function isRoute(value: unknown): value is SiteHealthRoute {
  return typeof value === "string" && (SITE_HEALTH_ROUTES as readonly string[]).includes(value);
}

function isMeasurement(value: unknown): value is SiteHealthMeasurement {
  if (typeof value !== "object" || value === null) return false;
  const route = "route" in value ? value.route : undefined;
  const audience = "audience" in value ? value.audience : undefined;
  const rscBytes = "rscBytes" in value ? value.rscBytes : undefined;
  const queries = "queries" in value ? value.queries : undefined;
  const serverMs = "serverMs" in value ? value.serverMs : undefined;
  const cacheEntryBytes = "cacheEntryBytes" in value ? value.cacheEntryBytes : undefined;
  return isRoute(route) && (audience === "anonymous" || audience === "signed-in")
    && typeof rscBytes === "number" && typeof queries === "number"
    && typeof serverMs === "number" && typeof cacheEntryBytes === "number";
}

/**
 * None when `report` is a passing measurement of `batchSha` under the current definition.
 * The stored `passed` flag is not trusted: the ceilings are applied again.
 */
export function reportRefusal(batchSha: string, report: unknown): string | null {
  if (!BATCH_SHA.test(batchSha)) return "batch sha must be 64 hex characters.";
  if (typeof report !== "object" || report === null) return "site-health report is unreadable";
  const sha = "batchSha" in report ? report.batchSha : undefined;
  const routes = "routes" in report ? report.routes : undefined;
  if (sha !== batchSha) return "site-health report is for a different batch";
  if (!Array.isArray(routes) || !routes.every(isMeasurement)) return "site-health report is unreadable";
  const failures = siteHealthFailures(routes);
  return failures[0] ?? null;
}
