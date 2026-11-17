import { REDIRECT_LIST_LIMIT, type RedirectCreate } from "../domain/contracts.ts";
import type { Outcome } from "./mutation.ts";
import { notFound, stateConflict, unprocessable } from "../../kernel/errors.ts";
import type { HandlerContext } from "./http.ts";
import { existingPaths } from "./common.ts";

// Redirect edits only touch slug_redirects; like every table edit they reach the site with the next release.

type RedirectListQuery = { limit?: number; cursor?: string };

/**
 * One keyset page. `live` is the next release: the target path is a published course or visible lesson, and the source
 * path is not. It is not "the row exists".
 */
export async function listRedirects(context: HandlerContext<unknown, RedirectListQuery, unknown>): Promise<Outcome> {
  const limit = context.query.limit ?? REDIRECT_LIST_LIMIT;
  const { rows } = await context.db.query(REDIRECT_PAGE_SQL, [context.query.cursor ?? null, limit + 1]);
  const page = rows.slice(0, limit);
  const nextCursor = rows.length > limit ? stringPath(page.at(-1)?.from_path) : null;
  return {
    data: {
      redirects: page.map((row) => ({ from: stringPath(row.from_path), to: stringPath(row.to_path), live: row.live === true })),
      nextCursor,
    },
  };
}

const REDIRECT_PAGE_SQL = `WITH live AS (
  SELECT '/c/' || slug AS path FROM courses WHERE status = 'published'
  UNION ALL
  SELECT '/c/' || c.slug || '/' || l.slug
  FROM lessons l JOIN courses c ON c.id = l.course_id
  WHERE c.status = 'published' AND l.visible
),
page AS (
  SELECT from_path, to_path FROM slug_redirects
  WHERE ($1::text IS NULL OR from_path > $1)
  ORDER BY from_path
  LIMIT $2
)
SELECT p.from_path, p.to_path, (to_live.path IS NOT NULL AND from_live.path IS NULL) AS live
FROM page p
LEFT JOIN live to_live ON to_live.path = p.to_path
LEFT JOIN live from_live ON from_live.path = p.from_path
ORDER BY p.from_path`;

function stringPath(value: unknown): string {
  return typeof value === "string" ? value : "";
}

export async function createRedirect(context: HandlerContext<unknown, unknown, RedirectCreate>): Promise<Outcome> {
  const { from, to } = context.body;
  return context.mutate(async (tx) => {
    if (from === to) throw unprocessable("A redirect needs two different paths.");
    const paths = await existingPaths(tx);
    const errors = [
      ...(paths.has(from) ? [`${from} is a course or lesson page; a redirect would shadow it.`] : []),
      ...(paths.has(to) ? [] : [`${to} is not a course or lesson page.`]),
    ];
    const { rows: chained } = await tx.query("SELECT from_path FROM slug_redirects WHERE from_path = $1 OR to_path = $2", [to, from]);
    if (chained.length > 0) errors.push("Redirects do not chain: the target is itself redirected, or something redirects to the source.");
    if (errors.length > 0) throw unprocessable(`${String(errors.length)} problem(s) with this redirect.`, { errors });
    const { rows } = await tx.query("SELECT to_path FROM slug_redirects WHERE from_path = $1 FOR UPDATE", [from]);
    if (rows[0]?.to_path === to) return { data: { redirect: { from, to }, noop: true }, noop: true };
    if (rows[0]) throw stateConflict(`${from} already redirects to ${String(rows[0].to_path)}; delete it first.`, { current: rows[0].to_path });
    await tx.query("INSERT INTO slug_redirects (from_path, to_path) VALUES ($1, $2)", [from, to]);
    await tx.audit({ action: "redirect.create", entityKind: "redirect", entityId: from, after: { from, to } });
    return { status: 201, data: { redirect: { from, to } }, entity: `redirect:${from}` };
  });
}

/** Dry-run unless confirm=true. */
export async function deleteRedirect(context: HandlerContext<unknown, { from: string; confirm?: boolean }, unknown>): Promise<Outcome> {
  const { from } = context.query;
  const { rows } = await context.db.query("SELECT to_path FROM slug_redirects WHERE from_path = $1", [from]);
  if (!rows[0]) throw notFound(`Redirect ${from}`);
  const redirect = { from, to: String(rows[0].to_path) };
  if (context.query.confirm !== true) return { data: { dryRun: true, redirect } };
  return context.mutate(async (tx) => {
    const { rows: deleted } = await tx.query("DELETE FROM slug_redirects WHERE from_path = $1 RETURNING to_path", [from]);
    if (!deleted[0]) throw notFound(`Redirect ${from}`);
    await tx.audit({ action: "redirect.delete", entityKind: "redirect", entityId: from, before: { from, to: deleted[0].to_path } });
    return { data: { dryRun: false, deleted: true, redirect: { from, to: String(deleted[0].to_path) } }, entity: `redirect:${from}` };
  });
}
