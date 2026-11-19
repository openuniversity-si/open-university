import { expect, it } from "vitest";
import { REQUIRED_COVERS } from "./rules/status.ts";
import { coverDeclarationProblem, coverOwner, missingCoverKinds, reviewedCoverBackfill } from "./cover-source.ts";

// Verifies: D-031
const kinds = [...REQUIRED_COVERS];

it("D-031: own, the course's subarea, or its area when it has none, are the only declarations", () => {
  expect(coverOwner("own", "course-1")).toEqual({ kind: "course", id: "course-1" });
  expect(coverOwner("subarea:mechanics", "course-1")).toEqual({ kind: "subarea", id: "mechanics" });
  expect(coverOwner("area:physics", "course-1")).toEqual({ kind: "area", id: "physics" });
  expect(coverOwner("institution:usp", "course-1")).toBeUndefined();
  const course = { id: "course-1", areaId: "physics", subareaId: "mechanics" };
  expect(coverDeclarationProblem(course, "own")).toBeNull();
  expect(coverDeclarationProblem(course, "subarea:mechanics")).toBeNull();
  expect(coverDeclarationProblem(course, "subarea:optics")).toMatch(/not its subarea/);
  expect(coverDeclarationProblem(course, "area:physics")).toMatch(/cannot declare/);
  expect(coverDeclarationProblem({ id: "course-2", areaId: "physics", subareaId: null }, "area:physics")).toBeNull();
  expect(coverDeclarationProblem({ id: "course-2", areaId: "physics", subareaId: null }, "area:math")).toMatch(/not its area/);
  expect(coverDeclarationProblem(course, "institution:usp")).toMatch(/coverFrom/);
});

it("D-031: a declared owner without a required kind is named, and an institution cover is not a kind", () => {
  expect(missingCoverKinds(new Set(kinds))).toEqual([]);
  expect(missingCoverKinds(new Set(["poster_9x16"]))).toEqual(["hero_desktop_16x9", "hero_present", "hero_mobile_9x16"]);
});

it("D-031: backfill declares the provisional owner and holds a published course whose owner has no cover", () => {
  const base = { id: "course-1", status: "published", areaId: "physics", subareaId: "mechanics", coverProvisional: true, ownKinds: kinds, subareaKinds: kinds, areaKinds: kinds };
  expect(reviewedCoverBackfill(base)).toEqual({ coverFrom: "subarea:mechanics", held: false, reason: null });
  expect(reviewedCoverBackfill({ ...base, coverProvisional: false })).toEqual({ coverFrom: "own", held: false, reason: null });
  expect(reviewedCoverBackfill({ ...base, subareaId: null })).toEqual({ coverFrom: "area:physics", held: false, reason: null });
  const bare = reviewedCoverBackfill({ ...base, subareaKinds: ["poster_9x16"], areaKinds: kinds });
  expect(bare.coverFrom).toBe("subarea:mechanics");
  expect(bare.held).toBe(true);
  expect(bare.reason).toMatch(/missing /);
  expect(reviewedCoverBackfill({ ...base, subareaKinds: ["poster_9x16"], areaKinds: kinds, status: "draft" }).held).toBe(false);
  expect(reviewedCoverBackfill({ ...base, coverProvisional: false, ownKinds: [] }).held).toBe(true);
});
