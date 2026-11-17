import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import type { BillboardView, RailView } from "@/catalog/domain/view-model.ts";
import { homeShelves } from "./home-shelves.ts";

const here = dirname(fileURLToPath(import.meta.url));
const source = (path: string) => readFileSync(join(here, path), "utf8");
const course = (id: string) => ({ id }) as BillboardView;
const rail = (id: string, courses: readonly BillboardView[]): RailView => ({ id, title: id, courses });

describe("home shelves", () => {
  it("keeps a resume shelf first, with the title and id the signed-in Home shows today", () => {
    const published = rail("fixture-lecturer-1", [course("course-2")]);
    expect(homeShelves([])).toEqual([]);
    expect(homeShelves([published])).toEqual([{ id: "fixture-lecturer-1", title: "fixture-lecturer-1", courses: [course("course-2")], resume: false }]);
    const resume = homeShelves([], [course("course-4")]);
    expect(resume).toEqual([{ id: "continue-watching", title: "Continue Watching", courses: [course("course-4")], resume: true }]);
    expect(homeShelves([published], [course("course-4")]).map((shelf) => shelf.id)).toEqual(["continue-watching", "fixture-lecturer-1"]);
  });

  it("leaves the billboard selection without a resume prop of its own", () => {
    const selection = source("../Billboard/BillboardSelection.tsx");
    const signedIn = source("../../app/signed-in-home/page.tsx");
    expect(selection).not.toContain("continueWatching");
    expect(selection).toContain('useAuthSelection("home")');
    expect(signedIn).toContain("homeShelves([], home.continueWatching)");
    expect(source("../../app/page.tsx")).toContain("homeShelves([])");
    expect(source("../../app/authors/view.tsx")).toContain("homeShelves(tab.rails)");
  });
});
