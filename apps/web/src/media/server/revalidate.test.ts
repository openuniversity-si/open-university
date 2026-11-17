import { afterEach, describe, expect, it, vi } from "vitest";

const { appPool } = vi.hoisted(() => ({ appPool: vi.fn() }));
vi.mock("../../platform/db/pool.ts", () => ({ appPool }));

import { handleMediaRevalidation } from "./revalidate.ts";
import type { Queryable } from "../../platform/db/uow.ts";
const secret = "fixture-secret";
function request(body: string, auth = `Bearer ${secret}`) {
  return new Request("https://example.invalid/api/media/revalidate", { method: "POST", headers: { authorization: auth }, body });
}
afterEach(() => { appPool.mockReset(); });
describe("protected media revalidation", () => {
  it.each(["", "Bearer wrong", "Basic fixture-secret"])("rejects %s without invalidating tags", async (auth) => {
    const tags: string[] = [];
    expect((await handleMediaRevalidation(request("{}", auth), secret, (plan) => tags.push(...plan.tags))).status).toBe(401);
    expect(tags).toEqual([]);
  });
  it("fails closed without a configured secret", async () => {
    expect((await handleMediaRevalidation(request("{}"), undefined, () => { throw new Error("Must not run"); })).status).toBe(503);
  });
  it.each(["not-json", '{"courseId":"../private"}', '{"secret":"anything"}'])("rejects malformed bodies", async (body) => {
    expect((await handleMediaRevalidation(request(body), secret, () => { throw new Error("Must not run"); })).status).toBe(400);
  });
  it("expires one published course's media reads, or every media read without a course", async () => {
    const plans: unknown[] = [];
    expect((await handleMediaRevalidation(request('{"courseId":"course-3"}'), secret, (plan) => plans.push(plan), (courseId) => Promise.resolve({ courseId, published: true }))).status).toBe(200);
    expect((await handleMediaRevalidation(request("{}"), secret, (plan) => plans.push(plan))).status).toBe(200);
    expect(plans).toEqual([{ tags: ["media:course:course-3", "media:courses"], paths: [] }, { tags: ["media"], paths: [] }]);
  });
  it("expires nothing for direct writes to unpublished courses", async () => {
    const plans: unknown[] = [];
    const response = await handleMediaRevalidation(request('{"courseId":"course-3","kind":"poster_9x16"}'), secret, (plan) => { plans.push(plan); }, (courseId) => Promise.resolve({ courseId, published: false }));
    expect(response.status).toBe(200);
    expect(plans).toEqual([]);
  });
  it("supplies the app pool when the caller omits the database", async () => {
    const query = vi.fn().mockResolvedValue({ rows: [] });
    appPool.mockReturnValue({ query });
    let seen: (() => Queryable) | undefined;
    const response = await handleMediaRevalidation(request('{"courseId":"course-3"}'), secret, () => undefined, (courseId, db) => {
      seen = db;
      return db().query("select 1").then(() => ({ courseId, published: true }));
    });
    expect(response.status).toBe(200);
    expect(seen).toBe(appPool);
    expect(query).toHaveBeenCalledOnce();
  });
  it("uses an injected database instead of the app pool", async () => {
    const query = vi.fn().mockResolvedValue({ rows: [] });
    const fake = (): Queryable => ({ query });
    const response = await handleMediaRevalidation(request('{"courseId":"course-3"}'), secret, () => undefined, (courseId, db) => db().query("select 1").then(() => ({ courseId, published: false })), fake);
    expect(response.status).toBe(200);
    expect(appPool).not.toHaveBeenCalled();
    expect(query).toHaveBeenCalledOnce();
  });
});
