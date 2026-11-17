import { stateConflict } from "../../kernel/errors.ts";
import type {
  ClaimResult, DurableCatalogJob, JobCheckpoint, JobIdentity, JobLease, JobResult, JobStage, JobStorePort, JobTiming,
} from "../ports/jobs.ts";

export interface InMemoryJobOptions {
  readonly now: () => number;
  readonly ids?: () => string;
}

interface MutableJob {
  identity: JobIdentity;
  jobId: string;
  stage: JobStage;
  leaseToken: number;
  leaseUntil: string | null;
  attemptCount: number;
  checkpoint: JobCheckpoint | null;
  timings: JobTiming[];
  lastError: string | null;
  completed: boolean;
}

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

function keyOf(identity: JobIdentity): string {
  return `${identity.environment}\u0000${identity.actorId}\u0000${identity.idempotencyKey}`;
}

function leaseOf(job: MutableJob): JobLease {
  return { identity: clone(job.identity), jobId: job.jobId, token: job.leaseToken, expiresAt: job.leaseUntil ?? "" };
}

function view(job: MutableJob): DurableCatalogJob {
  return clone(job);
}

function live(job: MutableJob, now: number): boolean {
  return job.leaseUntil !== null && Date.parse(job.leaseUntil) > now;
}

function requireLease(job: MutableJob | undefined, lease: JobLease, now: number): MutableJob {
  const sameActor = job?.identity.actorId === lease.identity.actorId && job.identity.environment === lease.identity.environment;
  if (!job || !sameActor || job.leaseToken !== lease.token || job.jobId !== lease.jobId || !live(job, now)) {
    throw stateConflict("The job lease is no longer current.");
  }
  return job;
}

/** Same CAS and fencing as the SQL adapter. Clock and ids are injected; nothing is fetched. */
export function createInMemoryJobStore(options: InMemoryJobOptions): JobStorePort {
  const rows = new Map<string, MutableJob>();
  const byId = new Map<string, MutableJob>();
  let sequence = 0;
  const ids = options.ids ?? (() => { sequence += 1; return `job-${String(sequence)}`; });
  const at = () => new Date(options.now()).toISOString();

  return {
    claim(input, leaseMs) {
      const current = rows.get(keyOf(input));
      if (!current) {
        const job: MutableJob = {
          identity: clone(input), jobId: ids(), stage: "VALIDATED", leaseToken: 1,
          leaseUntil: new Date(options.now() + leaseMs).toISOString(), attemptCount: 1, checkpoint: null, timings: [], lastError: null, completed: false,
        };
        rows.set(keyOf(input), job);
        byId.set(job.jobId, job);
        return Promise.resolve({ status: "acquired", lease: leaseOf(job), job: view(job) } satisfies ClaimResult);
      }
      if (current.identity.bundleSha256 !== input.bundleSha256) return Promise.resolve({ status: "conflict" } satisfies ClaimResult);
      if (current.completed || current.stage === "VERIFIED") return Promise.resolve({ status: "completed", job: view(current) } satisfies ClaimResult);
      if (live(current, options.now())) return Promise.resolve({ status: "occupied", job: view(current) } satisfies ClaimResult);
      current.leaseToken += 1;
      current.attemptCount += 1;
      current.leaseUntil = new Date(options.now() + leaseMs).toISOString();
      return Promise.resolve({ status: "acquired", lease: leaseOf(current), job: view(current) } satisfies ClaimResult);
    },
    renew(lease, leaseMs) {
      return Promise.resolve().then(() => {
        const job = requireLease(byId.get(lease.jobId), lease, options.now());
        job.leaseUntil = new Date(options.now() + leaseMs).toISOString();
        return leaseOf(job);
      });
    },
    advance(lease, expected, next) {
      return Promise.resolve().then(() => {
        const job = requireLease(byId.get(lease.jobId), lease, options.now());
        if (job.stage !== expected) throw stateConflict(`Stage ${job.stage} is not ${expected}.`);
        job.stage = next.stage;
        job.checkpoint = clone(next);
        job.timings.push({ stage: next.stage, at: at() });
        job.completed = next.stage === "VERIFIED";
        if (job.completed) job.leaseUntil = null;
      });
    },
    complete(lease, result: JobResult) {
      return Promise.resolve().then(() => {
        const job = requireLease(byId.get(lease.jobId), lease, options.now());
        job.stage = result.stage;
        job.lastError = result.error ?? null;
        if (result.checkpoint) job.checkpoint = clone(result.checkpoint);
        job.timings.push({ stage: result.stage, at: at() });
        job.leaseUntil = null;
        job.completed = result.stage === "VERIFIED";
      });
    },
    get(identity) {
      const job = rows.get(keyOf(identity));
      return Promise.resolve(job ? view(job) : null);
    },
  };
}
