import { preconditionsFailed, invalid } from "../../kernel/errors.ts";
import { activeCoverKinds, attachCoverSet, clearOrphanedMany, readObjects, type CoverAttachRow } from "./media-gateway.ts";
import { MEDIA_PUBLIC_HOST } from "../../media/domain/types.ts";
import type { Queryable } from "../../platform/db/uow.ts";
import type { CourseBundleV1 } from "../domain/bundle.ts";
import { planBatch, type BatchPlan, type BatchRefs } from "../domain/batch-plan.ts";
import { batchV2Hash, mergeBatchParts, type ApplyBatchBody, type ApplyBatchData, type ApplyBatchReport } from "../domain/batch-v2.ts";
import { catalogBatchV2Schema, taxonomyCoverEntries, type CatalogBatchV2 } from "../domain/schema/batch-v2.ts";
import { catalogCourseFacts, evaluateRules } from "../domain/rules/status.ts";
import { notWrittenFailures } from "../domain/rules/lifecycle.ts";
import { readCourseState } from "./common.ts";
import type { HandlerContext } from "./http.ts";
import type { Outcome, Tx } from "./mutation.ts";
import { publishRelease, scheduleActivation } from "./releases.ts";
import { writeBundles } from "./ship-batch.ts";
import { assignCourseInstitutions, bumpHomeRevision, commitShipBatch, insertBatchLicenses, insertBatchPlacements, insertCuratedHomeRow, lockCatalogV2Batch, openBatchApplySavepoint, openCatalogV2Batch, publishShipCourses, releaseBatchApply, restoreHomePositions, rollbackBatchApply, saveShipChunk, selectBatchRefs, selectHomeRowPosition, selectMaxHomePosition, selectShipChunkBundles, setConstraintsDeferred, setConstraintsImmediate, shiftHomePositions, updateBatchHomeRow, upsertBatchAuthors, upsertContentSources, upsertSubjectAreas, upsertSubjectSubareas } from "./table-io.ts";

// POST /batches/apply (S08, CONTRACT §5): a CatalogBatchV2 in one transaction. The core plans it (planBatch); this
// adapter writes the rows, then publishes only when the batch is not a draft (D-053).

function shasOf(batch: CatalogBatchV2): string[] {
  return [...new Set([
    ...batch.institutions.flatMap((item) => [item.cover.poster, item.cover.og ?? ""]),
    ...batch.homeRows.flatMap((row) => [row.cover.sha, row.og ?? ""]),
    ...batch.areas.flatMap((node) => taxonomyCoverEntries("area", node.cover).map((cover) => cover.sha)),
    ...batch.subareas.flatMap((node) => taxonomyCoverEntries("subarea", node.cover).map((cover) => cover.sha)),
    ...batch.courses.flatMap((item) => item.covers.map((cover) => cover.sha)),
  ].filter(Boolean))];
}

/** The stored rows a batch reaches: catalog refs in one round trip, registered media through the media port. */
export async function loadBatchRefs(db: Queryable, batch: CatalogBatchV2): Promise<BatchRefs> {
  const authors = [...batch.institutions, ...batch.lecturers];
  const row = await selectBatchRefs(db,
    [...batch.sources.map((source) => source.id), ...batch.courses.flatMap((item) => (item.course.sourceId ? [item.course.sourceId] : []))], [...authors.map((author) => author.id), ...batch.courses.flatMap((item) => [item.institutionId, item.course.authorId]), ...batch.homeRows.map((row) => row.institutionId)],
    authors.map((author) => author.slug), batch.courses.map((item) => item.course.id), batch.courses.map((item) => item.course.slug),
  );
  // Registered objects come from the media context's port (L2.sql-owner).
  const registered = await readObjects(db, shasOf(batch));
  const refs = row?.refs as {
    sources: Record<string, Record<string, unknown>>; authors: Record<string, { slug: string; name: string; monogram: string; kind: string }>;
    areas: Record<string, { title: string }>; subareas: Record<string, { areaId: string; title: string }>;
    homeRows: Record<string, { institutionId: string | null; title: string | null }>; courses: Record<string, { slug: string; institutionId: string | null }>;
    licenses: string[];
  };
  const map = <T>(value: Record<string, T>) => new Map(Object.entries(value));
  const covers = await activeCoverKinds(db, batch.courses.map((item) => item.course.id));
  return {
    sources: map(refs.sources), authors: map(refs.authors), areas: map(refs.areas), subareas: map(refs.subareas), homeRows: map(refs.homeRows),
    courses: map(refs.courses), licenses: new Set(refs.licenses), covers, media: new Set(registered.map((object) => object.sha256)),
  };
}

const actions = (plan: BatchPlan, step: string) => new Map(plan.ops.filter((op) => op.step === step).map((op) => [op.id, op.action]));

/** Refs, lecturers and taxonomy in one statement per table (D-035). A noop is left untouched. */
export async function writeRefs(tx: Tx, batch: CatalogBatchV2, plan: BatchPlan): Promise<void> {
  const sources = actions(plan, "source");
  await upsertContentSources(tx, batch.sources.filter((source) => sources.get(source.id) !== "noop").map((source) => ({
    id: source.id, kind: source.kind, title: source.title, publisher: source.publisher ?? source.title, url: source.url, youtube_channel_id: source.youtubeChannelId ?? null,
  })));
  const authors = new Map([...actions(plan, "institution"), ...actions(plan, "lecturer")]);
  await upsertBatchAuthors(tx, [...batch.institutions, ...batch.lecturers].filter((author) => authors.get(author.id) !== "noop").map((author) => ({
    id: author.id, slug: author.slug, name: author.name, monogram: author.monogram, kind: author.kind,
  })));
  const licenses = actions(plan, "license");
  await insertBatchLicenses(tx, batch.licenses.filter((license) => licenses.get(license.code) === "create").map((license) => ({
    code: license.code, name: license.name, url: license.url ?? null, requires_attribution: license.requiresAttribution,
    non_commercial: license.nonCommercial, share_alike: license.shareAlike, embed_only: license.embedOnly, attribution_template: license.attributionTemplate ?? null,
  })));
  const areas = actions(plan, "area");
  await upsertSubjectAreas(tx, batch.areas.filter((area) => areas.get(area.id) !== "noop").map((area) => ({ id: area.id, title: area.title })));
  const subareas = actions(plan, "subarea");
  await upsertSubjectSubareas(tx, batch.subareas.filter((subarea) => subareas.get(subarea.id) !== "noop").map((subarea) => ({ id: subarea.id, area_id: subarea.areaId, title: subarea.title })));
}

async function writeHomeRows(tx: Tx, batch: CatalogBatchV2, plan: BatchPlan): Promise<void> {
  const rows = actions(plan, "home-row");
  for (const row of batch.homeRows) {
    if (rows.get(row.id) === "noop") continue;
    const [object] = await readObjects(tx, [row.cover.sha]);
    const [og] = row.og ? await readObjects(tx, [row.og]) : [];
    if (!object) throw invalid(`Media object ${row.cover.sha} is not registered.`);
    const url = (sha: string, ext: string) => `https://${MEDIA_PUBLIC_HOST}/m/${sha}.${ext}`;
    const cover = {
      mediaSha256: object.sha256, url: url(object.sha256, object.ext), width: object.width, height: object.height, sha256: object.sha256,
      alt: row.cover.alt, credit: row.cover.credit, sourceUrl: row.cover.sourceUrl, license: row.cover.license, note: row.cover.note ?? null,
      ...(og ? { og: { mediaSha256: og.sha256, url: url(og.sha256, og.ext), width: og.width, height: og.height, sha256: og.sha256 } } : {}),
    };
    if (rows.get(row.id) === "update") {
      await updateBatchHomeRow(tx, row.id, row.title, row.fullName ?? null, row.place ?? null, row.visible, JSON.stringify(cover));
      continue;
    }
    // Insert after `after` (else last): shift the later rows out of the unique position range and back, one step down.
    const after = row.after ? Number((await selectHomeRowPosition(tx, row.after))?.position) : null;
    const position = after ?? Number((await selectMaxHomePosition(tx))?.p) ;
    await shiftHomePositions(tx, position);
    await restoreHomePositions(tx);
    await insertCuratedHomeRow(tx, [row.id, row.institutionId, row.title, row.fullName ?? null, row.place ?? null, position + 1, row.visible, JSON.stringify(cover)]);
  }
  if (batch.homeRows.length > 0 || batch.courses.some((item) => item.homeRowId)) await bumpHomeRevision(tx);
}

interface CoverAttach { readonly owner_kind: string; readonly owner_id: string; readonly kind: string; readonly sha: string; readonly alt: string }

function coverAttaches(batch: CatalogBatchV2): CoverAttach[] {
  const rows: CoverAttach[] = [];
  const push = (owner: string, ownerId: string, kind: string, sha: string, alt: string) => rows.push({ owner_kind: owner, owner_id: ownerId, kind, sha, alt });
  for (const item of batch.institutions) {
    push("institution", item.id, "poster_9x16", item.cover.poster, item.name);
    if (item.cover.og) push("institution", item.id, "og", item.cover.og, item.name);
  }
  for (const row of batch.homeRows) {
    push("institution", row.id, "university_cover_9x16", row.cover.sha, row.cover.alt);
    if (row.og) push("institution", row.id, "og", row.og, row.cover.alt);
  }
  for (const [owner, nodes] of [["area", batch.areas], ["subarea", batch.subareas]] as const) {
    for (const node of nodes) {
      for (const cover of taxonomyCoverEntries(owner, node.cover)) if (cover.allowed) push(owner, node.id, cover.kind, cover.sha, node.title);
    }
  }
  for (const item of batch.courses) for (const cover of item.covers) push("course", item.course.id, cover.kind, cover.sha, item.course.title);
  // Sequential attach kept the last declaration of one owner and kind. A home-row og can replace the institution og.
  const last = new Map<string, CoverAttach>();
  for (const row of rows) last.set(`${row.owner_kind}\n${row.owner_id}\n${row.kind}`, row);
  return [...last.values()];
}

/**
 * Every declared cover, written by the media adapter in two set-based statements (D-035).
 * The ship transaction already holds the batch; per-row advisory locks are not taken.
 */
export async function writeMedia(tx: Tx, batch: CatalogBatchV2): Promise<void> {
  const wanted = coverAttaches(batch);
  if (wanted.length === 0) return;
  const objects = new Map((await readObjects(tx, [...new Set(wanted.map((row) => row.sha))])).map((object) => [object.sha256, object]));
  const rows: CoverAttachRow[] = wanted.map((row) => {
    const object = objects.get(row.sha);
    if (!object) throw invalid(`Media object ${row.sha} is not registered.`);
    const pathname = `m/${object.sha256}.${object.ext}`;
    return {
      owner_kind: row.owner_kind, owner_id: row.owner_id, kind: row.kind, variant: "default",
      url: `https://${MEDIA_PUBLIC_HOST}/${pathname}`, pathname, width: object.width, height: object.height,
      sha256: object.sha256, alt: row.alt, media_sha256: object.sha256,
    };
  });
  await attachCoverSet(tx, rows);
  await clearOrphanedMany(tx, [...new Set(rows.map((row) => row.media_sha256))]);
}

export async function writeCourses(tx: Tx, batch: CatalogBatchV2, refs: BatchRefs, checkedAt: string): Promise<string[]> {
  const people = new Map<string, CourseBundleV1["author"]>();
  for (const [id, author] of refs.authors) people.set(id, { id, slug: author.slug, name: author.name, monogram: author.monogram, kind: author.kind as CourseBundleV1["author"]["kind"] });
  for (const author of [...batch.institutions, ...batch.lecturers]) people.set(author.id, { id: author.id, slug: author.slug, name: author.name, monogram: author.monogram, kind: author.kind });
  const bundles: CourseBundleV1[] = batch.courses.map((item) => {
    const author = people.get(item.course.authorId);
    if (!author) throw invalid(`Lecturer ${item.course.authorId} does not exist.`);
    return { version: 1, author, course: item.course, editions: item.editions, lessons: item.lessons, texts: item.texts, home: null, covers: [] };
  });
  await writeBundles(tx, bundles, { licenses: new Set(), sources: new Set(), areas: new Set(), subareas: [], authors: [], courses: [], editions: [], videos: [], shares: [], lessons: [], homeRows: [] }, checkedAt);
  await assignCourseInstitutions(tx, JSON.stringify(batch.courses.map((item) => ({ id: item.course.id, institution_id: item.institutionId }))));
  const placements = batch.courses.flatMap((item) => (item.homeRowId ? [{ row_id: item.homeRowId, course_id: item.course.id }] : []));
  if (placements.length > 0) await insertBatchPlacements(tx, JSON.stringify(placements));
  return batch.courses.map((item) => item.course.id);
}

/** Rows of one batch. This function does not publish (D-053). */
export async function writeBatchRows(tx: Tx, batch: CatalogBatchV2, checkedAt: string): Promise<{ plan: BatchPlan; ids: string[] }> {
  await openBatchApplySavepoint(tx);
  const refs = await loadBatchRefs(tx, batch);
  const plan = planBatch(batch, refs);
  if (plan.failures.length > 0) throw preconditionsFailed(plan.failures);
  await writeRefs(tx, batch, plan);
  await writeHomeRows(tx, batch, plan);
  await writeMedia(tx, batch);
  const ids = await writeCourses(tx, batch, refs, checkedAt);
  return { plan, ids };
}

/** Publish the courses this apply just wrote, then cut the release. A draft does not call this (D-053). */
export async function publishAppliedBatch(tx: Tx, ids: readonly string[], options: { allowOrphan: boolean; note: string | null; actor: string; now: Date }): Promise<{ release: NonNullable<ApplyBatchReport["release"]>; publication: Awaited<ReturnType<typeof publishRelease>> }> {
  await publishShipCourses(tx, ids);
  const state = await readCourseState(tx, ids);
  const facts = catalogCourseFacts(state.tables, state.covers);
  const blocked = [...notWrittenFailures(ids, new Set(facts.keys())), ...ids.flatMap((id) => {
    const course = facts.get(id);
    return course ? evaluateRules("published", course, { allowOrphan: options.allowOrphan }) : [];
  })];
  if (blocked.length > 0) throw preconditionsFailed(blocked);
  // The commit-time rules (deferred triggers) run now, so a dry run meets every one a write would.
  await setConstraintsImmediate(tx);
  const publication = await publishRelease(tx, { note: options.note ?? `batch ${String(ids.length)}`, actor: options.actor, fresh: new Set(ids), now: options.now });
  return { release: { number: publication.release.number, created: publication.release.created }, publication };
}

function summary(plan: BatchPlan): ApplyBatchReport["plan"] {
  const counts: Record<string, Record<string, number>> = {};
  for (const op of plan.ops) {
    const step = (counts[op.step] ??= {});
    step[op.action] = (step[op.action] ?? 0) + 1;
  }
  return counts;
}

/**
 * POST /batches/apply. Chunks only stage the parts; the completing request writes the rows, then publishes when
 * `draft` is false, in that transaction (G-1, D-053). The same content hash returns the stored result (G-2). `dryRun`
 * runs the same writes, rules, deferred constraints and release compile inside a savepoint and rolls them back (G-3).
 */
export async function applyBatch(context: HandlerContext<unknown, unknown, ApplyBatchBody>): Promise<Outcome<ApplyBatchData>> {
  const body = context.body;
  const hash = body.batchHash;
  const allowOrphan = body.allowOrphan !== false;
  const note = body.note ?? null;
  const entity = `batch:${hash.slice(0, 12)}`;
  const outcome = await context.mutate(async (tx) => {
    await tx.acquireLock({ scope: "xact", key: `ship-batch:${hash}` });
    await openCatalogV2Batch(tx, hash, body.draft, allowOrphan, note, body.chunks);
    const stored = await lockCatalogV2Batch(tx, hash);
    if (stored?.status === "committed") return { data: stored.result as ApplyBatchData, noop: true, entity };
    if (stored?.format !== "catalog-v2" || stored.draft !== body.draft || stored.allow_orphan !== allowOrphan || (stored.note ?? null) !== note || Number(stored.chunk_count) !== body.chunks) {
      throw invalid("This batch hash was already opened with different options.");
    }
    await saveShipChunk(tx, hash, body.chunk, JSON.stringify(body.part));
    const parts = (await selectShipChunkBundles(tx, hash)).map((row) => row.bundles);
    if (parts.length < body.chunks) {
      await tx.audit({ action: "course.publish.apply", entityKind: "batch", entityId: hash.slice(0, 16), after: { status: "partial", received: parts.length, chunks: body.chunks } });
      return { data: { status: "partial", batchHash: hash, received: parts.length, chunks: body.chunks }, entity };
    }
    const parsed = catalogBatchV2Schema.safeParse(mergeBatchParts(parts));
    if (!parsed.success) throw invalid("The batch is not a valid CatalogBatchV2.", { issues: parsed.error.issues.map((issue) => `${issue.path.join(".")}: ${issue.message}`) });
    const batch = parsed.data;
    if (batchV2Hash(batch) !== hash) throw invalid("The batch hash does not match its parts.");

    const { plan, ids } = await writeBatchRows(tx, batch, context.deps.now().toISOString());
    let release: ApplyBatchReport["release"] = null;
    let publication: Awaited<ReturnType<typeof publishRelease>> | null = null;
    if (!body.draft) {
      const published = await publishAppliedBatch(tx, ids, { allowOrphan, note, actor: context.actor, now: context.deps.now() });
      release = published.release;
      publication = published.publication;
    } else {
      // The commit-time rules (deferred triggers) run now, so a dry run meets every one a write would.
      await setConstraintsImmediate(tx);
    }
    const report: ApplyBatchReport = { status: body.dryRun ? "dry-run" : "committed", batchHash: hash, draft: body.draft, plan: summary(plan), courses: ids, release };
    if (body.dryRun) {
      await rollbackBatchApply(tx);
      await setConstraintsDeferred(tx);
      await tx.audit({ action: "course.publish.apply", entityKind: "batch", entityId: hash.slice(0, 16), after: { dryRun: true, courses: ids.length } });
      return { data: report, entity };
    }
    await releaseBatchApply(tx);
    if (publication) scheduleActivation(tx, context.deps, publication.release, publication.release.created);
    await commitShipBatch(tx, hash, JSON.stringify(report));
    await tx.audit({ action: "course.publish.apply", entityKind: "batch", entityId: hash.slice(0, 16), after: { draft: body.draft, courses: ids.length, release: release?.number ?? null }, releaseNumber: release?.number ?? null });
    return { status: 201, data: report, entity };
  });
  return outcome as Outcome<ApplyBatchData>;
}
