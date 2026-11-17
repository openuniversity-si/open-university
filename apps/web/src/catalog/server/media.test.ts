import { readFileSync } from "node:fs";
import { describe, expect, it, vi } from "vitest";

vi.mock("server-only", () => ({}));
vi.mock("./page-reads.ts", () => ({ readPageCatalog: () => Promise.resolve({ courses: [], lessons: [], authors: [], home: { rows: [] } }) }));
vi.mock("./media-gateway.ts", () => ({
  readPublicOwnerAssets: vi.fn(() => Promise.resolve([])),
  readLessonAssets: vi.fn(() => Promise.resolve([])),
}));

import { readPublicOwnerAssets } from "./media-gateway.ts";
import { getCourseMedia } from "./media.ts";

describe("public cover read", () => {
  it("rejects a missing course list and does not ask storage for an empty one", async () => {
    await expect(getCourseMedia(undefined)).rejects.toThrow("courseIds are required");
    await getCourseMedia([]);
    expect(readPublicOwnerAssets).not.toHaveBeenCalled();
  });

  it("asks storage for the declared owner and resolves the cover in this module", () => {
    const source = readFileSync(new URL("./media.ts", import.meta.url), "utf8");
    expect(source).toContain("readPublicOwnerAssets");
    expect(source).toContain("courseCoverAssets");
    expect(source).toContain("lessonCoverAssets");
    expect(source).not.toContain("media/server/");
  });
});
