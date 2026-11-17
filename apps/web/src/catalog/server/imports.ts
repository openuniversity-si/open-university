import type { ImportCreate, ImportDraft, ImportItem, LessonPart } from "../domain/contracts.ts";
import { lockRow, touchCourse, type Outcome, type Tx } from "./mutation.ts";
import { notFound, stateConflict, unprocessable } from "../../kernel/errors.ts";
import type { HandlerContext } from "./http.ts";
import { playlistIdFromUrl } from "../domain/youtube-identity.ts";
import type { OEmbedResult } from "../../playback/ports/oembed.ts";
import { cleanLessonSlug, cleanTitle, looksLikeTrailer } from "../domain/lesson-address.ts";
import { insertAuthor } from "./authors.ts";
import { insertCourse } from "./courses.ts";
import { iso } from "./common.ts";
import { editionView, insertEdition, type EditionView } from "./editions.ts";
import { insertLesson, looksLikeLab, videoOwner, videoTaken } from "./lessons.ts";

// Imports store what the CLI extracted on the box (yt-dlp, P6) plus the report of plan §4.2; the API runs no extractor.

export interface AcceptedItem {
  readonly id: string; readonly position: number; readonly title: string; readonly suggestedTitle: string; readonly suggestedKind: "lecture" | "trailer";
  readonly suggestedSlug: string; readonly durationSeconds: number;
  /** Absent in imports stored before editions (ADR-21): those read as lectures. */
  readonly suggestedPart?: LessonPart;
}
export interface ImportReport {
  readonly playlist: { readonly id: string; readonly title: string | null; readonly channelId: string | null; readonly channel: string | null };
  readonly accepted: AcceptedItem[];
  readonly excluded: { readonly id: string; readonly reason: string; readonly courseId?: string }[];
  readonly warnings: { readonly id: string; readonly reason: string }[];
}
const PRIVATE = new Set(["private", "premium_only", "subscriber_only", "needs_auth"]);
const NOT_LIVE = new Set(["not_live", "was_live"]);

/** The exclusion rules that need only the item itself (plan §4.2); null when it may go on. */
export function itemExclusion(item: ImportItem): string | null {
  if (item.playableInEmbed === false) return "embed-disabled";
  if (item.availability != null && PRIVATE.has(item.availability)) return "private";
  if (item.liveStatus != null && !NOT_LIVE.has(item.liveStatus)) return "live";
  if ((item.ageLimit ?? 0) >= 18) return "age-restricted";
  if (!item.duration || item.duration <= 0) return item.liveStatus === "was_live" ? "live-no-duration" : "no-duration";
  return null;
}
export function itemWarnings(item: ImportItem, channelId: string | null): string[] {
  const duration = item.duration ?? 0;
  return [
    ...(duration < 300 || duration > 4 * 3600 ? ["duration"] : []),
    ...(item.height != null && item.height < 480 ? ["resolution"] : []),
    ...(channelId !== null && item.channelId != null && item.channelId !== channelId ? ["channel"] : []),
    ...(item.license === "creativeCommon" ? ["creative-commons"] : []),
  ];
}

export async function createImport(context: HandlerContext<unknown, unknown, ImportCreate>): Promise<Outcome> {
  const body = context.body;
  const playlistId = playlistIdFromUrl(body.playlistUrl);
  const items = [...body.items].sort((a, b) => (a.playlistIndex ?? Number.MAX_SAFE_INTEGER) - (b.playlistIndex ?? Number.MAX_SAFE_INTEGER));
  const report: ImportReport = { playlist: { id: playlistId, title: body.playlistTitle ?? null, channelId: body.channelId ?? null, channel: body.channel ?? null }, accepted: [], excluded: [], warnings: [] };
  const seen = new Set<string>();
  const slugs = new Set<string>();
  // oEmbed is network I/O: it runs before the transaction opens. A video already in another course is still accepted.
  for (const [index, item] of items.entries()) {
    if (seen.has(item.id)) { report.excluded.push({ id: item.id, reason: "duplicate" }); continue; }
    seen.add(item.id);
    const reason = itemExclusion(item);
    if (reason) { report.excluded.push({ id: item.id, reason }); continue; }
    const embed: OEmbedResult = await context.deps.oembed(item.id);
    if (embed.status !== "ok") { report.excluded.push({ id: item.id, reason: embed.status }); continue; }
    for (const warning of itemWarnings(item, report.playlist.channelId)) report.warnings.push({ id: item.id, reason: warning });
    const suggestedTitle = cleanTitle(item.title);
    const position = report.accepted.length + 1;
    const suggestedKind = looksLikeTrailer(item.title, item.duration, index) ? "trailer" : "lecture";
    // A preview with the playlist as the course; the draft makes the slug again with the real course and edition.
    const suggestedSlug = cleanLessonSlug({ youtubeTitle: item.title, courseTitle: body.playlistTitle ?? "", courseSlug: "", institution: body.channel ?? null, position, kind: suggestedKind }, slugs);
    slugs.add(suggestedSlug);
    report.accepted.push({
      id: item.id, position, title: item.title, suggestedTitle, suggestedSlug, suggestedKind, durationSeconds: Math.max(1, Math.round(item.duration ?? 1)),
      suggestedPart: looksLikeLab(item.title, body.playlistTitle) ? "labs" : "lectures",
    });
  }
  const now = context.deps.now();
  const stamp = now.toISOString().replace(/[-:T]/g, "").slice(0, 12);
  return context.mutate(async (tx) => {
    const base = `import-${playlistId}-${stamp}`;
    const { rows } = await tx.query("SELECT id FROM catalog_imports WHERE id = $1 OR id LIKE $1 || '-%'", [base]);
    const taken = new Set(rows.map((row) => String(row.id)));
    let id = base;
    for (let suffix = 2; taken.has(id); suffix += 1) id = `${base}-${String(suffix)}`;
    await tx.query(`INSERT INTO catalog_imports (id, playlist_id, source_url, tool, fetched_at, items, report) VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7::jsonb)`,
      [id, playlistId, body.playlistUrl, body.tool ?? "admin-api", now.toISOString(), JSON.stringify(body.items), JSON.stringify(report)]);
    const summary = { playlistId, accepted: report.accepted.length, excluded: report.excluded.length, warnings: report.warnings.length };
    await tx.audit({ action: "import.create", entityKind: "import", entityId: id, after: summary });
    return { status: 201, data: { import: { id, playlistId, status: "received", report } }, entity: `import:${id}` };
  });
}

/** The edition an import drafts into: the named one of an existing course (created in its date place when new). */
async function targetEdition(tx: Tx, courseId: string, edition: NonNullable<ImportDraft["edition"]>, playlistId: string): Promise<{ edition: EditionView; created: boolean }> {
  const { rows } = await tx.query("SELECT * FROM course_editions WHERE course_id = $1 AND slug = $2", [courseId, edition.slug]);
  if (rows[0]) {
    const existing = editionView(rows[0]);
    if (!existing.sourcePlaylistIds.includes(playlistId)) {
      await tx.query("UPDATE course_editions SET source_playlist_ids = array_append(source_playlist_ids, $2), revision = revision + 1, updated_at = now() WHERE id = $1", [existing.id, playlistId]);
    }
    return { edition: existing, created: false };
  }
  return { edition: await insertEdition(tx, courseId, { ...edition, sourcePlaylistIds: [playlistId] }), created: true };
}

/**
 * Turns a received import into lessons, in one transaction: a new draft course with its first edition, or (with `courseId`)
 * a new or existing edition of a course that already exists, which keeps its status (ADR-21).
 */
export async function draftImport(context: HandlerContext<{ id: string }, unknown, ImportDraft>): Promise<Outcome> {
  const { id } = context.params;
  const body = context.body;
  return context.mutate(async (tx) => {
    const { rows } = await tx.query("SELECT * FROM catalog_imports WHERE id = $1 FOR UPDATE", [id]);
    const record = rows[0];
    if (!record) throw notFound(`Import ${id}`);
    if (record.status !== "received") throw stateConflict(`Import ${id} is ${String(record.status)}.`, { status: record.status, courseId: record.course_id ?? null });
    const report = record.report as ImportReport;
    const accepted = new Map(report.accepted.map((item) => [item.id, item]));
    const unknown = [...(body.include ?? []), ...(body.exclude ?? [])].filter((videoId) => !accepted.has(videoId));
    if (unknown.length > 0) throw unprocessable("include/exclude name videos the import did not accept.", { unknown });
    const excluded = new Set(body.exclude ?? []);
    const chosen = (body.include ? report.accepted.filter((item) => body.include?.includes(item.id)) : report.accepted).filter((item) => !excluded.has(item.id));
    if (chosen.length === 0) throw unprocessable("No video is left to draft.");
    let courseId: string;
    let course: unknown;
    let courseTitle: string;
    let courseSlug: string;
    let target: { edition: EditionView; created: boolean };
    if (body.courseId !== undefined && body.edition !== undefined) {
      const locked = await lockRow(tx, "courses", body.courseId, `Course ${body.courseId}`);
      if (locked.status === "archived") throw stateConflict("An archived course takes no new lessons; move it to draft first.");
      courseId = body.courseId;
      course = { id: courseId, slug: locked.slug, status: locked.status };
      courseTitle = String(locked.title);
      courseSlug = String(locked.slug);
      target = await targetEdition(tx, courseId, body.edition, report.playlist.id);
    } else {
      let authorId = body.authorId;
      if (body.newAuthor) {
        const author = await insertAuthor(tx, body.newAuthor);
        await tx.audit({ action: "author.create", entityKind: "author", entityId: author.id, after: author });
        authorId = author.id;
      }
      const created = await insertCourse(tx, {
        slug: body.slug ?? "", authorId: authorId ?? "", title: body.title ?? report.playlist.title ?? report.playlist.id, coverFrom: "own",
        ...(body.lessonNoun === undefined ? {} : { lessonNoun: body.lessonNoun }), ...(body.sourceId === undefined ? {} : { sourceId: body.sourceId }),
        ...(body.licenseCode === undefined ? {} : { licenseCode: body.licenseCode }), ...(body.canonicalUrl === undefined ? {} : { canonicalUrl: body.canonicalUrl }),
      });
      await tx.audit({ action: "course.create", entityKind: "course", entityId: created.id, after: { ...created, importId: id } });
      courseId = created.id;
      course = created;
      courseTitle = created.title;
      courseSlug = created.slug;
      // Without a named edition, a new course starts with one named after the import's year.
      const year = context.deps.now().getUTCFullYear();
      target = await targetEdition(tx, courseId, body.edition ?? { slug: String(year), label: String(year), term: null, year }, report.playlist.id);
    }
    if (target.created) await tx.audit({ action: "edition.create", entityKind: "edition", entityId: target.edition.id, after: { ...target.edition, importId: id } });
    const checkedAt = iso(record.fetched_at) ?? context.deps.now().toISOString();
    for (const item of chosen) {
      const owner = await videoOwner(tx, courseId, item.id);
      if (owner) throw videoTaken(item.id, owner);
    }
    const lessons = [];
    // The lesson slug rule (src/catalog/domain/lesson-address.ts), unique against the course's lessons (ADR-21): existing slugs never change.
    const { rows: existing } = await tx.query("SELECT slug, edition_id FROM lessons WHERE course_id = $1", [courseId]);
    const taken = new Set(existing.map((row) => String(row.slug)));
    const before = existing.filter((row) => row.edition_id === target.edition.id).length;
    const edition = { label: target.edition.label, term: target.edition.term, year: target.edition.year };
    for (const [index, item] of chosen.entries()) {
      const slug = cleanLessonSlug({ youtubeTitle: item.title, courseTitle, courseSlug, institution: report.playlist.channel, edition, position: before + index + 1, kind: item.suggestedKind }, taken);
      taken.add(slug);
      const lesson = await insertLesson(tx, {
        courseId, editionId: target.edition.id, part: body.part ?? item.suggestedPart ?? "lectures", youtubeId: item.id, youtubeTitle: item.title,
        durationSeconds: item.durationSeconds, slug, kind: item.suggestedKind,
        displayTitle: { text: item.suggestedTitle, source: "youtube", confidence: "medium" }, checkedAt, checkedBy: context.deps.oembedChecker,
      });
      await tx.audit({ action: "lesson.create", entityKind: "lesson", entityId: lesson.id, after: { ...lesson, youtubeId: item.id, importId: id } });
      lessons.push({ ...lesson, youtubeId: item.id });
    }
    const courseRevision = body.courseId === undefined ? undefined : await touchCourse(tx, courseId);
    await tx.query("UPDATE catalog_imports SET status = 'drafted', course_id = $2 WHERE id = $1", [id, courseId]);
    await tx.audit({ action: "import.draft", entityKind: "import", entityId: id, before: { status: "received" }, after: { status: "drafted", courseId, editionId: target.edition.id, lessons: lessons.length } });
    return {
      status: 201, data: { import: { id, status: "drafted", courseId, editionId: target.edition.id }, course, edition: target.edition, lessons, ...(courseRevision === undefined ? {} : { courseRevision }) },
      entity: `import:${id}`,
    };
  });
}
