import type { PreviewTokenBody } from "../domain/contracts.ts";
import type { Outcome } from "./mutation.ts";
import { AppError, notFound } from "../../kernel/errors.ts";
import type { HandlerContext } from "./http.ts";
import { signPreviewToken } from "./preview-token.ts";
import { iso } from "./common.ts";

export const PREVIEW_ROUTE = "/api/catalog/preview";

/** A short-lived preview URL (≤ 60 min), optionally scoped to one course. Issuing one changes nothing, so it is not audited. */
export async function createPreviewToken(context: HandlerContext<unknown, unknown, PreviewTokenBody>): Promise<Outcome> {
  const { secret } = context.deps;
  if (!secret) throw new AppError("unconfigured", "The admin API is not configured.");
  const courseId = context.body.courseId ?? null;
  let to = "/";
  if (courseId !== null) {
    const { rows } = await context.db.query("SELECT slug FROM courses WHERE id = $1", [courseId]);
    if (!rows[0]) throw notFound(`Course ${courseId}`);
    to = `/c/${String(rows[0].slug)}`;
  }
  const { token, expiresAt } = signPreviewToken(secret, courseId, context.body.ttlMinutes ?? 30, context.deps.now());
  const url = `${PREVIEW_ROUTE}?${new URLSearchParams({ token, to }).toString()}`;
  return { data: { url, to, courseId, expiresAt: expiresAt.toISOString() } };
}

/** The audit trail of one entity, most recent first (limit ≤ 200). */
export async function readAudit(context: HandlerContext<unknown, { entity: string; limit?: number }, unknown>): Promise<Outcome> {
  const separator = context.query.entity.indexOf(":");
  const kind = context.query.entity.slice(0, separator);
  const id = context.query.entity.slice(separator + 1);
  const { rows } = await context.db.query(`SELECT id, at, actor, request_id, action, before, after, release_number FROM catalog_audit
    WHERE entity_kind = $1 AND entity_id = $2 ORDER BY at DESC, id DESC LIMIT $3`, [kind, id, context.query.limit ?? 50]);
  return {
    data: {
      entity: context.query.entity,
      entries: rows.map((row) => ({
        id: Number(row.id), at: iso(row.at), actor: String(row.actor), requestId: String(row.request_id), action: String(row.action),
        before: row.before ?? null, after: row.after ?? null, releaseNumber: row.release_number === null ? null : Number(row.release_number),
      })),
    },
  };
}
