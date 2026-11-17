import { describe, expect, it } from "vitest";
import type { HandlerContext } from "../catalog/server/http.ts";
import { dispatchAdminRequest } from "./http-dispatcher.ts";
import { claimJob } from "./server/job-handlers.ts";
import { resetLifecyclePreview } from "./server/lifecycle-handlers.ts";
import { operatorIdentity, requestIdentity, verifyAdminScope, type AdminIdentity } from "./permissions.ts";
import type { JobClaimBody } from "./job-body.ts";

const preview: AdminIdentity = { actorId: "actor-a", environment: "preview", scopes: ["catalog:write:preview", "media:write"] };
const prod: AdminIdentity = { actorId: "actor-a", environment: "prod", scopes: ["catalog:write:prod", "catalog:publish:prod", "media:write", "media:gc:execute"] };

describe("admin scope", () => {
  it("denies by default, keeps a preview key off prod, and does not treat draft as publish", () => {
    expect(() => { verifyAdminScope(preview, "catalog:publish:prod", "prod"); }).toThrow(/credential/);
    expect(() => { verifyAdminScope(preview, "catalog:write:preview", "prod"); }).toThrow(/credential/);
    expect(() => { verifyAdminScope({ ...preview, scopes: [] }, "catalog:write:preview", "preview"); }).toThrow(/credential/);
    expect(() => { verifyAdminScope(preview, "catalog:publish:preview", "preview"); }).toThrow(/credential/);
    expect(() => { verifyAdminScope(prod, "media:gc:execute", "prod"); }).not.toThrow();
    expect(() => { verifyAdminScope(preview, "catalog:write:preview", "preview"); }).not.toThrow();
  });

  it("rejects a preview publish through the dispatcher before the handler runs", async () => {
    let called = false;
    const response = await dispatchAdminRequest(new Request("https://tower.test/api/admin/catalog/courses/course-1/publish", {
      method: "POST", headers: { "content-type": "application/json", "idempotency-key": "key-1" }, body: "{}",
    }), {
      handlers: new Map([["catalog:POST /courses/:id/publish", () => { called = true; return Promise.resolve({ data: { id: "course-1" } }); }]]),
      authorize: () => Promise.resolve(null),
      identity: () => preview,
      uuid: () => "req-fixed",
    });
    expect(response.status).toBe(403);
    expect(called).toBe(false);
    const body = await response.json() as { error?: { message?: string } };
    expect(body.error?.message ?? "").not.toMatch(/secret|Bearer|token/i);
  });

  it("refuses a prod claim before opening the database", async () => {
    const context = {
      params: {}, query: {}, actor: "actor-a", requestId: "req",
      body: { idempotencyKey: "ship-1", bundleSha256: "a".repeat(64), environment: "prod", draft: false } satisfies JobClaimBody,
      deps: { pool: () => { throw new Error("database opened"); }, uuid: () => "job-1", adminIdentity: preview },
    } as unknown as HandlerContext<unknown, unknown, JobClaimBody>;
    await expect((async () => claimJob(context))()).rejects.toThrow(/credential/);
  });

  it("binds the deployment's admin key to that deployment's environment", () => {
    expect(requestIdentity({ environment: "prod" }, "daniel")).toEqual(operatorIdentity("daniel", "prod"));
    expect(requestIdentity({ environment: "prod", adminIdentity: preview }, "daniel")).toBe(preview);
    expect(requestIdentity({}, "daniel").environment).toBe("preview");
    const operator = operatorIdentity("daniel", "prod");
    expect(() => { verifyAdminScope(operator, "catalog:publish:prod", "prod"); }).not.toThrow();
    expect(() => { verifyAdminScope(operator, "catalog:write:preview", "preview"); }).toThrow(/credential/);
  });

  function claimContext(environment: "preview" | "prod", deployment: "preview" | "prod") {
    return {
      params: {}, query: {}, actor: "daniel", requestId: "req",
      body: { idempotencyKey: "ship-1", bundleSha256: "a".repeat(64), environment, draft: false } satisfies JobClaimBody,
      deps: { pool: () => { throw new Error("database opened"); }, uuid: () => "job-1", environment: deployment },
      mutate: () => Promise.reject(new Error("database opened")),
    } as unknown as HandlerContext<unknown, unknown, JobClaimBody>;
  }

  it("lets a production deployment claim a prod job and refuses a preview claim there", async () => {
    // Past the scope check, the claim opens the database: that is the error a prod claim must reach.
    await expect((async () => claimJob(claimContext("prod", "prod")))()).rejects.toThrow("database opened");
    await expect((async () => claimJob(claimContext("preview", "prod")))()).rejects.toThrow(/credential/);
    await expect((async () => claimJob(claimContext("prod", "preview")))()).rejects.toThrow(/credential/);
  });

  it("never runs a preview reset on a production deployment", async () => {
    const context = {
      params: {}, query: {}, actor: "daniel", requestId: "req", body: { dryRun: true },
      deps: { pool: () => { throw new Error("database opened"); }, environment: "prod" },
      db: { query: () => Promise.reject(new Error("database opened")) },
    } as unknown as Parameters<typeof resetLifecyclePreview>[0];
    await expect((async () => resetLifecyclePreview(context))()).rejects.toThrow("Production preview reset is rejected.");
  });
});
