import { sha256Hex } from "../../kernel/canonical.ts";
import type { CatalogRow } from "./tables.ts";
import { iso } from "./rules-helpers.ts";

/** The course columns the API shows, camelCase, with its revision. */
export function courseView(row: Record<string, unknown>) {
  return {
    id: String(row.id), slug: String(row.slug), authorId: String(row.author_id), title: String(row.title), languageLabel: String(row.language_label),
    lessonNoun: String(row.lesson_noun), status: String(row.status), featured: row.featured === true,
    sourceId: (row.source_id ?? null) as string | null, licenseCode: (row.license_code ?? null) as string | null,
    attributionText: (row.attribution_text ?? null) as string | null, canonicalUrl: (row.canonical_url ?? null) as string | null,
    rightsStatus: String(row.rights_status), rightsNotes: (row.rights_notes ?? null) as string | null,
    rightsCheckedBy: (row.rights_checked_by ?? null) as string | null, rightsCheckedAt: iso(row.rights_checked_at),
    areaId: (row.area_id ?? null) as string | null, subareaId: (row.subarea_id ?? null) as string | null, coverFrom: String(row.cover_from), publishedAt: iso(row.published_at), revision: Number(row.revision),
  };
}

/** Only the fields that differ, for audit before/after. */
export function changed<T extends Record<string, unknown>>(before: T, after: T): { before: Partial<T>; after: Partial<T> } {
  const keys = Object.keys(after).filter((key) => key !== "revision" && JSON.stringify(before[key]) !== JSON.stringify(after[key]));
  return { before: Object.fromEntries(keys.map((key) => [key, before[key]])) as Partial<T>, after: Object.fromEntries(keys.map((key) => [key, after[key]])) as Partial<T> };
}

/** `sha256` is the hash of the current text (what POST /texts/approve takes); `approvedSha256` the one last approved. */
export function textSummary(text: CatalogRow<"catalog_texts">) {
  return {
    text: text.text, status: text.status, sha256: sha256Hex(text.text), approvedSha256: text.approved_sha256 ?? null, source: text.source, sourceRef: text.source_ref,
    confidence: text.confidence, approvedBy: text.approved_by, approvedAt: text.approved_at,
  };
}

/**
 * ADR-26: the classification a course ends with must hold. The server resolves whether the area exists and which area
 * owns the subarea; this function only decides the message.
 */
export function classificationProblem(
  course: { id: string; area_id: unknown; subarea_id: unknown },
  next: { area_id?: unknown; subarea_id?: unknown },
  lookup: { readonly areaExists: boolean; readonly subareaAreaId: string | null },
): string | null {
  const text = (value: unknown): string | null => (typeof value === "string" ? value : null);
  const area = text(next.area_id !== undefined ? next.area_id : course.area_id);
  const subarea = text(next.subarea_id !== undefined ? next.subarea_id : course.subarea_id);
  if (area !== null && !lookup.areaExists) return `Unknown area ${area}.`;
  if (subarea === null) return null;
  if (next.subarea_id === undefined && next.area_id !== undefined && area !== course.area_id) {
    return `Course ${course.id} has subarea ${subarea} of ${text(course.area_id) ?? "-"}; name its subarea in ${area ?? "-"} (or null) in the same change.`;
  }
  const owner = lookup.subareaAreaId;
  if (owner === null) return `Unknown subarea ${subarea}.`;
  if (area === null) return `Subarea ${subarea} needs an area: set ${owner} first.`;
  if (owner !== area) return `Subarea ${subarea} belongs to ${owner}, not to ${area}.`;
  return null;
}
