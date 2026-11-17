import "server-only";
import { currentEnv } from "../../kernel/env.ts";
import { errorSummary } from "../../kernel/errors.ts";
import { logStructured } from "../../platform/observability/logger.ts";
import { appPool } from "../../platform/db/pool.ts";
import type { Queryable } from "../../platform/db/uow.ts";
import { verifyPreviewToken, type PreviewClaims } from "./preview-token.ts";
import { compileRelease } from "../domain/compile.ts";
import { previewTables } from "../domain/preview.ts";
import { parseRelease, type PublicCatalog } from "../domain/release.ts";
import { releaseSha } from "../../kernel/sha.ts";
import { readActiveNumberAndPayload } from "./releases.ts";
import { readCatalogTables } from "./table-io.ts";

/** The preview claims of a signed preview cookie, or null. */
export function previewClaims(cookie: string | undefined): PreviewClaims | null {
  return verifyPreviewToken(currentEnv().TOWER_ADMIN_MEDIA_SECRET, cookie, new Date());
}

/**
 * The catalog a reviewer previews (plan §2.4): the tables compiled with the draft/review courses of the token's scope, read
 * uncached on every request. A published course outside the scope keeps its live text.
 */
export async function compileDraftCatalog(db: Queryable, scope: string | null): Promise<{ catalog: PublicCatalog; sha: string }> {
  const tables = await readCatalogTables(db);
  const active = await readActiveNumberAndPayload(db);
  const previous = active ? parseRelease(active.payload) : undefined;
  const fresh = new Set(scope === null ? tables.courses.map((course) => course.id) : [scope]);
  const catalog = compileRelease(previewTables(tables, scope), { number: Number(active?.number ?? 1), publishedAt: new Date().toISOString() }, { ...(previous ? { previous } : {}), fresh });
  return { catalog, sha: releaseSha(catalog) };
}

/** Draft mode with a valid preview cookie: the draft catalog; otherwise (or if it cannot compile) null, and the site serves the release. */
export async function draftCatalogState(cookie: string | undefined): Promise<{ catalog: PublicCatalog; sha: string; source: "preview" } | null> {
  const claims = previewClaims(cookie);
  if (!claims) return null;
  try {
    return { ...(await compileDraftCatalog(appPool(), claims.scope)), source: "preview" };
  } catch (error) {
    logStructured("error", "CATALOG_PREVIEW_FAILED", { error: errorSummary(error) });
    return null;
  }
}
