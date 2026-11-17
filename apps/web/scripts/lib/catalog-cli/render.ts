import type { PreconditionFailure } from "../../../src/catalog/domain/contracts.ts";
import { REQUIRED_COVERS } from "../../../src/catalog/domain/rules/status.ts";
import type { courseDetail } from "../../../src/catalog/server/courses.ts";
import type { ReleaseDiff } from "../../../src/catalog/server/releases.ts";
import { TEXT_FIELDS, textIssues } from "../../../src/catalog/domain/fields.ts";

export type CourseDetail = Awaited<ReturnType<typeof courseDetail>>;
type TextEntry = CourseDetail["texts"][string];

/** Left-aligned columns, two spaces apart, no trailing blanks (no colours: output is the same in a pipe and a TTY). */
export function table(header: readonly string[], rows: readonly (readonly string[])[]): string[] {
  const all = [header, ...rows];
  const widths = header.map((_, column) => Math.max(...all.map((row) => Array.from(row[column] ?? "").length)));
  return all.map((row) => row.map((cell, column) => (column === row.length - 1 ? cell : cell + " ".repeat((widths[column] ?? 0) - Array.from(cell).length))).join("  ").trimEnd());
}

export const shortSha = (sha: string | null | undefined) => (sha ? sha.slice(0, 12) : "-");
export const orDash = (value: string | number | null | undefined) => (value === null || value === undefined || value === "" ? "-" : String(value));
export const chars = (text: string) => Array.from(text).length;

export function duration(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  return `${h > 0 ? `${String(h)}:${String(m).padStart(2, "0")}` : String(m)}:${String(s).padStart(2, "0")}`;
}

/** Every unmet rule, one line each, never truncated (412 details and `preconditions` alike). */
export function preconditionLines(failed: readonly PreconditionFailure[]): string[] {
  return failed.map((failure) => `  - ${failure.rule} ${failure.entity}: ${failure.message}`);
}

/** A release diff as ids and field names (what publish, release diff and home set show before asking). */
export function diffLines(diff: ReleaseDiff | null): string[] {
  if (diff === null) return ["  (no diff)"];
  if (diff.empty) return ["  no change"];
  const lines: string[] = [];
  for (const kind of ["authors", "courses", "lessons"] as const) {
    const entry = diff[kind];
    if (entry.added.length) lines.push(`  ${kind} added: ${entry.added.join(", ")}`);
    if (entry.removed.length) lines.push(`  ${kind} removed: ${entry.removed.join(", ")}`);
    for (const changed of entry.changed) lines.push(`  ${kind} changed: ${changed.id} (${changed.fields.join(", ")})`);
  }
  if (diff.texts.changed.length) lines.push(`  texts changed: ${diff.texts.changed.join(", ")}`);
  if (diff.home.changed) lines.push("  home changed");
  if (diff.redirects.added.length) lines.push(`  redirects added: ${diff.redirects.added.join(", ")}`);
  if (diff.redirects.removed.length) lines.push(`  redirects removed: ${diff.redirects.removed.join(", ")}`);
  return lines;
}

function textRows(kind: "course" | "lesson", entityId: string, texts: Readonly<Record<string, TextEntry>>, indent: string): string[] {
  const lines: string[] = [];
  for (const [field, spec] of Object.entries(TEXT_FIELDS[kind])) {
    const entry = texts[field];
    const need = spec.publish ? "publish" : spec.review ? "review" : "optional";
    if (!entry) { lines.push(`${indent}${field} [${need}] limit ${String(spec.maxChars)}: ${need === "optional" ? "empty" : "MISSING"}`); continue; }
    const approved = entry.approvedSha256 === entry.sha256 ? "approved" : entry.approvedSha256 ? "changed since approval" : entry.status;
    const issues = textIssues(kind, field, entry.text).map((issue) => issue.rule);
    lines.push(`${indent}${field} [${need}] ${String(chars(entry.text))}/${String(spec.maxChars)} ${approved} sha256 ${shortSha(entry.sha256)} ${entry.source}/${entry.confidence}${issues.length ? ` ISSUES ${issues.join(",")}` : ""}`);
    lines.push(`${indent}  «${entry.text}»`);
  }
  for (const field of Object.keys(texts).filter((name) => !(name in TEXT_FIELDS[kind]))) lines.push(`${indent}${field}: not a ${kind} field (${entityId})`);
  return lines;
}

/** `tower-catalog review`: the whole course on one screen, in a stable order (tower-catalog.test.ts snapshots it). */
export function reviewLines(detail: CourseDetail): string[] {
  const { course, rights } = detail;
  const covers = new Map(detail.covers.map((cover) => [String(cover.kind), cover]));
  const lines = [
    `Course ${course.id} · /c/${course.slug} · status ${course.status} · revision ${String(course.revision)}${course.featured ? " · featured" : ""}`,
    `  title ${course.title} · author ${course.authorId} · ${course.lessonNoun} · ${course.languageLabel} · published ${orDash(course.publishedAt)}`,
    `Rights: license ${orDash(rights.licenseCode)} · source ${orDash(rights.sourceId)} · canonical ${orDash(rights.canonicalUrl)}`,
    `  status ${rights.rightsStatus} · checked by ${orDash(rights.rightsCheckedBy)} at ${orDash(rights.rightsCheckedAt)} · notes ${orDash(rights.rightsNotes)} · attribution ${orDash(rights.attributionText)}`,
    `Home rows: ${detail.homeRows.length ? detail.homeRows.join(", ") : "none"}`,
    "",
    "Course texts:",
    ...textRows("course", course.id, detail.texts, "  "),
    "",
    `Covers: ${REQUIRED_COVERS.map((kind) => `${kind} ${covers.has(kind) ? `v${String(covers.get(kind)?.version)}` : "MISSING"}`).join(" · ")}`,
    ...[...covers.keys()].filter((kind) => !(REQUIRED_COVERS as readonly string[]).includes(kind)).map((kind) => `  also ${kind} v${String(covers.get(kind)?.version)}`),
    "",
    `Editions (${String(detail.editions.length)}; position 1 opens by default):`,
    ...detail.editions.map((edition) => `  ${String(edition.position)} ${edition.id} ${edition.slug} · ${edition.label} · ${String(edition.counts.parts.lectures)} lectures + ${String(edition.counts.parts.labs)} labs · ${String(edition.counts.visibleLessons)}/${String(edition.counts.lessons)} visible · revision ${String(edition.revision)}${edition.pending.length ? ` · ${String(edition.pending.length)} pending` : ""}`),
    "",
    `Lessons (${String(detail.lessons.length)}, ${String(detail.lessons.filter((lesson) => lesson.visible).length)} visible):`,
  ];
  const editionSlug = new Map(detail.editions.map((edition) => [edition.id, edition.slug]));
  for (const lesson of detail.lessons) {
    const videos = lesson.videos.map((video) => `${video.provider}:${video.externalId} ${video.status}`).join(", ") || "no video";
    lines.push(`  ${editionSlug.get(lesson.editionId) ?? lesson.editionId} ${String(lesson.position).padStart(2, "0")} ${lesson.id} ${lesson.slug} · ${lesson.part} · ${lesson.kind} · ${lesson.visible ? "visible" : "hidden"} · ${duration(lesson.durationSeconds)} · ${videos} · covers ${lesson.covers.length ? lesson.covers.map((cover) => `${String(cover.kind)} v${String(cover.version)}`).join(", ") : "fallback"} · revision ${String(lesson.revision)}`);
    lines.push(`     YouTube title: ${lesson.youtubeTitle}`);
    lines.push(...textRows("lesson", lesson.id, lesson.texts, "     "));
  }
  const pre = detail.preconditions;
  lines.push("", `Preconditions for review: ${pre ? (pre.review.length ? `${String(pre.review.length)} unmet` : "all met") : "n/a"}`, ...preconditionLines(pre?.review ?? []));
  lines.push(`Preconditions for publish: ${pre ? (pre.published.length ? `${String(pre.published.length)} unmet` : "all met") : "n/a"}`, ...preconditionLines(pre?.published ?? []));
  return lines;
}
