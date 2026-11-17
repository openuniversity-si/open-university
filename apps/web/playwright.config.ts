import { generateKeyPairSync } from "node:crypto";
import { defineConfig, devices } from "@playwright/test";
import { approvedFontConfig } from "./e2e/fixtures/approved-font.ts";
import { TEST_SESSION_SECRET } from "./e2e/fixtures/session.ts";

// Each local browser run uses its own server and a free port.
const PORT = Number(process.env.TOWER_E2E_PORT ?? 3100);
if (!Number.isInteger(PORT) || PORT < 1 || PORT > 65535) throw new Error("TOWER_E2E_PORT must be a valid port.");
const hostname = "127.0.0.1";
const baseURL = `http://${hostname}:${String(PORT)}`;
const impactRun = process.env.TOWER_E2E_SELECTION === "impact";
const isCI = process.env.CI === "true";
// Optional local Docker WebKit runtime for non-root cloud workers without system libraries.
// The same pinned browser runs every assertion; loopback is tunneled back to this worker's test server.
const webkitEndpoint = process.env.TOWER_WEBKIT_WS_ENDPOINT;
// Throwaway signing key per run: the Player signs at route render and Try again refreshes through the server action.
const playbackSigningKey = generateKeyPairSync("rsa", { modulusLength: 2048 }).privateKey.export({ type: "pkcs8", format: "pem" }).toString();
// Local browsers resolve "Inter" to the approved bytes only (e2e/fixtures/approved-font.ts); workers inherit it.
process.env.FONTCONFIG_FILE = approvedFontConfig();
// Match Figma's fractional advances and grayscale antialiasing across Linux fontconfig defaults.
// uid 0 cannot start Chromium's sandbox. Other uids keep the default sandbox.
const runningAsRoot = typeof process.getuid === "function" && process.getuid() === 0;
const chromiumArgs = [
  ...(runningAsRoot ? ["--no-sandbox", "--disable-setuid-sandbox"] : []),
  "--autoplay-policy=user-gesture-required",
  "--disable-gpu",
  "--font-render-hinting=none",
  "--disable-lcd-text",
];

/**
 * E2E and a11y run against the test build (`pnpm build:test`, fake playback
 * engine, ADR-11). Every spec imports `test` from e2e/fixtures/no-video-guard.ts.
 */
export default defineConfig({
  testDir: "./e2e",
  testMatch: "**/*.spec.ts",
  outputDir: process.env.TOWER_E2E_OUTPUT ?? "./test-results",
  fullyParallel: true,
  forbidOnly: isCI,
  retries: 0,
  // Measured locally: four bounded workers beat two/three without exceeding 8 GiB.
  workers: 4,
  reporter: [["list"], ["json", { outputFile: process.env.TOWER_E2E_REPORT ?? "test-results/gate.json" }],
    ...(process.env.TOWER_E2E_PROFILE ? [["./e2e/fixtures/profile-reporter.ts"] as [string]] : [])],
  use: {
    baseURL,
    serviceWorkers: "block",
    trace: "retain-on-failure",
  },
  projects: [
    {
      name: "chromium-desktop",
      // Keep Chromium projects bounded so WebKit can start alongside them.
      workers: impactRun ? 2 : 1,
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 1366, height: 768 },
        launchOptions: { args: chromiumArgs },
      },
    },
    {
      name: "chromium-mobile-390",
      workers: 1,
      // Product screenshots use desktop Chromium with each frame's explicit viewport/DPR.
      testIgnore: "**/fidelity.spec.ts",
      ...(impactRun ? { grep: /@engine/ } : {}),
      use: {
        ...devices["Pixel 7"],
        viewport: { width: 390, height: 844 },
        launchOptions: { args: chromiumArgs },
      },
    },
    {
      name: "webkit-mobile-390",
      workers: 2,
      testIgnore: "**/fidelity.spec.ts",
      ...(impactRun ? { grep: /@engine/ } : {}),
      use: {
        ...devices["iPhone 14"],
        ...(webkitEndpoint ? { connectOptions: { wsEndpoint: webkitEndpoint, exposeNetwork: "<loopback>" } } : {}),
      },
    },
    ...([390, 1366, 1920] as const).flatMap((width) => ([1, 2] as const)
      .filter((dpr) => width !== 1366 || dpr !== 1)
      .map((dpr) => ({
        name: `chromium-fidelity-${String(width)}-dpr${String(dpr)}`,
        testMatch: "specimen.spec.ts",
        use: {
          browserName: "chromium" as const,
          viewport: { width, height: width === 390 ? 844 : width === 1366 ? 768 : 1080 },
          deviceScaleFactor: dpr,
          launchOptions: { args: chromiumArgs },
        },
      }))),
  ],
  webServer: {
    command: `pnpm start:test --port ${String(PORT)} --hostname ${hostname}`,
    url: `${baseURL}/api/health`,
    reuseExistingServer: false,
    timeout: 60_000,
    env: {
      AUTH_URL: baseURL,
      AUTH_SECRET: TEST_SESSION_SECRET,
      AUTH_GOOGLE_ID: "",
      AUTH_GOOGLE_SECRET: "",
      APP_DATABASE_URL: process.env.TEST_DATABASE_URL ?? "",
      MUX_SIGNING_KEY_ID: "e2e-throwaway",
      MUX_SIGNING_PRIVATE_KEY: playbackSigningKey,
      PLAYBACK_ORIGIN: baseURL,
    },
  },
});
