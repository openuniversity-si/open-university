import { describe, expect, it, vi } from "vitest";
vi.mock("server-only", () => ({}));
const { revalidateTag, revalidatePath } = vi.hoisted(() => ({ revalidateTag: vi.fn(), revalidatePath: vi.fn() }));
vi.mock("next/cache", () => ({ revalidateTag, revalidatePath, unstable_cache: (read: () => unknown) => read }));
vi.mock("next/headers", () => ({ draftMode: () => Promise.resolve({ isEnabled: false }), cookies: () => Promise.resolve({ get: () => undefined }) }));
import { invalidateCatalog } from "./invalidate.ts";
import { CACHE } from "../../kernel/cache.ts";
import { AppError } from "../../kernel/errors.ts";

describe("invalidateCatalog", () => {
  it("expires the catalog tag immediately, the static Home and the sitemap", () => {
    invalidateCatalog();
    expect(CACHE.immediateExpiry).toBe(0);
    expect(revalidateTag).toHaveBeenCalledWith("catalog", { expire: CACHE.immediateExpiry });
    expect(revalidatePath).toHaveBeenCalledWith("/");
    expect(revalidatePath).toHaveBeenCalledWith("/sitemap.xml");
    // One layout purge for every static course and lesson page; they regenerate lazily on their next visit.
    expect(revalidatePath).toHaveBeenCalledWith("/c/[courseSlug]", "layout");
  });

  it("defers the purge until the transaction commits", () => {
    revalidateTag.mockClear();
    const effects: (() => void)[] = [];
    invalidateCatalog({ onAfterCommit(effect) { effects.push(effect); } });
    expect(revalidateTag).not.toHaveBeenCalled();
    for (const effect of effects) effect();
    expect(revalidateTag).toHaveBeenCalledWith("catalog", { expire: CACHE.immediateExpiry });
  });
});

it("classifies OEmbed and audit invariant failures under the common root", async () => {
  const { OEmbedUnavailableError } = await import("../../playback/server/oembed-resolver.ts");
  const { AuditMissingError } = await import("./mutation.ts");
  for (const [error, status] of [[new OEmbedUnavailableError(503), 502], [new AuditMissingError(), 500]] as const) {
    expect(error).toBeInstanceOf(AppError);
    expect((error as unknown as { status: number }).status).toBe(status);
  }
});
