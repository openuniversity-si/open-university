import { readFileSync } from "node:fs";
import { CACHE, PUBLIC_ASSET_CACHE_CONTROL } from "./src/kernel/cache.ts";
import { mediaPublicHosts } from "./src/media/server/public-hosts.ts";
import type { NextConfig } from "next";
import { playbackContentSources } from "./src/playback/server/source-registry.ts";
import { CSP_REPORT_PATH, reportOnlyContentSecurityPolicy } from "./src/platform/security/csp.ts";
import { SECURITY_HEADERS } from "./src/platform/security/headers.ts";
import { alternateHostRedirects } from "./src/site/domain/hosts.ts";
import { hostCommit, indexingFacts } from "./src/platform/host/env.ts";
import { isSiteIndexable, NOINDEX_HEADER_VALUE } from "./src/site/domain/indexing.ts";

/**
 * `TOWER_BUILD_TARGET=test` (pnpm build:test / start:test) swaps the playback
 * engine for the fake one and writes to its own dist dir, so the production
 * and test builds can coexist (ADR-11).
 */
const isTestBuild = process.env.TOWER_BUILD_TARGET === "test";

const engineModule = isTestBuild ? "./src/playback/testing/fake-engine.ts" : "./src/playback/client/engine.ts";

const packageJson = JSON.parse(readFileSync(new URL("./package.json", import.meta.url), "utf8")) as {
  version: string;
};

const commitSha = hostCommit(process.env) ?? "";

const nextConfig: NextConfig = {
  // TOWER_DIST_DIR: the production-like e2e build (playwright.production.config.ts) keeps its own output.
  distDir: process.env.TOWER_DIST_DIR ?? (isTestBuild ? ".next-test" : ".next"),
  pageExtensions: isTestBuild ? ["test.tsx", "tsx", "ts"] : ["tsx", "ts"],
  images: {
    // H1 / ADR-31: immutable, byte-budgeted origin files; never use a metered optimizer.
    unoptimized: true,
    // The public media host (MEDIA_PUBLIC_HOST in src/media/domain/types.ts).
    remotePatterns: mediaPublicHosts(process.env).flatMap((hostname) => ["/covers/**", "/m/**"].map((pathname) => ({ protocol: "https" as const, hostname, port: "", pathname, search: "" }))),
    minimumCacheTTL: CACHE.immutableObjectSeconds,
    deviceSizes: [640, 1080, 1920],
    imageSizes: [96, 208, 384],
    formats: ["image/webp"],
    qualities: [75],
  },
  poweredByHeader: false,
  reactStrictMode: true,
  env: {
    TOWER_APP_VERSION: packageJson.version,
    TOWER_BUILD_COMMIT: commitSha === "" ? "local" : commitSha.slice(0, 7),
  },
  turbopack: {
    resolveAlias: {
      "@tower/playback-engine": engineModule,
      "@tower/media": isTestBuild ? "./test/fixtures/media-entry.ts" : "./src/catalog/server/media.ts",
      // ADR-17: the test build reads the versioned snapshot, never a database.
      "@tower/catalog": isTestBuild ? "./src/catalog/testing/fake.ts" : "./src/catalog/server/read.ts",
    },
  },
  // Browsers ask for /favicon.ico on their own; the file lives with the other icons (ADR-13).
  rewrites() {
    return Promise.resolve([{ source: "/favicon.ico", destination: "/icons/favicon.ico" }]);
  },
  // thetower.si (temporary, 307) and the other alternate hosts (src/site/domain/hosts.ts) redirect to the canonical Open University origin.
  redirects() {
    return Promise.resolve(alternateHostRedirects());
  },
  headers() {
    const csp = { key: "Content-Security-Policy", value: reportOnlyContentSecurityPolicy(mediaPublicHosts(process.env), playbackContentSources()) };
    const robots = isSiteIndexable(indexingFacts(process.env)) ? [] : [{ key: "X-Robots-Tag", value: NOINDEX_HEADER_VALUE }];
    const reporting = { key: "Reporting-Endpoints", value: `csp="${CSP_REPORT_PATH}"` };
    // public/ files keep stable, unversioned names: cache them a day and revalidate in the background, never immutable.
    // (/_next/static is already immutable; next/font serves Inter from there.)
    const publicCache = [csp, reporting, { key: "Cache-Control", value: PUBLIC_ASSET_CACHE_CONTROL }];
    return Promise.resolve([
      { source: "/:path*", headers: [csp, reporting, ...SECURITY_HEADERS, ...robots] },
      ...["/icons/:path*", "/brand/:path*", "/fonts/:path*", "/favicon.ico"].map((source) => ({ source, headers: publicCache })),
    ]);
  },
};

export default nextConfig;
