import type { PlaybackEngineModule } from "./types.ts";

/**
 * Engine ids that bundle:check searches for in build output. The engine
 * modules repeat these literals instead of importing this file, so that each
 * build only contains the id of the engine it actually bundles.
 */
export const ENGINE_MARKERS = {
  youtube: "tower-playback-engine:youtube",
  fake: "tower-playback-engine:fake",
} as const satisfies Record<string, PlaybackEngineModule["id"]>;
