import type { PreconditionFailure } from "../../../src/catalog/domain/contracts.ts";
import type { authorView } from "../../../src/catalog/server/authors.ts";
import type { courseDetail, courseView } from "../../../src/catalog/server/courses.ts";
import type { Finding } from "../../../src/catalog/server/doctor.ts";
import type { ImportReport } from "../../../src/catalog/server/imports.ts";
import type { EditionView } from "../../../src/catalog/server/editions.ts";
import type { lessonView } from "../../../src/catalog/server/lessons.ts";
import type { SlugBatchPlan, SlugPlan } from "../../../src/catalog/domain/lesson-slug.ts";
import type { ReleaseDiff, ReleaseSummary } from "../../../src/catalog/server/releases.ts";
import type { PublicCatalog } from "../../../src/catalog/domain/release.ts";
import type { CatalogTables } from "../../../src/catalog/domain/tables.ts";
import type { RouteKey } from "./routes.ts";

// The `data` of each admin route, from the service's own types where it exports them (type-only imports: nothing of
// the server runs in the CLI). The integration suite runs every command against the real handlers, so a shape that
// drifts from what the service returns fails there.
export type CourseView = ReturnType<typeof courseView>;
export type CourseDetail = Awaited<ReturnType<typeof courseDetail>>;
export type LessonView = ReturnType<typeof lessonView>;
export type AuthorRow = ReturnType<typeof authorView> & { courses: number; homeRows: number };
export interface CourseRow {
  id: string; slug: string; title: string; authorId: string; status: string; featured: boolean; revision: number; publishedAt: string | null; areaId?: string | null; subareaId?: string | null;
  counts: { editions: number; lessons: number; visibleLessons: number; texts: number; draftTexts: number }; pending: { target: string | null; failed: PreconditionFailure[] };
}
export interface TextField { field: string; maxChars: number; requiredForReview: boolean; requiredForPublish: boolean; text: string | null; status: string | null; sha256?: string; approvedSha256?: string | null; issues: { rule: string; message: string }[] }
export interface ReleaseRow { number: number; sha: string; counts: Record<string, number>; note: string; createdBy: string; createdAt: string; isActive: boolean; activatedAt: string | null }
export interface Publication { release: ReleaseSummary & { created: boolean }; diff: ReleaseDiff; noop?: true }
export interface DryRunRelease { valid: boolean; errors: string[]; unchanged?: boolean; diff: ReleaseDiff | null; counts?: Record<string, number> }
export interface HomeRow { id: string; kind: "continue" | "author" | "curated"; title: string | null; authorId: string | null; visible: boolean; position: number; courseIds: string[]; cover?: unknown; fullName?: string | null; place?: string | null }
export interface HomeData { revision: number; featuredCourseId: string | null; rows: HomeRow[] }
export interface SubareaRow { id: string; areaId: string; title: string; position: number; uses?: number; published?: number; covers?: { kind: string; variant: string; sha256: string }[] }
export interface ClassifyChange { id: string; before: { areaId: string | null; subareaId: string | null }; after: { areaId: string | null; subareaId: string | null } }
export interface AreaRow { id: string; title: string; position: number; uses?: number; published?: number }
export interface LicenseRow { code: string; name: string; url: string | null; requiresAttribution: boolean; nonCommercial: boolean; embedOnly: boolean; uses: number }
export interface SourceRow { id: string; kind: string; title: string; publisher: string; url: string; revision: number; uses: number }
export interface Redirect { from: string; to: string; live?: boolean }
export interface DeleteAnswer { dryRun: boolean; report?: Record<string, unknown>; [key: string]: unknown }
export interface TextWrite { entity: string; field: string; sha256: string; status: string; changed: boolean }

export interface Responses {
  "GET /courses": { courses: CourseRow[]; nextCursor: string | null };
  "POST /courses": { course: CourseView };
  "GET /courses/:id": CourseDetail;
  "PATCH /courses/:id": { course: CourseView; noop?: true };
  "DELETE /courses/:id": DeleteAnswer;
  "POST /courses/:id/status": { course: CourseView };
  "POST /courses/:id/publish": Publication;
  "POST /courses/publish-batch": Publication & { previous: number | null; courses: { id: string; from: string }[] };
  "POST /courses/:id/unpublish": Publication;
  "GET /courses/:id/editions": { courseId: string; editions: (EditionView & { counts: CourseDetail["editions"][number]["counts"] })[] };
  "POST /courses/:id/editions": { edition: EditionView; order: string[]; courseRevision: number };
  "PUT /courses/:id/editions/order": { editionIds: string[]; revision: number; noop?: true };
  "PATCH /editions/:id": { edition: EditionView; courseRevision?: number; noop?: true };
  "DELETE /editions/:id": DeleteAnswer;
  "PUT /editions/:id/lessons/order": { editionId: string; lessonIds: string[]; revision: number; noop?: true };
  "POST /courses/:id/lessons": { lesson: LessonView; youtubeId: string; courseRevision: number };
  "PUT /courses/:id/lessons/order": { lessonIds: string[]; revision: number; noop?: true };
  "PUT /lessons/slugs": { courseId: string; courseRevision: number; plan: SlugBatchPlan; lessons: { id: string; slug: string; revision: number }[] } | { courseId: string; plan: SlugBatchPlan; lessons: []; noop: true } | { dryRun: true; courseId: string; plan: SlugBatchPlan; noop: boolean };
  "PATCH /lessons/:id": { lesson: LessonView; courseRevision?: number; redirects?: SlugPlan; noop?: true } | { dryRun: true; lesson: LessonView; changes: Record<string, { before: unknown; after: unknown }>; redirects: SlugPlan | null; noop: boolean };
  "DELETE /lessons/:id": DeleteAnswer;
  "GET /authors": { authors: AuthorRow[] };
  "POST /authors": { author: ReturnType<typeof authorView> };
  "PATCH /authors/:id": { author: ReturnType<typeof authorView>; noop?: true };
  "DELETE /authors/:id": DeleteAnswer;
  "GET /texts": { entity: string; fields: TextField[] };
  "PUT /texts": { items: TextWrite[]; noop?: true };
  "POST /texts/approve": { items: unknown[]; approvedBy: string };
  "POST /texts/revoke": { items: unknown[] };
  "GET /home": HomeData;
  "PUT /home": { home: HomeData; release: ReleaseSummary & { created: boolean }; diff: ReleaseDiff; noop?: true };
  "GET /areas": { areas: AreaRow[] };
  "POST /areas": { area: AreaRow };
  "PATCH /areas/:id": { area: AreaRow; release?: ReleaseSummary & { created: boolean }; diff?: ReleaseDiff; noop?: true };
  "POST /areas/:id/move": { area: AreaRow; areas: AreaRow[]; release?: ReleaseSummary & { created: boolean }; diff?: ReleaseDiff; noop?: true };
  "GET /subareas": { subareas: SubareaRow[] };
  "POST /subareas": { subarea: SubareaRow };
  "POST /courses/classify": { changed: ClassifyChange[]; unchanged: number; noop?: true };
  "GET /licenses": { licenses: LicenseRow[] };
  "POST /media/references": { used: string[] };
  "POST /licenses": { license: LicenseRow };
  "GET /sources": { sources: SourceRow[] };
  "POST /sources": { source: SourceRow };
  "PATCH /sources/:id": { source: SourceRow; noop?: true };
  "POST /imports": { import: { id: string; playlistId: string; status: string; report: ImportReport } };
  "POST /imports/:id/draft": { import: { id: string; status: string; courseId: string; editionId: string }; course: Pick<CourseView, "id" | "slug" | "status">; edition: EditionView; lessons: LessonView[]; courseRevision?: number };
  "GET /releases": { releases: ReleaseRow[] };
  "GET /releases/:n": { release: { number: number; sha: string; payload: PublicCatalog; isActive: boolean; note: string; createdBy: string; createdAt: string; activatedAt: string | null } };
  /** `?dryRun=true` answers the report; otherwise the publication (see releaseDryRun/createRelease in commands/shared.ts). */
  "POST /releases": DryRunRelease | Publication;
  "POST /releases/:n/activate": { release: { number: number; sha: string }; previous?: number | null; noop?: true };
  "GET /redirects": { redirects: Redirect[]; nextCursor?: string | null };
  "POST /redirects": { redirect: Redirect; noop?: true };
  "DELETE /redirects": { dryRun: boolean; redirect: Redirect; deleted?: true };
  "POST /preview-token": { url: string; to: string; courseId: string | null; expiresAt: string };
  "GET /audit": { entity: string; entries: { id: number; at: string; actor: string; requestId: string; action: string; before: unknown; after: unknown; releaseNumber: number | null }[] };
  "GET /tables": { activeRelease: { number: number; sha: string } | null; tables: CatalogTables };
  "GET /doctor": { ok: boolean; activeRelease: { number: number; sha: string } | null; findings: Finding[] };
}
/** Compile-time guardians: Responses names every route of the table (ResponseOf fails otherwise), and only those. */
export type ResponseOf<K extends RouteKey> = K extends keyof Responses ? Responses[K] : unknown;
export const RESPONSES_HAVE_NO_EXTRA_ROUTE: [Exclude<keyof Responses, RouteKey>] extends [never] ? true : never = true;
