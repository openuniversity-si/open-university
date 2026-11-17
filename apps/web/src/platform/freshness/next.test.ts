import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it, vi } from "vitest";

const { revalidateTag, revalidatePath, unstable_cache } = vi.hoisted(() => ({
  revalidateTag: vi.fn(),
  revalidatePath: vi.fn(),
  unstable_cache: vi.fn((read: () => Promise<unknown>) => read),
}));
vi.mock("server-only", () => ({}));
vi.mock("next/cache", () => ({ revalidateTag, revalidatePath, unstable_cache }));

import { expirePath, expireTag, remember } from "./next.ts";

describe("host freshness", () => {
  it("remembers a read with the caller's key, tags and lifetime", async () => {
    unstable_cache.mockClear();
    const read = () => Promise.resolve("sha");
    const cached = remember(read, ["catalog", "sha"], { tags: ["catalog"], revalidate: false });
    expect(unstable_cache).toHaveBeenCalledWith(read, ["catalog", "sha"], { tags: ["catalog"], revalidate: false });
    await expect(cached()).resolves.toBe("sha");
  });

  it("expires a tag with the same immediate profile", () => {
    expireTag("catalog", { expire: 0 });
    expect(revalidateTag).toHaveBeenCalledWith("catalog", { expire: 0 });
  });

  it("purges a path, and a layout path with its type", () => {
    expirePath("/");
    expirePath("/c/[courseSlug]", "layout");
    expect(revalidatePath).toHaveBeenNthCalledWith(1, "/");
    expect(revalidatePath).toHaveBeenNthCalledWith(2, "/c/[courseSlug]", "layout");
  });
});

describe("vendor cache client", () => {
  it("stays in the freshness adapter", () => {
    const web = new URL("../../../", import.meta.url);
    const leaks: string[] = [];
    const walk = (directory: string) => {
      for (const name of readdirSync(directory)) {
        const path = join(directory, name);
        if (statSync(path).isDirectory()) {
          walk(path);
          continue;
        }
        if (!path.endsWith(".ts") && !path.endsWith(".tsx")) continue;
        if (path.endsWith(".test.ts") || path.endsWith(".int.test.ts")) continue;
        if (readFileSync(path, "utf8").includes('next/cache')) leaks.push(path);
      }
    };
    for (const root of ["src/catalog", "src/config", "src/media"]) walk(new URL(root, web).pathname);
    expect(leaks).toEqual([]);
  });
});
