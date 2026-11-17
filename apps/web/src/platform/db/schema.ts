import { sql } from "drizzle-orm";
import { coverKindsByOwner, coverOwners } from "../../kernel/cover-kinds.ts";
import { EXTENT } from "../../kernel/extent.ts";
import { EDITION_YEARS, LIMITS } from "../../kernel/limits.ts";
import { catalogTextsFieldSql, coursesStatusSql, homeRowsKindSql, lessonsKindSql } from "./checks.ts";
import { bigint, bigserial, foreignKey, jsonb, numeric, pgSequence, unique, uniqueIndex, boolean, check, index, integer, pgTable, primaryKey, text, timestamp } from "drizzle-orm/pg-core";

// Better Auth 1.7.7 core fields. Nullable privacy fields remain adapter-compatible;
// F10 must prevent storing Google images, IP addresses, and user agents (§5.2).
export const user = pgTable("user", {
  id: text("id").primaryKey(),
  name: text("name").notNull(),
  email: text("email").notNull().unique(),
  emailVerified: boolean("email_verified").notNull().default(false),
  image: text("image"),
  createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
});

export const session = pgTable("session", {
  id: text("id").primaryKey(),
  expiresAt: timestamp("expires_at", { withTimezone: true }).notNull(),
  token: text("token").notNull().unique(),
  createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
  ipAddress: text("ip_address"),
  userAgent: text("user_agent"),
  userId: text("user_id").notNull().references(() => user.id, { onDelete: "cascade" }),
}, (table) => [index("session_user_id_idx").on(table.userId)]);

export const account = pgTable("account", {
  id: text("id").primaryKey(),
  accountId: text("account_id").notNull(),
  providerId: text("provider_id").notNull(),
  userId: text("user_id").notNull().references(() => user.id, { onDelete: "cascade" }),
  accessToken: text("access_token"),
  refreshToken: text("refresh_token"),
  idToken: text("id_token"),
  accessTokenExpiresAt: timestamp("access_token_expires_at", { withTimezone: true }),
  refreshTokenExpiresAt: timestamp("refresh_token_expires_at", { withTimezone: true }),
  scope: text("scope"),
  password: text("password"),
  createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
}, (table) => [index("account_user_id_idx").on(table.userId)]);

export const verification = pgTable("verification", {
  id: text("id").primaryKey(),
  identifier: text("identifier").notNull(),
  value: text("value").notNull(),
  expiresAt: timestamp("expires_at", { withTimezone: true }).notNull(),
  createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
}, (table) => [index("verification_identifier_idx").on(table.identifier)]);

export const lessonProgress = pgTable("lesson_progress", {
  userId: text("user_id").notNull().references(() => user.id, { onDelete: "cascade" }),
  lessonId: text("lesson_id").notNull(),
  courseId: text("course_id").notNull(),
  positionSeconds: integer("position_seconds").notNull(),
  durationSeconds: integer("duration_seconds"),
  completedAt: timestamp("completed_at", { withTimezone: true }),
  updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
}, (table) => [
  primaryKey({ columns: [table.userId, table.lessonId] }),
  check("lesson_progress_position_nonnegative", sql`${table.positionSeconds} >= 0`),
  check("lesson_progress_duration_positive", sql`${table.durationSeconds} > 0`),
  index("lesson_progress_user_recent").on(table.userId, table.updatedAt.desc().nullsFirst()),
  // 0007: the catalog doctor and the DELETE reports count progress rows per lesson (rows are never deleted by the catalog).
  index("lesson_progress_lesson").on(table.lessonId),
]);

// F10's already-applied 0002; preserve its immutable history.
export const rateLimit = pgTable("rate_limit", {
  id: text("id").primaryKey(),
  key: text("key").notNull().unique(),
  count: integer("count").notNull(),
  lastRequest: bigint("last_request", { mode: "number" }).notNull(),
});

// E2 expand phase: legacy descriptors remain valid for the pre-E2 deployment.
export const mediaObjects = pgTable("media_objects", {
  sha256: text("sha256").primaryKey(),
  ext: text("ext").notNull(),
  contentType: text("content_type").notNull(),
  bytes: bigint("bytes", { mode: "number" }).notNull(),
  width: integer("width").notNull(),
  height: integer("height").notNull(),
  createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  orphanedAt: timestamp("orphaned_at", { withTimezone: true }),
}, (table) => [
  check("media_objects_sha256", sql`${table.sha256} ~ '^[a-f0-9]{64}$'`),
  check("media_objects_ext", sql`${table.ext} IN ('jpg','png','webp','avif')`),
  check("media_objects_type", sql`${table.contentType} = 'image/' || CASE WHEN ${table.ext} = 'jpg' THEN 'jpeg' ELSE ${table.ext} END`),
  check("media_objects_dimensions", sql`${table.bytes} > 0 AND ${table.width} > 0 AND ${table.height} > 0`),
  index("media_objects_orphaned_candidates").on(table.orphanedAt).where(sql`${table.orphanedAt} IS NOT NULL`),
]);

// Dynamic catalog (0005). Text ids continue the static series and are never reused.
const slugPattern = "^[a-z0-9]+(?:-[a-z0-9]+)*$";
export const authorSeq = pgSequence("author_seq", { startWith: 3 });
export const courseSeq = pgSequence("course_seq", { startWith: 6 });
export const lessonSeq = pgSequence("lesson_seq", { startWith: 127 });
// 0009 (ADR-21): edition ids start a new series.
export const editionSeq = pgSequence("edition_seq", { startWith: 1 });

export const licenses = pgTable("licenses", {
  code: text("code").primaryKey(),
  name: text("name").notNull(),
  url: text("url"),
  requiresAttribution: boolean("requires_attribution").notNull(),
  nonCommercial: boolean("non_commercial").notNull().default(false),
  shareAlike: boolean("share_alike").notNull().default(false),
  embedOnly: boolean("embed_only").notNull().default(true),
  attributionTemplate: text("attribution_template"),
  createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
}, (table) => [
  check("licenses_code", sql`${table.code} ~ '^[a-z0-9]+(?:[-.][a-z0-9]+)*$'`),
]);

export const contentSources = pgTable("content_sources", {
  id: text("id").primaryKey(),
  kind: text("kind").notNull(),
  title: text("title").notNull(),
  publisher: text("publisher").notNull(),
  url: text("url").notNull(),
  youtubeChannelId: text("youtube_channel_id"),
  youtubePlaylistId: text("youtube_playlist_id"),
  // 0007: optimistic concurrency for PATCH /api/admin/catalog/sources/:id (ADR-18).
  revision: integer("revision").notNull().default(1),
  createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
}, (table) => [
  uniqueIndex("content_sources_playlist").on(table.youtubePlaylistId).where(sql`${table.youtubePlaylistId} IS NOT NULL`),
  check("content_sources_kind", sql`${table.kind} IN ('youtube-playlist', 'youtube-channel', 'institution-site')`),
  check("content_sources_url", sql`${table.url} ~ '^https://'`),
]);

export const authors = pgTable("authors", {
  id: text("id").primaryKey().default(sql`('author-' || nextval('author_seq'))`),
  slug: text("slug").notNull().unique(),
  name: text("name").notNull(),
  monogram: text("monogram").notNull(),
  role: text("role").notNull().default("Lecturer"),
  // Future author/institution pages (plan §11) extend from here; nothing else yet.
  kind: text("kind").notNull(),
  // 0010: the author cover (src/catalog/domain/author-cover.ts), null until set with `tower-catalog author cover`.
  cover: jsonb("cover"),
  revision: integer("revision").notNull().default(1),
  createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
}, (table) => [
  check("authors_slug", sql`${table.slug} ~ '${sql.raw(slugPattern)}'`),
  check("authors_monogram", sql`char_length(${table.monogram}) BETWEEN ${sql.raw(String(EXTENT.one))} AND ${sql.raw(String(LIMITS.monogram))}`),
  check("authors_kind", sql`${table.kind} IN ('person', 'institution', 'channel')`),
]);

// 0012 (ADR-25): the global subject areas in order. Data owned by the admin API (area create/move/update, docs/catalog/areas.md).
export const subjectAreas = pgTable("subject_areas", {
  id: text("id").primaryKey(),
  title: text("title").notNull(),
  position: integer("position").notNull(),
}, (table) => [
  uniqueIndex("subject_areas_position_unique").on(table.position),
  uniqueIndex("subject_areas_title_unique").on(table.title),
  check("subject_areas_id", sql`${table.id} ~ '${sql.raw(slugPattern)}'`),
  check("subject_areas_position", sql`${table.position} > 0`),
]);

// 0014 (ADR-26, D-030): optional subareas of an area. The rows live in this table; position is their order inside the area.
// Ids are unique across all areas; (area_id, id) is unique so courses can point at a subarea *of their own area*.
export const subjectSubareas = pgTable("subject_subareas", {
  id: text("id").primaryKey(),
  areaId: text("area_id").notNull().references(() => subjectAreas.id, { onDelete: "restrict" }),
  title: text("title").notNull(),
  position: integer("position").notNull(),
}, (table) => [
  uniqueIndex("subject_subareas_area_position_unique").on(table.areaId, table.position),
  uniqueIndex("subject_subareas_area_id_unique").on(table.areaId, table.id),
  uniqueIndex("subject_subareas_title_unique").on(table.title),
  check("subject_subareas_id", sql`${table.id} ~ '${sql.raw(slugPattern)}'`),
  check("subject_subareas_position", sql`${table.position} > 0`),
]);

export const courses = pgTable("courses", {
  id: text("id").primaryKey().default(sql`('course-' || nextval('course_seq'))`),
  slug: text("slug").notNull().unique(),
  // The lecturer (a person, or a channel); the offering institution is institutionId (D-024).
  authorId: text("author_id").notNull().references(() => authors.id, { onDelete: "restrict" }),
  // 0025 (D-024): the institution offering the course, set when it is placed on that institution's University row.
  institutionId: text("institution_id").references(() => authors.id, { onDelete: "restrict" }),
  title: text("title").notNull(),
  languageLabel: text("language_label").notNull().default("English"),
  lessonNoun: text("lesson_noun").notNull().default("Lecture"),
  status: text("status").notNull().default("draft"),
  featured: boolean("featured").notNull().default(false),
  sourceId: text("source_id").references(() => contentSources.id, { onDelete: "restrict" }),
  licenseCode: text("license_code").references(() => licenses.code, { onDelete: "restrict" }),
  attributionText: text("attribution_text"),
  canonicalUrl: text("canonical_url"),
  rightsStatus: text("rights_status").notNull().default("unverified"),
  rightsNotes: text("rights_notes"),
  rightsCheckedBy: text("rights_checked_by"),
  rightsCheckedAt: timestamp("rights_checked_at", { withTimezone: true }),
  legacy: jsonb("legacy"),
  // 0012: the course's one subject area (ADR-25), null until set with `tower-catalog course set --area-id`.
  areaId: text("area_id").references(() => subjectAreas.id, { onDelete: "restrict" }),
  // 0014: the course's optional subarea (ADR-26); the composite key below keeps it inside the course's own area.
  subareaId: text("subarea_id"),
  // D-031: the one declared cover owner. No default: a missing declaration is a rejected row, not `own`.
  coverFrom: text("cover_from").notNull(),
  // D-032: course ids this course shares a video with. No default: a missing list is a rejected row, not "share with anyone".
  sharedWith: text("shared_with").array().notNull(),
  revision: integer("revision").notNull().default(1),
  publishedAt: timestamp("published_at", { withTimezone: true }),
  createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
}, (table) => [
  uniqueIndex("courses_one_featured").on(sql`(true)`).where(sql`${table.featured} AND ${table.status} = 'published'`),
  index("courses_author").on(table.authorId),
  index("courses_institution").on(table.institutionId),
  index("courses_status").on(table.status),
  check("courses_slug", sql`${table.slug} ~ '${sql.raw(slugPattern)}' AND char_length(${table.slug}) <= ${sql.raw(String(LIMITS.courseSlug))}`),
  check("courses_status", sql.raw(coursesStatusSql())),
  check("courses_noun", sql`${table.lessonNoun} IN ('Lecture', 'Episode')`),
  check("courses_rights", sql`${table.rightsStatus} IN ('unverified', 'cleared', 'permission-requested', 'accepted-risk', 'restricted')`),
  check("courses_canonical", sql`${table.canonicalUrl} IS NULL OR ${table.canonicalUrl} ~ '^https://'`),
  // Rights gate: nothing is published without a license, a source, a canonical page, and cleared (or accepted) rights.
  // A subarea needs an area (with MATCH SIMPLE the composite key alone would accept a subarea without an area).
  check("courses_subarea_area", sql`${table.subareaId} IS NULL OR ${table.areaId} IS NOT NULL`),
  foreignKey({ name: "courses_subarea_area_fk", columns: [table.areaId, table.subareaId], foreignColumns: [subjectSubareas.areaId, subjectSubareas.id] }).onDelete("restrict"),
  check("courses_published_area", sql`${table.status} <> 'published' OR ${table.areaId} IS NOT NULL`),
  check("courses_published_rights", sql`${table.status} <> 'published' OR (${table.licenseCode} IS NOT NULL AND ${table.sourceId} IS NOT NULL AND ${table.canonicalUrl} IS NOT NULL AND ${table.rightsStatus} IN ('cleared', 'accepted-risk'))`),
  check("courses_cover_from", sql`${table.coverFrom} ~ '^(own|subarea:[a-z0-9]+(?:-[a-z0-9]+)*|area:[a-z0-9]+(?:-[a-z0-9]+)*)$'`),
]);

// 0009 (ADR-21): a course's editions (semester/year). Position 1 is the most recent edition, open by default.
export const courseEditions = pgTable("course_editions", {
  id: text("id").primaryKey().default(sql`('edition-' || nextval('edition_seq'))`),
  courseId: text("course_id").notNull().references(() => courses.id, { onDelete: "restrict" }),
  slug: text("slug").notNull(),
  label: text("label").notNull(),
  term: text("term"),
  year: integer("year").notNull(),
  // D-034. Both null, or a kind (language, term, group) and a short label. Not the season column above.
  variantKind: text("variant_kind"),
  variantLabel: text("variant_label"),
  // D-035. One language. A variant of kind language stores this same string in variant_label.
  language: text("language"),
  position: integer("position").notNull(),
  resolution: text("resolution"),
  // YouTube playlists the edition was imported from; informative, for a re-import.
  sourcePlaylistIds: text("source_playlist_ids").array().notNull().default(sql`'{}'::text[]`),
  revision: integer("revision").notNull().default(1),
  createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
}, (table) => [
  uniqueIndex("course_editions_course_slug").on(table.courseId, table.slug),
  uniqueIndex("course_editions_course_position").on(table.courseId, table.position),
  unique("course_editions_course_year_variant").on(table.courseId, table.year, table.variantKind, table.variantLabel).nullsNotDistinct(),
  // Target of the lessons (edition_id, course_id) foreign key: a lesson's edition belongs to the lesson's course.
  uniqueIndex("course_editions_id_course").on(table.id, table.courseId),
  check("course_editions_slug", sql`${table.slug} ~ '${sql.raw(slugPattern)}' AND char_length(${table.slug}) <= ${sql.raw(String(LIMITS.editionSlug))}`),
  check("course_editions_label", sql`char_length(btrim(${table.label})) BETWEEN ${sql.raw(String(EXTENT.one))} AND ${sql.raw(String(LIMITS.editionLabel))}`),
  check("course_editions_term", sql`${table.term} IS NULL OR ${table.term} IN ('spring', 'summer', 'fall', 'winter')`),
  check("course_editions_year", sql`${table.year} BETWEEN ${sql.raw(String(EDITION_YEARS.min))} AND ${sql.raw(String(EDITION_YEARS.max))}`),
  check("course_editions_variant", sql`((${table.variantKind} IS NULL) = (${table.variantLabel} IS NULL)) AND (${table.variantKind} IS NULL OR (${table.variantKind} IN ('language', 'term', 'group') AND char_length(btrim(${table.variantLabel})) BETWEEN ${sql.raw(String(EXTENT.one))} AND ${sql.raw(String(LIMITS.editionVariantLabel))}))`),
  check("course_editions_language", sql`${table.language} IS NULL OR char_length(btrim(${table.language})) BETWEEN ${sql.raw(String(EXTENT.one))} AND ${sql.raw(String(LIMITS.languageLabel))}`),
  check("course_editions_language_variant", sql`${table.variantKind} IS DISTINCT FROM 'language' OR (${table.language} IS NOT NULL AND ${table.variantLabel} = ${table.language})`),
  // Reorders move through positions above the current maximum, never through 0 or negatives.
  check("course_editions_position", sql`${table.position} > 0`),
]);

export const lessons = pgTable("lessons", {
  id: text("id").primaryKey().default(sql`('lesson-' || nextval('lesson_seq'))`),
  courseId: text("course_id").notNull().references(() => courses.id, { onDelete: "restrict" }),
  // 0009 (ADR-21): the lesson's edition (same course, enforced by the composite foreign key) and its part in it.
  editionId: text("edition_id").notNull(),
  part: text("part").notNull().default("lectures"),
  slug: text("slug").notNull(),
  // Order within the edition (0009; it was within the course before).
  position: integer("position").notNull(),
  kind: text("kind").notNull().default("lecture"),
  youtubeTitle: text("youtube_title").notNull(),
  durationSeconds: integer("duration_seconds").notNull(),
  visible: boolean("visible").notNull().default(true),
  licenseCode: text("license_code").references(() => licenses.code),
  attributionText: text("attribution_text"),
  revision: integer("revision").notNull().default(1),
  createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
}, (table) => [
  // Slugs stay unique per course: /c/<course>/<lesson> carries no edition (ADR-21).
  uniqueIndex("lessons_course_slug").on(table.courseId, table.slug),
  uniqueIndex("lessons_edition_position").on(table.editionId, table.position),
  foreignKey({ name: "lessons_edition_course_fk", columns: [table.editionId, table.courseId], foreignColumns: [courseEditions.id, courseEditions.courseId] }).onDelete("restrict"),
  check("lessons_part", sql`${table.part} IN ('lectures', 'labs')`),
  check("lessons_slug", sql`${table.slug} ~ '${sql.raw(slugPattern)}' AND char_length(${table.slug}) <= ${sql.raw(String(LIMITS.lessonSlug))}`),
  check("lessons_kind", sql.raw(lessonsKindSql())),
  // Reorder uses transient negatives; > 0 and contiguity are checked when a release compiles.
  check("lessons_position", sql`${table.position} <> 0`),
  check("lessons_duration", sql`${table.durationSeconds} > 0`),
]);

// YouTube is required to play; Mux (paused, ADR-11) moves here from video-assets.json.
export const lessonVideos = pgTable("lesson_videos", {
  lessonId: text("lesson_id").notNull().references(() => lessons.id, { onDelete: "cascade" }),
  // Copied from the lesson (0023 trigger) so YouTube uniqueness can be (course, video) without a join in the index.
  courseId: text("course_id").notNull().references(() => courses.id, { onDelete: "restrict" }),
  provider: text("provider").notNull(),
  externalId: text("external_id").notNull(),
  playbackId: text("playback_id"),
  playbackPolicy: text("playback_policy"),
  resolutionTier: text("resolution_tier"),
  status: text("status").notNull(),
  durationSeconds: numeric("duration_seconds", { precision: 12, scale: 6 }),
  youtubeLicense: text("youtube_license"),
  channelId: text("channel_id"),
  checkedAt: timestamp("checked_at", { withTimezone: true }).notNull(),
  checkedBy: text("checked_by").notNull(),
}, (table) => [
  primaryKey({ columns: [table.lessonId, table.provider] }),
  uniqueIndex("lesson_videos_youtube_course").on(table.courseId, table.externalId).where(sql`${table.provider} = 'youtube'`),
  uniqueIndex("lesson_videos_mux_external").on(table.provider, table.externalId).where(sql`${table.provider} <> 'youtube'`),
  check("lesson_videos_provider", sql`${table.provider} IN ('youtube', 'mux')`),
  check("lesson_videos_youtube_id", sql`${table.provider} <> 'youtube' OR ${table.externalId} ~ '^[A-Za-z0-9_-]{11}$'`),
]);

// Editorial text per (entity, field, locale). Approval pins the approved hash; an edit returns the text to draft.
// approved_by names the reviewer, human or automatic ('catalog-bot'). convert_to() is only STABLE, so the
// generated hash goes through the IMMUTABLE catalog_text_sha256() that 0005 creates first (the database is UTF8).
export const catalogTexts = pgTable("catalog_texts", {
  entityKind: text("entity_kind").notNull(),
  entityId: text("entity_id").notNull(),
  field: text("field").notNull(),
  locale: text("locale").notNull().default("en"),
  text: text("text").notNull(),
  textSha256: text("text_sha256").generatedAlwaysAs(sql`catalog_text_sha256("text")`),
  source: text("source").notNull(),
  sourceRef: text("source_ref").notNull(),
  confidence: text("confidence").notNull(),
  status: text("status").notNull().default("draft"),
  approvedBy: text("approved_by"),
  approvedAt: timestamp("approved_at", { withTimezone: true }),
  approvedSha256: text("approved_sha256"),
  updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
}, (table) => [
  primaryKey({ columns: [table.entityKind, table.entityId, table.field, table.locale] }),
  index("catalog_texts_pending").on(table.entityKind, table.entityId).where(sql`${table.status} = 'draft'`),
  check("catalog_texts_kind", sql`${table.entityKind} IN ('course', 'lesson', 'author')`),
  check("catalog_texts_field", sql.raw(catalogTextsFieldSql())),
  check("catalog_texts_source", sql`${table.source} IN ('figma', 'dossier/catalog', 'youtube', 'llm', 'manual')`),
  check("catalog_texts_confidence", sql`${table.confidence} IN ('figma-approved', 'high', 'medium', 'low')`),
  check("catalog_texts_approval", sql`(${table.status} = 'approved' AND ${table.approvedBy} IS NOT NULL AND ${table.approvedAt} IS NOT NULL AND ${table.approvedSha256} = ${table.textSha256}) OR (${table.status} = 'draft' AND ${table.approvedBy} IS NULL AND ${table.approvedAt} IS NULL AND ${table.approvedSha256} IS NULL)`),
  check("catalog_texts_approved_by", sql`${table.approvedBy} IS NULL OR char_length(btrim(${table.approvedBy})) BETWEEN ${sql.raw(String(EXTENT.one))} AND ${sql.raw(String(LIMITS.actorId))}`),
  check("catalog_texts_nonempty", sql`char_length(btrim(${table.text})) > 0`),
]);

export const homeRows = pgTable("home_rows", {
  id: text("id").primaryKey(),
  kind: text("kind").notNull(),
  institutionId: text("institution_id").references(() => authors.id, { onDelete: "restrict" }),
  authorId: text("author_id").references(() => authors.id, { onDelete: "restrict" }),
  title: text("title"),
  position: integer("position").notNull(),
  visible: boolean("visible").notNull().default(true),
  // 0011: the cover of a curated (university) row (src/catalog/domain/university-cover.ts), null until a batch ships it.
  cover: jsonb("cover"),
  // 0013: a curated (university) row's full name and place, shown under its card ("Yale University · New Haven, CT").
  fullName: text("full_name"),
  place: text("place"),
  revision: integer("revision").notNull().default(1),
  updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
}, (table) => [
  uniqueIndex("home_rows_institution_unique").on(table.institutionId).where(sql`${table.kind} = 'curated'`),
  check("home_rows_institution", sql`(${table.kind} = 'curated') = (${table.institutionId} IS NOT NULL)`),
  uniqueIndex("home_rows_position_unique").on(table.position),
  uniqueIndex("home_rows_one_continue").on(sql`(true)`).where(sql`${table.kind} = 'continue'`),
  check("home_rows_id", sql`${table.id} ~ '${sql.raw(slugPattern)}'`),
  check("home_rows_kind", sql.raw(homeRowsKindSql())),
  check("home_rows_shape", sql`(${table.kind} = 'author' AND ${table.authorId} IS NOT NULL) OR (${table.kind} = 'curated' AND ${table.title} IS NOT NULL AND ${table.authorId} IS NULL) OR (${table.kind} = 'continue' AND ${table.authorId} IS NULL)`),
  check("home_rows_position", sql`${table.position} <> 0`),
]);

export const homeRowItems = pgTable("home_row_items", {
  rowId: text("row_id").notNull().references(() => homeRows.id, { onDelete: "cascade" }),
  courseId: text("course_id").notNull().references(() => courses.id, { onDelete: "restrict" }),
  position: integer("position").notNull(),
}, (table) => [
  primaryKey({ columns: [table.rowId, table.courseId] }),
  uniqueIndex("home_row_items_position_unique").on(table.rowId, table.position),
  check("home_row_items_position", sql`${table.position} <> 0`),
]);

export const slugRedirects = pgTable("slug_redirects", {
  fromPath: text("from_path").primaryKey(),
  toPath: text("to_path").notNull(),
  createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
}, (table) => [
  check("slug_redirects_paths", sql`${table.fromPath} ~ '^/c/' AND ${table.toPath} ~ '^/c/' AND ${table.fromPath} <> ${table.toPath}`),
]);

// Published versions are immutable (the app only flips is_active/activated_at); exactly one is active.
export const catalogReleases = pgTable("catalog_releases", {
  number: integer("number").primaryKey(),
  schemaVersion: integer("schema_version").notNull(),
  payload: jsonb("payload").notNull(),
  payloadSha256: text("payload_sha256").notNull(),
  counts: jsonb("counts").notNull(),
  note: text("note").notNull(),
  createdBy: text("created_by").notNull(),
  createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  isActive: boolean("is_active").notNull().default(false),
  activatedAt: timestamp("activated_at", { withTimezone: true }),
}, (table) => [
  uniqueIndex("catalog_releases_one_active").on(sql`(true)`).where(sql`${table.isActive}`),
  check("catalog_releases_sha", sql`${table.payloadSha256} ~ '^[a-f0-9]{64}$'`),
]);

export const catalogAudit = pgTable("catalog_audit", {
  id: bigserial("id", { mode: "number" }).primaryKey(),
  at: timestamp("at", { withTimezone: true }).notNull().defaultNow(),
  actor: text("actor").notNull(),
  requestId: text("request_id").notNull(),
  action: text("action").notNull(),
  entityKind: text("entity_kind").notNull(),
  entityId: text("entity_id").notNull(),
  before: jsonb("before"),
  after: jsonb("after"),
  releaseNumber: integer("release_number").references(() => catalogReleases.number),
}, (table) => [
  index("catalog_audit_entity").on(table.entityKind, table.entityId, table.at.desc().nullsFirst()),
]);

export const adminIdempotency = pgTable("admin_idempotency", {
  key: text("key").primaryKey(),
  route: text("route").notNull(),
  requestSha256: text("request_sha256").notNull(),
  status: integer("status").notNull(),
  response: jsonb("response").notNull(),
  createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
});

export const catalogImports = pgTable("catalog_imports", {
  id: text("id").primaryKey(),
  playlistId: text("playlist_id").notNull(),
  sourceUrl: text("source_url").notNull(),
  tool: text("tool").notNull(),
  fetchedAt: timestamp("fetched_at", { withTimezone: true }).notNull(),
  items: jsonb("items").notNull(),
  report: jsonb("report").notNull(),
  courseId: text("course_id").references(() => courses.id, { onDelete: "set null" }),
  // 0007: an import is stored first ('received'), then turned into a draft course by POST /imports/:id/draft (ADR-18).
  status: text("status").notNull().default("received"),
  createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
}, (table) => [
  check("catalog_imports_status", sql`${table.status} IN ('received', 'drafted', 'discarded')`),
]);

// 0007 (ADR-18). The Home's optimistic-concurrency revision: one row, because PUT /home replaces every home_rows row.
export const catalogHome = pgTable("catalog_home", {
  singleton: boolean("singleton").primaryKey().default(true),
  revision: integer("revision").notNull().default(1),
  updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
}, (table) => [
  check("catalog_home_singleton", sql`${table.singleton}`),
]);

// 0007 (ADR-18). R2 keys whose rows a catalog DELETE removed: bytes go after the commit; a failed delete stays here until a
// re-run of the same DELETE finishes it, and the doctor reports what is left.
export const r2PendingDeletions = pgTable("r2_pending_deletions", {
  key: text("key").primaryKey(),
  ownerKind: text("owner_kind").notNull(),
  ownerId: text("owner_id").notNull(),
  courseId: text("course_id").notNull(),
  requestId: text("request_id").notNull(),
  attempts: integer("attempts").notNull().default(0),
  lastError: text("last_error"),
  createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
}, (table) => [
  index("r2_pending_deletions_course").on(table.courseId),
  check("r2_pending_deletions_owner_kind", sql`${table.ownerKind} IN ('course', 'lesson')`),
]);

// Shared fixed-minute admin allowance; only a SHA-256 digest is stored, never an IP or token.
export const adminRateLimits = pgTable("admin_rate_limits", {
  secretHash: text("secret_hash").primaryKey(),
  minute: bigint("minute", { mode: "number" }).notNull(),
  requests: integer("requests").notNull(),
});

/** CHECK expression for `(owner_kind, kind)`. `table` is the closed catalog_media identifier. */
export function coverOwnerKindSql(table: "catalog_media"): string {
  const pairs = coverOwners.flatMap((owner) => coverKindsByOwner[owner].map((kind) => `('${owner}', '${kind}')`));
  return `("${table}"."owner_kind", "${table}"."kind") in (${pairs.join(", ")})`;
}

// 0024 (INV-M1): one attachment table for every hierarchy node. 0027 drops the frozen asset tables.
export const catalogMedia = pgTable("catalog_media", {
  id: text("id").primaryKey(),
  ownerKind: text("owner_kind").notNull(),
  ownerId: text("owner_id").notNull(),
  kind: text("kind").notNull(),
  variant: text("variant").notNull().default("default"),
  mediaSha256: text("media_sha256").references(() => mediaObjects.sha256, { onDelete: "restrict" }),
  url: text("url").notNull(),
  pathname: text("pathname").notNull(),
  width: integer("width").notNull(),
  height: integer("height").notNull(),
  sha256: text("sha256").notNull(),
  alt: text("alt").notNull(),
  transform: jsonb("transform"),
  designStatus: text("design_status").notNull(),
  version: integer("version").notNull(),
  isActive: boolean("is_active").notNull().default(true),
  createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
}, (table) => [
  uniqueIndex("catalog_media_one_active").on(table.ownerKind, table.ownerId, table.kind, table.variant).where(sql`${table.isActive}`),
  uniqueIndex("catalog_media_version").on(table.ownerKind, table.ownerId, table.kind, table.variant, table.version),
  check("catalog_media_owner_kind", sql`${table.ownerKind} in ('institution', 'area', 'subarea', 'course', 'lesson')`),
  check("catalog_media_owner_kind_pair", sql.raw(coverOwnerKindSql("catalog_media"))),
  check("catalog_media_dimensions", sql`${table.width} > 0 and ${table.height} > 0 and ${table.version} > 0`),
  check("catalog_media_sha256", sql`${table.sha256} ~ '^[a-f0-9]{64}$'`),
  check("catalog_media_design_status", sql`${table.designStatus} in ('approved', 'draft', 'legacy')`),
]);

// 0019. Course projections keep every hash. A release index and its redirects point at one release and are not overwritten in place.
export const catalogCourseProjections = pgTable("catalog_course_projections", {
  courseId: text("course_id").notNull(),
  projectionSha256: text("projection_sha256").notNull(),
  sourceRevision: integer("source_revision").notNull(),
  summaryJson: jsonb("summary_json").notNull(),
  detailJson: jsonb("detail_json").notNull(),
}, (table) => [
  primaryKey({ columns: [table.courseId, table.projectionSha256] }),
  check("catalog_course_projections_sha", sql`${table.projectionSha256} ~ '^[a-f0-9]{64}$'`),
]);

export const catalogReleaseIndex = pgTable("catalog_release_index", {
  releaseNumber: integer("release_number").primaryKey().references(() => catalogReleases.number),
  manifestSha256: text("manifest_sha256").notNull(),
  indexJson: jsonb("index_json").notNull(),
  formatVersion: integer("format_version").notNull(),
}, (table) => [
  check("catalog_release_index_sha", sql`${table.manifestSha256} ~ '^[a-f0-9]{64}$'`),
  check("catalog_release_index_format", sql`${table.formatVersion} > 0`),
]);

export const catalogRedirects = pgTable("catalog_redirects", {
  releaseNumber: integer("release_number").notNull().references(() => catalogReleases.number),
  fromPath: text("from_path").notNull(),
  toPath: text("to_path").notNull(),
  statusCode: integer("status_code").notNull(),
}, (table) => [
  primaryKey({ columns: [table.releaseNumber, table.fromPath] }),
  index("catalog_redirects_release").on(table.releaseNumber),
  check("catalog_redirects_status", sql`${table.statusCode} IN (301, 308)`),
]);

// 0020. Durable ship jobs. The lease token fences an expired worker; the service owns stage transitions.
export const catalogJobs = pgTable("catalog_jobs", {
  jobId: text("job_id").primaryKey(),
  idempotencyKey: text("idempotency_key").notNull(),
  bundleSha256: text("bundle_sha256").notNull(),
  targetEnv: text("target_env").notNull(),
  actorId: text("actor_id").notNull(),
  stage: text("stage").notNull(),
  leaseUntil: timestamp("lease_until", { withTimezone: true }),
  leaseToken: integer("lease_token").notNull().default(0),
  attemptCount: integer("attempt_count").notNull().default(0),
  checkpointJson: jsonb("checkpoint_json"),
  stageTimingsJson: jsonb("stage_timings_json").notNull().default(sql`'[]'::jsonb`),
  lastError: text("last_error"),
  createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
}, (table) => [
  uniqueIndex("catalog_jobs_identity").on(table.targetEnv, table.actorId, table.idempotencyKey),
  index("catalog_jobs_lease").on(table.leaseUntil),
  index("catalog_jobs_stage").on(table.stage),
  check("catalog_jobs_env", sql`${table.targetEnv} IN ('preview', 'prod')`),
  check("catalog_jobs_sha", sql`${table.bundleSha256} ~ '^[a-f0-9]{64}$'`),
  check("catalog_jobs_stage", sql`${table.stage} IN ('VALIDATED', 'MEDIA_CHECKED', 'MEDIA_UPLOADED', 'BUNDLE_APPLIED', 'PUBLISHED', 'DRAFT_READY', 'VERIFIED', 'FAILED', 'PAUSED')`),
]);

// 0022. One bulk ship, keyed by the hash of its bundles. Chunks stage JSON until the batch commits.
export const catalogShipBatches = pgTable("catalog_ship_batches", {
  contentHash: text("content_hash").primaryKey(),
  status: text("status").notNull(),
  draft: boolean("draft").notNull(),
  allowOrphan: boolean("allow_orphan").notNull(),
  note: text("note"),
  chunkCount: integer("chunk_count").notNull(),
  // 0026 (S08): what the staged chunks hold; CourseBundleV1 arrays (POST /bundles/ship) or CatalogBatchV2 parts (POST /batches/apply).
  format: text("format").notNull().default("bundles-v1"),
  result: jsonb("result"),
  createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
}, (table) => [
  check("catalog_ship_batches_hash", sql`${table.contentHash} ~ '^[a-f0-9]{64}$'`),
  check("catalog_ship_batches_status", sql`${table.status} IN ('open', 'committed')`),
  check("catalog_ship_batches_chunks", sql`${table.chunkCount} BETWEEN ${sql.raw(String(EXTENT.one))} AND ${sql.raw(String(LIMITS.shipChunkCount))}`),
  check("catalog_ship_batches_format", sql`${table.format} IN ('bundles-v1', 'catalog-v2')`),
]);

export const catalogShipChunks = pgTable("catalog_ship_chunks", {
  contentHash: text("content_hash").notNull().references(() => catalogShipBatches.contentHash, { onDelete: "cascade" }),
  chunkIndex: integer("chunk_index").notNull(),
  bundles: jsonb("bundles").notNull(),
  createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
}, (table) => [
  primaryKey({ columns: [table.contentHash, table.chunkIndex] }),
  check("catalog_ship_chunks_index", sql`${table.chunkIndex} >= 0`),
]);

// D-051. Versioned configuration. Revision 0 is the code and is not a row.
export const configDocuments = pgTable("config_documents", {
  kind: text("kind").primaryKey(),
  revision: integer("revision").notNull(),
  body: jsonb("body").notNull(),
  actor: text("actor").notNull(),
  note: text("note"),
  updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
}, (table) => [
  check("config_documents_kind", sql`${table.kind} IN ('theme', 'copy', 'limits', 'editorial')`),
  check("config_documents_revision", sql`${table.revision} >= 1`),
]);

export const configDocumentRevisions = pgTable("config_document_revisions", {
  kind: text("kind").notNull(),
  revision: integer("revision").notNull(),
  body: jsonb("body").notNull(),
  actor: text("actor").notNull(),
  note: text("note"),
  createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
}, (table) => [
  primaryKey({ columns: [table.kind, table.revision] }),
  check("config_document_revisions_kind", sql`${table.kind} IN ('theme', 'copy', 'limits', 'editorial')`),
  check("config_document_revisions_revision", sql`${table.revision} >= 1`),
]);
