import { readObjects, syncInstitutionCover, validateObject } from "./media-gateway.ts";
import { homeFailures, homeInstitutionFailures, rowInstitution, storedCoverErrors } from "../domain/rules/home.ts";
import { homeRowSpec } from "../domain/home-row-kind.ts";
import { universityCoverSchema } from "../domain/university-cover.ts";
import { coverObjectReference } from "../domain/cover-object.ts";
import type { Queryable } from "../../platform/db/uow.ts";
import { canonicalJson } from "../../kernel/canonical.ts";
import type { HomePut } from "../domain/contracts.ts";
import { lockReleases, type Outcome } from "./mutation.ts";
import { adoptRowInstitutions } from "./row-institution.ts";
import { assertRevision, unprocessable } from "../../kernel/errors.ts";
import type { HandlerContext } from "./http.ts";
import { publishRelease, scheduleActivation, type Publication } from "./releases.ts";
import { bumpHomeRevision, clearFeaturedExcept, deleteHomeRows, insertHomeRow, insertHomeRowItem, lockHomeRevision, openHomeDryRun, rollbackHomeDryRun, selectAuthorCoverFlags, selectAuthorKindRows, selectCourseInstitutionRows, selectFeaturedPublishedCourse, selectHomeRevision, selectHomeRowItems, selectHomeRows, setConstraintsDeferred, setConstraintsImmediate, setCourseFeatured } from "./table-io.ts";

// The Home's expectedRevision is catalog_home.revision (0007), not MAX(home_rows.revision): PUT /home replaces every
// home_rows row, so their revisions restart and a MAX could repeat an old value (ADR-18).

async function readHome(db: Queryable) {
  const revision = Number((await selectHomeRevision(db))?.revision ?? 1);
  const featured = (await selectFeaturedPublishedCourse(db))?.id;
  const rows = await selectHomeRows(db);
  const items = await selectHomeRowItems(db);
  return {
    revision,
    featuredCourseId: typeof featured === "string" ? featured : null,
    rows: rows.map((row) => ({
      id: String(row.id), kind: String(row.kind), title: (row.title ?? null) as string | null, authorId: (row.author_id ?? null) as string | null,
      institutionId: (row.institution_id ?? null) as string | null, visible: row.visible === true, position: Number(row.position), cover: row.cover ?? null, fullName: (row.full_name ?? null) as string | null, place: (row.place ?? null) as string | null, courseIds: items.filter((item) => item.row_id === row.id).map((item) => String(item.course_id)),
    })),
  };
}

export async function getHome(context: HandlerContext<unknown, unknown, unknown>): Promise<Outcome> {
  return { data: await readHome(context.db) };
}

export async function putHome(context: HandlerContext<unknown, unknown, HomePut>): Promise<Outcome> {
  const body = context.body;
  let publication: Publication | null = null;
  const outcome = await context.mutate(async (tx) => {
    await lockReleases(tx);
    const revision = Number((await lockHomeRevision(tx))?.revision ?? 1);
    assertRevision(revision, body.expectedRevision);
    const before = await readHome(tx);
    const courses = await selectCourseInstitutionRows(tx);
    const statuses = new Map(courses.map((course) => [String(course.id), String(course.status)]));
    // D-024: the provenance parent is the course's institution, never its lecturer (author_id).
    const parents = new Map(courses.flatMap((course) => typeof course.institution_id === "string" ? [[String(course.id), course.institution_id] as const] : []));
    const authors = await selectAuthorKindRows(tx);
    const authorIds = new Set(authors.map((row) => String(row.id)));
    const institutions = new Set(authors.filter((row) => row.kind === "institution").map((row) => String(row.id)));
    const normalized = body.rows.map((row) => {
      const stored = before.rows.find((entry) => entry.id === row.id)?.institutionId;
      const institutionId = row.institutionId ?? (homeRowSpec(row.kind).institution ? stored ?? rowInstitution(row, parents) : undefined);
      return { ...row, ...(institutionId ? { institutionId } : {}) };
    });
    const errors = [...homeFailures({ ...body, rows: normalized }, statuses, authorIds), ...homeInstitutionFailures(normalized, institutions, parents)].map((failure) => failure.message);
    const wanted = normalized.map((row, index) => ({ id: row.id, kind: row.kind, title: row.title ?? null, authorId: row.authorId ?? null, institutionId: homeRowSpec(row.kind).institution ? row.institutionId ?? null : null, visible: row.visible ?? true, position: index + 1,
      // An omitted cover keeps the row's current one. null is an end state with no cover and is refused when the row is visible.
      cover: universityCoverSchema.nullable().parse(row.cover === undefined ? (before.rows.find((entry) => entry.id === row.id)?.cover ?? null) : row.cover),
      fullName: row.fullName === undefined ? (before.rows.find((entry) => entry.id === row.id)?.fullName ?? null) : row.fullName,
      place: row.place === undefined ? (before.rows.find((entry) => entry.id === row.id)?.place ?? null) : row.place, courseIds: row.courseIds }));
    const authorCovers = new Map((await selectAuthorCoverFlags(tx)).map((row) => [String(row.id), row.has_cover === true]));
    const broken = [...errors, ...storedCoverErrors(wanted, authorCovers)];
    if (broken.length > 0) throw unprocessable(`${String(broken.length)} Home invariant(s) fail; nothing changed.`, { errors: broken });
    if (before.featuredCourseId === body.featuredCourseId && canonicalJson(before.rows) === canonicalJson(wanted)) {
      return { data: { home: before, noop: true, ...(body.dryRun ? { dryRun: true as const } : {}) }, noop: true };
    }
    if (body.dryRun) await openHomeDryRun(tx);
    await deleteHomeRows(tx);
    for (const row of wanted) {
      coverObjectReference(row.cover ? (await readObjects(tx, [row.cover.sha256]))[0] : undefined, row.cover);
      const ogRegistered = row.cover?.og ? await validateObject(tx, row.cover.og.sha256) : null;
      if (row.cover?.og?.mediaSha256 && !ogRegistered) throw new Error("Register the OG media object first.");
      if (homeRowSpec(row.kind).cover === "own") {
        await syncInstitutionCover(tx, row.id, "university_cover_9x16", row.cover);
        if (row.institutionId) await syncInstitutionCover(tx, row.institutionId, "poster_9x16", row.cover);
      }
      await insertHomeRow(tx, [row.id, row.kind, row.authorId, row.institutionId, row.title, row.position, row.visible, row.cover === null ? null : JSON.stringify(row.cover), row.fullName, row.place]);
      for (const [index, courseId] of row.courseIds.entries()) await insertHomeRowItem(tx, row.id, courseId, index + 1);
    }
    await adoptRowInstitutions(tx, wanted.map((row) => row.id));
    if (before.featuredCourseId !== body.featuredCourseId) {
      await clearFeaturedExcept(tx, body.featuredCourseId);
      if (body.featuredCourseId !== null) await setCourseFeatured(tx, body.featuredCourseId);
    }
    await bumpHomeRevision(tx);
    // The commit-time rules (deferred own-cover trigger) run now, so a dry run meets every one a write would.
    await setConstraintsImmediate(tx);
    publication = await publishRelease(tx, { note: body.note ?? "Home update", actor: context.actor, fresh: new Set(), now: context.deps.now() });
    const after = await readHome(tx);
    if (body.dryRun) {
      const report = { home: after, release: publication.release, diff: publication.diff, dryRun: true as const };
      await rollbackHomeDryRun(tx);
      await setConstraintsDeferred(tx);
      await tx.audit({ action: "home.set", entityKind: "home", entityId: "home", before, after: { dryRun: true } });
      return { data: report, entity: "home:home" };
    }
    await tx.audit({ action: "home.set", entityKind: "home", entityId: "home", before, after, releaseNumber: publication.release.number });
    scheduleActivation(tx, context.deps, publication.release, publication.release.created);
    return { data: { home: after, release: publication.release, diff: publication.diff }, entity: "home:home" };
  });
  return outcome;
}
