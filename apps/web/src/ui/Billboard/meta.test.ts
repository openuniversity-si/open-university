import { describe, expect, it } from "vitest";
import { snapshotCatalog as catalog } from "@/catalog/testing/fake";
import { signedOutHome } from "@/catalog/domain/home";
import { billboardMeta } from "./meta";

describe("Billboard meta status", () => {
  const home = signedOutHome(catalog);
  it("reads Featured for the initial course and Selected after the first activation (Tap1)", () => {
    if (!home.featured) throw new Error("Fixture Course 1 must be featured.");
    expect(billboardMeta(home.featured, false)).toEqual({ mobile: "Featured  ·  17 lectures  ·  17h", desktop: "Featured  ·  17 lectures  ·  17h  ·  Intermediate  ·  English" });
    expect(billboardMeta(home.featured, true)).toEqual({ mobile: "Selected  ·  17 lectures  ·  17h", desktop: "Selected  ·  17 lectures  ·  17h  ·  Intermediate  ·  English" });
  });
  it("has no status for a non-featured course until it is selected", () => {
    const course = home.rails[1]?.courses[0];
    if (!course) throw new Error("Vervaeke's first course is published.");
    expect(course.featured).toBe(false);
    expect(billboardMeta(course, false).mobile).toBe(course.metaMobile);
    expect(billboardMeta(course, true).mobile).toBe(`Selected  ·  ${course.metaMobile}`);
  });
});
