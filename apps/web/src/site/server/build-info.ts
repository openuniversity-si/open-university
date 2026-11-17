import { playbackEngine } from "@tower/playback-engine";
import { currentEnv, getBuildEnv, type EnvInput } from "../../kernel/env.ts";
import { buildEnvFromHost } from "../../platform/host/env.ts";
import type { PlaybackEngineModule } from "@/playback/domain/types";

export interface BuildInfo {
  readonly version: string;
  readonly commit: string;
  readonly diagnostics: "ok" | "unknown";
  readonly engine: PlaybackEngineModule["id"];
}

/**
 * Public build identity. Commit and version come from the inlined build env. The host adapter
 * supplies a published commit when the build did not inline one (PR #200 regression).
 */
export function getBuildInfo(input?: EnvInput): BuildInfo {
  const build = getBuildEnv(buildEnvFromHost(input ?? currentEnv()));
  return {
    version: build.version,
    commit: build.commit,
    diagnostics: build.diagnostics,
    engine: playbackEngine.id,
  };
}
