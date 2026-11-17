import { describe, expect, it, vi } from "vitest";
import { createAdminRateLimiter } from "../../admin/auth.ts";
import { LIMITS } from "../../kernel/limits.ts";
import { codeLimits, nextStoredRevision, parseDocument, type ConfigKind } from "../domain/documents.ts";
import type { ConfigDocuments, ConfigRevision } from "../ports/documents.ts";
import { handleConfigAdmin, type ConfigAdminDeps } from "./admin.ts";

const secret = "test-admin-secret";

function memory(): ConfigDocuments {
  const rows = new Map<ConfigKind, ConfigRevision[]>();
  return {
    read(kind) {
      const list = rows.get(kind) ?? [];
      return Promise.resolve(list[list.length - 1] ?? null);
    },
    history(kind) {
      return Promise.resolve([...(rows.get(kind) ?? [])]);
    },
    commit(input) {
      const list = rows.get(input.kind) ?? [];
      const seen = list[list.length - 1]?.revision ?? 0;
      const revision = nextStoredRevision(seen, input.expectedRevision);
      const row: ConfigRevision = {
        kind: input.kind,
        revision,
        body: parseDocument(input.kind, input.body),
        actor: input.actor,
        note: input.note,
        at: "2026-10-25T00:00:00.000Z",
      };
      rows.set(input.kind, [...list, row]);
      return Promise.resolve(row);
    },
  };
}

function deps(documents: ConfigDocuments, options?: { readonly unconfigured?: boolean; readonly invalidate?: (kind: ConfigKind) => void }): ConfigAdminDeps {
  return {
    secret: options?.unconfigured === true ? undefined : secret,
    limiter: createAdminRateLimiter({ requests: 100, failures: 20 }),
    documents,
    invalidate: options?.invalidate,
  };
}

function call(documents: ConfigDocuments, method: string, path: string, body?: unknown, invalidate?: (kind: ConfigKind) => void) {
  return handleConfigAdmin(new Request(`https://open.university${path}`, {
    method,
    headers: { authorization: `Bearer ${secret}`, "content-type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  }), deps(documents, { invalidate }));
}

describe("configuration admin API", () => {
  it("refuses a request without the catalog admin secret", async () => {
    const documents = memory();
    const open = await handleConfigAdmin(new Request("https://open.university/api/admin/config/limits"), deps(documents, { unconfigured: true }));
    expect(open.status).toBe(503);
    const wrong = await handleConfigAdmin(new Request("https://open.university/api/admin/config/limits", {
      headers: { authorization: "Bearer wrong" },
    }), deps(documents));
    expect(wrong.status).toBe(401);
    expect(await documents.read("limits")).toBeNull();
  });

  it("appends a valid revision and refuses one outside the contract", async () => {
    const documents = memory();
    const invalidate = vi.fn();
    const created = await call(documents, "PUT", "/api/admin/config/limits", { expectedRevision: 0, document: codeLimits() }, invalidate);
    expect(created.status).toBe(200);
    expect(invalidate).toHaveBeenCalledWith("limits");
    await expect(created.json()).resolves.toMatchObject({ ok: true, data: { revision: 1, document: codeLimits() } });
    const rejected = await call(documents, "PUT", "/api/admin/config/limits", {
      expectedRevision: 1,
      document: { ...codeLimits(), courseTitle: LIMITS.courseTitle + 1 },
    });
    expect(rejected.status).toBe(400);
    await expect(documents.read("limits")).resolves.toMatchObject({ revision: 1 });
    const lowered = { ...codeLimits(), courseTitle: 10 };
    const updated = await call(documents, "PUT", "/api/admin/config/limits", { expectedRevision: 1, document: lowered, note: "lower" });
    expect(updated.status).toBe(200);
    const current = await call(documents, "GET", "/api/admin/config/limits");
    await expect(current.json()).resolves.toMatchObject({ ok: true, data: { revision: 2, source: "database", document: lowered } });
  });

  it("copies an older revision forward and keeps the history", async () => {
    const documents = memory();
    await call(documents, "PUT", "/api/admin/config/limits", { expectedRevision: 0, document: codeLimits() });
    const lowered = { ...codeLimits(), courseTitle: 10 };
    await call(documents, "PUT", "/api/admin/config/limits", { expectedRevision: 1, document: lowered });
    const invalidate = vi.fn();
    const rolled = await call(documents, "POST", "/api/admin/config/limits/rollback", { revision: 0, expectedRevision: 2 }, invalidate);
    expect(rolled.status).toBe(200);
    expect(invalidate).toHaveBeenCalledWith("limits");
    await expect(rolled.json()).resolves.toMatchObject({ ok: true, data: { revision: 3, document: codeLimits() } });
    const history = await call(documents, "GET", "/api/admin/config/limits/history");
    const payload = await history.json() as { data: { revisions: { revision: number }[] } };
    expect(payload.data.revisions.map((row) => row.revision)).toEqual([1, 2, 3]);
    expect(payload.data.revisions[1]).toMatchObject({ document: lowered });
  });
});
