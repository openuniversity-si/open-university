import type { Queryable } from "../../platform/db/uow.ts";
import { AppError, assertRevision, notFound } from "../../kernel/errors.ts";
import { PAGINATION } from "../../kernel/pagination.ts";

import { withUnitOfWork, type UnitOfWork, type DbPool } from "../../platform/db/uow.ts";
export type { PooledClient } from "../../platform/db/uow.ts";
export type AdminPool = DbPool;

export interface AuditEntry {
  readonly action: string;
  readonly entityKind: string;
  readonly entityId: string;
  readonly before?: unknown;
  readonly after?: unknown;
  readonly releaseNumber?: number | null;
}

/** The open transaction of one mutation: every write and its catalog_audit rows commit or roll back together. */
export interface Tx extends UnitOfWork {
  audit(entry: AuditEntry): Promise<void>;
  readonly audits: number;
}

/** What a handler answers. `noop`: nothing changed, so no audit row is required (and none is written). */
export interface Outcome<T = unknown> {
  readonly status?: number;
  readonly data: T;
  readonly noop?: boolean;
  /** `kind:id` for the CATALOG_ADMIN log line. */
  readonly entity?: string;
}

export interface Idempotency { readonly key: string; readonly route: string; readonly requestSha256: string }

/** The key was already used for this exact request: answer with what was stored (no re-execution, no new audit). */
export class IdempotentReplay extends Error {
  readonly status: number;
  readonly data: unknown;
  constructor(status: number, data: unknown) {
    super("Idempotent replay.");
    this.name = "IdempotentReplay";
    this.status = status;
    this.data = data;
  }
}
/** A handler returned success without writing catalog_audit: a programming error, rolled back like any failure. */
export class AuditMissingError extends AppError {
  constructor() { super("internal", "A catalog mutation must write catalog_audit in its transaction."); this.name = "AuditMissingError"; }
}

/** Replays or refuses a key seen before; null when the key is new. Runs before any network work and again under the lock. */
export async function checkIdempotency(db: Queryable, idempotency: Idempotency, forUpdate = false): Promise<null> {
  const { rows } = await db.query(`SELECT route, request_sha256, status, response FROM admin_idempotency WHERE key = $1${forUpdate ? " FOR UPDATE" : ""}`, [idempotency.key]);
  const stored = rows[0];
  if (!stored) return null;
  if (stored.route !== idempotency.route || stored.request_sha256 !== idempotency.requestSha256) {
    throw new AppError("idempotency_mismatch", "This Idempotency-Key was used for a different request; use a new key.");
  }
  throw new IdempotentReplay(Number(stored.status), (stored.response as { data: unknown }).data);
}

export interface MutationMeta { readonly requestId: string; readonly actor: string }

/**
 * One mutation, one transaction (ADR-18): BEGIN, the idempotency key under an advisory lock, the work and its audit rows,
 * the stored response for a 2xx, COMMIT. Any throw rolls everything back. Concurrent requests with the same key queue on
 * the lock, so exactly one executes and the others replay its stored response.
 */
export async function runMutation<T>(pool: AdminPool, meta: MutationMeta, idempotency: Idempotency | null, work: (tx: Tx) => Promise<Outcome<T>>): Promise<Outcome<T>> {
  return withUnitOfWork(pool, async (client) => {
      if (idempotency) {
        await client.acquireLock({ scope: "xact", key: `idempotency:${idempotency.key}` });
        await checkIdempotency(client, idempotency, true);
      }
      let audits = 0;
      const tx: Tx = {
        acquireLock: (lock) => client.acquireLock(lock),
        onAfterCommit: (effect) => { client.onAfterCommit(effect); },
        query: (sql, values) => client.query(sql, values),
        async audit(entry) {
          await client.query(`INSERT INTO catalog_audit (actor, request_id, action, entity_kind, entity_id, before, after, release_number)
            VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7::jsonb, $8)`, [meta.actor, meta.requestId, entry.action, entry.entityKind, entry.entityId,
            entry.before === undefined ? null : JSON.stringify(entry.before), entry.after === undefined ? null : JSON.stringify(entry.after), entry.releaseNumber ?? null]);
          audits += 1;
        },
        get audits() { return audits; },
      };
      const outcome = await work(tx);
      if (!outcome.noop && audits === 0) throw new AuditMissingError();
      const status = outcome.status ?? 200;
      if (idempotency && status >= 200 && status < 300) {
        await client.query(`INSERT INTO admin_idempotency (key, route, request_sha256, status, response) VALUES ($1, $2, $3, $4, $5::jsonb) ON CONFLICT (key) DO NOTHING`,
          [idempotency.key, idempotency.route, idempotency.requestSha256, status, JSON.stringify({ data: outcome.data })]);
      }
      if (idempotency) client.onAfterCommit(() => pruneIdempotency(pool));
      return outcome;
  });
}

/** Opportunistic cleanup (no job, plan §8): keys older than 30 days, a bounded batch, never failing the request. */
async function pruneIdempotency(client: Queryable): Promise<void> {
  try {
    await client.query(`DELETE FROM admin_idempotency WHERE key IN (SELECT key FROM admin_idempotency WHERE created_at < now() - interval '30 days' LIMIT ${String(PAGINATION.idempotencySweep)})`);
  } catch { /* the request already committed; the next POST retries */ }
}

/** Serializes every transaction that compiles or activates a release, so each one sees the previous one committed. */
export async function lockReleases(tx: Queryable): Promise<void> {
  await tx.query("SELECT pg_advisory_xact_lock(hashtext('catalog:release'))");
}

type Locked = Record<string, unknown> & { revision: number };
/** `SELECT … FOR UPDATE` on one row, checking `expectedRevision` when given; 404 when absent. */
export async function lockRow(tx: Queryable, table: "courses" | "course_editions" | "lessons" | "authors" | "content_sources", id: string, what: string, expectedRevision?: number): Promise<Locked> {
  const { rows } = await tx.query(`SELECT * FROM ${table} WHERE id = $1 FOR UPDATE`, [id]);
  const row = rows[0];
  if (!row) throw notFound(what);
  const locked = { ...row, revision: Number(row.revision) };
  if (expectedRevision !== undefined) assertRevision(locked.revision, expectedRevision);
  return locked;
}

/** Bumps a course's revision: lesson changes count as course changes, so the course's expectedRevision covers the order. */
export async function touchCourse(tx: Queryable, courseId: string): Promise<number> {
  const { rows } = await tx.query("UPDATE courses SET revision = revision + 1, updated_at = now() WHERE id = $1 RETURNING revision", [courseId]);
  return Number(rows[0]?.revision);
}
