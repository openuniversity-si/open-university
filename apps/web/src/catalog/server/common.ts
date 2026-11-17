import { limitConcurrency, type ConcurrencyLimit } from "../../platform/db/limit.ts";
import type { Queryable } from "../../platform/db/uow.ts";
import { courseScope, readCatalogTables } from "./table-io.ts";
import { AppError, unprocessable } from "../../kernel/errors.ts";
import { activeCoverKinds } from "./cover-kinds.ts";
import { coursePath, type CatalogState } from "../domain/rules-helpers.ts";

export { coursePath, editionCounts, factsOf, iso, lessonPath, livePaths, pendingFor, type CatalogState } from "../domain/rules-helpers.ts";

const REVISIONS = "SELECT id, revision FROM courses UNION ALL SELECT id, revision FROM course_editions UNION ALL SELECT id, revision FROM lessons UNION ALL SELECT id, revision FROM authors";

/** Tables and revisions, overlapping. Covers stay a later read: they open their own media queries. */
export async function readTablesAndRevisions(db: Queryable, occupy?: ConcurrencyLimit): Promise<Pick<CatalogState, "tables" | "revisions">> {
  const slots = occupy ?? limitConcurrency(3);
  const [tables, revision] = await Promise.all([
    readCatalogTables(db, undefined, slots),
    slots(() => db.query(REVISIONS)),
  ]);
  return { tables, revisions: new Map(revision.rows.map((row) => [String(row.id), Number(row.revision)])) };
}

export async function readState(db: Queryable): Promise<CatalogState> {
  const body = await readTablesAndRevisions(db);
  return { ...body, covers: await activeCoverKinds(db) };
}

/**
 * readState for some courses only: the same facts and course detail, without reading the whole catalog. A single-course
 * route (GET /courses/:id, a status move, a publish) costs its course's rows, not O(catalog) per call.
 */
export async function readCourseState(db: Queryable, courseIds: readonly string[]): Promise<CatalogState> {
  const [tables, revision] = await Promise.all([
    readCatalogTables(db, courseScope(courseIds)),
    db.query(`SELECT id, revision FROM courses WHERE id = ANY($1) UNION ALL SELECT id, revision FROM course_editions WHERE course_id = ANY($1)
    UNION ALL SELECT id, revision FROM lessons WHERE course_id = ANY($1) UNION ALL SELECT id, revision FROM authors WHERE id IN (SELECT author_id FROM courses WHERE id = ANY($1))`, [courseIds]),
  ]);
  return { tables, revisions: new Map(revision.rows.map((row) => [String(row.id), Number(row.revision)])), covers: await activeCoverKinds(db, courseIds) };
}

/** Every course and lesson path the tables hold, published or not: a valid redirect target or a slug taken. */
export async function existingPaths(db: Queryable): Promise<Set<string>> {
  const { rows } = await db.query("SELECT '/c/' || slug AS path FROM courses UNION ALL SELECT '/c/' || c.slug || '/' || l.slug FROM lessons l JOIN courses c ON c.id = l.course_id");
  return new Set(rows.map((row) => String(row.path)));
}

/** A new course or lesson path must not be the source of a redirect (409): the old URL keeps pointing where it did. */
export async function assertPathFree(db: Queryable, path: string): Promise<void> {
  const { rows } = await db.query("SELECT to_path FROM slug_redirects WHERE from_path = $1", [path]);
  if (rows[0]) throw new AppError("slug_taken", `${path} is the source of a redirect to ${String(rows[0].to_path)}; delete the redirect first.`, { redirect: { from: path, to: rows[0].to_path } });
}

/**
 * `from` now redirects to `to`. Redirects that pointed at `from` move to `to` (no chains), so a later rename never
 * strands an old URL; `to` must not itself be a redirect source (no cycle).
 */
export async function addRedirect(tx: Queryable, from: string, to: string): Promise<void> {
  if (from === to) return;
  const { rows } = await tx.query("SELECT 1 FROM slug_redirects WHERE from_path = $1", [to]);
  if (rows[0]) throw new AppError("state_conflict", `Redirecting ${from} to ${to} would form a cycle.`);
  await tx.query("UPDATE slug_redirects SET to_path = $2 WHERE to_path = $1", [from, to]);
  await tx.query("INSERT INTO slug_redirects (from_path, to_path) VALUES ($1, $2) ON CONFLICT (from_path) DO UPDATE SET to_path = EXCLUDED.to_path", [from, to]);
}

/** Redirects ending at the course's pages (the course or its lessons), e.g. before a purge removes those pages. */
export async function redirectsInto(db: Queryable, courseSlug: string): Promise<{ from: string; to: string }[]> {
  const { rows } = await db.query("SELECT from_path, to_path FROM slug_redirects WHERE to_path = $1 OR to_path LIKE $2 ORDER BY from_path", [coursePath(courseSlug), `${coursePath(courseSlug)}/%`]);
  return rows.map((row) => ({ from: String(row.from_path), to: String(row.to_path) }));
}

export async function assertExists(db: Queryable, table: "authors" | "licenses" | "content_sources" | "courses" | "subject_areas" | "subject_subareas", key: string, label: string): Promise<void> {
  const column = table === "licenses" ? "code" : "id";
  const { rows } = await db.query(`SELECT 1 FROM ${table} WHERE ${column} = $1`, [key]);
  if (!rows[0]) throw unprocessable(`Unknown ${label} ${key}.`);
}

/** Visible-lesson count of a course, for the "a published course keeps a lesson" rule. */
export async function visibleLessons(db: Queryable, courseId: string): Promise<number> {
  const { rows } = await db.query("SELECT count(*)::int AS n FROM lessons WHERE course_id = $1 AND visible", [courseId]);
  return Number(rows[0]?.n ?? 0);
}

/** Moves the lessons of an edition to positions 1..N in `order` without ever colliding on (edition_id, position). */
export async function writePositions(tx: Queryable, editionId: string, order: readonly string[]): Promise<void> {
  if (order.length === 0) return;
  await tx.query("UPDATE lessons SET position = -position WHERE edition_id = $1 AND position > 0", [editionId]);
  await tx.query(`UPDATE lessons l SET position = o.position, updated_at = now() FROM unnest($2::text[]) WITH ORDINALITY AS o(id, position)
    WHERE l.edition_id = $1 AND l.id = o.id`, [editionId, order]);
}

/** The edition's lessons renumbered 1..N in their current order (after a lesson left it). */
export async function compactPositions(tx: Queryable, editionId: string): Promise<void> {
  const { rows } = await tx.query("SELECT id FROM lessons WHERE edition_id = $1 ORDER BY position", [editionId]);
  await writePositions(tx, editionId, rows.map((row) => String(row.id)));
}

