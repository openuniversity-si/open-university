import { describe, expect, it } from "vitest";
import { canonicalJson, requestHash, sha256Hex } from "../../kernel/canonical.ts";
import { requestIdFrom } from "../../platform/observability/context.ts";
import * as c from "./contracts.ts";

describe("admin catalog contract", () => {
  it("has exactly the plan's error codes and statuses", () => {
    expect(c.errorCodes).toEqual({
      invalid: 400, unauthorized: 401, forbidden: 403, not_found: 404, revision_conflict: 409, state_conflict: 409, slug_taken: 409, has_dependents: 409,
      preconditions_failed: 412, payload_too_large: 413, unsupported_media: 415, idempotency_mismatch: 422, unprocessable: 422, rate_limited: 429, internal: 500, upstream_failed: 502, unconfigured: 503,
    });
  });

  // The suite baseline still names this case here. The parser lives in platform observability.
  it("echoes a safe x-request-id and replaces anything else with a fresh id", () => {
    const uuid = () => "fresh";
    expect(requestIdFrom("cli.run_42-a", uuid)).toBe("cli.run_42-a");
    expect(requestIdFrom("x".repeat(64), uuid)).toBe("x".repeat(64));
    for (const bad of [null, "", "x".repeat(65), "has space", "semi;colon", "ünïcode"]) expect(requestIdFrom(bad, uuid)).toBe("fresh");
  });

  it("validates Idempotency-Key and X-Tower-Actor formats", () => {
    expect(c.idempotencyKeySchema.safeParse("publish:course-6:2026-10-11T10.00").success).toBe(true);
    expect(c.idempotencyKeySchema.safeParse("k".repeat(129)).success).toBe(false);
    expect(c.idempotencyKeySchema.safeParse("bad key").success).toBe(false);
    expect(c.actorSchema.safeParse(c.DEFAULT_ACTOR).success).toBe(true);
    expect(c.actorSchema.safeParse("cli:tower-catalog@box daniel").success).toBe(true);
    expect(c.actorSchema.safeParse("Daniel").success).toBe(false);
    expect(c.actorSchema.safeParse("a".repeat(65)).success).toBe(false);
  });

  it("refuses unknown fields and empty patches", () => {
    expect(c.courseCreate.safeParse({ slug: "new-course", authorId: "author-1", title: "New", coverFrom: "own" }).success).toBe(true);
    expect(c.courseCreate.safeParse({ slug: "new-course", authorId: "author-1", title: "New", status: "published" }).success).toBe(false);
    expect(c.coursePatch.safeParse({ expectedRevision: 3 }).success).toBe(false);
    expect(c.coursePatch.safeParse({ expectedRevision: 3, title: "Renamed" }).success).toBe(true);
    expect(c.lessonPatch.safeParse({ expectedRevision: 1 }).success).toBe(false);
    expect(c.authorPatch.safeParse({ expectedRevision: 1 }).success).toBe(false);
    expect(c.sourcePatch.safeParse({ expectedRevision: 1 }).success).toBe(false);
  });

  it("parses query booleans and integers from strings", () => {
    expect(c.courseDeleteQuery.parse({ mode: "purge", confirm: "true", expectedRevision: "4" })).toEqual({ mode: "purge", confirm: true, expectedRevision: 4 });
    expect(c.courseDeleteQuery.safeParse({ mode: "purge", confirm: "yes" }).success).toBe(false);
    expect(c.releaseParams.parse({ n: "12" })).toEqual({ n: 12 });
    expect(c.releaseParams.safeParse({ n: "0" }).success).toBe(false);
    expect(c.auditQuery.safeParse({ entity: "course:course-6", limit: "201" }).success).toBe(false);
    expect(c.auditQuery.parse({ entity: "redirect:/c/old", limit: "5" }).limit).toBe(5);
  });

  it("needs exactly one of authorId and newAuthor to draft an import", () => {
    const base = { slug: "new-course" };
    expect(c.importDraft.safeParse(base).success).toBe(false);
    expect(c.importDraft.safeParse({ ...base, authorId: "author-1" }).success).toBe(true);
    expect(c.importDraft.safeParse({ ...base, newAuthor: { slug: "x", name: "X", monogram: "X", kind: "person" } }).success).toBe(true);
    expect(c.importDraft.safeParse({ ...base, authorId: "author-1", newAuthor: { slug: "x", name: "X", monogram: "X", kind: "person" } }).success).toBe(false);
  });

  it("keeps catalog paths and preview TTLs inside their bounds", () => {
    expect(c.catalogPathSchema.safeParse("/c/genesis/lecture-1").success).toBe(true);
    expect(c.catalogPathSchema.safeParse("/c/genesis/a/b").success).toBe(false);
    expect(c.catalogPathSchema.safeParse("/x/genesis").success).toBe(false);
    expect(c.previewTokenBody.safeParse({ ttlMinutes: 61 }).success).toBe(false);
    expect(c.previewTokenBody.safeParse({ ttlMinutes: 60, courseId: "course-6" }).success).toBe(true);
  });
});

describe("canonical request hash", () => {
  it("ignores key order and undefined members at every level", () => {
    expect(canonicalJson({ b: 1, a: { d: [1, { y: 2, x: 1 }], c: undefined } })).toBe('{"a":{"d":[1,{"x":1,"y":2}]},"b":1}');
    expect(canonicalJson([undefined, null])).toBe("[null,null]");
    expect(canonicalJson(undefined)).toBe("null");
    expect(requestHash({ q: "1" }, { b: 2, a: 1 })).toBe(requestHash({ q: "1" }, { a: 1, b: 2 }));
  });

  it("separates query and body, and differs for any change", () => {
    expect(requestHash({}, { a: 1 })).not.toBe(requestHash({ a: "1" }, undefined));
    expect(requestHash({}, { a: 1 })).not.toBe(requestHash({}, { a: 2 }));
    expect(requestHash(undefined, undefined)).toBe(requestHash({}, null));
    expect(sha256Hex("abc")).toBe("ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
  });

  it("parses an edition label into term + year (ADR-21)", () => {
    expect(c.parseEditionLabel("Fall 2025")).toEqual({ slug: "fall-2025", label: "Fall 2025", term: "fall", year: 2025 });
    expect(c.parseEditionLabel("Spring 2024 Lectures")).toEqual({ slug: "spring-2024", label: "Spring 2024", term: "spring", year: 2024 });
    expect(c.parseEditionLabel("[FA24] Intro")).toEqual({ slug: "fall-2024", label: "Fall 2024", term: "fall", year: 2024 });
    expect(c.parseEditionLabel("SP25")).toEqual({ slug: "spring-2025", label: "Spring 2025", term: "spring", year: 2025 });
    expect(c.parseEditionLabel("Autumn 2023")).toMatchObject({ term: "fall", label: "Fall 2023" });
    expect(c.parseEditionLabel("DeVane 2024")).toEqual({ slug: "2024", label: "2024", term: null, year: 2024 });
    expect(c.parseEditionLabel("CS50x 2025")).toMatchObject({ slug: "2025", year: 2025 });
    expect(c.parseEditionLabel("Lectures")).toBeNull();
    expect(c.editionLabel("winter", 2026)).toBe("Winter 2026");
  });

  it("drafts an import into a new course or an existing one, never both", () => {
    const edition = { slug: "fall-2025", label: "Fall 2025", term: "fall", year: 2025 };
    expect(c.importDraft.safeParse({ slug: "new", authorId: "author-1" }).success).toBe(true);
    expect(c.importDraft.safeParse({ courseId: "course-6", edition, part: "labs" }).success).toBe(true);
    expect(c.importDraft.safeParse({ courseId: "course-6" }).success).toBe(false);
    expect(c.importDraft.safeParse({ courseId: "course-6", edition, slug: "x" }).success).toBe(false);
    expect(c.importDraft.safeParse({ authorId: "author-1" }).success).toBe(false);
    expect(c.lessonCreate.safeParse({ youtubeId: "AAAAAAAAAAA", durationSeconds: 60 }).success).toBe(false);
  });

  it("accepts a Home row of 250 courses and refuses 251", () => {
    expect(c.HOME_ROW_MAX_COURSES).toBe(250);
    const home = (count: number) => ({
      featuredCourseId: null,
      rows: [{ id: "iit-guwahati", kind: "curated", courseIds: Array.from({ length: count }, (_, index) => `course-${String(index + 1)}`) }],
      expectedRevision: 1,
    });
    expect(c.homePut.safeParse(home(250)).success).toBe(true);
    const refused = c.homePut.safeParse(home(251));
    expect(refused.success).toBe(false);
    expect(refused.error?.issues.map((issue) => issue.path.join("."))).toEqual(["rows.0.courseIds"]);
  });
});
