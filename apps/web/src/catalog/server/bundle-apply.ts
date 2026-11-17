import { AppError, invalid, notFound, preconditionsFailed, revisionConflict, stateConflict, unprocessable } from "../../kernel/errors.ts";
import { lockMediaOwners } from "../../media/server/media-locks.ts";
import type { Queryable, UnitOfWork } from "../../platform/db/uow.ts";
import { withUnitOfWork, type DbPool } from "../../platform/db/uow.ts";
import type { OEmbedResolverPort, VideoMetadataResult } from "../../playback/ports/oembed.ts";
import { catalogVideoProvider } from "../../playback/server/source-registry.ts";
import { bundleHash, unknownYearMessage, type CourseBundleV1 } from "../domain/bundle.ts";
import { defaultEdition } from "../domain/edition-variant.ts";
import { coverOwner } from "../domain/cover-source.ts";
import { publishedKeepsCovers } from "../domain/rules/status.ts";
import { storedCoverErrors } from "../domain/rules/home.ts";
import { activeCoverKinds } from "./cover-kinds.ts";
import { adoptRowInstitutions } from "./row-institution.ts";
import type { Outcome, Tx } from "./mutation.ts";
import { insertLesson } from "./lessons.ts";
import { insertApprovedBundleText, insertBundleAudit, insertBundleEdition, insertDraftBundleText, insertHomeItemIgnore, lockHomeRevision, selectBundleHomeRow, selectCourseLegacyStatus, selectHomeRowId, selectLessonId, selectNextHomeItemPosition, upsertBundleAuthor, upsertBundleCourse } from "./table-io.ts";

export interface PreparedBundle {
  readonly bundle: CourseBundleV1;
  readonly hash: string;
  readonly metadata: readonly VideoMetadataResult[];
  readonly preparedAt: string;
}

export interface PrepareDeps {
  readonly resolver: OEmbedResolverPort;
  readonly now: () => Date;
  readonly signal?: AbortSignal;
}

export interface BundleApplyDeps {
  readonly actor: string;
  readonly requestId: string;
  readonly replayKey: string | null;
  readonly beforeLesson?: (index: number) => void;
  readonly uow?: Tx;
  readonly pool?: DbPool;
}

interface StoredLegacy { readonly bundleSha256?: string; readonly replayKey?: string | null }

function legacyOf(value: unknown): StoredLegacy | null {
  if (typeof value !== "object" || value === null) return null;
  const bundleSha256 = "bundleSha256" in value && typeof value.bundleSha256 === "string" ? value.bundleSha256 : undefined;
  const replayKey = "replayKey" in value && (typeof value.replayKey === "string" || value.replayKey === null) ? value.replayKey : undefined;
  return { ...(bundleSha256 ? { bundleSha256 } : {}), ...(replayKey !== undefined ? { replayKey } : {}) };
}

/** oEmbed and validation finish before a transaction exists. */
export async function prepareCourseBundle(bundle: CourseBundleV1, deps: PrepareDeps): Promise<PreparedBundle> {
  const unknownYear = unknownYearMessage(bundle);
  if (unknownYear) throw invalid(unknownYear);
  const metadata = await deps.resolver.resolveMany(bundle.lessons.map((lesson) => ({ provider: catalogVideoProvider(), externalId: lesson.youtubeId })), deps.signal);
  for (const lesson of bundle.lessons) {
    const result = metadata.find((entry) => entry.identity.externalId === lesson.youtubeId);
    const verified = result?.status === "resolved" && result.durationSeconds !== undefined && result.durationSeconds > 0 ? result.durationSeconds : null;
    if (lesson.durationSeconds <= 0 && verified === null) throw invalid(`Lesson ${lesson.id} has no duration.`);
    if (result?.status === "unavailable" && lesson.durationSeconds <= 0) throw new AppError("upstream_failed", `Video ${lesson.youtubeId} is unavailable.`);
    if (result?.status === "resolved" && result.durationSeconds === 0) throw invalid(`Video ${lesson.youtubeId} cannot use a fabricated duration.`);
  }
  return { bundle, hash: bundleHash(bundle), metadata, preparedAt: deps.now().toISOString() };
}

async function writeAudit(uow: Queryable & Partial<Pick<Tx, "audit">>, deps: BundleApplyDeps, courseId: string, after: unknown): Promise<void> {
  if (uow.audit) {
    await uow.audit({ action: "course.bundle", entityKind: "course", entityId: courseId, after });
    return;
  }
  await insertBundleAudit(uow, deps.actor, deps.requestId, courseId, JSON.stringify(after));
}

async function assertBundleHomeCover(uow: Queryable, home: NonNullable<CourseBundleV1["home"]>): Promise<void> {
  const found = await selectBundleHomeRow(uow, home.rowId);
  if (!found) throw notFound(`Home row ${home.rowId}`);
  const authorId = typeof found.author_id === "string" ? found.author_id : null;
  const authors = new Map(authorId !== null && found.author !== null ? [[authorId, found.author_cover === true]] : []);
  const errors = storedCoverErrors([{ id: String(found.id), kind: String(found.kind), visible: found.visible !== false, cover: found.cover, authorId }], authors);
  if (errors.length > 0) throw unprocessable(errors.join(" "), { errors });
}

async function writeBundle(prepared: PreparedBundle, uow: UnitOfWork & Partial<Pick<Tx, "audit">>, deps: BundleApplyDeps): Promise<Outcome> {
  const { bundle, hash } = prepared;
  // D-031: the declaration names the one cover owner. Lock that owner before the write, as PATCH /courses/:id does.
  const declaredOwner = coverOwner(bundle.course.coverFrom, bundle.course.id);
  const owners: { owner: "course" | "subarea" | "area"; ownerId: string }[] = [{ owner: "course", ownerId: bundle.course.id }];
  if (typeof bundle.course.areaId === "string") owners.push({ owner: "area", ownerId: bundle.course.areaId });
  if (typeof bundle.course.subareaId === "string") owners.push({ owner: "subarea", ownerId: bundle.course.subareaId });
  if (declaredOwner && declaredOwner.kind !== "course" && !owners.some((owner) => owner.owner === declaredOwner.kind && owner.ownerId === declaredOwner.id)) {
    owners.push({ owner: declaredOwner.kind, ownerId: declaredOwner.id });
  }
  await lockMediaOwners(uow, owners);
  const existing = await selectCourseLegacyStatus(uow, bundle.course.id);
  const legacy = legacyOf(existing?.legacy);
  if (legacy?.bundleSha256 === hash) return { data: { courseId: bundle.course.id, hash, applied: false }, noop: true };
  if (deps.replayKey && legacy?.replayKey === deps.replayKey) throw stateConflict("This replay key was used for a different bundle.");
  if (bundle.home) await assertBundleHomeCover(uow, bundle.home);
  const stored: StoredLegacy = { bundleSha256: hash, replayKey: deps.replayKey };
  await upsertBundleAuthor(uow, bundle.author.id, bundle.author.slug, bundle.author.name, bundle.author.monogram, bundle.author.kind);
  const meta: { column: string; value: unknown }[] = [];
  const course = bundle.course;
  const editionLanguage = defaultEdition(bundle.editions)?.language;
  if (course.languageLabel !== undefined) meta.push({ column: "language_label", value: course.languageLabel });
  else if (editionLanguage) meta.push({ column: "language_label", value: editionLanguage });
  if (course.areaId !== undefined) meta.push({ column: "area_id", value: course.areaId });
  if (course.subareaId !== undefined) meta.push({ column: "subarea_id", value: course.subareaId });
  if (course.licenseCode !== undefined) meta.push({ column: "license_code", value: course.licenseCode });
  if (course.sourceId !== undefined) meta.push({ column: "source_id", value: course.sourceId });
  if (course.attributionText !== undefined) meta.push({ column: "attribution_text", value: course.attributionText });
  if (course.canonicalUrl !== undefined) meta.push({ column: "canonical_url", value: course.canonicalUrl });
  if (course.rightsStatus !== undefined) meta.push({ column: "rights_status", value: course.rightsStatus });
  meta.push({ column: "cover_from", value: course.coverFrom });
  meta.push({ column: "shared_with", value: [...course.sharedWith] });
  const columns = ["id", "slug", "author_id", "title", "lesson_noun", "status", "legacy", ...meta.map((entry) => entry.column)];
  const values = [bundle.course.id, bundle.course.slug, bundle.course.authorId, bundle.course.title, bundle.course.lessonNoun, "draft", JSON.stringify(stored), ...meta.map((entry) => entry.value)];
  await upsertBundleCourse(uow, columns, values, meta.map((entry) => entry.column));
  if (existing?.status === "published") {
    const covers = (await activeCoverKinds(uow, [bundle.course.id])).get(bundle.course.id);
    const failed = publishedKeepsCovers(bundle.course.id, covers);
    if (failed.length) throw preconditionsFailed(failed);
  }
  for (const edition of bundle.editions) {
    await insertBundleEdition(uow, [edition.id, bundle.course.id, edition.slug, edition.label, edition.year, edition.position, edition.variant?.kind ?? null, edition.variant?.label ?? null, edition.language ?? null]);
  }
  for (const [index, lesson] of bundle.lessons.entries()) {
    deps.beforeLesson?.(index);
    const found = await selectLessonId(uow, lesson.id);
    if (found) continue;
    await insertLesson(uow, {
      id: lesson.id, courseId: bundle.course.id, editionId: lesson.editionId, slug: lesson.slug, part: lesson.part, position: lesson.position,
      youtubeId: lesson.youtubeId, youtubeTitle: lesson.title, durationSeconds: lesson.durationSeconds,
      displayTitle: { text: lesson.title, source: "manual", confidence: "high" },
      checkedAt: prepared.preparedAt, checkedBy: "oembed",
    });
  }
  for (const row of bundle.texts) {
    if (row.approved && row.approvedBy && row.approvedAt) {
      await insertApprovedBundleText(uow, row.entityKind, row.entityId, row.field, row.text, row.approvedBy, row.approvedAt);
    } else {
      await insertDraftBundleText(uow, row.entityKind, row.entityId, row.field, row.text);
    }
  }
  if (bundle.home) {
    const locked = await lockHomeRevision(uow);
    const revision = Number(locked?.revision ?? 0);
    if (revision !== bundle.home.expectedRevision) throw revisionConflict(revision);
    const row = await selectHomeRowId(uow, bundle.home.rowId);
    if (!row) throw notFound(`Home row ${bundle.home.rowId}`);
    await assertBundleHomeCover(uow, bundle.home);
    const position = Number((await selectNextHomeItemPosition(uow, bundle.home.rowId))?.n ?? 1);
    await insertHomeItemIgnore(uow, bundle.home.rowId, bundle.course.id, position);
    await adoptRowInstitutions(uow, [bundle.home.rowId]);
  }
  await writeAudit(uow, deps, bundle.course.id, { hash, lessons: bundle.lessons.length });
  return { data: { courseId: bundle.course.id, hash, applied: true } };
}

/** One transaction. A caller that already holds the admin unit of work passes it in. */
export async function applyCourseBundle(prepared: PreparedBundle, deps: BundleApplyDeps): Promise<Outcome> {
  if (prepared.hash !== bundleHash(prepared.bundle)) throw stateConflict("Prepared bundle hash does not match its payload.");
  if (deps.uow) return writeBundle(prepared, deps.uow, deps);
  if (!deps.pool) throw invalid("Applying a bundle needs a unit of work.");
  return withUnitOfWork(deps.pool, (uow: UnitOfWork) => writeBundle(prepared, uow, deps));
}
