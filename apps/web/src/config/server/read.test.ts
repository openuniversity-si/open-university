import { beforeEach, describe, expect, it, vi } from "vitest";

const flags = vi.hoisted(() => ({ withoutDatabase: false }));
vi.mock("next/cache", () => ({ unstable_cache: (read: () => Promise<unknown>) => read }));
vi.mock("../../platform/db/database-env.ts", () => ({ buildWithoutDatabase: () => flags.withoutDatabase }));
vi.mock("../../platform/db/pool.ts", () => ({ appPool: () => ({}) }));
vi.mock("./repository.ts", () => ({ configRepository: () => ({ read: () => Promise.resolve(null) }) }));

import { codeLimits } from "../domain/documents.ts";
import { LIMITS } from "../../kernel/limits.ts";
import { readServed } from "./read.ts";

describe("served configuration", () => {
  beforeEach(() => { flags.withoutDatabase = false; });

  it("serves the code when nothing is stored, the read fails, or the build has no database", async () => {
    await expect(readServed("limits", () => Promise.resolve(null))).resolves.toEqual(codeLimits());
    await expect(readServed("limits", () => Promise.reject(new Error("down")))).resolves.toEqual(codeLimits());
    await expect(readServed("limits", () => Promise.resolve({ ...codeLimits(), courseTitle: LIMITS.courseTitle + 1 }))).resolves.toEqual(codeLimits());
    flags.withoutDatabase = true;
    await expect(readServed("limits", () => Promise.reject(new Error("should not read")))).resolves.toEqual(codeLimits());
  });

  it("serves a stored revision that stays inside the contract", async () => {
    const lowered = { ...codeLimits(), courseTitle: 10 };
    await expect(readServed("limits", () => Promise.resolve(lowered))).resolves.toEqual(lowered);
  });
});
