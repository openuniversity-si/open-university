import { expect } from "vitest";
import type { UnitOfWork } from "../../platform/db/uow.ts";
import type { ContractSuite } from "../../platform/db/testing/uow-contract.ts";
import type { MediaCommandsPort } from "../ports/commands.ts";
import type { MediaObjectStore } from "../ports/storage.ts";

const sha = "ab".repeat(32);
const key = `m/${sha}.jpg`;
const url = `https://media.test/${key}`;

export interface MediaBench {
  readonly port: MediaObjectStore;
  commandsIn(tx: UnitOfWork): MediaCommandsPort;
  reset(): Promise<void>;
  dispose(): Promise<void>;
  pending(): Promise<readonly string[]>;
  failNextDelete(): void;
  transaction<T>(work: (tx: UnitOfWork) => Promise<T>): Promise<T>;
}

/** Object-store and deletion-queue cases. The store does not pretend to share a transaction with a remote bucket. */
export function mediaContract(): ContractSuite<MediaBench> {
  return {
    portId: "MediaObjectStore",
    cases: [
      { id: "media.object.put-get", async run(harness) {
        expect(await harness.port.put(key, Uint8Array.of(1, 2, 3))).toBe("created");
        const bytes = await harness.port.get(key);
        expect(bytes).toEqual(Buffer.from([1, 2, 3]));
        expect(await harness.port.head(key)).toEqual({ size: 3 });
        expect(harness.port.publicUrl(key)).toBe(url);
        expect(await harness.port.head("m/missing.jpg")).toBeNull();
        expect(await harness.port.get("m/missing.jpg")).toBeNull();
      } },
      { id: "media.object.overwrite", async run(harness) {
        await harness.port.put(key, Uint8Array.of(1));
        expect(await harness.port.put(key, Uint8Array.of(9, 9))).toBe("exists");
        expect(await harness.port.get(key)).toEqual(Buffer.from([1]));
      } },
      { id: "media.object.delete", async run(harness) {
        await harness.port.put(key, Uint8Array.of(1));
        await harness.port.delete(key);
        await harness.port.delete(key);
        expect(await harness.port.head(key)).toBeNull();
      } },
      { id: "media.object.copy", async run(harness) {
        const target = `m/${"cd".repeat(32)}.jpg`;
        await harness.port.put(key, Uint8Array.of(4, 5));
        expect(await harness.port.copy?.(key, target)).toBe("created");
        expect(await harness.port.copy?.(key, target)).toBe("exists");
        expect(await harness.port.get(target)).toEqual(Buffer.from([4, 5]));
      } },
      { id: "media.object.isolated", async run(harness) {
        await harness.port.put(key, Uint8Array.of(1, 2));
        const bytes = await harness.port.get(key);
        if (!bytes) throw new Error("missing object");
        bytes[0] = 9;
        expect(await harness.port.get(key)).toEqual(Buffer.from([1, 2]));
      } },
      { id: "media.queue.rollback", async run(harness) {
        await expect(harness.transaction(async (tx) => {
          await harness.commandsIn(tx).queuePending({ keys: [key], rows: [], courseId: "course-ready", requestId: "req" });
          throw new Error("no");
        })).rejects.toThrow("no");
        expect(await harness.pending()).toEqual([]);
      } },
      { id: "media.drain.failure", async run(harness) {
        await harness.transaction(async (tx) => {
          await harness.commandsIn(tx).queuePending({ keys: [key], rows: [{ pathname: key, owner: "course", ownerId: "course-ready" }], courseId: "course-ready", requestId: "req" });
        });
        harness.failNextDelete();
        const failed = await harness.transaction((tx) => harness.commandsIn(tx).drain(() => harness.port, { courseId: "course-ready" }, [key]));
        expect(failed).toEqual({ deleted: [], pending: [key] });
        expect(await harness.pending()).toEqual([key]);
      } },
      { id: "media.drain.idempotent", async run(harness) {
        await harness.transaction(async (tx) => {
          await harness.commandsIn(tx).queuePending({ keys: [key], rows: [], courseId: "course-ready", requestId: "req" });
        });
        const first = await harness.transaction((tx) => harness.commandsIn(tx).drain(() => harness.port, { courseId: "course-ready" }, [key]));
        expect(first.deleted).toEqual([key]);
        const second = await harness.transaction((tx) => harness.commandsIn(tx).drain(() => harness.port, { courseId: "course-ready" }, [key]));
        expect(second).toEqual({ deleted: [], pending: [] });
      } },
      { id: "media.validate.known", async run(harness) {
        await harness.port.put(key, Uint8Array.of(1));
        const known = await harness.transaction((tx) => harness.commandsIn(tx).validateObject({ sha256: sha, url, width: 16, height: 9 }));
        const missing = await harness.transaction((tx) => harness.commandsIn(tx).validateObject({ sha256: "cd".repeat(32), url, width: 16, height: 9 }));
        expect(known).toBe(sha);
        expect(missing).toBeNull();
      } },
      { id: "media.diagnose.pending", async run(harness) {
        await harness.transaction(async (tx) => {
          await harness.commandsIn(tx).queuePending({ keys: [key], rows: [], courseId: "course-ready", requestId: "req" });
        });
        const findings = await harness.transaction((tx) => harness.commandsIn(tx).diagnose({ courseIds: ["course-ready"], lessonIds: [], covers: [] }));
        expect(findings.map((finding) => finding.code)).toContain("r2.pending");
      } },
    ],
  };
}
