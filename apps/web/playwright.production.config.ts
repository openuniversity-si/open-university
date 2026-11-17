import { randomBytes } from "node:crypto";
import { defineConfig } from "@playwright/test";
import base from "./playwright.config.ts";

/**
 * Production-like indexing check (ADR-12): the test build with SITE_ENV=production in its own dist dir
 * (TOWER_DIST_DIR), so the headers baked in at build match production. HTTP requests only.
 */
const webServer = Array.isArray(base.webServer) ? base.webServer[0] : base.webServer;
if (!webServer) throw new Error("playwright.config.ts must define webServer.");
// SITE_INDEXABLE="false" proves SITE_ENV alone makes production indexable; a throwaway admin secret makes
// unauthenticated admin calls answer 401 (not 503 "not configured").
const env = {
  ...webServer.env,
  SITE_ENV: "production",
  SITE_INDEXABLE: "false",
  TOWER_DIST_DIR: ".next-production",
  TOWER_ADMIN_MEDIA_SECRET: randomBytes(32).toString("hex"),
};

export default defineConfig({
  ...base,
  testMatch: "*.production.ts",
  testIgnore: [],
  projects: [{ name: "production-like" }],
  webServer: {
    ...webServer,
    command: `pnpm build:test && ${webServer.command}`,
    timeout: 600_000,
    env,
  },
});
