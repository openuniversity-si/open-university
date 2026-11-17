import { expect } from "vitest";
import type { JobIdentity, JobStorePort } from "../ports/jobs.ts";

export interface JobsContractClock { now: number }

const HASH_A = "a".repeat(64);
const HASH_B = "b".repeat(64);

function identity(hash = HASH_A, actorId = "actor-a"): JobIdentity {
  return { actorId, environment: "preview", idempotencyKey: "ship-1", bundleSha256: hash };
}

/** Shared cases. The caller owns the clock the adapter reads. */
export function jobsContract(store: JobStorePort, clock: JobsContractClock): { readonly id: string; readonly run: () => Promise<void> }[] {
  return [
    { id: "admin.job.occupied", run: async () => {
      const first = await store.claim(identity(), 5_000);
      const second = await store.claim(identity(), 5_000);
      expect(first.status).toBe("acquired");
      expect(second.status).toBe("occupied");
      if (second.status === "occupied") expect(second.job.leaseToken).toBe(1);
    } },
    { id: "admin.job.expired", run: async () => {
      const first = await store.claim(identity(), 1_000);
      clock.now += 1_000;
      const second = await store.claim(identity(), 1_000);
      expect(first.status).toBe("acquired");
      expect(second.status).toBe("acquired");
      if (first.status === "acquired" && second.status === "acquired") expect(second.lease.token).toBe(first.lease.token + 1);
    } },
    { id: "admin.job.heartbeat", run: async () => {
      const claimed = await store.claim(identity(), 1_000);
      if (claimed.status !== "acquired") throw new Error("expected a lease");
      const renewed = await store.renew(claimed.lease, 5_000);
      clock.now += 1_000;
      await store.advance(renewed, "VALIDATED", { stage: "MEDIA_CHECKED", uploads: [] });
      expect((await store.get(identity()))?.stage).toBe("MEDIA_CHECKED");
    } },
    { id: "admin.job.fencing", run: async () => {
      const workerA = await store.claim(identity(), 1_000);
      clock.now += 1_000;
      const workerB = await store.claim(identity(), 5_000);
      if (workerA.status !== "acquired" || workerB.status !== "acquired") throw new Error("expected both claims");
      await expect(store.advance(workerA.lease, "VALIDATED", { stage: "MEDIA_CHECKED" })).rejects.toThrow(/lease/i);
      await store.advance(workerB.lease, "VALIDATED", { stage: "MEDIA_CHECKED" });
      expect((await store.get(identity()))?.stage).toBe("MEDIA_CHECKED");
    } },
    { id: "admin.job.hash", run: async () => {
      await store.claim(identity(HASH_A), 5_000);
      const conflict = await store.claim(identity(HASH_B), 5_000);
      expect(conflict.status).toBe("conflict");
      expect((await store.get(identity(HASH_A)))?.identity.bundleSha256).toBe(HASH_A);
      expect(await store.get({ ...identity(HASH_A), actorId: "actor-b" })).toBeNull();
    } },
    { id: "admin.job.cas", run: async () => {
      const claimed = await store.claim(identity(), 5_000);
      if (claimed.status !== "acquired") throw new Error("expected a lease");
      await expect(store.advance(claimed.lease, "MEDIA_CHECKED", { stage: "MEDIA_UPLOADED" })).rejects.toThrow(/MEDIA_CHECKED/);
      expect((await store.get(identity()))?.stage).toBe("VALIDATED");
      await store.advance(claimed.lease, "VALIDATED", { stage: "MEDIA_CHECKED", uploads: [{ sha256: HASH_A, objectKey: "covers/a" }] });
      const job = await store.get(identity());
      expect(job?.checkpoint?.uploads?.[0]?.objectKey).toBe("covers/a");
    } },
  ];
}
