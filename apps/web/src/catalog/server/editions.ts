import type { Queryable } from "../../platform/db/uow.ts";
import { editionLabel, type EditionCreate, type EditionOrder, type EditionPatch, type EditionTerm } from "../domain/contracts.ts";
import { columnsToVariant, indistinctEditionMessage, languageVariantProblem } from "../domain/edition-variant.ts";
import type { EditionVariant } from "../domain/schema/fields.ts";
import { lockRow, touchCourse, type Outcome } from "./mutation.ts";
import { EXTENT } from "../../kernel/extent.ts";
import { AppError, notFound, stateConflict, unprocessable } from "../../kernel/errors.ts";
import type { HandlerContext } from "./http.ts";
import { changed } from "./courses.ts";

// Course editions (ADR-21): position 1 is the newest edition, open by default. A new or re-dated edition takes its place by
// (year, term), newest first, without disturbing the relative order of the others; PUT …/editions/order is the manual exception.

type Ctx<P = { id: string }, Q = unknown, B = unknown> = HandlerContext<P, Q, B>;

/** Within a year: winter (January) < spring < summer < fall; an edition without a term sorts before the termed ones. */
const TERM_RANK: Readonly<Record<EditionTerm, number>> = { winter: 1, spring: 2, summer: 3, fall: 4 };
export function editionDate(edition: { year: number; term: string | null }): number {
  return edition.year * 10 + (edition.term === null ? 0 : TERM_RANK[edition.term as EditionTerm]);
}

export function editionView(row: Record<string, unknown>) {
  return {
    id: String(row.id), courseId: String(row.course_id), slug: String(row.slug), label: String(row.label), term: (row.term ?? null) as string | null,
    year: Number(row.year), position: Number(row.position), resolution: (row.resolution ?? null) as string | null,
    variant: columnsToVariant(typeof row.variant_kind === "string" ? row.variant_kind : null, typeof row.variant_label === "string" ? row.variant_label : null),
    language: typeof row.language === "string" ? row.language : null,
    sourcePlaylistIds: (row.source_playlist_ids ?? []) as string[], revision: Number(row.revision),
  };
}
export type EditionView = ReturnType<typeof editionView>;

async function courseEditions(db: Queryable, courseId: string): Promise<EditionView[]> {
  const { rows } = await db.query("SELECT * FROM course_editions WHERE course_id = $1 ORDER BY position", [courseId]);
  return rows.map(editionView);
}

/**
 * Moves the course's editions to positions 1..N in `order`. Positions pass through values above the current maximum, so
 * neither (course_id, position) nor `position > 0` is ever violated mid-way.
 */
export async function writeEditionPositions(tx: Queryable, courseId: string, order: readonly string[]): Promise<void> {
  if (order.length === EXTENT.empty) return;
  await tx.query(`UPDATE course_editions SET position = position + (SELECT max(position) FROM course_editions WHERE course_id = $1) + $2
    WHERE course_id = $1`, [courseId, order.length]);
  await tx.query(`UPDATE course_editions e SET position = o.position, updated_at = now() FROM unnest($2::text[]) WITH ORDINALITY AS o(id, position)
    WHERE e.course_id = $1 AND e.id = o.id`, [courseId, order]);
}

/** Where `edition` goes among `others` (kept in their order): after every edition at least as recent. */
function placeByDate(others: readonly EditionView[], edition: { id: string; year: number; term: string | null }): string[] {
  const ids = others.filter((other) => other.id !== edition.id).map((other) => other.id);
  const dates = new Map(others.map((other) => [other.id, editionDate(other)]));
  const date = editionDate(edition);
  const index = ids.findIndex((id) => (dates.get(id) ?? 0) < date);
  ids.splice(index === -1 ? ids.length : index, 0, edition.id);
  return ids;
}

/** The label is the term and year, nothing else ("Fall 2024", "2026"): what the selector and the Player kicker show. */
function assertLabel(edition: { label: string; term: string | null; year: number }): void {
  const expected = editionLabel(edition.term as EditionTerm | null, edition.year);
  if (edition.label !== expected) throw unprocessable(`The label of a ${edition.term ?? "year"} ${String(edition.year)} edition is "${expected}", not "${edition.label}" (term and year only; parts such as Labs are not editions).`, { expected });
}

async function assertEditionSlugFree(db: Queryable, courseId: string, slug: string, except?: string): Promise<void> {
  const { rows } = await db.query("SELECT id FROM course_editions WHERE course_id = $1 AND slug = $2 AND id IS DISTINCT FROM $3", [courseId, slug, except ?? null]);
  const taken = rows[EXTENT.first];
  if (taken) throw new AppError("slug_taken", `The edition slug ${slug} is taken in ${courseId}.`, { editionId: taken.id });
}

/** The database unique index is the backstop. This names the other edition before the insert. */
async function assertOfferingFree(db: Queryable, courseId: string, year: number, variant: EditionVariant | null, except?: string): Promise<void> {
  const { rows } = await db.query(`SELECT id FROM course_editions WHERE course_id = $1 AND year = $2 AND id IS DISTINCT FROM $3
    AND variant_kind IS NOT DISTINCT FROM $4 AND variant_label IS NOT DISTINCT FROM $5`,
  [courseId, year, except ?? null, variant?.kind ?? null, variant?.label ?? null]);
  const other = rows[EXTENT.first]?.id;
  if (typeof other === "string") throw unprocessable(indistinctEditionMessage(year, [except ?? "a new edition", other]));
}

/** Inserts an edition in its date place, inside the caller's transaction (the course row is locked). Shared with imports. */
export async function insertEdition(tx: Queryable, courseId: string, input: EditionCreate): Promise<EditionView> {
  assertLabel({ label: input.label, term: input.term ?? null, year: input.year });
  await assertEditionSlugFree(tx, courseId, input.slug);
  await assertOfferingFree(tx, courseId, input.year, input.variant ?? null);
  const variantProblem = languageVariantProblem({ id: input.slug, language: input.language ?? null, variant: input.variant ?? null });
  if (variantProblem) throw unprocessable(variantProblem);
  const existing = await courseEditions(tx, courseId);
  const top = existing.reduce((max, edition) => Math.max(max, edition.position), 0);
  const { rows } = await tx.query(`INSERT INTO course_editions (course_id, slug, label, term, year, position, resolution, source_playlist_ids, variant_kind, variant_label, language)
    VALUES ($1, $2, $3, $4, $5, $6, $7, $8::text[], $9, $10, $11) RETURNING *`,
  [courseId, input.slug, input.label, input.term ?? null, input.year, top + 1, input.resolution ?? null, input.sourcePlaylistIds ?? [], input.variant?.kind ?? null, input.variant?.label ?? null, input.language ?? null]);
  const created = editionView(rows[EXTENT.first] ?? {});
  const order = placeByDate(existing, created);
  await writeEditionPositions(tx, courseId, order);
  return { ...created, position: order.indexOf(created.id) + 1 };
}

/** The edition and its course, or 404. */
export async function editionRow(db: Queryable, id: string): Promise<Record<string, unknown>> {
  const { rows } = await db.query("SELECT * FROM course_editions WHERE id = $1", [id]);
  const edition = rows[EXTENT.first];
  if (!edition) throw notFound(`Edition ${id}`);
  return edition;
}

/** An edition of `courseId`, or 422 (an edition of another course is not a valid target). */
export async function assertCourseEdition(db: Queryable, courseId: string, editionId: string): Promise<void> {
  const { rows } = await db.query("SELECT course_id FROM course_editions WHERE id = $1", [editionId]);
  const edition = rows[EXTENT.first];
  if (!edition) throw unprocessable(`Unknown edition ${editionId}.`);
  if (edition.course_id !== courseId) throw unprocessable(`Edition ${editionId} belongs to ${String(edition.course_id)}, not ${courseId}.`);
}

export async function listEditions(context: Ctx): Promise<Outcome> {
  const courseId = context.params.id;
  const { rows } = await context.db.query("SELECT id FROM courses WHERE id = $1", [courseId]);
  if (!rows[EXTENT.first]) throw notFound(`Course ${courseId}`);
  const { rows: counts } = await context.db.query(`SELECT edition_id, count(*)::int AS lessons, count(*) FILTER (WHERE visible)::int AS visible,
      count(*) FILTER (WHERE part = 'lectures')::int AS lectures, count(*) FILTER (WHERE part = 'labs')::int AS labs, coalesce(sum(duration_seconds), 0)::int AS duration
    FROM lessons WHERE course_id = $1 GROUP BY edition_id`, [courseId]);
  const byEdition = new Map(counts.map((row) => [String(row.edition_id), row]));
  const editions = (await courseEditions(context.db, courseId)).map((edition) => {
    const row = byEdition.get(edition.id);
    return {
      ...edition,
      counts: { lessons: Number(row?.lessons ?? 0), visibleLessons: Number(row?.visible ?? 0), parts: { lectures: Number(row?.lectures ?? 0), labs: Number(row?.labs ?? 0) }, durationSeconds: Number(row?.duration ?? 0) },
    };
  });
  return { data: { courseId, editions } };
}

export async function createEdition(context: Ctx<{ id: string }, unknown, EditionCreate>): Promise<Outcome> {
  const courseId = context.params.id;
  return context.mutate(async (tx) => {
    const course = await lockRow(tx, "courses", courseId, `Course ${courseId}`);
    if (course.status === "archived") throw stateConflict("An archived course takes no new edition; move it to draft first.");
    const edition = await insertEdition(tx, courseId, context.body);
    const courseRevision = await touchCourse(tx, courseId);
    const order = (await courseEditions(tx, courseId)).map((entry) => entry.id);
    await tx.audit({ action: "edition.create", entityKind: "edition", entityId: edition.id, after: { ...edition, order, courseRevision } });
    return { status: 201, data: { edition, order, courseRevision }, entity: `edition:${edition.id}` };
  });
}

export async function patchEdition(context: Ctx<{ id: string }, unknown, EditionPatch>): Promise<Outcome> {
  const { id } = context.params;
  const body = context.body;
  const courseId = String((await editionRow(context.db, id)).course_id);
  return context.mutate(async (tx) => {
    await lockRow(tx, "courses", courseId, `Course ${courseId}`);
    const before = editionView(await lockRow(tx, "course_editions", id, `Edition ${id}`, body.expectedRevision));
    const columns = { slug: "slug", label: "label", term: "term", year: "year", resolution: "resolution", sourcePlaylistIds: "source_playlist_ids", language: "language" } as const;
    const next: Record<string, unknown> = {};
    for (const [field, column] of Object.entries(columns)) {
      const value = body[field as keyof typeof columns];
      if (value !== undefined && JSON.stringify(value) !== JSON.stringify(before[field as keyof EditionView])) next[column] = value;
    }
    if (body.variant !== undefined && JSON.stringify(body.variant) !== JSON.stringify(before.variant)) {
      next.variant_kind = body.variant?.kind ?? null;
      next.variant_label = body.variant?.label ?? null;
    }
    const variantProblem = languageVariantProblem({
      id, language: body.language === undefined ? before.language : body.language, variant: body.variant === undefined ? before.variant : body.variant,
    });
    if (variantProblem) throw unprocessable(variantProblem);
    if (Object.keys(next).length === EXTENT.empty) return { data: { edition: before, noop: true }, noop: true, entity: `edition:${id}` };
    if (typeof next.slug === "string") await assertEditionSlugFree(tx, courseId, next.slug, id);
    if ("label" in next || "term" in next || "year" in next) {
      assertLabel({ label: body.label ?? before.label, term: body.term === undefined ? before.term : body.term, year: body.year ?? before.year });
    }
    if ("year" in next || "variant_kind" in next) {
      const variant = body.variant === undefined ? before.variant : body.variant;
      await assertOfferingFree(tx, courseId, body.year ?? before.year, variant, id);
    }
    const names = Object.keys(next);
    const { rows: updated } = await tx.query(`UPDATE course_editions SET ${names.map((column, index) => `${column} = $${String(index + 2)}${column === "source_playlist_ids" ? "::text[]" : ""}`).join(", ")},
      revision = revision + 1, updated_at = now() WHERE id = $1 RETURNING *`, [id, ...names.map((column) => next[column])]);
    let after = editionView(updated[EXTENT.first] ?? {});
    if ("year" in next || "term" in next) {
      const order = placeByDate(await courseEditions(tx, courseId), after);
      await writeEditionPositions(tx, courseId, order);
      after = { ...after, position: order.indexOf(id) + 1 };
    }
    const courseRevision = await touchCourse(tx, courseId);
    await tx.audit({ action: "edition.update", entityKind: "edition", entityId: id, ...changed(before, after) });
    return { data: { edition: after, courseRevision }, entity: `edition:${id}` };
  });
}

/** Full, atomic reorder: `editionIds` must be exactly the course's editions; the first becomes the default (position 1). */
export async function reorderEditions(context: Ctx<{ id: string }, unknown, EditionOrder>): Promise<Outcome> {
  const courseId = context.params.id;
  const { editionIds, expectedRevision } = context.body;
  return context.mutate(async (tx) => {
    await lockRow(tx, "courses", courseId, `Course ${courseId}`, expectedRevision);
    const current = (await courseEditions(tx, courseId)).map((edition) => edition.id);
    const seen = new Set<string>();
    const duplicated = [...new Set(editionIds.filter((id) => (seen.has(id) ? true : (seen.add(id), false))))];
    const missing = current.filter((id) => !seen.has(id));
    const unknown = [...seen].filter((id) => !current.includes(id));
    if (missing.length + unknown.length + duplicated.length > EXTENT.empty) throw unprocessable("editionIds must list every edition of the course exactly once.", { missing, unknown, duplicated });
    if (current.every((id, index) => editionIds[index] === id)) return { data: { editionIds: current, revision: expectedRevision, noop: true }, noop: true, entity: `course:${courseId}` };
    await writeEditionPositions(tx, courseId, editionIds);
    const revision = await touchCourse(tx, courseId);
    await tx.audit({ action: "edition.reorder", entityKind: "course", entityId: courseId, before: { editionIds: current }, after: { editionIds, manual: true } });
    return { data: { editionIds, revision }, entity: `course:${courseId}` };
  });
}
