import { describe, expect, it } from "vitest";
import { assertJobTransition, pendingJobStage } from "./jobs.ts";
import { createInMemoryJobStore } from "./testing/in-memory-jobs.ts";
import { jobsContract } from "./testing/jobs-contract.ts";
import type { DurableCatalogJob } from "./ports/jobs.ts";

describe("job store contract", () => {
  const cases = jobsContract(createInMemoryJobStore({ now: () => 0 }), { now: 0 });
  it.each(cases.map((entry) => entry.id))("%s", async (id) => {
    const clock = { now: 0 };
    const store = createInMemoryJobStore({ now: () => clock.now });
    const entry = jobsContract(store, clock).find((item) => item.id === id);
    if (!entry) throw new Error(id);
    await entry.run();
  });
});

describe("job stages", () => {
  it("refuses to publish a draft and resumes apply after an upload", () => {
    expect(() => { assertJobTransition("BUNDLE_APPLIED", { stage: "PUBLISHED" }, true); }).toThrow(/does not publish/);
    const job: DurableCatalogJob = {
      identity: { actorId: "a", environment: "preview", idempotencyKey: "k", bundleSha256: "a".repeat(64) },
      jobId: "job-1", stage: "MEDIA_UPLOADED", leaseToken: 1, leaseUntil: null, attemptCount: 1,
      checkpoint: { stage: "MEDIA_UPLOADED", uploads: [] }, timings: [], lastError: null, completed: false,
    };
    expect(pendingJobStage(job, false)).toBe("BUNDLE_APPLIED");
    expect(pendingJobStage({ ...job, stage: "PUBLISHED", checkpoint: { stage: "PUBLISHED" } }, false)).toBe("VERIFIED");
  });
});
