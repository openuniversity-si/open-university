import type { Queryable } from "../../platform/db/uow.ts";
import type { LessonSlugsPut } from "../domain/contracts.ts";
import { lockRow, touchCourse, type Outcome } from "./mutation.ts";
import type { HandlerContext } from "./http.ts";
import { coursePath } from "./common.ts";
import { planSlugBatch, type SlugBatchPlan } from "../domain/lesson-slug.ts";

/**
 * PUT /lessons/slugs (BRIEF-P7 §2): one course's lesson slugs in one transaction, all or nothing. The plan (planSlugBatch)
 * sees every change at once, so swaps and rotations work; the writes go through a temporary slug per moved lesson because
 * lessons_course_slug is checked row by row. Each lesson gets its own `lesson.slug` audit row; the course revision moves
 * once. `dryRun: true` answers the same plan without writing. Live with the next release, like PATCH.
 */
export async function putLessonSlugs(context: HandlerContext<unknown, unknown, LessonSlugsPut>): Promise<Outcome> {
  const body = context.body;
  // Every read and check; the dry-run stops here (outside a transaction, so its row locks end with each statement).
  const prepare = async (tx: Queryable) => {
    const course = await lockRow(tx, "courses", body.courseId, `Course ${body.courseId}`, body.expectedRevision);
    const prefix = coursePath(String(course.slug));
    const { rows: lessons } = await tx.query("SELECT id, slug FROM lessons WHERE course_id = $1 ORDER BY id FOR UPDATE", [body.courseId]);
    const { rows: redirects } = await tx.query("SELECT from_path, to_path FROM slug_redirects WHERE from_path LIKE $1 OR to_path LIKE $1 ORDER BY from_path FOR UPDATE", [`${prefix}/%`]);
    const plan = planSlugBatch(prefix, lessons.map((row) => ({ id: String(row.id), slug: String(row.slug) })),
      redirects.map((row) => ({ from: String(row.from_path), to: String(row.to_path) })), body.changes);
    return { plan, prefix };
  };
  if (body.dryRun === true) {
    const { plan } = await prepare(context.db);
    return { data: { dryRun: true, courseId: body.courseId, plan, noop: plan.changes.length === 0 } };
  }
  return context.mutate(async (tx) => {
    const { plan, prefix } = await prepare(tx);
    if (plan.changes.length === 0) return { data: { courseId: body.courseId, plan, lessons: [], noop: true }, noop: true, entity: `course:${body.courseId}` };
    const ids = plan.changes.map((change) => change.lessonId);
    await tx.query("UPDATE lessons SET slug = 'reslug-' || id WHERE id = ANY($1::text[])", [ids]);
    const { rows } = await tx.query(`UPDATE lessons l SET slug = v.slug, revision = l.revision + 1, updated_at = now()
      FROM unnest($1::text[], $2::text[]) AS v(id, slug) WHERE l.id = v.id RETURNING l.id, l.slug, l.revision`, [ids, plan.changes.map((change) => change.after)]);
    if (plan.removed.length > 0) await tx.query("DELETE FROM slug_redirects WHERE from_path = ANY($1::text[])", [plan.removed.map((redirect) => redirect.from)]);
    for (const change of plan.flattened) await tx.query("UPDATE slug_redirects SET to_path = $2 WHERE from_path = $1", [change.from, change.after]);
    for (const redirect of plan.created) {
      await tx.query("INSERT INTO slug_redirects (from_path, to_path) VALUES ($1, $2) ON CONFLICT (from_path) DO UPDATE SET to_path = EXCLUDED.to_path", [redirect.from, redirect.to]);
    }
    const courseRevision = await touchCourse(tx, body.courseId);
    for (const change of plan.changes) {
      await tx.audit({ action: "lesson.slug", entityKind: "lesson", entityId: change.lessonId, before: { slug: change.before, path: `${prefix}/${change.before}` },
        after: { slug: change.after, path: `${prefix}/${change.after}`, batch: true, redirects: lessonShare(plan, `${prefix}/${change.before}`, `${prefix}/${change.after}`), courseRevision } });
    }
    const lessons = rows.map((row) => ({ id: String(row.id), slug: String(row.slug), revision: Number(row.revision) })).sort((a, b) => ids.indexOf(a.id) - ids.indexOf(b.id));
    return { data: { courseId: body.courseId, courseRevision, plan, lessons }, entity: `course:${body.courseId}` };
  });
}

/** The part of the plan one lesson's audit row records: its own redirect and the ones moved to or dropped from its path. */
function lessonShare(plan: SlugBatchPlan, oldPath: string, newPath: string) {
  return {
    created: plan.created.find((redirect) => redirect.from === oldPath) ?? null,
    flattened: plan.flattened.filter((change) => change.after === newPath),
    removed: plan.removed.filter((redirect) => redirect.from === newPath),
    reused: plan.reused.includes(oldPath),
  };
}
