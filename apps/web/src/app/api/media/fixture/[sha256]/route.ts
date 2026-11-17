import "server-only";
import { MEDIA_CACHE_CONTROL } from "@/kernel/cache.ts";
import { currentEnv } from "@/kernel/env.ts";
import { readFile } from "node:fs/promises";
import { resolve } from "node:path";

export async function GET(_request: Request, context: { params: Promise<{ sha256: string }> }) {
  if (currentEnv().TOWER_BUILD_TARGET !== "test") return new Response(null, { status: 404 });
  const { sha256 } = await context.params;
  if (!/^[a-f0-9]{64}$/.test(sha256)) return new Response(null, { status: 404 });
  try {
    const bytes = await readFile(resolve(process.cwd(), ".fidelity-cache/media", sha256));
    return new Response(bytes, { headers: { "Content-Type": bytes[0] === 255 ? "image/jpeg" : bytes[0] === 137 ? "image/png" : bytes.toString("ascii", 0, 4) === "RIFF" ? "image/webp" : "image/avif", "Cache-Control": MEDIA_CACHE_CONTROL } });
  } catch { return new Response(null, { status: 404 }); }
}
