import { describe, expect, it, vi } from "vitest";
import { AppError } from "../kernel/errors.ts";
import { ADMIN_ROUTE_SPECS } from "./route-specs.ts";
import { dispatchAdminRequest, multipartHash, type AdminHandler, type AdminJournal, type DispatchDeps } from "./http-dispatcher.ts";

function urlFor(scope: "catalog" | "media", path: string): string {
  const concrete = path.replace(":id", "course-1").replace(":n", "3");
  const base = scope === "catalog" ? "/api/admin/catalog" : "/api/admin/media";
  return `https://tower.test${base}${concrete === "/" ? "" : concrete}`;
}

function deps(handlers: Map<string, AdminHandler>, authorize: DispatchDeps["authorize"], journal?: AdminJournal): DispatchDeps {
  return { handlers, authorize, journal, uuid: () => "req-fixed" };
}

describe("admin HTTP dispatcher", () => {
  it("gives every spec an enveloped response with requestId and no-store", async () => {
    const seen: string[] = [];
    const handlers = new Map(ADMIN_ROUTE_SPECS.map((spec) => [spec.handlerId, () => { seen.push(spec.handlerId); return Promise.resolve({ data: { id: spec.handlerId } }); }]));
    const authorize = vi.fn(() => Promise.resolve(null));
    for (const spec of ADMIN_ROUTE_SPECS) {
      const headers = new Headers({ authorization: "Bearer secret", "x-request-id": "edge-1" });
      if (spec.idempotency === "required") headers.set("idempotency-key", "key-1");
      const init: RequestInit = { method: spec.method, headers };
      if (spec.body.kind === "json") init.body = "{}";
      if (spec.body.kind === "multipart") {
        const form = new FormData();
        form.set("file", new Blob([Uint8Array.from([1, 2, 3])]), "a.png");
        init.body = form;
      }
      const response = await dispatchAdminRequest(new Request(urlFor(spec.scope, spec.path), init), deps(handlers, authorize));
      expect(response.headers.get("cache-control"), spec.handlerId).toBe("no-store");
      expect(response.headers.get("x-request-id"), spec.handlerId).toBe("edge-1");
      const body = await response.json() as { ok: boolean; requestId: string; error?: { code: string } };
      expect(body.requestId, spec.handlerId).toBe("edge-1");
      expect(typeof body.ok, spec.handlerId).toBe("boolean");
      if (!body.ok) expect(body.error?.code, spec.handlerId).toBeTruthy();
    }
    expect(authorize).toHaveBeenCalledTimes(ADMIN_ROUTE_SPECS.length);
    expect(seen.length).toBeGreaterThan(0);
  });

  it("refuses before reading the body", async () => {
    let read = false;
    const request = new Request("https://tower.test/api/admin/media", { method: "POST", body: "secret-body", headers: { "content-type": "text/plain" } });
    const mark = () => { read = true; return Promise.reject(new Error("body")); };
    request.formData = mark;
    request.arrayBuffer = mark;
    request.json = mark;
    const handlers = new Map<string, AdminHandler>([["media:POST /", () => Promise.reject(new Error("handler"))]]);
    const response = await dispatchAdminRequest(request, deps(handlers, () => Promise.resolve(Response.json({ ok: false, error: { code: "unauthorized", message: "Unauthorized." }, requestId: "r" }, { status: 401, headers: { "cache-control": "no-store", "retry-after": "7" } }))));
    expect(response.status).toBe(401);
    expect(response.headers.get("retry-after")).toBe("7");
    expect(read).toBe(false);
  });

  it("replays a stored response and refuses a mismatched key without calling the handler", async () => {
    const calls: string[] = [];
    const journal: AdminJournal = {
      prepare: (claim) => Promise.resolve(claim.key === "again" ? { replay: { status: 200, data: { sha256: "abc" } } } : {}),
      finish: (claim) => { calls.push(`finish:${claim.key}`); return Promise.resolve(); },
    };
    const handlers = new Map<string, AdminHandler>([["media:POST /rollback", () => { calls.push("handler"); return Promise.resolve({ data: { version: 1 } }); }]]);
    const rollback = JSON.stringify({ owner: "course", ownerId: "course-1", kind: "poster_9x16", version: 1 });
    const headers = { authorization: "Bearer s", "idempotency-key": "again", "content-type": "application/json" };
    const replay = await dispatchAdminRequest(new Request("https://tower.test/api/admin/media/rollback", { method: "POST", headers, body: rollback }), deps(handlers, () => Promise.resolve(null), journal));
    expect(replay.headers.get("idempotent-replay")).toBe("true");
    expect(await replay.json()).toMatchObject({ ok: true, data: { sha256: "abc" } });
    journal.prepare = () => Promise.reject(new AppError("idempotency_mismatch", "different request"));
    const mismatch = await dispatchAdminRequest(new Request("https://tower.test/api/admin/media/rollback", { method: "POST", headers: { ...headers, "idempotency-key": "other" }, body: rollback }), deps(handlers, () => Promise.resolve(null), journal));
    expect(mismatch.status).toBe(422);
    expect(calls).toEqual([]);
  });

  it("does not record a journal success when rollback fails", async () => {
    const finish = vi.fn();
    const journal: AdminJournal = { prepare: () => Promise.resolve({}), finish };
    const handlers = new Map<string, AdminHandler>([["media:POST /rollback", () => Promise.reject(new AppError("not_found", "Version not found."))]]);
    const response = await dispatchAdminRequest(new Request("https://tower.test/api/admin/media/rollback", {
      method: "POST", headers: { "idempotency-key": "roll-1", "content-type": "application/json" }, body: JSON.stringify({ owner: "course", ownerId: "course-1", kind: "poster_9x16", version: 1 }),
    }), deps(handlers, () => Promise.resolve(null), journal));
    expect(response.status).toBe(404);
    expect(finish).not.toHaveBeenCalled();
  });

  it("hashes multipart bytes and fields without the boundary", () => {
    const bytes = Uint8Array.from([9, 8, 7]);
    expect(multipartHash(bytes, { b: "2", a: "1" })).toBe(multipartHash(bytes, { a: "1", b: "2" }));
    expect(multipartHash(bytes, { a: "1" })).not.toBe(multipartHash(bytes, { a: "2" }));
  });

  it("answers 405 with Allow and 404 for an unknown path", async () => {
    const response = await dispatchAdminRequest(new Request("https://tower.test/api/admin/media/check", { method: "GET" }), deps(new Map(), () => Promise.resolve(null)));
    expect(response.status).toBe(405);
    expect(response.headers.get("allow")).toBe("POST");
    const missing = await dispatchAdminRequest(new Request("https://tower.test/api/admin/media/nope"), deps(new Map(), () => Promise.resolve(null)));
    expect(missing.status).toBe(404);
  });
});
