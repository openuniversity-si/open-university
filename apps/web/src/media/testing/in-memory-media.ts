import { createInMemoryUnitOfWork, type InMemoryUnitOfWork } from "../../platform/db/testing/in-memory-uow.ts";
import type { Queryable, UnitOfWork } from "../../platform/db/uow.ts";
import type { MediaCommandsPort } from "../ports/commands.ts";
import type { MediaObjectStore } from "../ports/storage.ts";
import type { MediaBench } from "./media-contract.ts";

interface StoredObject { readonly bytes: Uint8Array }
interface PendingRow {
  readonly key: string;
  readonly owner: string;
  readonly ownerId: string;
  readonly courseId: string;
  readonly requestId: string;
  attempts: number;
  lastError: string | null;
}
interface MediaState {
  objects: Map<string, StoredObject>;
  pending: PendingRow[];
}

function copy(bytes: Uint8Array): Uint8Array {
  return new Uint8Array(bytes);
}

/**
 * Content-addressed bytes plus the deletion queue.
 * Bytes are copied on the way in and out. `query` is never called.
 */
export function createInMemoryMedia(host = "media.test", uow: InMemoryUnitOfWork = createInMemoryUnitOfWork()): MediaBench {
  let state: MediaState = { objects: new Map(), pending: [] };
  let closed = false;
  let failDelete = false;
  const participant = {
    snapshot: () => structuredClone(state),
    restore(snapshot: MediaState) { state = snapshot; },
  };
  uow.register(participant);

  function assertTx(tx: Queryable): asserts tx is UnitOfWork {
    if (!uow.owns(tx as UnitOfWork)) throw new Error("Transaction is not the in-memory unit of work.");
  }
  function shaOf(pathname: string): string | null {
    const match = /^m\/([a-f0-9]{64})\.(?:jpg|png|webp|avif)$/.exec(pathname);
    return match?.[1] ?? null;
  }

  const store: MediaObjectStore = {
    publicUrl(pathname) { return `https://${host}/${pathname}`; },
    head(pathname) {
      const object = state.objects.get(pathname);
      return Promise.resolve(object ? { size: object.bytes.byteLength } : null);
    },
    get(pathname) {
      const object = state.objects.get(pathname);
      return Promise.resolve(object ? Buffer.from(copy(object.bytes)) : null);
    },
    put(pathname, bytes) {
      if (state.objects.has(pathname)) return Promise.resolve("exists");
      state.objects.set(pathname, { bytes: copy(bytes) });
      return Promise.resolve("created");
    },
    copy(source, target) {
      const object = state.objects.get(source);
      if (!object) return Promise.reject(new Error(`Object ${source} not found.`));
      if (state.objects.has(target)) return Promise.resolve("exists");
      state.objects.set(target, { bytes: copy(object.bytes) });
      return Promise.resolve("created");
    },
    delete(pathname) {
      if (failDelete) {
        failDelete = false;
        return Promise.reject(new Error("delete failed"));
      }
      state.objects.delete(pathname);
      return Promise.resolve();
    },
  };

  function commandsIn(tx: UnitOfWork): MediaCommandsPort {
    assertTx(tx);
    return {
      covers() {
        assertTx(tx);
        return Promise.resolve([]);
      },
      validateObject(cover) {
        assertTx(tx);
        for (const [pathname] of state.objects) if (shaOf(pathname) === cover.sha256) return Promise.resolve(cover.sha256);
        return Promise.resolve(null);
      },
      queuePending(input) {
        assertTx(tx);
        for (const key of input.keys) {
          if (state.pending.some((row) => row.key === key)) continue;
          const described = input.rows.find((row) => row.pathname === key);
          state.pending.push({
            key, owner: described?.owner ?? "course", ownerId: described?.ownerId ?? input.courseId, courseId: input.courseId,
            requestId: input.requestId, attempts: 0, lastError: null,
          });
        }
        return Promise.resolve();
      },
      usedKeys(keys) {
        assertTx(tx);
        return Promise.resolve(keys.filter((key) => state.objects.has(key)));
      },
      diagnose(catalog) {
        assertTx(tx);
        const findings: { code: string; count: number; sample: readonly unknown[] }[] = [];
        if (state.pending.length > 0) findings.push({ code: "r2.pending", count: state.pending.length, sample: state.pending.slice(0, 10).map((row) => row.key) });
        const broken = catalog.covers.filter((cover) => cover.sha256 !== null && ![...state.objects.keys()].some((pathname) => shaOf(pathname) === cover.sha256));
        if (broken.length > 0) findings.push({ code: "media.registry.missing", count: broken.length, sample: broken.slice(0, 10).map((cover) => cover.id) });
        return Promise.resolve(findings);
      },
      pending(filter) {
        assertTx(tx);
        return Promise.resolve(state.pending.filter((row) => {
          if (filter.courseId) return row.courseId === filter.courseId;
          if (filter.lessonId) return row.owner === "lesson" && row.ownerId === filter.lessonId;
          return false;
        }).map((row) => row.key).sort());
      },
      async drain(bucket, filter, checkedKeys) {
        assertTx(tx);
        const deleted: string[] = [];
        const pending: string[] = [];
        const rows = state.pending.filter((row) => checkedKeys.includes(row.key) && ("courseId" in filter ? row.courseId === filter.courseId : row.owner === "lesson" && row.ownerId === filter.lessonId));
        for (const row of rows) {
          try {
            await bucket().delete(row.key);
            state.pending = state.pending.filter((item) => item.key !== row.key);
            deleted.push(row.key);
          } catch (error) {
            row.attempts += 1;
            row.lastError = error instanceof Error ? error.message : "delete failed";
            pending.push(row.key);
          }
        }
        return { deleted, pending };
      },
    };
  }

  return {
    port: store,
    commandsIn,
    reset() {
      if (closed) throw new Error("The in-memory media store is closed.");
      state = { objects: new Map(), pending: [] };
      failDelete = false;
      return Promise.resolve();
    },
    dispose() { closed = true; return Promise.resolve(); },
    pending() { return Promise.resolve(state.pending.map((row) => row.key).sort()); },
    failNextDelete() { failDelete = true; },
    transaction(work) {
      if (closed) return Promise.reject(new Error("The in-memory media store is closed."));
      return uow.run(work);
    },
  };
}
