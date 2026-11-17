import { readFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { CACHE_CATALOG, CACHE_CONFIG, cacheOffenders, colorOffenders, EDITORIAL_CALLS, EDITORIAL_CATALOG, editorialLooseWords, EXTENT_CALLS, EXTENT_CATALOG, extentOffenders, LIMITS_CATALOG, limitOffenders, OG_MATTE, OG_MATTE_FILE, OG_MATTE_KEY_FILE, PAGINATION_CATALOG, paginationOffenders, productionSources, spacingOffenders, typographyOffenders, UI_TEXT_CATALOG, uiTextOffenders } from "./domain-literals.ts";
import { TEXT_FIELDS } from "../../src/catalog/domain/fields.ts";
import { CACHE } from "../../src/kernel/cache.ts";
import { ogMatte } from "../../src/media/domain/og.ts";
import { readerPhrases } from "../../src/site/domain/reader-copy.ts";

const repo = fileURLToPath(new URL("../../../..", import.meta.url));
const snapshot = JSON.parse(readFileSync(new URL("../../design/figma-tokens.snapshot.json", import.meta.url), "utf8")) as {
  readonly variables: Readonly<Record<string, { readonly value: string }>>;
};
const catalogValues = new Set(Object.values(snapshot.variables).map((token) => token.value));

describe("D-050 type gate", () => {
  it("D-050: a raw type measure is refused", () => {
    expect(typographyOffenders([{ path: "apps/web/src/example.css", text: ".x { text-transform: uppercase; }" }])).toEqual(["apps/web/src/example.css: text-transform: uppercase"]);
    expect(typographyOffenders([{ path: "apps/web/src/example.css", text: ".x { text-decoration: underline; }" }])).toEqual(["apps/web/src/example.css: text-decoration: underline"]);
    expect(typographyOffenders([{ path: "apps/web/src/example.css", text: ".x { text-decoration: none; }" }])).toEqual(["apps/web/src/example.css: text-decoration: none"]);
    expect(typographyOffenders([{ path: "apps/web/src/example.css", text: ".x { font-size: 12px; }" }])).toEqual(["apps/web/src/example.css: font-size: 12px"]);
    expect(typographyOffenders([{ path: "apps/web/src/example.css", text: ".x { text-transform: var(--tower-label-transform); }" }])).toEqual([]);
    expect(typographyOffenders([{ path: "apps/web/src/ui/typography.css", text: ".x { text-transform: uppercase; }" }])).toEqual([]);
  });

  it("D-050: type stays green", () => {
    expect(typographyOffenders(productionSources(repo))).toEqual([]);
  });
});

describe("D-050 UI text gate", () => {
  it("refuses a quoted phrase outside the catalog", () => {
    const phrases = ["Play lecture", "Home"];
    expect(uiTextOffenders([{ path: "apps/web/src/example.tsx", text: 'aria-label="Play lecture"' }], phrases)).toEqual(['apps/web/src/example.tsx: "Play lecture"']);
    expect(uiTextOffenders([{ path: UI_TEXT_CATALOG, text: 'export const playLecture = "Play lecture";' }], phrases)).toEqual([]);
    expect(uiTextOffenders([{ path: "apps/web/src/example.tsx", text: 'if (key === "Home") return 0;' }], phrases)).toEqual([]);
    expect(uiTextOffenders([{ path: "apps/web/src/example.css", text: '[data-kind="Home"] { color: red; }' }], phrases)).toEqual([]);
    expect(uiTextOffenders([{ path: "apps/web/src/example.ts", text: 'plural(n, "course")' }], phrases)).toEqual(['apps/web/src/example.ts: plural(n, "course")']);
    expect(uiTextOffenders([{ path: "apps/web/src/example.ts", text: "plural(n, courseNoun)" }], phrases)).toEqual([]);
  });

  it("D-050: public chrome stays in the reader catalog", () => {
    const files = productionSources(repo);
    expect(uiTextOffenders(files, readerPhrases)).toEqual([]);
    const compile = files.find((file) => file.path === "apps/web/src/catalog/domain/compile.ts");
    const meta = files.find((file) => file.path === "apps/web/src/ui/Billboard/meta.ts");
    const nav = files.find((file) => file.path === "apps/web/src/ui/TopNav/TopNav.tsx");
    const queries = files.find((file) => file.path === "apps/web/src/catalog/domain/queries.ts");
    const player = files.find((file) => file.path === "apps/web/src/ui/playback/PlayerControls.tsx");
    const playlist = files.find((file) => file.path === "apps/web/src/ui/lesson-row/PlaylistItem.tsx");
    expect(compile?.text).toContain("CONTINUE_TITLE = continueWatchingTitle");
    expect(compile?.text).not.toContain('"Continue Watching"');
    expect(meta?.text).not.toContain('" · "');
    expect(nav?.text).not.toContain('"Home"');
    expect(nav?.text).not.toContain('key === "Home"');
    expect(queries?.text).not.toContain('"Background"');
    expect(player?.text).not.toContain('"Play lecture"');
    expect(playlist?.text).not.toContain('"Now playing"');
    const edition = files.find((file) => file.path === "apps/web/src/ui/EditionSelector/EditionSelector.tsx");
    expect(edition?.text).toContain('key === "Home"');
  });
});

describe("D-050 limit gate", () => {
  it("refuses a cap that is not a catalog key", () => {
    const file = "apps/web/src/example.ts";
    expect(limitOffenders([{ path: file, text: "z.string().max(40)" }])).toEqual([`${file}: .max(40)`]);
    expect(limitOffenders([{ path: file, text: "label(200)" }])).toEqual([`${file}: label(200)`]);
    expect(limitOffenders([{ path: file, text: "AbortSignal.timeout(10_000)" }])).toEqual([`${file}: AbortSignal.timeout(10_000)`]);
    expect(limitOffenders([{ path: file, text: "const bytes = 4 * 1024 * 1024;" }])).toEqual([`${file}: 4 * 1024 * 1024`]);
    expect(limitOffenders([{ path: LIMITS_CATALOG[0], text: "export const mediaBodyBytes = 4 * 1024 * 1024;" }])).toEqual([]);
    expect(limitOffenders([{ path: file, text: "z.string().min(1)" }])).toEqual([]);
    expect(limitOffenders([{ path: file, text: "Math.max(40, width)" }])).toEqual([]);
    expect(limitOffenders([{ path: file, text: "sql`BETWEEN 1 AND 40`" }])).toEqual([`${file}: BETWEEN 1 AND 40`]);
    expect(limitOffenders([{ path: file, text: "sql`BETWEEN 1 AND ${sql.raw(String(LIMITS.monogram))}`" }])).toEqual([]);
  });

  it("D-050: limits stay in the catalog", () => {
    const files = productionSources(repo);
    expect(limitOffenders(files)).toEqual([]);
    const schema = files.find((file) => file.path === "apps/web/src/platform/db/schema.ts");
    const pool = files.find((file) => file.path === "apps/web/src/platform/db/pool.ts");
    const oembed = files.find((file) => file.path === "apps/web/src/playback/server/oembed-resolver.ts");
    expect(schema?.text).toContain("BETWEEN ${sql.raw(String(EXTENT.one))} AND");
    expect(schema?.text).not.toContain("BETWEEN 1 AND");
    expect(schema?.text).not.toContain("<= 120");
    expect(pool?.text).toContain("connectionString: databaseUrl");
    expect(pool?.text).not.toContain("20_000");
    expect(oembed?.text).toContain("https://www.youtube.com/oembed");
    expect(oembed?.text).not.toContain("timeout(10_000)");
  });
});

describe("D-050 cache gate", () => {
  it("refuses a duration that is not a catalog key", () => {
    const file = "apps/web/src/example.ts";
    expect(cacheOffenders([{ path: file, text: "export const revalidate = 900;" }])).toEqual([`${file}: revalidate = 900`]);
    expect(cacheOffenders([{ path: file, text: "revalidate: false" }])).toEqual([`${file}: revalidate: false`]);
    expect(cacheOffenders([{ path: file, text: "export const revalidate = CACHE.homeSeconds;" }])).toEqual([]);
    expect(cacheOffenders([{ path: file, text: "export const revalidate = 300 satisfies typeof CACHE.homeSeconds;" }])).toEqual([]);
    expect(cacheOffenders([{ path: file, text: "export const revalidate = false satisfies typeof CACHE.untilTagged;" }])).toEqual([]);
    expect(cacheOffenders([{ path: CACHE_CATALOG[0], text: 'responseNoStore: "no-store"' }])).toEqual([]);
    expect(cacheOffenders([{ path: file, text: '"Cache-Control": "no-store"' }])).toEqual([`${file}: "no-store"`]);
    expect(cacheOffenders([{ path: file, text: "cache: CACHE.fetchNoStore" }])).toEqual([]);
    expect(cacheOffenders([{ path: file, text: "revalidateTag(tag, { expire: 0 })" }])).toEqual([`${file}: expire: 0`]);
    expect(cacheOffenders([{ path: file, text: "revalidateTag(tag, { expire: CACHE.immediateExpiry })" }])).toEqual([]);
    expect(cacheOffenders([{ path: file, text: '"public, max-age=86400, stale-while-revalidate=604800"' }])).toEqual([
      `${file}: max-age=86400`,
      `${file}: stale-while-revalidate=604800`,
    ]);
    expect(cacheOffenders([{ path: file, text: "cacheControlMaxAge: 31536000" }])).toEqual([`${file}: cacheControlMaxAge: 31536000`]);
    expect(cacheOffenders([{ path: "apps/web/next.config.ts", text: "minimumCacheTTL: 31536000" }])).toEqual(["apps/web/next.config.ts: minimumCacheTTL: 31536000"]);
    expect(cacheOffenders([{ path: file, text: "const bytes = 2 * 1024 * 1024;" }])).toEqual([`${file}: 2 * 1024 * 1024`]);
    expect(cacheOffenders([{ path: file, text: "Math.floor(1.5 * 1024 * 1024)" }])).toEqual([`${file}: 1.5 * 1024 * 1024`]);
    expect(cacheOffenders([{ path: file, text: "const body = 4 * 1024 * 1024;" }])).toEqual([]);
    expect(cacheOffenders([{ path: file, text: "const body = 1024 * 1024;" }])).toEqual([]);
    expect(cacheOffenders([{ path: file, text: "30 * 24 * 60 * 60" }])).toEqual([`${file}: 30 * 24 * 60 * 60`]);
    expect(cacheOffenders([{ path: file, text: "24 * 60 * 60 * 1000" }])).toEqual([`${file}: 24 * 60 * 60 * 1000`]);
    expect(cacheOffenders([{ path: file, text: "export const RETENTION_MS = 30 * 24 * 60 * 60 * 1000;" }])).toEqual([]);
  });

  it("D-050: cache durations stay in the catalog", () => {
    const files = productionSources(repo);
    files.push({ path: CACHE_CONFIG, text: readFileSync(join(repo, CACHE_CONFIG), "utf8") });
    expect(cacheOffenders(files)).toEqual([]);
    const home = files.find((file) => file.path === "apps/web/src/app/page.tsx");
    const credits = files.find((file) => file.path === "apps/web/src/app/credits/page.tsx");
    const settings = files.find((file) => file.path === "apps/web/src/identity/domain/settings.ts");
    expect(home?.text).toContain("export const revalidate = 300 satisfies typeof CACHE.homeSeconds");
    expect(home?.text).not.toMatch(/revalidate = 300;/);
    expect(credits?.text).toContain("export const revalidate = 86_400 satisfies typeof CACHE.directorySeconds");
    expect(credits?.text).not.toContain("revalidate = 86400");
    for (const file of files) {
      for (const match of file.text.matchAll(/revalidate\s*=\s*(\d[\d_]*|false)\s+satisfies\s+typeof\s+CACHE\.(\w+)/g)) {
        const raw = match[1] ?? "";
        const key = match[2] ?? "";
        const value = raw === "false" ? false : Number(raw.replaceAll("_", ""));
        expect(value, `${file.path} ${key}`).toBe(CACHE[key as keyof typeof CACHE]);
      }
    }
    expect(settings?.text).not.toContain("30 * 24 * 60 * 60");
    const catalog = readFileSync(join(repo, CACHE_CATALOG[0]), "utf8");
    expect(catalog).toContain("Visitor Home regenerates on this interval");
    expect(catalog).toContain("directorySeconds: 86_400");
    expect(catalog).toContain("mediaReadSeconds: 86_400");
    expect(catalog).toContain("publicAssetSeconds: 86_400");
    expect(catalog).toContain("fetch() cache mode that bypasses the HTTP cache");
    expect(catalog).toContain("expire: 0");
    expect(catalog).toContain("immediateExpiry: 0");
    expect(catalog).not.toContain("86400");
    const catalogInvalidate = files.find((file) => file.path === "apps/web/src/catalog/server/invalidate.ts");
    const mediaInvalidate = files.find((file) => file.path === "apps/web/src/media/server/invalidate.ts");
    expect(catalogInvalidate?.text).toContain("expire: CACHE.immediateExpiry");
    expect(catalogInvalidate?.text).not.toContain("expire: 0");
    expect(mediaInvalidate?.text).toContain("expire: CACHE.immediateExpiry");
    expect(mediaInvalidate?.text).not.toContain("expire: 0");
  });
});

describe("D-050 page gate", () => {
  it("refuses a page size that is not a catalog key", () => {
    const file = "apps/web/src/example.ts";
    expect(paginationOffenders([{ path: file, text: "SELECT sha256 FROM media_objects ORDER BY sha256 LIMIT 500" }])).toEqual([`${file}: LIMIT 500`]);
    expect(paginationOffenders([{ path: file, text: "SELECT 1 AS hit FROM catalog_media WHERE media_sha256 = $1 LIMIT 1" }])).toEqual([]);
    expect(paginationOffenders([{ path: file, text: "rows.length === 500" }])).toEqual([`${file}: rows.length === 500`]);
    expect(paginationOffenders([{ path: file, text: "rows.length < 500" }])).toEqual([`${file}: rows.length < 500`]);
    expect(paginationOffenders([{ path: file, text: "if (rows.length === 0) return;" }])).toEqual([]);
    expect(paginationOffenders([{ path: file, text: "if (pages > 10_000) break;" }])).toEqual([`${file}: pages > 10_000`]);
    expect(paginationOffenders([{ path: file, text: "if (pages > PAGINATION.maxStoragePages) break;" }])).toEqual([]);
    expect(paginationOffenders([{ path: file, text: "if (windows.size > 10_000) windows.clear();" }])).toEqual([]);
    expect(paginationOffenders([{ path: file, text: "const areaPosition = 1000;" }])).toEqual([]);
    expect(paginationOffenders([{ path: PAGINATION_CATALOG[0], text: "objectListPage: 500,\n  idempotencySweep: 500," }])).toEqual([]);
  });

  it("D-050: page sizes stay in the catalog", () => {
    const files = productionSources(repo);
    expect(paginationOffenders(files)).toEqual([]);
    const objects = files.find((file) => file.path === "apps/web/src/media/server/lifecycle.ts");
    const sweep = files.find((file) => file.path === "apps/web/src/catalog/server/mutation.ts");
    const walk = files.find((file) => file.path === "apps/web/src/media/domain/figure-exit.ts");
    expect(objects?.text).toContain("LIMIT ${String(PAGINATION.objectListPage)}");
    expect(objects?.text).not.toContain("LIMIT 500");
    expect(objects?.text).toContain("LIMIT 1");
    expect(objects?.text).not.toContain("rows.length === 500");
    expect(objects?.text).not.toContain("rows.length < 500");
    expect(sweep?.text).toContain("LIMIT ${String(PAGINATION.idempotencySweep)}");
    expect(sweep?.text).not.toContain("LIMIT 500");
    expect(sweep?.text).toContain("interval '30 days'");
    expect(walk?.text).toContain("pages > PAGINATION.maxStoragePages");
    expect(walk?.text).not.toContain("pages > 10_000");
    const catalog = readFileSync(join(repo, PAGINATION_CATALOG[0]), "utf8");
    expect(catalog).toContain("One page of media object keys");
    expect(catalog).toContain("Not the object-list page");
    expect(catalog).toContain("COURSE_LIST_LIMIT");
  });
});

describe("D-050 editorial words", () => {
  it("refuses a status or kind written outside the enum", () => {
    const file = "apps/web/src/example.ts";
    expect(editorialLooseWords([{ path: file, text: 'course.status === "published"' }])).toEqual([`${file}: "published"`]);
    expect(editorialLooseWords([{ path: file, text: 'kind: "background"' }])).toEqual([`${file}: "background"`]);
    expect(editorialLooseWords([{ path: file, text: 'author.kind !== "person"' }])).toEqual([`${file}: "person"`]);
    expect(editorialLooseWords([{ path: file, text: 'if (status === "draft") return;' }])).toEqual([`${file}: "draft"`]);
    expect(editorialLooseWords([{ path: file, text: 'video.provider === "youtube"' }])).toEqual([]);
    expect(editorialLooseWords([{ path: file, text: "lesson.part === \"labs\"" }])).toEqual([]);
    expect(editorialLooseWords([{ path: EDITORIAL_CATALOG[0], text: 'published: "published",' }])).toEqual([]);
  });

  it("D-050: the named editorial functions read the enum", () => {
    const files = productionSources(repo).filter((file) => (EDITORIAL_CALLS as readonly string[]).includes(file.path));
    expect(files.map((file) => file.path).sort()).toEqual([...EDITORIAL_CALLS].sort());
    expect(editorialLooseWords(files)).toEqual([]);
    expect(Object.keys(TEXT_FIELDS.lesson)).toEqual(["displayTitle", "about"]);
    const compile = files.find((file) => file.path.endsWith("/compile.ts"));
    const preview = files.find((file) => file.path.endsWith("/preview.ts"));
    const status = files.find((file) => file.path.endsWith("/rules/status.ts"));
    const queries = files.find((file) => file.path.endsWith("/queries.ts"));
    expect(compile?.text).toContain('provider === "youtube"');
    expect(compile?.text).toContain("course.status === courseStatus.published");
    expect(compile?.text).not.toContain('course.status === "published"');
    expect(preview?.text).toContain('provider === "youtube"');
    expect(status?.text).toContain('provider === "youtube"');
    expect(queries?.text).toContain("lesson.kind === lessonKind.background");
    expect(queries?.text).toContain('lesson.part === "labs"');
    expect(queries?.text).not.toContain('"background"');
  });
});

describe("D-050 extent", () => {
  it("refuses a bare empty result or a bare floor of one", () => {
    const file = "apps/web/src/example.ts";
    expect(extentOffenders([{ path: file, text: "if (rows.length === 0) return;" }])).toEqual([`${file}: .length === 0`]);
    expect(extentOffenders([{ path: file, text: "z.string().min(1)" }])).toEqual([`${file}: .min(1)`]);
    expect(extentOffenders([{ path: file, text: "sql`BETWEEN 1 AND ${sql.raw(String(LIMITS.monogram))}`" }])).toEqual([`${file}: BETWEEN 1 AND`]);
    expect(extentOffenders([{ path: file, text: "SELECT 1 AS hit FROM catalog_media LIMIT 1" }])).toEqual([]);
    expect(extentOffenders([{ path: file, text: "const origin = 0; const scale = Math.max(0, n);" }])).toEqual([]);
    expect(extentOffenders([{ path: file, text: "SELECT coalesce(max(position), 0) AS p FROM home_rows" }])).toEqual([]);
    expect(extentOffenders([{ path: EXTENT_CATALOG[0], text: "empty: 0,\n  one: 1," }])).toEqual([]);
  });

  it("D-050: the named extent calls read the keys", () => {
    const files = productionSources(repo).filter((file) => (EXTENT_CALLS as readonly string[]).includes(file.path));
    expect(files.map((file) => file.path).sort()).toEqual([...EXTENT_CALLS].sort());
    expect(extentOffenders(files)).toEqual([]);
    const table = files.find((file) => file.path.endsWith("/table-io.ts"));
    const contracts = files.find((file) => file.path.endsWith("/contracts.ts"));
    const schema = files.find((file) => file.path.endsWith("/platform/db/schema.ts"));
    const lifecycle = productionSources(repo).find((file) => file.path.endsWith("/media/server/lifecycle.ts"));
    expect(table?.text).not.toContain("rows.length === 0");
    expect(table?.text).toContain("rows[EXTENT.first]");
    expect(table?.text).toContain("coalesce(max(position), 0)");
    expect(contracts?.text).not.toContain(".min(1)");
    expect(contracts?.text).toContain(".min(EXTENT.one)");
    expect(schema?.text).not.toContain("BETWEEN 1 AND");
    expect(schema?.text).toContain("BETWEEN ${sql.raw(String(EXTENT.one))} AND");
    expect(lifecycle?.text).toContain("LIMIT 1");
  });
});

describe("D-050 color and spacing gates", () => {
  it("refuses a color or a length that is not a catalog value", () => {
    expect(colorOffenders([{ path: "apps/web/src/example.css", text: ".x { color: #fff; }" }])).toEqual(["apps/web/src/example.css: #fff"]);
    expect(colorOffenders([{ path: OG_MATTE_KEY_FILE, text: `export const ogMatte = "${OG_MATTE}";` }])).toEqual([]);
    expect(colorOffenders([{ path: OG_MATTE_KEY_FILE, text: 'export const ogMatte = "#ffffff";' }])).toEqual([`${OG_MATTE_KEY_FILE}: #ffffff`]);
    expect(colorOffenders([{ path: OG_MATTE_FILE, text: `background: "${OG_MATTE}"` }])).toEqual([`${OG_MATTE_FILE}: ${OG_MATTE}`]);
    expect(colorOffenders([{ path: OG_MATTE_FILE, text: 'background: "#ffffff"' }])).toEqual([`${OG_MATTE_FILE}: #ffffff`]);
    expect(spacingOffenders([{ path: "apps/web/src/example.css", text: "@media (min-width: 900px) {" }], catalogValues)).toEqual(["apps/web/src/example.css: 900px"]);
    expect(spacingOffenders([{ path: "apps/web/src/example.css", text: "@media (min-width: 1024px) {" }], catalogValues)).toEqual([]);
    expect(spacingOffenders([{ path: "apps/web/src/example.ts", text: "const width = \"12px\";" }], catalogValues)).toEqual(["apps/web/src/example.ts: 12px"]);
    expect(spacingOffenders([{ path: "apps/web/src/example.css", text: "width: var(--tower-layout-gutter-tablet);" }], catalogValues)).toEqual([]);
  });

  it("D-050: color and spacing stay green except the link-preview matte", () => {
    const files = productionSources(repo);
    expect(colorOffenders(files)).toEqual([]);
    expect(spacingOffenders(files, catalogValues)).toEqual([]);
    expect(ogMatte).toBe(OG_MATTE);
    const key = files.find((file) => file.path === OG_MATTE_KEY_FILE);
    const matte = files.find((file) => file.path === OG_MATTE_FILE);
    expect(key?.text).toContain(OG_MATTE);
    expect(matte?.text).not.toContain(OG_MATTE);
    const theme = readFileSync(new URL("../../src/ui/tokens/layout.ts", import.meta.url), "utf8");
    expect(theme).not.toContain(OG_MATTE);
    expect(theme).not.toContain("#0c0c0d");
  });
});
