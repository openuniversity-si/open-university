import "server-only";
import { remember } from "../../platform/freshness/next.ts";
import { buildWithoutDatabase } from "../../platform/db/database-env.ts";
import { CACHE } from "../../kernel/cache.ts";
import { sha256Hex } from "../../kernel/canonical.ts";
import { CacheEntryOverBudget, assertCacheEntry, loadWithinBudget } from "../../kernel/cache-budget.ts";
import { cache } from "react";
import { appPool } from "../../platform/db/pool.ts";
import type { Queryable } from "../../platform/db/uow.ts";
import { frameForCourses } from "../domain/page-frame.ts";
import { stitchRelease, type CatalogReleaseIndex, type CompiledCourseProjection } from "../domain/incremental-compile.ts";
import type { PublicCatalog } from "../domain/release.ts";
import type { CatalogQueriesPort, ReadScope } from "../ports/queries.ts";
import { createCatalogQueries } from "./queries.ts";
import { authorIdsOfProjections, readActiveReleaseNumber, readProjections, readReleaseIndex } from "./projections-repo.ts";
import { CATALOG_TAG, getCatalog, presentCatalog } from "./read.ts";

/** Which slice of the active release a public page needs. */
export type PageRead =
  | { readonly kind: "release" }
  | { readonly kind: "university"; readonly slug: string }
  | { readonly kind: "area"; readonly slug: string; readonly area: string }
  | { readonly kind: "course"; readonly slug: string };

function selectionFromKey(key: string): PageRead {
  const value: unknown = JSON.parse(key);
  if (typeof value !== "object" || value === null || !("kind" in value)) return { kind: "release" };
  const kind = value.kind;
  const slug = "slug" in value && typeof value.slug === "string" ? value.slug : "";
  const area = "area" in value && typeof value.area === "string" ? value.area : "";
  if (kind === "university" && slug) return { kind: "university", slug };
  if (kind === "area" && slug && area) return { kind: "area", slug, area };
  if (kind === "course" && slug) return { kind: "course", slug };
  return { kind: "release" };
}

async function selectedIds(db: Queryable, queries: CatalogQueriesPort, scope: ReadScope, index: CatalogReleaseIndex, featuredCourseId: string | null, selection: PageRead): Promise<ReadonlySet<string>> {
  const all = new Set(index.courses.map((course) => course.courseId));
  const withFeatured = (ids: Iterable<string>) => {
    const set = new Set(ids);
    if (featuredCourseId && all.has(featuredCourseId)) set.add(featuredCourseId);
    return set;
  };
  if (selection.kind === "release") return all;
  if (selection.kind === "university") {
    const page = await queries.getUniversityPageProjection(selection.slug, scope);
    return page ? withFeatured(page.courseIds) : all;
  }
  if (selection.kind === "area") {
    const page = await queries.getUniversityAreaProjection(selection.slug, selection.area, scope);
    return page ? withFeatured(page.courseIds) : all;
  }
  const detail = await queries.getCourseDetailProjection(selection.slug, scope);
  if (!detail) return all;
  const authors = await authorIdsOfProjections(db, index.courses);
  const authorId = authors.get(detail.id);
  const sameAuthor = index.courses.filter((course) => authors.get(course.courseId) === authorId).map((course) => course.courseId);
  return withFeatured(sameAuthor.length > 0 ? sameAuthor : [detail.id]);
}

async function readUncached(selection: PageRead, preview: boolean, cookie?: string): Promise<PublicCatalog> {
  if (preview) return getCatalog(2, true, cookie);
  if (buildWithoutDatabase()) return getCatalog();
  const db = appPool();
  try {
    const number = await readActiveReleaseNumber(db);
    const queries = createCatalogQueries(db);
    const scope: ReadScope = { releaseNumber: number, preview: false };
    const index = await queries.getCatalogIndex(scope);
    const stored = index ? await readReleaseIndex(db, number) : null;
    if (!index || !stored) return await getCatalog();
    const ids = await selectedIds(db, queries, scope, index, stored.frame.home.featuredCourseId, selection);
    const refs = index.courses.filter((course) => ids.has(course.courseId));
    const projections = await cachedProjections(db, number, stored.manifestSha256, refs);
    const stitched = stitchRelease({
      number,
      publishedAt: stored.publishedAt,
      projections,
      frame: frameForCourses(stored.frame, projections.map((projection) => projection.detail.course), projections.flatMap((projection) => projection.detail.lessons)),
    });
    return await presentCatalog(stitched);
  } catch (error) {
    if (error instanceof CacheEntryOverBudget) throw error;
    return await getCatalog();
  }
}

/** One batched read for the request, stored as chunks keyed by release number, manifest sha and the slice. */
async function cachedProjections(db: Queryable, number: number, manifestSha: string, refs: readonly { readonly courseId: string; readonly sha256: string }[]): Promise<CompiledCourseProjection[]> {
  let pending: Promise<Map<string, CompiledCourseProjection>> | undefined;
  const readAll = () => (pending ??= readProjections(db, refs));
  const parts = await loadWithinBudget(refs, (slice) => {
    const hash = sha256Hex(slice.map((ref) => `${ref.courseId}:${ref.sha256}`).join("\n"));
    return remember(async () => {
      const loaded = await readAll();
      const projections = slice.map((ref) => {
        const found = loaded.get(ref.courseId);
        if (!found || found.sha256 !== ref.sha256) throw new Error(`Projection ${ref.courseId} is missing.`);
        return found;
      });
      assertCacheEntry(projections);
      return projections;
    }, ["catalog", "projections", String(number), manifestSha, hash], { tags: [CATALOG_TAG], revalidate: CACHE.untilTagged })();
  });
  return parts.flat();
}

const loadPageCatalog = cache((key: string, preview: boolean, cookie = "") => readUncached(selectionFromKey(key), preview, cookie || undefined));

/** Public pages read one release through CatalogQueriesPort. Draft mode and a missing index stay on the v2 payload. */
export function readPageCatalog(selection: PageRead = { kind: "release" }, preview = false, cookie?: string): Promise<PublicCatalog> {
  return loadPageCatalog(JSON.stringify(selection), preview, cookie ?? "");
}
