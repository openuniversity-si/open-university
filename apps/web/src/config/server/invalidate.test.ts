import { beforeEach, describe, expect, it, vi } from "vitest";

const { revalidateTag } = vi.hoisted(() => ({ revalidateTag: vi.fn() }));
vi.mock("server-only", () => ({}));
vi.mock("next/cache", () => ({ revalidateTag, unstable_cache: (read: () => Promise<unknown>) => read }));

import { CACHE } from "../../kernel/cache.ts";
import { invalidateConfig } from "./invalidate.ts";

describe("configuration cache expiry", () => {
  beforeEach(() => { revalidateTag.mockClear(); });

  it("expires the shared tag and the kind tag immediately", () => {
    invalidateConfig("theme");
    expect(revalidateTag).toHaveBeenCalledWith("config", { expire: CACHE.immediateExpiry });
    expect(revalidateTag).toHaveBeenCalledWith("config:theme", { expire: CACHE.immediateExpiry });
    expect(CACHE.immediateExpiry).toBe(0);
  });
});
