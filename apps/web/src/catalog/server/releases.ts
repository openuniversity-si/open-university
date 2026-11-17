import { ZodError } from "zod";
import type { Queryable } from "../../platform/db/uow.ts";
import {
  cutRelease, diffReleases, prepareReleaseCut, releaseCounts, type ReleaseDiff, type StoredReleaseIndex,
} from "../domain/incremental-compile.ts";
import { parseRelease, type PublicCatalog } from "../domain/release.ts";
import type { CatalogTables } from "../domain/tables.ts";
import { loadReleaseTables } from "./release-load.ts";
import { readCourseRevisions, readProjections, readReleaseIndex, writeProjections, writeRedirects, writeReleaseIndex } from "./projections-repo.ts";
import type { Tx } from "./mutation.ts";
import { lockReleases } from "./mutation.ts";
import { notFound, unprocessable } from "../../kernel/errors.ts";
import { markPublishStart, recordPublishCommitted } from "../../platform/observability/slis.ts";
import type { AdminCatalogDeps } from "./http.ts";
import { iso } from "./common.ts";

export { diffReleases, releaseCounts, type ReleaseDiff };

/** `payload` is normalized to the current schema version (a version 1 release reads as one edition per course); `sha` is the stored one. */
export interface ActiveRelease { readonly number: number; readonly sha: string; readonly payload: PublicCatalog }
export interface ReleaseSummary { readonly number: number; readonly sha: string; readonly counts: Record<string, number> }

export async function readActive(db: Queryable): Promise<ActiveRelease | null> {
  const { rows } = await db.query("SELECT number, payload_sha256, payload FROM catalog_releases WHERE is_active");
  const row = rows[0];
  return row ? { number: Number(row.number), sha: String(row.payload_sha256), payload: parseRelease(row.payload) } : null;
}

/** Active release number and raw payload for a draft compile, or undefined when none is active. */
export async function readActiveNumberAndPayload(db: Queryable): Promise<{ number: unknown; payload: unknown } | undefined> {
  const row = (await db.query("SELECT number, payload FROM catalog_releases WHERE is_active")).rows[0];
  return row ? { number: row.number, payload: row.payload } : undefined;
}

/** Compile failures are 422 with what failed (ids and field names, never text). */
function compileOrFail<T>(compile: () => T): T {
  try {
    return compile();
  } catch (error) {
    if (error instanceof ZodError) throw unprocessable("The release does not validate.", { errors: error.issues.map((issue) => issue.message) });
    throw unprocessable("The release does not compile.", { errors: [error instanceof Error ? error.message : "unknown"] });
  }
}

export interface Compiled {
  readonly payload: PublicCatalog;
  readonly sha: string;
  readonly unchanged: boolean;
  /** Courses whose projection this cut compiled. Empty when the stored projections were reused. */
  readonly compiledCourseIds: readonly string[];
}

/**
 * The tables compiled as the next release would be (ADR-18): `fresh` names the courses being (re)published, whose table
 * text is authoritative; every other published course keeps its live text until its edits are approved and published.
 * `unchanged`: the payload equals the active one (same number and date), so no new release is needed.
 */
function storedIndex(row: Awaited<ReturnType<typeof readReleaseIndex>>): StoredReleaseIndex | null {
  if (!row) return null;
  return {
    courses: row.courses, authors: row.authors, globalFingerprint: row.globalFingerprint,
    ...(row.licenses === undefined ? {} : { licenses: row.licenses }),
    ...(row.sources === undefined ? {} : { sources: row.sources }),
  };
}

async function releaseWrittenAt(db: Queryable, number: number | null): Promise<Date | null> {
  if (number === null) return null;
  const { rows } = await db.query("SELECT created_at FROM catalog_releases WHERE number = $1", [number]);
  const value = rows[0]?.created_at;
  return value instanceof Date ? value : typeof value === "string" ? new Date(value) : null;
}

export async function compileNext(db: Queryable, active: ActiveRelease | null, fresh: ReadonlySet<string>, now: Date, tables?: CatalogTables): Promise<Compiled> {
  const stored = storedIndex(active ? await readReleaseIndex(db, active.number) : null);
  const loaded = tables
    ? { tables, revisions: await readCourseRevisions(db), reuse: undefined }
    : await loadReleaseTables(db, fresh, stored, await releaseWrittenAt(db, active?.number ?? null));
  const prepared = prepareReleaseCut({ tables: loaded.tables, revisions: loaded.revisions, stored, active, fresh, ...(loaded.reuse ? { reuse: loaded.reuse } : {}) });
  if (prepared.plan.noop && active) return { payload: active.payload, sha: active.sha, unchanged: true, compiledCourseIds: [] };
  const storedProjections = await readProjections(db, prepared.refs);
  const { rows } = await db.query("SELECT coalesce(max(number), 0)::int + 1 AS next FROM catalog_releases");
  const cut = compileOrFail(() => cutRelease({
    tables: loaded.tables, prepared, stored, storedProjections, active, now, nextNumber: Number(rows[0]?.next ?? 1),
  }));
  return { payload: cut.payload, sha: cut.sha, unchanged: cut.unchanged, compiledCourseIds: cut.compiledCourseIds };
}

/** Deactivates the active release and activates `number` (the partial unique index allows one active row). Never touches payload. */
export async function activateNumber(tx: Queryable, number: number): Promise<void> {
  await tx.query("UPDATE catalog_releases SET is_active = false WHERE is_active AND number <> $1", [number]);
  await tx.query("UPDATE catalog_releases SET is_active = true, activated_at = now() WHERE number = $1", [number]);
}

export interface Publication { readonly release: ReleaseSummary & { readonly created: boolean; readonly invalidatedCourseIds?: readonly string[] }; readonly diff: ReleaseDiff; readonly previous: number | null }

/**
 * Inside a mutation: compiles the tables, and unless nothing changed, inserts release MAX+1 and activates it, with a
 * `release.create` audit row. The caller revalidates after the commit (afterActivation).
 */
export async function publishRelease(tx: Tx, options: { note: string; actor: string; fresh: ReadonlySet<string>; now: Date; onCourseCompiled?: (courseId: string) => void }): Promise<Publication> {
  markPublishStart();
  await lockReleases(tx);
  const active = await readActive(tx);
  const stored = storedIndex(active ? await readReleaseIndex(tx, active.number) : null);
  const loaded = await loadReleaseTables(tx, options.fresh, stored, await releaseWrittenAt(tx, active?.number ?? null));
  const prepared = prepareReleaseCut({ tables: loaded.tables, revisions: loaded.revisions, stored, active, fresh: options.fresh, reuse: loaded.reuse });
  if (prepared.plan.noop && active) {
    return { release: { number: active.number, sha: active.sha, counts: releaseCounts(active.payload), created: false, invalidatedCourseIds: [] }, diff: diffReleases(active.payload, active.payload), previous: active.number };
  }
  const storedProjections = await readProjections(tx, prepared.refs);
  const { rows } = await tx.query("SELECT coalesce(max(number), 0)::int + 1 AS next FROM catalog_releases");
  const cut = compileOrFail(() => cutRelease({
    tables: loaded.tables, prepared, stored, storedProjections, active, now: options.now, nextNumber: Number(rows[0]?.next ?? 1), onCourseCompiled: options.onCourseCompiled,
  }));
  await writeProjections(tx, cut.written);
  const frame = cut.frame;
  if (cut.unchanged && active) {
    if (!stored) {
      await writeReleaseIndex(tx, active.number, cut.index, frame, cut.payload.publishedAt);
      await writeRedirects(tx, active.number, frame.redirects);
    }
    return { release: { number: active.number, sha: active.sha, counts: releaseCounts(active.payload), created: false, invalidatedCourseIds: [] }, diff: diffReleases(active.payload, active.payload), previous: active.number };
  }
  const payload = cut.payload;
  const counts = releaseCounts(payload);
  const diff = diffReleases(active?.payload ?? null, payload);
  await tx.query(`INSERT INTO catalog_releases (number, schema_version, payload, payload_sha256, counts, note, created_by)
    VALUES ($1, $2, $3::jsonb, $4, $5::jsonb, $6, $7)`, [payload.number, payload.schemaVersion, JSON.stringify(payload), cut.sha, JSON.stringify(counts), options.note, options.actor]);
  await writeReleaseIndex(tx, payload.number, cut.index, frame, payload.publishedAt);
  await writeRedirects(tx, payload.number, frame.redirects);
  await activateNumber(tx, payload.number);
  await tx.audit({ action: "release.create", entityKind: "release", entityId: String(payload.number), before: active ? { active: active.number, sha: active.sha } : null, after: { sha: cut.sha, counts, note: options.note, invalidated: prepared.plan.reasons }, releaseNumber: payload.number });
  return { release: { number: payload.number, sha: cut.sha, counts, created: true, invalidatedCourseIds: prepared.plan.dirty }, diff, previous: active?.number ?? null };
}

/** After the commit only: revalidate the catalog (the site never lacks an active release in between) and log it. */
export function afterActivation(deps: AdminCatalogDeps, release: { number: number; sha: string; invalidatedCourseIds?: readonly string[] }): void {
  deps.invalidateCatalog(release.invalidatedCourseIds ?? []);
  deps.log({ event: "CATALOG_RELEASE_ACTIVATED", number: release.number, sha: release.sha });
}

/** Register activation effects on the open transaction so a rollback never purges the public pages. */
export function scheduleActivation(tx: Tx, deps: AdminCatalogDeps, release: { number: number; sha: string; invalidatedCourseIds?: readonly string[] } | null, when = true): void {
  if (!release || !when) return;
  tx.onAfterCommit(() => {
    recordPublishCommitted();
    afterActivation(deps, release);
  });
}

export async function readRelease(db: Queryable, number: number): Promise<{ number: number; sha: string; payload: unknown; isActive: boolean; note: string; createdBy: string; createdAt: string; activatedAt: string | null }> {
  const { rows } = await db.query("SELECT number, payload_sha256, payload, is_active, note, created_by, created_at, activated_at FROM catalog_releases WHERE number = $1", [number]);
  const row = rows[0];
  if (!row) throw notFound(`Release ${String(number)}`);
  return {
    number: Number(row.number), sha: String(row.payload_sha256), payload: row.payload, isActive: row.is_active === true, note: String(row.note), createdBy: String(row.created_by),
    createdAt: iso(row.created_at) ?? "", activatedAt: iso(row.activated_at),
  };
}

/** Re-validates a stored payload before activating it: any version the reader serves (version 1 normalizes, ADR-21). */
export function assertServable(payload: unknown): PublicCatalog {
  try {
    return parseRelease(payload);
  } catch (error) {
    if (error instanceof ZodError) throw unprocessable("That release no longer validates against the release schema.", { errors: error.issues.map((issue) => issue.message) });
    throw error;
  }
}

