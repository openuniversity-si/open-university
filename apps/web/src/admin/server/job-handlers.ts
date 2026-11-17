import type { HandlerContext } from "../../catalog/server/http.ts";
import type { Outcome } from "../../catalog/server/mutation.ts";
import { stateConflict } from "../../kernel/errors.ts";
import { advanceJobStage, claimOrResumeJob, completeJob, renewJobLease } from "../jobs.ts";
import type { JobAdvanceBody, JobClaimBody, JobCompleteBody, JobRenewBody } from "../job-body.ts";
import { requestIdentity, scopedPermission, verifyAdminScope, type AdminIdentity } from "../permissions.ts";
import type { JobCheckpoint, JobIdentity } from "../ports/jobs.ts";
import { createSqlJobStore, storedJobActor } from "./jobs-repo.ts";

const LEASE_MS = 60_000;

/** A claim names its environment; advance and complete act in the credential's own. */
function identityOf(context: HandlerContext<unknown, unknown, { draft: boolean; environment?: "preview" | "prod" }>, environment?: "preview" | "prod"): AdminIdentity {
  const identity = requestIdentity(context.deps, context.actor);
  const kind = context.body.draft ? "catalog:write" : "catalog:publish";
  verifyAdminScope(identity, scopedPermission(kind, identity.environment), environment ?? identity.environment);
  return identity;
}

function publicClaim(result: Awaited<ReturnType<typeof claimOrResumeJob>>) {
  if (result.status === "conflict") throw stateConflict("This idempotency key was used for a different bundle.");
  if (result.status === "acquired") return { status: result.status, jobId: result.job.jobId, token: result.lease.token, stage: result.job.stage, expiresAt: result.lease.expiresAt, leaseMs: LEASE_MS };
  return { status: result.status, jobId: result.job.jobId, stage: result.job.stage };
}

export function claimJob(context: HandlerContext<unknown, unknown, JobClaimBody>): Promise<Outcome> {
  const actor = identityOf(context, context.body.environment);
  const identity: JobIdentity = { actorId: actor.actorId, environment: context.body.environment, idempotencyKey: context.body.idempotencyKey, bundleSha256: context.body.bundleSha256 };
  return context.mutate(async (tx) => {
    const store = createSqlJobStore(context.deps.pool(), { db: tx, ids: () => context.deps.uuid().toLowerCase() });
    const data = publicClaim(await claimOrResumeJob(store, identity, LEASE_MS));
    await tx.audit({ action: "job.claim", entityKind: "job", entityId: "jobId" in data ? data.jobId : identity.idempotencyKey, after: data });
    return { data };
  });
}

async function jobActor(context: HandlerContext<{ id: string }, unknown, { draft: boolean }>, fallback: string): Promise<string> {
  return await storedJobActor(context.db, context.params.id) ?? fallback;
}

/** Heartbeat for a worker that still holds its lease (ship renews before it lapses). */
export function renewJob(context: HandlerContext<{ id: string }, unknown, JobRenewBody>): Promise<Outcome> {
  const { environment } = identityOf(context);
  return context.mutate(async (tx) => {
    const lease = {
      identity: { actorId: await jobActor(context, context.actor), environment, idempotencyKey: "route", bundleSha256: "a".repeat(64) },
      jobId: context.params.id, token: context.body.token, expiresAt: "",
    };
    const store = createSqlJobStore(context.deps.pool(), { db: tx });
    const renewed = await renewJobLease(store, lease, LEASE_MS);
    const data = { jobId: context.params.id, token: renewed.token, expiresAt: renewed.expiresAt, leaseMs: LEASE_MS };
    await tx.audit({ action: "job.renew", entityKind: "job", entityId: context.params.id, after: data });
    return { data };
  });
}

export function advanceJob(context: HandlerContext<{ id: string }, unknown, JobAdvanceBody>): Promise<Outcome> {
  const { environment } = identityOf(context);
  const checkpoint: JobCheckpoint = {
    stage: context.body.checkpoint.stage,
    ...(context.body.checkpoint.draft === undefined ? { draft: context.body.draft } : { draft: context.body.checkpoint.draft }),
    ...(context.body.checkpoint.uploads ? { uploads: context.body.checkpoint.uploads } : {}),
    ...(context.body.checkpoint.applyReceipt ? { applyReceipt: context.body.checkpoint.applyReceipt } : {}),
    ...(context.body.checkpoint.release ? { release: context.body.checkpoint.release } : {}),
    ...(context.body.checkpoint.verification ? { verification: context.body.checkpoint.verification } : {}),
  };
  return context.mutate(async (tx) => {
    const lease = {
      identity: { actorId: await jobActor(context, context.actor), environment, idempotencyKey: "route", bundleSha256: "a".repeat(64) },
      jobId: context.params.id, token: context.body.token, expiresAt: "",
    };
    const store = createSqlJobStore(context.deps.pool(), { db: tx });
    await advanceJobStage(store, lease, context.body.expected, checkpoint, context.body.draft);
    const data = { jobId: context.params.id, stage: checkpoint.stage };
    await tx.audit({ action: "job.advance", entityKind: "job", entityId: context.params.id, after: data });
    return { data };
  });
}

export function completeCatalogJob(context: HandlerContext<{ id: string }, unknown, JobCompleteBody>): Promise<Outcome> {
  const { environment } = identityOf(context);
  return context.mutate(async (tx) => {
    const lease = {
      identity: { actorId: await jobActor(context, context.actor), environment, idempotencyKey: "route", bundleSha256: "a".repeat(64) },
      jobId: context.params.id, token: context.body.token, expiresAt: "",
    };
    const store = createSqlJobStore(context.deps.pool(), { db: tx });
    await completeJob(store, lease, { stage: context.body.stage, ...(context.body.error ? { error: context.body.error } : {}) });
    const data = { jobId: context.params.id, stage: context.body.stage };
    await tx.audit({ action: "job.complete", entityKind: "job", entityId: context.params.id, after: data });
    return { data };
  });
}
