/** Durable ship progress. The port has no database, pool or SDK. */

export const JOB_STAGES = [
  "VALIDATED", "MEDIA_CHECKED", "MEDIA_UPLOADED", "BUNDLE_APPLIED", "PUBLISHED", "DRAFT_READY", "VERIFIED", "FAILED", "PAUSED",
] as const;
export type JobStage = (typeof JOB_STAGES)[number];

export const PUBLISH_STAGES = ["VALIDATED", "MEDIA_CHECKED", "MEDIA_UPLOADED", "BUNDLE_APPLIED", "PUBLISHED", "VERIFIED"] as const;
export const DRAFT_STAGES = ["VALIDATED", "MEDIA_CHECKED", "MEDIA_UPLOADED", "BUNDLE_APPLIED", "DRAFT_READY", "VERIFIED"] as const;

export type AdminEnvironment = "preview" | "prod";

export interface JobIdentity {
  readonly actorId: string;
  readonly environment: AdminEnvironment;
  readonly idempotencyKey: string;
  readonly bundleSha256: string;
}

export interface JobLease {
  readonly identity: JobIdentity;
  readonly jobId: string;
  readonly token: number;
  readonly expiresAt: string;
}

export interface JobCheckpoint {
  readonly stage: JobStage;
  readonly draft?: boolean;
  readonly uploads?: readonly { readonly sha256: string; readonly objectKey: string }[];
  readonly applyReceipt?: { readonly bundleSha256: string; readonly applied: boolean };
  readonly release?: { readonly number: number; readonly hash: string };
  readonly verification?: { readonly ok: boolean; readonly reason?: string };
}

export interface JobTiming { readonly stage: JobStage; readonly at: string }

export interface DurableCatalogJob {
  readonly identity: JobIdentity;
  readonly jobId: string;
  readonly stage: JobStage;
  readonly leaseToken: number;
  readonly leaseUntil: string | null;
  readonly attemptCount: number;
  readonly checkpoint: JobCheckpoint | null;
  readonly timings: readonly JobTiming[];
  readonly lastError: string | null;
  readonly completed: boolean;
}

export type ClaimResult =
  | { readonly status: "acquired"; readonly lease: JobLease; readonly job: DurableCatalogJob }
  | { readonly status: "occupied"; readonly job: DurableCatalogJob }
  | { readonly status: "completed"; readonly job: DurableCatalogJob }
  | { readonly status: "conflict" };

export interface JobResult {
  readonly stage: "VERIFIED" | "FAILED" | "PAUSED";
  readonly error?: string;
  readonly checkpoint?: JobCheckpoint;
}

export interface JobStorePort {
  claim(input: JobIdentity, leaseMs: number): Promise<ClaimResult>;
  renew(lease: JobLease, leaseMs: number): Promise<JobLease>;
  advance(lease: JobLease, expected: JobStage, next: JobCheckpoint): Promise<void>;
  complete(lease: JobLease, result: JobResult): Promise<void>;
  get(identity: JobIdentity): Promise<DurableCatalogJob | null>;
}
