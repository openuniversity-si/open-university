import { afterEach, expect, it } from "vitest";
import { resetEnvCache } from "../../kernel/env.ts";
import { getBuildInfo } from "./build-info.ts";

afterEach(() => {
  resetEnvCache();
});

it("exposes commit, version and diagnostics from a deployment fixture without TOWER_BUILD_COMMIT", () => {
  expect(
    getBuildInfo({
      SITE_ENV: "production",
      BUILD_SHA: "43844ff7889838d7f040463ae3f9d76c46ae37c3",
      TOWER_APP_VERSION: "0.1.0",
    }),
  ).toEqual({
    version: "0.1.0",
    commit: "43844ff",
    diagnostics: "ok",
    engine: "tower-playback-engine:youtube",
  });
});

it("does not report unknown when only BUILD_SHA is present at runtime", () => {
  const info = getBuildInfo({
    BUILD_SHA: "3007e24c2e5c916c51471584b7f38d9e108ef37d",
    TOWER_APP_VERSION: "0.1.0",
  });
  expect(info.commit).toBe("3007e24");
  expect(info.diagnostics).toBe("ok");
  expect(info.commit).not.toBe("unknown");
});
