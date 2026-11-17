import { readObjects, syncInstitutionCover } from "./media-gateway.ts";
import { authorDeleteBlockers } from "../domain/rules/lifecycle.ts";
import { coverObjectReference } from "../domain/cover-object.ts";
import type { AuthorCreate, AuthorPatch } from "../domain/contracts.ts";
import { lockRow, type Outcome } from "./mutation.ts";
import { AppError, invalid, notFound, unprocessable } from "../../kernel/errors.ts";
import type { HandlerContext } from "./http.ts";
import { changed } from "./courses.ts";
import { countAuthorTexts, deleteAuthorRow, deleteAuthorTexts, insertAuthorRow, selectAuthorCourseIds, selectAuthorHomeRowIds, selectAuthorIdForSlug, selectAuthorList, selectAuthorRow, selectVisibleAuthorHomeRows, updateAuthorColumns } from "./table-io.ts";

export function authorView(row: Record<string, unknown>) {
  return { id: String(row.id), slug: String(row.slug), name: String(row.name), monogram: String(row.monogram), role: String(row.role), kind: String(row.kind), cover: (row.cover ?? null) as unknown, revision: Number(row.revision) };
}

export async function listAuthors(context: HandlerContext<unknown, unknown, unknown>): Promise<Outcome> {
  const rows = await selectAuthorList(context.db);
  return { data: { authors: rows.map((row) => ({ ...authorView(row), courses: Number(row.courses), homeRows: Number(row.rows) })) } };
}

async function assertSlugFree(db: HandlerContext<unknown, unknown, unknown>["db"], slug: string, id: string | null): Promise<void> {
  const taken = await selectAuthorIdForSlug(db, slug, id);
  if (taken) throw new AppError("slug_taken", `The author slug ${slug} is taken by ${String(taken.id)}.`, { authorId: taken.id });
}

/** INSERT of an author (id from author_seq). Shared with imports (newAuthor). */
export async function insertAuthor(db: HandlerContext<unknown, unknown, unknown>["db"], body: AuthorCreate) {
  await assertSlugFree(db, body.slug, null);
  return authorView(await insertAuthorRow(db, body.slug, body.name, body.monogram, body.role ?? null, body.kind) ?? {});
}

export async function createAuthor(context: HandlerContext<unknown, unknown, AuthorCreate>): Promise<Outcome> {
  return context.mutate(async (tx) => {
    const author = await insertAuthor(tx, context.body);
    await tx.audit({ action: "author.create", entityKind: "author", entityId: author.id, after: author });
    return { status: 201, data: { author }, entity: `author:${author.id}` };
  });
}

export async function patchAuthor(context: HandlerContext<{ id: string }, unknown, AuthorPatch>): Promise<Outcome> {
  const { id } = context.params;
  const body = context.body;
  return context.mutate(async (tx) => {
    const locked = await lockRow(tx, "authors", id, `Author ${id}`, body.expectedRevision);
    const before = authorView(locked);
    const next: Record<string, unknown> = Object.fromEntries((["slug", "name", "monogram", "role", "kind"] as const)
      .filter((field) => body[field] !== undefined && body[field] !== locked[field]).map((field) => [field, body[field]]));
    if (body.cover === null && locked.cover != null) {
      const rows = await selectVisibleAuthorHomeRows(tx, id);
      if (rows.length > 0) {
        const coverErrors = rows.map((row) => `Author row ${String(row.id)} needs a cover on ${id}.`);
        throw unprocessable(coverErrors.join(" "), { errors: coverErrors });
      }
    }
    if (body.cover !== undefined && JSON.stringify(body.cover) !== JSON.stringify(locked.cover ?? null)) {
      await syncInstitutionCover(tx, id, "author_cover_9x16", body.cover);
      next.cover = body.cover === null ? null : JSON.stringify(body.cover);
      coverObjectReference(body.cover ? (await readObjects(tx, [body.cover.sha256]))[0] : undefined, body.cover);
    }
    if (Object.keys(next).length === 0) return { data: { author: before, noop: true }, noop: true, entity: `author:${id}` };
    if (typeof next.slug === "string") await assertSlugFree(tx, next.slug, id);
    const names = Object.keys(next);
    const after = authorView(await updateAuthorColumns(tx, id, names, names.map((column) => next[column])) ?? {});
    await tx.audit({ action: "author.update", entityKind: "author", entityId: id, ...changed(before, after) });
    return { data: { author: after }, entity: `author:${id}` };
  });
}

async function dependents(db: HandlerContext<unknown, unknown, unknown>["db"], id: string) {
  const courses = (await selectAuthorCourseIds(db, id)).map((row) => String(row.id));
  const homeRows = (await selectAuthorHomeRowIds(db, id)).map((row) => String(row.id));
  return { courses, homeRows };
}

/** Dry-run unless confirm=true; an author a course or a Home row points to is never deleted (409 has_dependents). */
export async function deleteAuthor(context: HandlerContext<{ id: string }, { confirm?: boolean; expectedRevision?: number }, unknown>): Promise<Outcome> {
  const { id } = context.params;
  const author = await selectAuthorRow(context.db, id);
  if (!author) throw notFound(`Author ${id}`);
  const report = async (db: HandlerContext<unknown, unknown, unknown>["db"]) => {
    const deps = await dependents(db, id);
    const texts = await countAuthorTexts(db, id);
    return { author: authorView(author), texts: Number(texts ?? 0), dependents: deps, blockedBy: authorDeleteBlockers(deps.courses.length + deps.homeRows.length) };
  };
  if (context.query.confirm !== true) return { data: { dryRun: true, report: await report(context.db) } };
  const expectedRevision = context.query.expectedRevision;
  if (expectedRevision === undefined) throw invalid("confirm=true needs expectedRevision.");
  return context.mutate(async (tx) => {
    const locked = await lockRow(tx, "authors", id, `Author ${id}`, expectedRevision);
    const current = await report(tx);
    if (current.blockedBy.length > 0) throw new AppError("has_dependents", `Author ${id} still has courses or Home rows.`, current.dependents);
    await deleteAuthorTexts(tx, id);
    await deleteAuthorRow(tx, id);
    await tx.audit({ action: "author.delete", entityKind: "author", entityId: id, before: authorView(locked), after: { deleted: true } });
    return { data: { dryRun: false, deleted: true, report: current }, entity: `author:${id}` };
  });
}
