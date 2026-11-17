import { describe, expect, it } from "vitest";
import { AppError } from "../../kernel/errors.ts";
import { planSlugBatch, planSlugChange, type Redirect, type SlugBatchPlan, type SlugPlan } from "./lesson-slug.ts";

/** The redirect table after a plan, as the PATCH writes it (delete removed, flatten, upsert created). */
function apply(redirects: readonly Redirect[], plan: SlugPlan): Redirect[] {
  const removed = new Set(plan.removed.map((redirect) => redirect.from));
  return [
    ...redirects.filter((redirect) => !removed.has(redirect.from) && redirect.from !== plan.created.from)
      .map((redirect) => ({ from: redirect.from, to: redirect.to === plan.created.from ? plan.created.to : redirect.to })),
    plan.created,
  ].sort((a, b) => a.from.localeCompare(b.from));
}

/** Renames the lesson through `slugs` in order, from an empty table. */
function walk(slugs: readonly string[]): Redirect[] {
  let redirects: Redirect[] = [];
  for (let index = 1; index < slugs.length; index += 1) {
    redirects = apply(redirects, planSlugChange(redirects, `/c/alpha/${slugs[index - 1] ?? ""}`, `/c/alpha/${slugs[index] ?? ""}`));
  }
  return redirects;
}

describe("planSlugChange", () => {
  it("redirects the old path to the new one", () => {
    expect(planSlugChange([], "/c/alpha/a", "/c/alpha/b")).toEqual({ created: { from: "/c/alpha/a", to: "/c/alpha/b" }, flattened: [], removed: [] });
  });

  it("flattens chains: A→B then B→C leaves A→C and B→C", () => {
    const plan = planSlugChange([{ from: "/c/alpha/a", to: "/c/alpha/b" }], "/c/alpha/b", "/c/alpha/c");
    expect(plan.flattened).toEqual([{ from: "/c/alpha/a", before: "/c/alpha/b", after: "/c/alpha/c" }]);
    expect(walk(["a", "b", "c"])).toEqual([{ from: "/c/alpha/a", to: "/c/alpha/c" }, { from: "/c/alpha/b", to: "/c/alpha/c" }]);
  });

  it("going back to an earlier slug removes its redirect: no self-redirect, no cycle", () => {
    const plan = planSlugChange([{ from: "/c/alpha/a", to: "/c/alpha/b" }], "/c/alpha/b", "/c/alpha/a");
    expect(plan).toEqual({ created: { from: "/c/alpha/b", to: "/c/alpha/a" }, flattened: [], removed: [{ from: "/c/alpha/a", to: "/c/alpha/b" }] });
    expect(walk(["a", "b", "a"])).toEqual([{ from: "/c/alpha/b", to: "/c/alpha/a" }]);
    expect(walk(["a", "b", "c", "a"])).toEqual([{ from: "/c/alpha/b", to: "/c/alpha/a" }, { from: "/c/alpha/c", to: "/c/alpha/a" }]);
  });

  it("refuses a slug whose path is another page's old URL (409 slug_taken)", () => {
    const other = { from: "/c/alpha/x", to: "/c/alpha/elsewhere" };
    const error = (() => { try { planSlugChange([other], "/c/alpha/a", "/c/alpha/x"); } catch (caught) { return caught; } return null; })();
    expect(error).toBeInstanceOf(AppError);
    expect(error).toMatchObject({ code: "slug_taken", details: { redirect: other } });
  });

  it("any rename sequence ends with every old URL one hop from the current one, never at itself", () => {
    const sequences = [["a", "b", "c", "d"], ["a", "b", "a", "b", "c"], ["a", "b", "c", "b", "a", "d"], ["a", "b", "c", "a", "c"]];
    for (const slugs of sequences) {
      const current = `/c/alpha/${slugs.at(-1) ?? ""}`;
      const redirects = walk(slugs);
      const sources = new Set(redirects.map((redirect) => redirect.from));
      expect(redirects.every((redirect) => redirect.to === current), slugs.join("→")).toBe(true);
      expect(sources.has(current)).toBe(false);
      expect([...sources].sort()).toEqual([...new Set(slugs.slice(0, -1).map((slug) => `/c/alpha/${slug}`))].filter((path) => path !== current).sort());
    }
  });
});

/** The redirect table after a batch plan, as PUT /lessons/slugs writes it. */
function applyBatch(redirects: readonly Redirect[], plan: SlugBatchPlan): Redirect[] {
  const removed = new Set(plan.removed.map((redirect) => redirect.from));
  const flattened = new Map(plan.flattened.map((change) => [change.from, change.after]));
  return [...redirects.filter((redirect) => !removed.has(redirect.from)).map((redirect) => ({ from: redirect.from, to: flattened.get(redirect.from) ?? redirect.to })), ...plan.created]
    .sort((a, b) => a.from.localeCompare(b.from));
}
const caught = (work: () => unknown) => { try { work(); } catch (error) { return error; } return null; };

describe("planSlugBatch", () => {
  const lessons = [{ id: "l1", slug: "a" }, { id: "l2", slug: "b" }, { id: "l3", slug: "c" }];
  const plan = (changes: { lessonId: string; slug: string }[], redirects: Redirect[] = []) => planSlugBatch("/c/alpha", lessons, redirects, changes);

  it("renames several lessons at once, one redirect each, and drops changes to the current slug", () => {
    const result = plan([{ lessonId: "l1", slug: "x" }, { lessonId: "l2", slug: "b" }, { lessonId: "l3", slug: "y" }]);
    expect(result.changes).toEqual([{ lessonId: "l1", before: "a", after: "x" }, { lessonId: "l3", before: "c", after: "y" }]);
    expect(result.created).toEqual([{ from: "/c/alpha/a", to: "/c/alpha/x" }, { from: "/c/alpha/c", to: "/c/alpha/y" }]);
    expect([result.flattened, result.removed, result.reused]).toEqual([[], [], []]);
  });

  it("swaps A↔B (and rotates three) without a redirect from a path a lesson still holds, flattening the old URLs", () => {
    const old = [{ from: "/c/alpha/old-a", to: "/c/alpha/a" }];
    const swap = plan([{ lessonId: "l1", slug: "b" }, { lessonId: "l2", slug: "a" }], old);
    expect(swap.created).toEqual([]);
    expect(swap.reused).toEqual(["/c/alpha/a", "/c/alpha/b"]);
    expect(applyBatch(old, swap)).toEqual([{ from: "/c/alpha/old-a", to: "/c/alpha/b" }]);
    const rotate = plan([{ lessonId: "l1", slug: "b" }, { lessonId: "l2", slug: "c" }, { lessonId: "l3", slug: "d" }]);
    expect(rotate.created).toEqual([{ from: "/c/alpha/a", to: "/c/alpha/b" }]);
    expect(rotate.reused).toEqual(["/c/alpha/b", "/c/alpha/c"]);
    expect(rotate.changes.map((change) => change.after)).toEqual(["b", "c", "d"]);
  });

  it("flattens chains into every moved lesson and drops the redirect when a lesson goes back to an earlier slug", () => {
    const redirects = [{ from: "/c/alpha/a0", to: "/c/alpha/a" }, { from: "/c/alpha/b0", to: "/c/alpha/b" }];
    const result = plan([{ lessonId: "l1", slug: "a1" }, { lessonId: "l2", slug: "b0" }], redirects);
    expect(result.flattened).toEqual([{ from: "/c/alpha/a0", before: "/c/alpha/a", after: "/c/alpha/a1" }]);
    expect(result.removed).toEqual([{ from: "/c/alpha/b0", to: "/c/alpha/b" }]);
    expect(applyBatch(redirects, result)).toEqual([
      { from: "/c/alpha/a", to: "/c/alpha/a1" }, { from: "/c/alpha/a0", to: "/c/alpha/a1" }, { from: "/c/alpha/b", to: "/c/alpha/b0" },
    ]);
  });

  it("refuses collisions between the changes, with an unchanged lesson and with another page's old URL (409), and bad lesson lists (422)", () => {
    expect(caught(() => plan([{ lessonId: "l1", slug: "x" }, { lessonId: "l2", slug: "x" }]))).toMatchObject({ code: "slug_taken", details: { slug: "x", lessonIds: ["l1", "l2"] } });
    expect(caught(() => plan([{ lessonId: "l1", slug: "c" }]))).toMatchObject({ code: "slug_taken", details: { slug: "c" } });
    const other = { from: "/c/alpha/x", to: "/c/beta" };
    expect(caught(() => plan([{ lessonId: "l1", slug: "x" }], [other]))).toMatchObject({ code: "slug_taken", details: { redirect: other } });
    expect(caught(() => plan([{ lessonId: "l9", slug: "x" }]))).toMatchObject({ code: "unprocessable" });
    expect(caught(() => plan([{ lessonId: "l1", slug: "x" }, { lessonId: "l1", slug: "y" }]))).toMatchObject({ code: "unprocessable" });
  });

  it("matches planSlugChange for a single change", () => {
    const redirects = [{ from: "/c/alpha/z", to: "/c/alpha/a" }, { from: "/c/alpha/x", to: "/c/alpha/a" }];
    const single = planSlugChange(redirects, "/c/alpha/a", "/c/alpha/x");
    const batch = plan([{ lessonId: "l1", slug: "x" }], redirects);
    expect([batch.created, batch.flattened, batch.removed]).toEqual([[single.created], single.flattened, single.removed]);
  });

  it("any batch leaves every redirect one hop from a lesson path, never from one", () => {
    let current = lessons;
    let redirects: Redirect[] = [];
    const batches = [[["l1", "b"], ["l2", "a"]], [["l1", "p"], ["l3", "b"]], [["l2", "q"], ["l1", "a"], ["l3", "p"]], [["l1", "z"], ["l2", "a"], ["l3", "c"]]];
    for (const batch of batches) {
      const changes = batch.map(([lessonId = "", slug = ""]) => ({ lessonId, slug }));
      redirects = applyBatch(redirects, planSlugBatch("/c/alpha", current, redirects, changes));
      current = current.map((lesson) => ({ ...lesson, slug: changes.find((change) => change.lessonId === lesson.id)?.slug ?? lesson.slug }));
      const paths = new Set(current.map((lesson) => `/c/alpha/${lesson.slug}`));
      for (const redirect of redirects) expect([paths.has(redirect.from), paths.has(redirect.to)], JSON.stringify(redirect)).toEqual([false, true]);
    }
  });
});
