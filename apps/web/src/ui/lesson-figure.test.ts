import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { pickAsset } from "@/media/domain/group";
import type { MediaAsset } from "@/media/domain/types";
import { chosenLessonCover } from "./lesson-figure.ts";

const here = dirname(fileURLToPath(import.meta.url));
const source = (path: string) => readFileSync(join(here, path), "utf8");

const asset = (url: string, kind: MediaAsset["kind"], extra: Partial<MediaAsset> = {}) => ({
  ownerId: "lesson-1", kind, variant: "default", url, isActive: true, ...extra,
}) as MediaAsset;

/** The URL the course list and the lesson poster show today, via `pickAsset`. */
function shownToday(assets: readonly MediaAsset[] | undefined): string | undefined {
  return pickAsset(assets, "cover_16x9")?.url;
}

describe("chosen lesson cover", () => {
  it("keeps the URL of an own cover, an inherited cover, and a lesson with no figure", () => {
    const own = [
      asset("https://media.example/covers/lesson-1/still.webp", "cover_9x16"),
      asset("https://media.example/covers/lesson-1/own.webp", "cover_16x9"),
    ];
    const inherited = [
      asset("https://media.example/covers/lesson-1/inactive.webp", "cover_16x9", { isActive: false }),
      asset("https://media.example/covers/area-1/inherited.webp", "cover_16x9"),
    ];
    const none = [asset("https://media.example/covers/lesson-1/portrait.webp", "cover_9x16")];

    expect(chosenLessonCover(own)?.url).toBe(shownToday(own));
    expect(chosenLessonCover(own)?.url).toBe("https://media.example/covers/lesson-1/own.webp");
    expect(chosenLessonCover(inherited)?.url).toBe(shownToday(inherited));
    expect(chosenLessonCover(inherited)?.url).toBe("https://media.example/covers/area-1/inherited.webp");
    expect(chosenLessonCover(none)?.url).toBe(shownToday(none));
    expect(chosenLessonCover(none)).toBeUndefined();
    expect(chosenLessonCover(undefined)).toBe(shownToday(undefined));
  });

  it("does not choose a cover", () => {
    expect(source("./lesson-figure.ts")).not.toMatch(/\bresolveCover\b|\bpickAsset\b/);
  });

  it("the course page paints the cover the opening already chose", () => {
    const page = source("../app/c/[courseSlug]/(course)/view.tsx");
    const opening = source("./showcase/course-opening.ts");
    expect(page).not.toMatch(/\bresolveCover\b|\bpickAsset\b|\bchosenLessonCover\b/);
    expect(page).toContain("view.covers");
    expect(opening).toContain("chosenLessonCover");
    expect(opening).not.toMatch(/\bresolveCover\b|\bpickAsset\b/);
  });

  it("the lesson page paints the cover the stage already chose", () => {
    const page = source("../app/c/[courseSlug]/[lessonSlug]/view.tsx");
    const stage = source("./playback/lesson-stage.ts");
    expect(page).not.toMatch(/\bresolveCover\b|\bpickAsset\b|\bchosenLessonCover\b/);
    expect(page).toContain("stage.poster");
    expect(stage).toContain("chosenLessonCover");
    expect(stage).not.toMatch(/\bresolveCover\b|\bpickAsset\b/);
  });
});
