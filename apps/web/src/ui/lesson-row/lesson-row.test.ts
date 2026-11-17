import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const here = dirname(fileURLToPath(import.meta.url));
const source = (path: string) => readFileSync(join(here, path), "utf8");

describe("lesson row", () => {
  it("does not branch on a player context", () => {
    const row = source("./PlaylistItem.tsx");
    const sheet = source("./PlaylistItem.module.css");
    expect(row).not.toMatch(/"player"/);
    expect(sheet).not.toContain('data-context="player"');
    expect(row).toContain("playlist-item-");
  });

  it("keeps the player row declarations on the rail sheet", () => {
    const rail = source("../playback/PlayerRail.module.css");
    const railView = source("../playback/PlayerRail.tsx");
    const course = source("../PlaylistItem/CoursePlaylist.tsx");
    expect(rail).toContain("padding-right: var(--tower-player-length-12);");
    expect(rail).toContain("white-space: pre-wrap;");
    expect(rail).toContain("box-shadow: var(--tower-el-inset-ring) var(--tower-player-length-1) var(--tower-ink);");
    expect(rail).toContain("opacity: var(--tower-el-opacity-dim);");
    expect(rail).toContain("color: var(--tower-muted);");
    expect(railView).not.toMatch(/CoursePlaylist/);
    expect(course).not.toMatch(/PlayerRail/);
    expect(railView).toContain("metaGap");
    expect(course).toContain("metaDot");
    expect(railView).toContain("@/ui/lesson-row/CourseProgress");
    expect(course).toContain("@/ui/lesson-row/CourseProgress");
    expect(source("../tokens/screen-measures.test.ts")).toContain("src/ui/lesson-row/CourseProgress.module.css");
    expect(source("../tokens/screen-measures.test.ts")).not.toContain("src/ui/PlaylistItem/CourseProgress.module.css");
  });
});
