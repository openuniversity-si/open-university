import { stateConflict } from "../../kernel/errors.ts";
import { withUnitOfWork, type DbPool, type Queryable } from "../../platform/db/uow.ts";
import type {
  ClaimResult, DurableCatalogJob, JobCheckpoint, JobLease, JobResult, JobStage, JobStorePort, JobTiming,
} from "../ports/jobs.ts";

export interface SqlJobOptions {
  /** When omitted, exclusivity uses the database clock. Tests inject a clock so the shared cases stay deterministic. */
  readonly now?: () => Date;
  readonly ids?: () => string;
  /** Run inside a transaction the caller already opened (the admin mutation). */
  readonly db?: Queryable;
}

interface JobRow {
  job_id: string;
  idempotency_key: string;
  bundle_sha256: string;
  target_env: "preview" | "prod";
  actor_id: string;
  stage: JobStage;
  lease_until: Date | string | null;
  lease_token: number | string;
  attempt_count: number | string;
  checkpoint_json: JobCheckpoint | null;
  stage_timings_json: JobTiming[] | null;
  last_error: string | null;
}

const COLUMNS = "job_id, idempotency_key, bundle_sha256, target_env, actor_id, stage, lease_until, lease_token, attempt_count, checkpoint_json, stage_timings_json, last_error";

function instant(value: Date | string | null): string | null {
  if (value === null) return null;
  return value instanceof Date ? value.toISOString() : new Date(value).toISOString();
}

export async function storedJobActor(db: Queryable, jobId: string): Promise<string | undefined> {
  const { rows } = await db.query("SELECT actor_id FROM catalog_jobs WHERE job_id = $1", [jobId]);
  const actor = rows[0]?.actor_id;
  return typeof actor === "string" ? actor : undefined;
}

function jobOf(row: JobRow): DurableCatalogJob {
  return {
    identity: { actorId: row.actor_id, environment: row.target_env, idempotencyKey: row.idempotency_key, bundleSha256: row.bundle_sha256 },
    jobId: row.job_id,
    stage: row.stage,
    leaseToken: Number(row.lease_token),
    leaseUntil: instant(row.lease_until),
    attemptCount: Number(row.attempt_count),
    checkpoint: row.checkpoint_json,
    timings: row.stage_timings_json ?? [],
    lastError: row.last_error,
    completed: row.stage === "VERIFIED",
  };
}

function leaseOf(job: DurableCatalogJob): JobLease {
  return { identity: job.identity, jobId: job.jobId, token: job.leaseToken, expiresAt: job.leaseUntil ?? "" };
}

export function sanitizeJobError(error: string | undefined): string | null {
  if (!error) return null;
  return error.replace(/Bearer\s+\S+/gi, "Bearer [redacted]").replace(/postgres:\/\/\S+/gi, "[redacted]").slice(0, 300);
}

/** Atomic claim, heartbeat and CAS. Only this adapter names catalog_jobs. */
export function createSqlJobStore(pool: DbPool, options: SqlJobOptions = {}): JobStorePort {
  let sequence = 0;
  const ids = options.ids ?? (() => { sequence += 1; return `job-${String(sequence)}`; });
  const clockSql = options.now ? "$CLOCK::timestamptz" : "now()";
  const clockValue = () => options.now?.().toISOString();
  const scope = <T>(work: (db: Queryable) => Promise<T>): Promise<T> => options.db ? work(options.db) : withUnitOfWork(pool, work);

  function bind(sql: string, values: unknown[]): { text: string; values: unknown[] } {
    const token = "$CLOCK::timestamptz";
    if (!sql.includes(token)) return { text: sql, values };
    if (!options.now) return { text: sql.replaceAll(token, "now()"), values };
    // split/join keeps `$n` literal. A string replace would treat it as a capture and drop it.
    const placeholder = `$${String(values.length + 1)}::timestamptz`;
    return { text: sql.split(token).join(placeholder), values: [...values, clockValue()] };
  }

  async function one<T>(db: Queryable, sql: string, values: unknown[]): Promise<T | undefined> {
    const statement = bind(sql, values);
    const result = await db.query(statement.text, statement.values);
    return result.rows[0] as T | undefined;
  }

  return {
    claim(input, leaseMs) {
      return scope(async (db) => {
        const inserted = await one<JobRow>(db, `INSERT INTO catalog_jobs
          (job_id, idempotency_key, bundle_sha256, target_env, actor_id, stage, lease_until, lease_token, attempt_count, checkpoint_json, stage_timings_json, created_at, updated_at)
          VALUES ($1, $2, $3, $4, $5, 'VALIDATED', ${clockSql} + ($6 || ' milliseconds')::interval, 1, 1, NULL, '[]'::jsonb, ${clockSql}, ${clockSql})
          ON CONFLICT (target_env, actor_id, idempotency_key) DO NOTHING
          RETURNING ${COLUMNS}`, [ids(), input.idempotencyKey, input.bundleSha256, input.environment, input.actorId, String(leaseMs)]);
        if (inserted) {
          const job = jobOf(inserted);
          return { status: "acquired", lease: leaseOf(job), job } satisfies ClaimResult;
        }
        const row = await one<JobRow>(db, `SELECT ${COLUMNS} FROM catalog_jobs WHERE target_env = $1 AND actor_id = $2 AND idempotency_key = $3 FOR UPDATE`, [input.environment, input.actorId, input.idempotencyKey]);
        if (!row) throw stateConflict("The job disappeared during claim.");
        if (row.bundle_sha256 !== input.bundleSha256) return { status: "conflict" } satisfies ClaimResult;
        const current = jobOf(row);
        if (current.completed || current.stage === "VERIFIED") return { status: "completed", job: current } satisfies ClaimResult;
        const held = await one<{ held: boolean }>(db, `SELECT lease_until > ${clockSql} AS held FROM catalog_jobs WHERE job_id = $1`, [row.job_id]);
        if (held?.held) return { status: "occupied", job: current } satisfies ClaimResult;
        const updated = await one<JobRow>(db, `UPDATE catalog_jobs
          SET lease_token = lease_token + 1, attempt_count = attempt_count + 1, lease_until = ${clockSql} + ($2 || ' milliseconds')::interval, updated_at = ${clockSql}
          WHERE job_id = $1 RETURNING ${COLUMNS}`, [row.job_id, String(leaseMs)]);
        if (!updated) throw stateConflict("The job lease is no longer current.");
        const job = jobOf(updated);
        return { status: "acquired", lease: leaseOf(job), job } satisfies ClaimResult;
      });
    },
    async renew(lease, leaseMs) {
      const updated = await scope((db) => one<JobRow>(db, `UPDATE catalog_jobs
        SET lease_until = ${clockSql} + ($5 || ' milliseconds')::interval, updated_at = ${clockSql}
        WHERE job_id = $1 AND lease_token = $2 AND actor_id = $3 AND target_env = $4 AND lease_until > ${clockSql}
        RETURNING ${COLUMNS}`, [lease.jobId, lease.token, lease.identity.actorId, lease.identity.environment, String(leaseMs)]));
      if (!updated) throw stateConflict("The job lease is no longer current.");
      return leaseOf(jobOf(updated));
    },
    async advance(lease, expected, next) {
      await scope(async (db) => {
        const timing = JSON.stringify([{ stage: next.stage, at: options.now?.().toISOString() ?? "db" }]);
        const updated = await one<JobRow>(db, `UPDATE catalog_jobs
          SET stage = $3, checkpoint_json = $4::jsonb, stage_timings_json = stage_timings_json || $5::jsonb, updated_at = ${clockSql},
              lease_until = CASE WHEN $3 = 'VERIFIED' THEN NULL ELSE lease_until END
          WHERE job_id = $1 AND lease_token = $2 AND actor_id = $7 AND target_env = $8 AND lease_until > ${clockSql} AND stage = $6
          RETURNING ${COLUMNS}`, [lease.jobId, lease.token, next.stage, JSON.stringify(next), timing, expected, lease.identity.actorId, lease.identity.environment]);
        if (updated) return;
        const row = await one<JobRow>(db, `SELECT ${COLUMNS} FROM catalog_jobs WHERE job_id = $1`, [lease.jobId]);
        if (!row || Number(row.lease_token) !== lease.token) throw stateConflict("The job lease is no longer current.");
        const held = await one<{ held: boolean }>(db, `SELECT lease_until > ${clockSql} AS held FROM catalog_jobs WHERE job_id = $1`, [lease.jobId]);
        if (!held?.held) throw stateConflict("The job lease is no longer current.");
        throw stateConflict(`Stage ${row.stage} is not ${expected}.`);
      });
    },
    async complete(lease, result: JobResult) {
      await scope(async (db) => {
        const updated = await one<{ job_id: string }>(db, `UPDATE catalog_jobs
          SET stage = $3, last_error = $4, checkpoint_json = COALESCE($5::jsonb, checkpoint_json), lease_until = NULL, updated_at = ${clockSql},
              stage_timings_json = stage_timings_json || $6::jsonb
          WHERE job_id = $1 AND lease_token = $2 AND actor_id = $7 AND target_env = $8 AND lease_until > ${clockSql}
          RETURNING job_id`, [lease.jobId, lease.token, result.stage, sanitizeJobError(result.error), result.checkpoint ? JSON.stringify(result.checkpoint) : null, JSON.stringify([{ stage: result.stage, at: "done" }]), lease.identity.actorId, lease.identity.environment]);
        if (!updated) throw stateConflict("The job lease is no longer current.");
      });
    },
    async get(identity) {
      const statement = bind(`SELECT ${COLUMNS} FROM catalog_jobs WHERE target_env = $1 AND actor_id = $2 AND idempotency_key = $3`, [identity.environment, identity.actorId, identity.idempotencyKey]);
      const result = await pool.query(statement.text, statement.values);
      const row = result.rows[0] as JobRow | undefined;
      if (!row || row.bundle_sha256 !== identity.bundleSha256) return null;
      return jobOf(row);
    },
  };
}
