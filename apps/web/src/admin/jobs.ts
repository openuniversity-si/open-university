import { stateConflict } from "../kernel/errors.ts";
import {
  DRAFT_STAGES, PUBLISH_STAGES, type ClaimResult, type DurableCatalogJob, type JobCheckpoint, type JobIdentity, type JobLease,
  type JobResult, type JobStage, type JobStorePort,
} from "./ports/jobs.ts";

const LEASE_MIN_MS = 1_000;
const LEASE_MAX_MS = 15 * 60 * 1000;

export function nextJobStage(stage: JobStage, draft: boolean): JobStage | null {
  const path: readonly JobStage[] = draft ? DRAFT_STAGES : PUBLISH_STAGES;
  const index = path.indexOf(stage);
  if (index < 0) return null;
  return path[index + 1] ?? null;
}

export function assertJobTransition(current: JobStage, next: JobCheckpoint, draft: boolean): void {
  if (draft && next.stage === "PUBLISHED") throw stateConflict("A draft job does not publish.");
  const expected = nextJobStage(current, draft);
  if (expected !== next.stage) throw stateConflict(`Stage ${current} cannot move to ${next.stage}.`);
}

function leaseWindow(leaseMs: number): number {
  if (!Number.isInteger(leaseMs) || leaseMs < LEASE_MIN_MS || leaseMs > LEASE_MAX_MS) throw stateConflict("The job lease is outside 1 s to 15 min.");
  return leaseMs;
}

/** Claim a new execution or the expired one with the same actor, environment, key and hash. */
export async function claimOrResumeJob(store: JobStorePort, identity: JobIdentity, leaseMs: number): Promise<ClaimResult> {
  return store.claim(identity, leaseWindow(leaseMs));
}

/** Heartbeat: extend a lease the token still holds. A lapsed or superseded lease is refused (fencing). */
export async function renewJobLease(store: JobStorePort, lease: JobLease, leaseMs: number): Promise<JobLease> {
  return store.renew(lease, leaseWindow(leaseMs));
}

/** Persist the next checkpoint only when the lease token still owns the expected stage. */
export async function advanceJobStage(store: JobStorePort, lease: JobLease, expected: JobStage, next: JobCheckpoint, draft: boolean): Promise<void> {
  assertJobTransition(expected, next, draft);
  await store.advance(lease, expected, next);
}

export async function completeJob(store: JobStorePort, lease: JobLease, result: JobResult): Promise<void> {
  await store.complete(lease, result);
}

/** The stage whose effect still has to run. A confirmed upload resumes at apply, never by skipping it. */
export function pendingJobStage(job: DurableCatalogJob, draft: boolean): JobStage | null {
  if (job.completed || job.stage === "VERIFIED") return null;
  if (job.stage === "FAILED" || job.stage === "PAUSED") return nextJobStage(job.checkpoint?.stage ?? "VALIDATED", draft);
  return nextJobStage(job.stage, draft);
}
