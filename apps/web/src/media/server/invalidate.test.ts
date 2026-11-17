import { describe, expect, it, vi } from "vitest";

vi.mock("server-only", () => ({}));
const { revalidateTag, revalidatePath } = vi.hoisted(() => ({ revalidateTag: vi.fn(), revalidatePath: vi.fn() }));
vi.mock("next/cache", () => ({ revalidateTag, revalidatePath }));

import { CACHE } from "../../kernel/cache.ts";
import { invalidateMedia } from "./invalidate.ts";

describe("invalidateMedia", () => {
  it("expires each planned tag immediately", () => {
    invalidateMedia({ tags: ["media:course:course-1"], paths: ["/c/example"] });
    expect(CACHE.immediateExpiry).toBe(0);
    expect(revalidateTag).toHaveBeenCalledWith("media:course:course-1", { expire: CACHE.immediateExpiry });
    expect(revalidatePath).toHaveBeenCalledWith("/c/example");
  });
});
