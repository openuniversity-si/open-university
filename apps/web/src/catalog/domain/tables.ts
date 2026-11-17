import { z } from "zod";
import { LIMITS } from "./schema/fields.ts";
import { EXTENT } from "../../kernel/extent.ts";

// Normalized catalog rows as stored in the 0005 tables, one key per column, without the columns the database
// manages (created_at, updated_at, revision, text_sha256). Timestamps are ISO strings (toISOString), numerics numbers.
// The admin table API and current release compiler share these shapes.
const text = z.string().min(EXTENT.one);
const nullable = text.nullable();
const timestamp = z.iso.datetime();

export const catalogTablesSchema = z.strictObject({
  licenses: z.array(z.strictObject({
    code: text, name: text, url: nullable, requires_attribution: z.boolean(), non_commercial: z.boolean(),
    share_alike: z.boolean(), embed_only: z.boolean(), attribution_template: nullable,
  })),
  content_sources: z.array(z.strictObject({
    id: text, kind: text, title: text, publisher: text, url: text, youtube_channel_id: nullable, youtube_playlist_id: nullable,
  })),
  authors: z.array(z.strictObject({ id: text, slug: text, name: text, monogram: text, role: text, kind: text, cover: z.json().nullable() })),
  subject_areas: z.array(z.strictObject({ id: text, title: text, position: z.number().int() })),
  subject_subareas: z.array(z.strictObject({ id: text, area_id: text, title: text, position: z.number().int() })),
  courses: z.array(z.strictObject({
    id: text, slug: text, author_id: text, title: text, language_label: text, lesson_noun: text, status: text, featured: z.boolean(),
    source_id: nullable, license_code: nullable, attribution_text: nullable, canonical_url: nullable, rights_status: text,
    rights_notes: nullable, rights_checked_by: nullable, rights_checked_at: timestamp.nullable(), legacy: z.json().nullable(),
    area_id: nullable, subarea_id: nullable, cover_from: text, shared_with: z.array(text), published_at: timestamp.nullable(),
  })),
  course_editions: z.array(z.strictObject({
    id: text, course_id: text, slug: text, label: text, term: nullable, year: z.number().int(), position: z.number().int(),
    resolution: nullable, source_playlist_ids: z.array(text),
    variant_kind: nullable, variant_label: nullable,
    /** D-035. Null when the edition does not declare a language. */
    language: z.string().min(EXTENT.one).max(LIMITS.languageLabel).nullish(),
  })),
  lessons: z.array(z.strictObject({
    id: text, course_id: text, edition_id: text, part: text, slug: text, position: z.number().int(), kind: text, youtube_title: text,
    duration_seconds: z.number().int(), visible: z.boolean(), license_code: nullable, attribution_text: nullable,
  })),
  lesson_videos: z.array(z.strictObject({
    lesson_id: text, provider: text, external_id: text, playback_id: nullable, playback_policy: nullable, resolution_tier: nullable,
    status: text, duration_seconds: z.number().nullable(), youtube_license: nullable, channel_id: nullable,
    checked_at: timestamp, checked_by: text,
  })),
  catalog_texts: z.array(z.strictObject({
    entity_kind: text, entity_id: text, field: text, locale: text, text, source: text, source_ref: text, confidence: text,
    status: text, approved_by: nullable, approved_at: timestamp.nullable(), approved_sha256: nullable,
  })),
  home_rows: z.array(z.strictObject({ id: text, kind: text, institution_id: nullable.optional(), author_id: nullable, title: nullable, position: z.number().int(), visible: z.boolean(), cover: z.json().nullable(), full_name: nullable, place: nullable })),
  home_row_items: z.array(z.strictObject({ row_id: text, course_id: text, position: z.number().int() })),
  slug_redirects: z.array(z.strictObject({ from_path: text, to_path: text })),
});

export type CatalogTables = z.infer<typeof catalogTablesSchema>;
export type CatalogTableName = keyof CatalogTables;
export type CatalogRow<T extends CatalogTableName> = CatalogTables[T][number];

/** Write order (foreign keys first), primary key, and whether the row carries revision/updated_at. */
export const catalogTables: readonly { readonly name: CatalogTableName; readonly key: readonly string[]; readonly tracked: "revision" | "updated" | null }[] = [
  { name: "licenses", key: ["code"], tracked: null },
  { name: "content_sources", key: ["id"], tracked: "revision" },
  { name: "authors", key: ["id"], tracked: "revision" },
  { name: "subject_areas", key: ["id"], tracked: null },
  { name: "subject_subareas", key: ["id"], tracked: null },
  { name: "courses", key: ["id"], tracked: "revision" },
  { name: "course_editions", key: ["id"], tracked: "revision" },
  { name: "lessons", key: ["id"], tracked: "revision" },
  { name: "lesson_videos", key: ["lesson_id", "provider"], tracked: null },
  { name: "catalog_texts", key: ["entity_kind", "entity_id", "field", "locale"], tracked: "updated" },
  { name: "home_rows", key: ["id"], tracked: "revision" },
  { name: "home_row_items", key: ["row_id", "course_id"], tracked: null },
  { name: "slug_redirects", key: ["from_path"], tracked: null },
];

export function catalogTableColumns(name: CatalogTableName): string[] {
  return Object.keys(catalogTablesSchema.shape[name].element.shape);
}

/** Stable identity of a row within its table, e.g. `lesson-1/youtube`. */
export function catalogRowKey(name: CatalogTableName, row: Readonly<Record<string, unknown>>): string {
  const table = catalogTables.find((entry) => entry.name === name);
  if (!table) throw new Error(`Unknown catalog table ${name}.`);
  return table.key.map((column) => String(row[column])).join("/");
}

/** Natural id order: `course-12` sorts after `course-9`. */
export function compareIds(a: string, b: string): number {
  return a.localeCompare(b, "en", { numeric: true });
}

/** Rows in key order, so exports and snapshots are stable regardless of where they came from. */
export function sortTables(tables: CatalogTables): CatalogTables {
  const sorted = (name: CatalogTableName) => [...tables[name]].sort((a, b) => compareIds(catalogRowKey(name, a), catalogRowKey(name, b)));
  return catalogTablesSchema.parse(Object.fromEntries(catalogTables.map(({ name }) => [name, sorted(name)])));
}
