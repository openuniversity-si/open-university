import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { architectureHalves, checkArchitecture, defaultRules, muxTombstones } from "../../tooling/check-architecture.mjs";

// Verifies: D-001
const roots: string[] = [];
function fixture(files: Record<string, string>) {
  const root = mkdtempSync(join(tmpdir(), "tower-architecture-")); roots.push(root);
  for (const [file, content] of Object.entries(files)) {
    const path = join(root, file.startsWith("apps/") ? file : `apps/web/src/${file}`);
    mkdirSync(dirname(path), { recursive: true }); writeFileSync(path, content);
  }
  return root;
}
const run = (root: string, id: string) => checkArchitecture({ root, rules: defaultRules.filter((rule) => rule.id === id) });
const violation = (rule: string, file: string, detail: string, line = 1) => ({ rule, file: `apps/web/src/${file}`, line, detail });
afterEach(() => { for (const root of roots.splice(0)) rmSync(root, { recursive: true, force: true }); });

describe("architecture v1", () => {
  it("INV-M3: rejects a second cover resolver and cover SQL outside the media adapter", () => {
    const root = fixture({
      "catalog/domain/cover-resolve.ts": "export function resolveCover() {}",
      "catalog/domain/other-cover.ts": "export const resolveCover = () => undefined;",
      "catalog/server/covers.ts": 'db.query("SELECT * FROM catalog_media");',
      "media/server/asset-reads.ts": 'db.query("SELECT * FROM catalog_media");',
      "catalog/domain/other-cover.test.ts": "function resolveCover() {}",
    });
    expect(run(root, "L6.single-cover-resolver")).toEqual([
      violation("L6.single-cover-resolver", "catalog/domain/other-cover.ts", "cover decisions belong to catalog/domain/cover-resolve.ts"),
      violation("L6.single-cover-resolver", "catalog/server/covers.ts", "cover rows are read only by the media adapter"),
    ]);
  });
  it("L3.source-registry keeps the YouTube id pattern on the lesson", () => {
    const pattern = "export const youtubeIdSchema = z.string().regex(/^[A-Za-z0-9_-]{11}$/);";
    const owner = `catalog/domain/youtube-identity.ts`;
    const driver = `playback/domain/drivers/youtube.ts`;
    const registry = `playback/server/source-registry.ts`;
    const registryBody = "export const drivers = [youtubeSourceDriver, institutionalUrlDriver];";
    const lesson = { [owner]: pattern, [driver]: 'import { youtubeIdSchema } from "../../../catalog/domain/youtube-identity.ts";\nexport { youtubeIdSchema };', [registry]: registryBody };
    expect(run(fixture(lesson), "L3.source-registry")).toEqual([]);
    const copied = { ...lesson, "catalog/domain/release.ts": pattern };
    expect(run(fixture(copied), "L3.source-registry")).toEqual([
      violation("L3.source-registry", "catalog/domain/release.ts", "youtube id pattern is copied outside the lesson"),
    ]);
    const playerCopy = { ...lesson, [driver]: pattern };
    expect(run(fixture(playerCopy), "L3.source-registry")).toEqual([
      violation("L3.source-registry", driver, "the player imports the lesson video id"),
      violation("L3.source-registry", driver, "youtube id pattern is copied in the player"),
    ]);
    const asking = { ...lesson, "catalog/domain/release.ts": 'import { youtubeIdSchema } from "../../playback/domain/drivers/youtube.ts";' };
    expect(run(fixture(asking), "L3.source-registry")).toEqual([
      violation("L3.source-registry", "catalog/domain/release.ts", "catalog domain does not import the youtube driver"),
    ]);
    const playbackCopy = { ...lesson, "playback/domain/other.ts": pattern };
    expect(run(fixture(playbackCopy), "L3.source-registry")).toEqual([
      violation("L3.source-registry", "playback/domain/other.ts", "youtube id pattern is copied outside the lesson"),
    ]);
  });
  it("L3.no-retired-paths lists the retired media paths", () => {
    const root = fixture({ "catalog/server/legacy.ts": 'db.query("SELECT id FROM course_assets");' });
    const listed = "retired media path: course_assets, lesson_assets, subarea_assets, authors.media_sha256, home_rows.media_sha256, home_rows.og_media_sha256";
    expect(run(root, "L3.no-retired-paths")).toEqual([violation("L3.no-retired-paths", "catalog/server/legacy.ts", listed)]);
    expect(run(fixture({ "kernel/a.ts": "export const a = 1;" }), "L3.no-retired-paths")).toEqual([]);
  });
  it("enforces every architecture rule on the real tree", () => {
    expect(checkArchitecture({ root: resolve(import.meta.dirname, "../../../..") })).toEqual([]);
  });
  it("rejects kernel dependencies on contexts while allowing production kernel and Node imports", () => {
    const root = fixture({ "kernel/a.ts": 'import { b } from "../catalog/b.ts";\nimport "node:crypto";\nexport { c } from "./c";', "kernel/c.ts": "export const c = 1;", "catalog/b.ts": "export const b = 1;" });
    expect(run(root, "L1.kernel-pure")).toEqual([violation("L1.kernel-pure", "kernel/a.ts", "../catalog/b.ts")]);
  });
  it("allows kernel tests to import Vitest, Node and contexts, without contaminating the production graph", () => {
    const root = fixture({ "kernel/a.test.ts": 'import "vitest"; import "node:fs"; import "@/catalog/read";', "kernel/a.ts": 'import "node:crypto";' });
    expect(run(root, "L1.kernel-pure")).toEqual([]);
  });
  it("keeps client kernel modules import free and rejects imports of kernel tests", () => {
    const root = fixture({ "kernel/brand-ids.ts": 'import "node:crypto";', "kernel/errors.ts": 'import "./helper";', "kernel/slug.ts": 'import "./helper";', "kernel/a.ts": 'export * from "./a.test";', "kernel/a.test.ts": "", "kernel/helper.ts": "" });
    expect(run(root, "L1.kernel-pure")).toEqual([
      violation("L1.kernel-pure", "kernel/a.ts", "./a.test"), violation("L1.kernel-pure", "kernel/brand-ids.ts", "node:crypto"), violation("L1.kernel-pure", "kernel/errors.ts", "./helper"), violation("L1.kernel-pure", "kernel/slug.ts", "./helper"),
    ]);
  });
  it("rejects production reexports and dynamic/side-effect imports of testing through relative and @/ paths", () => {
    const root = fixture({ "catalog/a.ts": 'export { fake } from "./testing/fake";\nimport("@/media/testing/fake.ts");\nimport "./testing/fake.ts";', "catalog/testing/fake.ts": "", "media/testing/fake.ts": "" });
    expect(run(root, "L1.testing-isolated")).toEqual([
      violation("L1.testing-isolated", "catalog/a.ts", "./testing/fake"), violation("L1.testing-isolated", "catalog/a.ts", "@/media/testing/fake.ts", 2), violation("L1.testing-isolated", "catalog/a.ts", "./testing/fake.ts", 3),
    ]);
  });
  it("excludes test origins but rejects production routes under (test)", () => {
    const root = fixture({ "catalog/a.test.ts": 'import "./testing/fake";', "catalog/testing/a.ts": 'export * from "./fake";', "app/(test)/page.test.tsx": 'import "@/catalog/testing/fake";', "app/(test)/page.tsx": "", "app/(test)/api/route.ts": "" });
    expect(run(root, "L1.testing-isolated")).toEqual([
      violation("L1.testing-isolated", "app/(test)/api/route.ts", "production route in test tree"), violation("L1.testing-isolated", "app/(test)/page.tsx", "production route in test tree"),
    ]);
  });
  it("tombstones all 14 paths even without importers and detects references to absent modules", () => {
    for (const path of muxTombstones) {
      const root = fixture({ [path]: "", "playback/a.test.ts": 'import "./token";' });
      const expected = [{ rule: "L1.mux-tombstone", file: path, line: 1, detail: "removed module exists" }, violation("L1.mux-tombstone", "playback/a.test.ts", "./token")];
      expect(run(root, "L1.mux-tombstone")).toEqual(expect.arrayContaining(expected));
      expect(run(root, "L1.mux-tombstone")).toHaveLength(2);
    }
  });
  it("detects extensionless removed TSX references in tooling and normalizes alias traversal", () => {
    const removedTsx = muxTombstones.find((path) => path.endsWith(".tsx"));
    expect(removedTsx).toBeDefined();
    const specifier = `../${removedTsx?.replace("apps/web/", "").replace(/\.tsx$/, "") ?? "missing"}`;
    const root = fixture({ "apps/web/scripts/probe.ts": `import "${specifier}";`, "kernel/a.ts": 'import "@/site/../catalog/read";' });
    expect(run(root, "L1.mux-tombstone")).toEqual([{ rule: "L1.mux-tombstone", file: "apps/web/scripts/probe.ts", line: 1, detail: specifier }]);
    expect(run(root, "L1.kernel-pure")).toEqual([violation("L1.kernel-pure", "kernel/a.ts", "@/site/../catalog/read")]);
  });
  it("rejects retired catalog JSON imports including tests and fixtures", () => {
    const root = fixture({ "catalog/a.test.ts": 'import "./schema.ts";', "catalog/a.ts": 'export * from "./load";\nimport data from "../../content/catalog/courses.json";', "catalog/testing/fake.ts": 'import "../../../content/catalog/snapshot/release.json";', "catalog/b.test.ts": 'import "../../content/catalog/courses.json";' });
    expect(run(root, "L1.legacy-catalog-out")).toEqual([
      violation("L1.legacy-catalog-out", "catalog/a.test.ts", "./schema.ts"), violation("L1.legacy-catalog-out", "catalog/a.ts", "./load"), violation("L1.legacy-catalog-out", "catalog/a.ts", "../../content/catalog/courses.json", 2),
      violation("L1.legacy-catalog-out", "catalog/b.test.ts", "../../content/catalog/courses.json"),
      violation("L1.legacy-catalog-out", "catalog/testing/fake.ts", "../../../content/catalog/snapshot/release.json"),
    ]);
  });
  it("keeps identity, playback and progress rings free of server edges", () => {
    const root = fixture({
      "playback/domain/engine.ts": 'import { start } from "../server/run.ts";\nexport const engine = start;',
      "playback/server/run.ts": "export const start = 1;",
      "playback/ports/engine.ts": 'import type { Engine } from "../domain/engine.ts";\nexport type Port = Engine;',
    });
    expect(run(root, "L3.inner-pure")).toEqual([violation("L3.inner-pure", "playback/domain/engine.ts", "../server/run.ts")]);
    expect(run(root, "L3.context-layout")).toEqual([]);
  });
  it("rejects type imports of the database from domain and ports", () => {
    const root = fixture({
      "catalog/domain/transition.ts": 'import type { UnitOfWork } from "../../platform/db/uow.ts";\nexport type Tx = UnitOfWork;',
      "catalog/ports/commands.ts": 'import type { Pool } from "pg";\nexport type P = Pool;',
      "media/ports/owner.ts": 'import type { SQL } from "drizzle-orm";\nexport type S = SQL;',
      "platform/db/uow.ts": "export interface UnitOfWork { query(): void }",
    });
    expect(run(root, "L3.inner-pure")).toEqual([
      violation("L3.inner-pure", "catalog/domain/transition.ts", "../../platform/db/uow.ts"),
      violation("L3.inner-pure", "catalog/ports/commands.ts", "pg"),
      violation("L3.inner-pure", "media/ports/owner.ts", "drizzle-orm"),
    ]);
  });
  it("rejects JSON and platform imports from production domain", () => {
    const root = fixture({
      "catalog/domain/fallback.ts": 'import generated from "./generated/release.json" with { type: "json" };\nexport const baked = generated;',
      "catalog/domain/contracts.ts": 'export { REQUEST_ID_HEADER } from "../../platform/observability/context.ts";',
      "catalog/domain/config/index.ts": 'import values from "./values.json" with { type: "json" };\nexport const title = values;',
      "catalog/ports/queries.ts": 'import { log } from "../../platform/observability/logger.ts";\nexport const x = log;',
      "platform/observability/context.ts": "export const REQUEST_ID_HEADER = 'x';",
      "platform/observability/logger.ts": "export const log = 1;",
    });
    expect(run(root, "L3.inner-pure")).toEqual([
      violation("L3.inner-pure", "catalog/domain/contracts.ts", "../../platform/observability/context.ts"),
      violation("L3.inner-pure", "catalog/domain/fallback.ts", "./generated/release.json"),
    ]);
  });
  it("rejects type imports of next from domain and ports", () => {
    const root = fixture({
      "site/domain/metadata.ts": 'import type { Metadata } from "next";\nexport type M = Metadata;',
      "catalog/ports/queries.ts": 'import type { MetadataRoute } from "next/types";\nexport type M = MetadataRoute;',
    });
    expect(run(root, "L3.inner-pure")).toEqual([
      violation("L3.inner-pure", "catalog/ports/queries.ts", "next/types"),
      violation("L3.inner-pure", "site/domain/metadata.ts", "next"),
    ]);
  });
  it("rejects SQL in a server module that imports Next or React", () => {
    const root = fixture({
      "catalog/server/read.ts": 'import { unstable_cache } from "next/cache";\nexport const read = (db) => db.query("SELECT 1");',
      "catalog/server/cache.ts": 'import { unstable_cache } from "next/cache";\nexport const read = () => unstable_cache;',
      "catalog/server/repo.ts": 'export const read = (db) => db.query("SELECT 1");',
      "catalog/server/read.test.ts": 'import { unstable_cache } from "next/cache";\nexport const read = (db) => db.query("SELECT 1");',
      "media/server/index.ts": 'import { cache } from "react";\nexport const read = (db) => db.query("SELECT 1");',
    });
    expect(run(root, "L7.cache-no-sql")).toEqual([
      violation("L7.cache-no-sql", "catalog/server/read.ts", ".query(", 2),
      violation("L7.cache-no-sql", "media/server/index.ts", ".query(", 2),
    ]);
  });
  it("rejects SQL in a handler once that handler is listed", () => {
    const root = fixture({
      "catalog/server/ship-batch.ts": 'export const write = (db) => db.query("INSERT INTO lessons");',
      "catalog/server/courses.ts": 'export const write = (db) => db.query("INSERT INTO courses");',
      "catalog/server/lessons.ts": 'export const write = (db) => db.query("INSERT INTO lessons");',
      "catalog/server/authors.ts": 'export const write = (db) => db.query("INSERT INTO authors");',
      "catalog/server/texts.ts": 'export const write = (db) => db.query("INSERT INTO texts");',
      "catalog/server/home.ts": 'export const write = (db) => db.query("INSERT INTO home_rows");',
      "catalog/server/deletion.ts": 'export const write = (db) => db.query("DELETE FROM courses");',
      "catalog/server/bundle-apply.ts": 'export const write = (db) => db.query("INSERT INTO courses");',
      "catalog/server/batch-apply.ts": 'export const write = (db) => db.query("INSERT INTO courses");',
      "catalog/server/doctor.ts": 'export const write = (db) => db.query("SELECT 1");',
      "catalog/server/list-projection.ts": 'export const write = (db) => db.query("SELECT 1");',
      "catalog/server/cover-kinds.ts": 'export const write = (db) => db.query("SELECT 1");',
      "catalog/server/editions.ts": 'export const write = (db) => db.query("SELECT 1");',
    });
    expect(run(root, "L7.handler-no-sql")).toEqual([
      violation("L7.handler-no-sql", "catalog/server/authors.ts", ".query("),
      violation("L7.handler-no-sql", "catalog/server/batch-apply.ts", ".query("),
      violation("L7.handler-no-sql", "catalog/server/bundle-apply.ts", ".query("),
      violation("L7.handler-no-sql", "catalog/server/courses.ts", ".query("),
      violation("L7.handler-no-sql", "catalog/server/cover-kinds.ts", ".query("),
      violation("L7.handler-no-sql", "catalog/server/deletion.ts", ".query("),
      violation("L7.handler-no-sql", "catalog/server/doctor.ts", ".query("),
      violation("L7.handler-no-sql", "catalog/server/home.ts", ".query("),
      violation("L7.handler-no-sql", "catalog/server/lessons.ts", ".query("),
      violation("L7.handler-no-sql", "catalog/server/list-projection.ts", ".query("),
      violation("L7.handler-no-sql", "catalog/server/ship-batch.ts", ".query("),
      violation("L7.handler-no-sql", "catalog/server/texts.ts", ".query("),
    ]);
  });
  it("rejects a listed catalog server import of media/server", () => {
    const root = fixture({
      "catalog/server/read.ts": 'import { readObjects } from "../../media/server/objects.ts";\nexport const read = readObjects;',
      "catalog/server/authors.ts": 'import { syncInstitutionCover } from "../../media/server/institution-cover.ts";\nexport const write = syncInstitutionCover;',
      "catalog/server/batch-apply.ts": 'import { attachCoverSet } from "../../media/server/attach-set.ts";\nexport const write = attachCoverSet;',
      "catalog/server/courses.ts": 'import { lockMediaOwners } from "../../media/server/media-locks.ts";\nexport const lock = lockMediaOwners;',
      "catalog/server/cover-kinds.ts": 'import { activeAssetRows } from "../../media/server/asset-reads.ts";\nexport const read = activeAssetRows;',
      "catalog/server/deletion.ts": 'import { ownedMedia } from "../../media/server/repository.ts";\nexport const read = ownedMedia;',
      "catalog/server/doctor.ts": 'import { diagnoseMedia } from "../../media/server/diagnose.ts";\nexport const read = diagnoseMedia;',
      "catalog/server/home.ts": 'import { validateObject } from "../../media/server/asset-reads.ts";\nexport const read = validateObject;',
      "catalog/server/media.ts": 'import { getCourseMedia } from "../../media/server/index.ts";\nexport const read = getCourseMedia;',
      "catalog/server/reference.ts": 'import { activeSubareaCovers } from "../../media/server/asset-reads.ts";\nexport const read = activeSubareaCovers;',
      "catalog/server/bundle-apply.ts": 'import { lockMediaOwners } from "../../media/server/media-locks.ts";\nexport const lock = lockMediaOwners;',
      "media/server/objects.ts": "export const readObjects = 1;",
      "media/server/index.ts": "export const getCourseMedia = 1;",
      "media/server/media-locks.ts": "export const lockMediaOwners = 1;",
    });
    expect(run(root, "L7.catalog-no-media-server")).toEqual([
      violation("L7.catalog-no-media-server", "catalog/server/authors.ts", "../../media/server/institution-cover.ts"),
      violation("L7.catalog-no-media-server", "catalog/server/batch-apply.ts", "../../media/server/attach-set.ts"),
      violation("L7.catalog-no-media-server", "catalog/server/courses.ts", "../../media/server/media-locks.ts"),
      violation("L7.catalog-no-media-server", "catalog/server/cover-kinds.ts", "../../media/server/asset-reads.ts"),
      violation("L7.catalog-no-media-server", "catalog/server/deletion.ts", "../../media/server/repository.ts"),
      violation("L7.catalog-no-media-server", "catalog/server/doctor.ts", "../../media/server/diagnose.ts"),
      violation("L7.catalog-no-media-server", "catalog/server/home.ts", "../../media/server/asset-reads.ts"),
      violation("L7.catalog-no-media-server", "catalog/server/media.ts", "../../media/server/index.ts"),
      violation("L7.catalog-no-media-server", "catalog/server/read.ts", "../../media/server/objects.ts"),
      violation("L7.catalog-no-media-server", "catalog/server/reference.ts", "../../media/server/asset-reads.ts"),
    ]);
  });
  it("rejects catalog HTTP imports of another context's server", () => {
    const root = fixture({
      "catalog/server/http.ts": 'import type { MediaObjectStore } from "../../media/server/storage.ts";\nimport type { OEmbed } from "../../playback/server/oembed-resolver.ts";\nimport type { Store } from "../../media/ports/storage.ts";',
      "media/server/storage.ts": "export interface MediaObjectStore {}",
      "media/ports/storage.ts": "export interface Store {}",
      "playback/server/oembed-resolver.ts": "export interface OEmbed {}",
    });
    expect(run(root, "L7.catalog-http-ports")).toEqual([
      violation("L7.catalog-http-ports", "catalog/server/http.ts", "../../media/server/storage.ts"),
      violation("L7.catalog-http-ports", "catalog/server/http.ts", "../../playback/server/oembed-resolver.ts", 2),
    ]);
  });
  it("allows next/headers only in app routes", () => {
    const root = fixture({
      "app/layout.tsx": 'import { draftMode } from "next/headers";\nexport const layout = draftMode;',
      "catalog/server/draft.ts": 'import { cookies } from "next/headers";\nexport const read = cookies;',
      "identity/server/session.ts": 'import { headers } from "next/headers";\nexport const read = headers;',
      "site/server/guard.ts": 'import { notFound } from "next/navigation";\nexport const guard = notFound;',
    });
    expect(run(root, "L7.cache-no-sql")).toEqual([
      violation("L7.cache-no-sql", "catalog/server/draft.ts", "next/headers"),
      violation("L7.cache-no-sql", "identity/server/session.ts", "next/headers"),
    ]);
  });
  it("rejects every production site import of catalog, including type and dynamic imports", () => {
    const root = fixture({ "site/domain/route-registry.ts": "export const routes = 1;", "site/new.ts": 'import "@tower/catalog";\nimport type { X } from "@/catalog/queries";\nimport("../catalog/read");' });
    expect(run(root, "L2.site-no-catalog")).toEqual([
      violation("L2.site-no-catalog", "site/new.ts", "@tower/catalog"),
      violation("L2.site-no-catalog", "site/new.ts", "@/catalog/queries", 2),
      violation("L2.site-no-catalog", "site/new.ts", "../catalog/read", 3),
    ]);
  });
  it("keeps pool construction, console and Error subclasses inside the platform", () => {
    const root = fixture({
      "platform/db/pool.ts": "export const pool = new pg.Pool({});",
      "platform/observability/logger.ts": "console.error('ok');",
      "kernel/errors.ts": "export class AppError extends Error {}",
      "catalog/server/mutation.ts": "export class IdempotentReplay extends Error {}\nexport class Other extends Error {}",
      "auth/config.ts": "export const pool = new pg.Pool({});\nconsole.log('x');",
      "media/storage.ts": "export class MediaInputError extends Error {}",
    });
    expect(run(root, "L1.single-pool")).toEqual([violation("L1.single-pool", "auth/config.ts", "pool construction outside platform")]);
    expect(run(root, "L1.logger-only")).toEqual([violation("L1.logger-only", "auth/config.ts", "console outside logger", 2)]);
    expect(run(root, "L1.app-error")).toEqual([
      violation("L1.app-error", "catalog/server/mutation.ts", "error outside AppError taxonomy", 2),
      violation("L1.app-error", "media/storage.ts", "error outside AppError taxonomy"),
    ]);
  });
  it("lets platform code reach the kernel and forbids the contexts above it", () => {
    const root = fixture({
      "platform/db/errors.ts": 'import { AppError } from "../../kernel/errors.ts";\nimport type { Row } from "pg";',
      "platform/security/rate-limit.ts": 'import { appPool } from "../../catalog/read.ts";',
      "kernel/errors.ts": "export class AppError extends Error {}",
      "catalog/read.ts": "export const appPool = () => undefined;",
    });
    expect(run(root, "L1.platform-down")).toEqual([violation("L1.platform-down", "platform/security/rate-limit.ts", "../../catalog/read.ts")]);
  });
  it("rejects SQL in the production kernel and cover-owner names in platform/db outside the schema", () => {
    const root = fixture({
      "kernel/query.ts": "export const q = `SELECT id`;\nexport const row = pgTable('t', {});\nexport const write = `INSERT INTO t`;",
      "kernel/query.test.ts": "export const q = `SELECT id`;",
      "platform/db/schema.ts": "export const check = `owner_kind in ('course', 'lesson')`;",
      "platform/db/uow.ts": 'export type Lock = { owner: "institution" | "area" | "subarea" | "course" | "lesson" };',
      "platform/db/locks.ts": "export const column = 'owner_kind';",
      "platform/db/owner.ts": "export const lock = { owner: 'lesson' };",
    });
    expect(run(root, "L1.no-cover-sql")).toEqual([
      violation("L1.no-cover-sql", "kernel/query.ts", "kernel does not emit SQL"),
      violation("L1.no-cover-sql", "kernel/query.ts", "kernel does not emit SQL", 2),
      violation("L1.no-cover-sql", "kernel/query.ts", "kernel does not emit SQL", 3),
      violation("L1.no-cover-sql", "platform/db/locks.ts", "platform/db does not name a cover owner"),
      violation("L1.no-cover-sql", "platform/db/owner.ts", "platform/db does not name a cover owner"),
      violation("L1.no-cover-sql", "platform/db/uow.ts", "platform/db does not name a cover owner"),
    ]);
    expect(run(fixture({
      "kernel/cover-kinds.ts": "export const owners = ['institution', 'area', 'subarea', 'course', 'lesson'] as const;",
      "platform/db/uow.ts": 'import type { CoverOwner } from "../../kernel/cover-kinds.ts";\nexport type Lock = { owner: CoverOwner };',
      "platform/db/schema.ts": "export const sql = `SELECT owner_kind`;\nexport const table = pgTable('catalog_media', {});",
    }), "L1.no-cover-sql")).toEqual([]);
  });
  it("blocks backend production and tests from importing ui, except the credits fixture", () => {
    const root = fixture({
      "auth/a.ts": 'import { Nav } from "../ui/TopNav/TopNav";',
      "catalog/domain/credits.test.ts": 'import { Footer } from "../../ui/Footer/Footer";',
      "site/pages/legal.test.ts": 'import { Footer } from "../../ui/Footer/Footer";',
      "progress/view.test.ts": 'import { Card } from "../ui/CourseCard/CourseCard";',
      "ui/TopNav/TopNav.tsx": "export const Nav = 1;",
      "ui/Footer/Footer.tsx": "export const Footer = 1;",
      "ui/CourseCard/CourseCard.tsx": "export const Card = 1;",
    });
    expect(run(root, "L1.no-backend-to-ui")).toEqual([
      violation("L1.no-backend-to-ui", "auth/a.ts", "../ui/TopNav/TopNav"),
      violation("L1.no-backend-to-ui", "progress/view.test.ts", "../ui/CourseCard/CourseCard"),
      violation("L1.no-backend-to-ui", "site/pages/legal.test.ts", "../../ui/Footer/Footer"),
    ]);
  });
  it("keeps CSS modules inside ui and app", () => {
    const root = fixture({
      "auth/panel.tsx": 'import "./panel.module.css";',
      "ui/identity/panel.tsx": 'import "./panel.module.css";',
      "app/layout.tsx": 'import "./globals.css";',
    });
    expect(run(root, "L1.no-css-in-backend")).toEqual([violation("L1.no-css-in-backend", "auth/panel.tsx", "./panel.module.css")]);
  });
  it("keeps the progress domain on its rules and the kernel", () => {
    const root = fixture({
      "progress/domain/view.ts": 'import { courseProgress } from "./rules.ts";\nimport { slug } from "../../kernel/slug.ts";\nimport { home } from "../../catalog/domain/home.ts";',
      "progress/domain/rules.ts": "export const courseProgress = 1;",
      "kernel/slug.ts": "export const slug = 1;",
      "catalog/domain/home.ts": "export const home = 1;",
    });
    expect(run(root, "L1.progress-domain-pure")).toEqual([violation("L1.progress-domain-pure", "progress/domain/view.ts", "../../catalog/domain/home.ts", 3)]);
  });
  it("keeps the shelf off playback, progress, identity and the factory domain", () => {
    const root = fixture({
      "playback/domain/player.ts": 'import { home } from "../../catalog/domain/home.ts";',
      "progress/domain/view.ts": 'import { universities } from "../../catalog/domain/universities.ts";',
      "identity/domain/account.ts": 'import { countries } from "../../catalog/domain/countries.ts";',
      "factory/domain/batch.ts": 'import { view } from "../../catalog/domain/view-model.ts";',
      "catalog/domain/rules/draw.ts": 'import { home } from "../home.ts";\nimport { universities } from "../universities.ts";\nimport { countries } from "../countries.ts";',
      "catalog/domain/home.ts": "export const home = 1;",
      "catalog/domain/universities.ts": "export const universities = 1;",
      "catalog/domain/countries.ts": "export const countries = 1;",
      "catalog/domain/view-model.ts": "export const view = 1;",
      "app/page.tsx": 'import { home } from "../catalog/domain/home.ts";',
    });
    expect(run(root, "L1.shelf-boundary")).toEqual([
      violation("L1.shelf-boundary", "catalog/domain/rules/draw.ts", "rules do not draw the shelf"),
      violation("L1.shelf-boundary", "catalog/domain/rules/draw.ts", "rules do not draw the shelf", 2),
      violation("L1.shelf-boundary", "factory/domain/batch.ts", "the shelf is not imported here"),
      violation("L1.shelf-boundary", "identity/domain/account.ts", "the shelf is not imported here"),
      violation("L1.shelf-boundary", "playback/domain/player.ts", "the shelf is not imported here"),
      violation("L1.shelf-boundary", "playback/domain/player.ts", "the player imports only the video id pattern"),
      violation("L1.shelf-boundary", "progress/domain/view.ts", "the shelf is not imported here"),
    ]);
    const media = fixture({ "media/domain/group.ts": 'import { resolveCover } from "../../catalog/domain/cover-resolve.ts";' });
    expect(run(media, "L1.shelf-boundary")).toEqual([
      violation("L1.shelf-boundary", "media/domain/group.ts", "media domain does not import catalog"),
    ]);
  });
  it("names the lesson summary as the case that is not built", () => {
    const root = fixture({
      "playback/domain/drivers/youtube.ts": 'import { youtubeIdSchema } from "../../../catalog/domain/youtube-identity.ts";\nexport const id = youtubeIdSchema;',
      "playback/domain/summary.ts": 'import { cleanLessonSlug } from "../../catalog/domain/lesson-address.ts";\nexport const slug = cleanLessonSlug;',
      "playback/domain/fresh.ts": "export const VIDEO_CHECK_FRESH_DAYS = 7;",
      "media/domain/read.ts": 'import { TEXT_FIELDS } from "../../kernel/text-fields.ts";\nexport const fields = TEXT_FIELDS;',
      "progress/domain/view.ts": 'import { videoCheckCutoff } from "../../catalog/domain/lesson-video.ts";\nexport const cutoff = videoCheckCutoff;',
      "catalog/domain/youtube-identity.ts": "export const youtubeIdSchema = 1;",
      "catalog/domain/lesson-address.ts": "export const cleanLessonSlug = 1;",
      "catalog/domain/lesson-video.ts": "export const videoCheckCutoff = 1;",
      "kernel/text-fields.ts": "export const TEXT_FIELDS = {\n  lesson: {\n    displayTitle: {},\n    about: {},\n  },\n  author: {},\n};\n",
      "catalog/domain/rules/publish-answers.ts": "export function lessonVideoCheckAnswer() { return { owner: LESSON }; }\nexport function lessonAboutAnswer() { return { owner: LESSON }; }",
    });
    expect(run(root, "L1.shelf-boundary")).toEqual([
      violation("L1.shelf-boundary", "catalog/domain/rules/publish-answers.ts", "the lesson has one publish answer, the video check"),
      violation("L1.shelf-boundary", "catalog/domain/rules/publish-answers.ts", "lesson text about is not its own publish answer"),
      violation("L1.shelf-boundary", "media/domain/read.ts", "the lesson summary is not built here"),
      violation("L1.shelf-boundary", "playback/domain/fresh.ts", "the lesson summary is not built here"),
      violation("L1.shelf-boundary", "playback/domain/summary.ts", "the lesson summary is not built here"),
      violation("L1.shelf-boundary", "playback/domain/summary.ts", "the player imports only the video id pattern"),
      violation("L1.shelf-boundary", "progress/domain/view.ts", "the lesson summary is not built here"),
    ]);
  });
  it("rejects a catalog domain value import of progress", () => {
    const root = fixture({
      "catalog/domain/progress-reading.ts": 'import { courseProgressView } from "../../progress/domain/view.ts";\nexport const reading = courseProgressView;',
      "catalog/domain/home.ts": 'import type { CourseProgressView } from "../../progress/domain/view.ts";\nexport type View = CourseProgressView;',
      "catalog/domain/schema.test.ts": 'import { courseProgress } from "../../progress/domain/rules.ts";\nexport const rows = courseProgress;',
      "progress/domain/view.ts": "export const courseProgressView = 1;\nexport type CourseProgressView = number;",
      "progress/domain/rules.ts": "export const courseProgress = 1;",
    });
    expect(run(root, "L1.catalog-no-progress-value")).toEqual([
      violation("L1.catalog-no-progress-value", "catalog/domain/progress-reading.ts", "catalog domain does not value-import progress"),
    ]);
  });
  it("keeps site JSON behind the server loader and out of client components", () => {
    const root = fixture({
      "site/server/site-data.ts": 'import data from "../../../content/site/site-data.v2.json";\nexport const siteData = () => data;',
      "site/domain/site-data.test.ts": 'import data from "../../../content/site/site-data.v2.json";',
      "catalog/read.ts": 'import data from "../../content/site/site-data.v2.json";',
      "ui/Footer/Footer.tsx": '"use client";\nimport { siteData } from "../../site/server/site-data";\nexport const Footer = siteData;',
      "site/pages/legal.ts": "export const page = 1;",
      "ui/Footer/copy.ts": "export const links = [];",
    });
    expect(run(root, "L1.site-data-boundary")).toEqual([violation("L1.site-data-boundary", "catalog/read.ts", "../../content/site/site-data.v2.json")]);
    expect(run(root, "L1.client-no-site-data")).toEqual([violation("L1.client-no-site-data", "ui/Footer/Footer.tsx", "../../site/server/site-data", 2)]);
    expect(run(root, "L1.no-site-pages")).toEqual([
      violation("L1.no-site-pages", "site/pages/legal.ts", "institutional copy still lives in code"),
      violation("L1.no-site-pages", "ui/Footer/copy.ts", "institutional copy still lives in code"),
    ]);
  });
  it("keeps SQL on the table owner and catalog out of media and progress", () => {
    const root = fixture({
      "media/server/read.ts": 'export const read = (db: { query(sql: string): Promise<unknown> }) => db.query("SELECT id FROM courses");',
      "media/testing/fake.ts": 'import { home } from "../../catalog/domain/home.ts";\nexport const homeRows = home;',
      "progress/server.ts": 'import { getCatalog } from "@tower/catalog";\nexport const load = getCatalog;',
      "catalog/domain/home.ts": "export const home = 1;",
      "platform/db/schema.ts": 'export const courses = pgTable("courses", {});',
    });
    expect(run(root, "L2.sql-owner")).toEqual([violation("L2.sql-owner", "media/server/read.ts", "courses owned by catalog")]);
    expect(run(root, "L2.media-no-catalog")).toEqual([violation("L2.media-no-catalog", "media/testing/fake.ts", "../../catalog/domain/home.ts")]);
    const domain = fixture({ "media/domain/group.ts": 'import { resolveCover } from "../../catalog/domain/cover-resolve.ts";' });
    expect(run(domain, "L2.media-no-catalog")).toEqual([
      violation("L2.media-no-catalog", "media/domain/group.ts", "media domain does not import catalog"),
    ]);
    expect(run(root, "L2.progress-no-catalog")).toEqual([violation("L2.progress-no-catalog", "progress/server.ts", "@tower/catalog")]);
  });
  it("parses multiline type imports/reexports and ignores comments, ordinary strings and import.meta", () => {
    const root = fixture({ "kernel/a.ts": `// import "@tower/catalog";\n/* export * from "@tower/media"; */\nconst text = 'import "@tower/catalog"';\nconst url = import.meta.url;\nimport type {\n  Catalog\n} from "@tower/catalog";\nexport type { Asset } from "@tower/media";\nimport("@tower/playback-engine");` });
    expect(run(root, "L1.kernel-pure")).toEqual([
      violation("L1.kernel-pure", "kernel/a.ts", "@tower/catalog", 7), violation("L1.kernel-pure", "kernel/a.ts", "@tower/media", 8), violation("L1.kernel-pure", "kernel/a.ts", "@tower/playback-engine", 9),
    ]);
  });
  it("requires a registry entry for every public port and ignores a tree with none", () => {
    expect(run(fixture({ "kernel/a.ts": "export const a = 1;" }), "L3.contract-coverage")).toEqual([]);
    const root = fixture({
      "catalog/ports/commands.ts": "export interface CatalogStatePort { read(): void }",
      "apps/web/tooling/architecture-contracts.json": '{ "ports": [] }',
    });
    expect(run(root, "L3.contract-coverage")).toEqual([{ rule: "L3.contract-coverage", file: "apps/web/tooling/architecture-contracts.json", line: 1, detail: "CatalogStatePort has no contract entry" }]);
  });
  it("rejects a memory adapter that fetches and a contract that imports it", () => {
    const root = fixture({
      "catalog/testing/in-memory-catalog.ts": 'export const load = () => fetch("https://example.test");',
      "catalog/testing/catalog-contract.ts": 'import { load } from "./in-memory-catalog.ts";\nexport const cases = load;',
    });
    expect(run(root, "L3.testing-no-io")).toEqual([
      violation("L3.testing-no-io", "catalog/testing/catalog-contract.ts", "./in-memory-catalog.ts"),
      violation("L3.testing-no-io", "catalog/testing/in-memory-catalog.ts", "memory adapter reads the clock, the environment or the network"),
    ]);
  });
  it("rejects a bundle domain that opens a unit of work and an apply module that imports a video SDK", () => {
    const root = fixture({
      "catalog/domain/bundle.ts": 'import { withUnitOfWork } from "../../platform/db/uow.ts";\nexport const open = withUnitOfWork;',
      "catalog/server/bundle-apply.ts": 'import "googleapis";\nexport const sdk = 1;',
    });
    expect(run(root, "L4.bundle-boundary")).toEqual([
      violation("L4.bundle-boundary", "catalog/domain/bundle.ts", "../../platform/db/uow.ts"),
      violation("L4.bundle-boundary", "catalog/server/bundle-apply.ts", "googleapis"),
    ]);
    expect(run(fixture({ "kernel/a.ts": "export const a = 1;" }), "L4.bundle-boundary")).toEqual([]);
  });
  it("rejects an app page that reads the full catalog or the projection repository", () => {
    const root = fixture({ "app/page.tsx": 'import { getCatalog } from "@tower/catalog";\nexport const page = getCatalog;' });
    expect(run(root, "L4.query-consumers")).toEqual([violation("L4.query-consumers", "app/page.tsx", "@tower/catalog")]);
    const health = fixture({ "app/api/health/route.ts": 'import { getCatalogState } from "@tower/catalog";\nexport const route = getCatalogState;' });
    expect(run(health, "L4.query-consumers")).toEqual([]);
  });
  it("rejects an app file that imports the database pool and leaves health on L5.env", () => {
    const root = fixture({
      "app/api/media/revalidate/route.ts": 'import type { Queryable } from "../../platform/db/uow.ts";\nexport type Db = Queryable;',
      "app/api/other/route.ts": 'import pg from "pg";\nexport const load = () => import("pg/lib/client");',
      "app/api/progress/route.ts": 'import { appPool } from "@/platform/db/pool.ts";\nexport const route = appPool;',
    });
    expect(run(root, "L4.query-consumers")).toEqual([
      violation("L4.query-consumers", "app/api/media/revalidate/route.ts", "../../platform/db/uow.ts"),
      violation("L4.query-consumers", "app/api/other/route.ts", "pg"),
      violation("L4.query-consumers", "app/api/other/route.ts", "pg/lib/client", 2),
      violation("L4.query-consumers", "app/api/progress/route.ts", "@/platform/db/pool.ts"),
    ]);
    const health = fixture({ "app/api/health/route.ts": 'import pg from "pg";\nimport { appPool } from "@/platform/db/pool.ts";\nexport const route = appPool;' });
    expect(run(health, "L4.query-consumers")).toEqual([]);
    expect(run(health, "L5.env")).toEqual([
      violation("L5.env", "app/api/health/route.ts", "pg"),
      violation("L5.env", "app/api/health/route.ts", "@/platform/db/pool.ts", 2),
    ]);
  });
  it("rejects a domain module that imports the projection repository", () => {
    const root = fixture({ "catalog/domain/incremental-compile.ts": 'import { readProjection } from "../server/projections-repo.ts";\nexport const readProjection = readProjection;' });
    expect(run(root, "L4.projection-boundary")).toEqual([violation("L4.projection-boundary", "catalog/domain/incremental-compile.ts", "../server/projections-repo.ts")]);
    expect(run(fixture({ "kernel/a.ts": "export const a = 1;" }), "L4.projection-boundary")).toEqual([]);
  });
  it("allows the job memory adapter once 4.4 is applied and rejects a ship command that opens the jobs table", () => {
    expect(run(fixture({ "admin/testing/in-memory-jobs.ts": "export const jobs = 1;" }), "L3.contract-coverage")).toEqual([]);
    const root = fixture({
      "admin/route-specs.ts": 'spec("catalog", "POST", "/courses/:id/publish", "required", "course.publish");',
      "scripts/lib/catalog-cli/commands/ship.ts": 'import { createSqlJobStore } from "../../../../src/admin/server/jobs-repo.ts";\nexport const ship = createSqlJobStore;',
    });
    expect(run(root, "L4.job-boundary")).toEqual([
      violation("L4.job-boundary", "admin/route-specs.ts", "mutable admin spec has no permission"),
      violation("L4.job-boundary", "scripts/lib/catalog-cli/commands/ship.ts", "../../../../src/admin/server/jobs-repo.ts"),
    ]);
    expect(run(fixture({ "kernel/a.ts": "export const a = 1;" }), "L4.job-boundary")).toEqual([]);
  });
  it("rejects a media subquery, a table lock and migration DNS inside the scheduler", () => {
    const root = fixture({
      "media/server/repository.ts": "export const sql = `SELECT ext FROM media_objects`;",
      "media/server/inheritance.ts": "export const lock = `LOCK TABLE lessons`;",
      "catalog/server/media-owners.ts": "export const lock = `LOCK TABLE courses`;",
      "media/server/r2-bulk.ts": 'import { installMigrationDnsCache } from "../../../scripts/lib/migrate-dns.ts";\nexport const store = installMigrationDnsCache;',
    });
    expect(run(root, "L5.media-queries")).toEqual([
      violation("L5.media-queries", "catalog/server/media-owners.ts", "catalog media owners use advisory locks"),
      violation("L5.media-queries", "media/server/inheritance.ts", "media queries use a join and advisory locks"),
      violation("L5.media-queries", "media/server/r2-bulk.ts", "../../../scripts/lib/migrate-dns.ts"),
      violation("L5.media-queries", "media/server/repository.ts", "media queries use a join and advisory locks"),
    ]);
    expect(run(fixture({ "kernel/a.ts": "export const a = 1;" }), "L5.media-queries")).toEqual([]);
  });
  it("rejects environment reads outside the facade, including bracket access and a client import", () => {
    const root = fixture({
      "kernel/env.ts": "export function currentEnv() { return process.env; }",
      "catalog/server/leaked.ts": "const env = process.env;\nexport const url = env.APP_DATABASE_URL ?? process['env'].APP_DATABASE_URL;",
      "ui/Widget.tsx": 'import { currentEnv } from "../kernel/env.ts";\nexport const value = currentEnv;',
      "app/api/health/route.ts": 'import pg from "pg";\nexport const route = pg;',
    });
    expect(run(root, "L5.env")).toEqual([
      violation("L5.env", "app/api/health/route.ts", "pg"),
      violation("L5.env", "catalog/server/leaked.ts", "process env is read outside the kernel facade"),
      violation("L5.env", "ui/Widget.tsx", "../kernel/env.ts"),
    ]);
    expect(run(fixture({ "kernel/a.ts": "export const a = 1;" }), "L5.env")).toEqual([]);
  });
  it("keeps lifecycle SQL in the media adapter and out of the admin port and the CLI", () => {
    const root = fixture({
      "admin/lifecycle.ts": 'import { listLifecycleRows } from "../media/server/lifecycle.ts";\nexport const rows = listLifecycleRows;',
      "scripts/lib/catalog-cli/commands/lifecycle.ts": 'import { withUnitOfWork } from "../../../../src/platform/db/uow.ts";\nexport const open = withUnitOfWork;',
      "media/server/lifecycle.ts": "export const sql = `UPDATE media_objects SET orphaned_at = now()`;",
    });
    expect(run(root, "L5.lifecycle")).toEqual([
      violation("L5.lifecycle", "admin/lifecycle.ts", "../media/server/lifecycle.ts"),
      violation("L5.lifecycle", "scripts/lib/catalog-cli/commands/lifecycle.ts", "../../../../src/platform/db/uow.ts"),
    ]);
    expect(run(fixture({ "kernel/a.ts": "export const a = 1;" }), "L5.lifecycle")).toEqual([]);
  });
  it("L6.rules-in-core: rejects a rule message built in catalog/server and a rule declared outside the rules core", () => {
    const root = fixture({
      "catalog/server/ship.ts": 'export const fail = (id: string) => ({ rule: "bundle.slug", entity: `course:${id}`, message: "taken" });\n// { rule: "a.comment" } is not code',
      "catalog/domain/rules/batch.ts": 'import { declareRule } from "./registry.ts";\nexport const SLUG = declareRule("bundle.slug", "free");\nexport const fail = { rule: "bundle.slug" };',
      "catalog/domain/home.ts": 'import { declareRule } from "./rules/registry.ts";\nexport const ROW = declareRule("home.row", "exists");',
      "catalog/server/ship.test.ts": 'export const expected = { rule: "bundle.slug" };',
    });
    expect(run(root, "L6.rules-in-core")).toEqual([
      violation("L6.rules-in-core", "catalog/domain/home.ts", "rule declared outside the rules core", 2),
      violation("L6.rules-in-core", "catalog/server/ship.ts", "rule message built in server"),
    ]);
  });
  it("L6.single-rule: rejects a rule id declared twice, even in the rules core", () => {
    const root = fixture({
      "catalog/domain/rules/batch.ts": 'export const A = declareRule("bundle.video", "once per course");',
      "catalog/domain/rules/refs.ts": 'export const B = declareRule(\n  "bundle.video", "copied");\nexport const C = declareRule("ref.source.unknown", "exists");',
    });
    expect(run(root, "L6.single-rule")).toEqual([
      violation("L6.single-rule", "catalog/domain/rules/refs.ts", "rule bundle.video is already declared in apps/web/src/catalog/domain/rules/batch.ts"),
    ]);
    expect(run(fixture({ "catalog/domain/rules/a.ts": 'declareRule("a.b", "x"); declareRule("a.c", "y");' }), "L6.single-rule")).toEqual([]);
  });
  it("lists the two halves and keeps the factory inside the rings", () => {
    expect(architectureHalves).toEqual({
      site: ["site", "catalog", "media", "playback", "progress", "identity", "config"],
      factory: ["factory"],
    });
    const root = fixture({
      "factory/leak.ts": "export const leak = 1;",
      "factory/domain/context.ts": "export const half = 'factory';",
      "factory/ports/delivery.ts": "export interface BatchDelivery { apply(): Promise<void>; }",
      "factory/server/deliver.ts": "export const delivery = {};",
    });
    expect(run(root, "L3.context-layout")).toEqual([
      violation("L3.context-layout", "factory/leak.ts", "context root must stay inside domain, ports, server, client or testing"),
    ]);
  });
  it("L6.factory-api-only: rejects a factory import of the database", () => {
    const root = fixture({
      "factory/domain/leak.ts": 'import { pool } from "../../platform/db/pool.ts";\nexport const db = pool;',
      "factory/server/api.ts": 'import pg from "pg";\nexport const client = pg;',
      "apps/web/scripts/tower-factory.ts": 'import { drizzle } from "drizzle-orm";\nexport const db = drizzle;',
      "catalog/server/courses.ts": 'import pg from "pg";\nexport const client = pg;',
    });
    expect(run(root, "L6.factory-api-only")).toEqual([
      { rule: "L6.factory-api-only", file: "apps/web/scripts/tower-factory.ts", line: 1, detail: "the factory delivers the batch through the admin API and never imports the database" },
      violation("L6.factory-api-only", "factory/domain/leak.ts", "the factory delivers the batch through the admin API and never imports the database"),
      violation("L6.factory-api-only", "factory/server/api.ts", "the factory delivers the batch through the admin API and never imports the database"),
    ]);
    expect(run(fixture({ "factory/domain/context.ts": "export const half = 'factory';" }), "L6.factory-api-only")).toEqual([]);
  });
  it("L7.one-store: storage.ts selects a provider and each other file imports at most one", () => {
    const root = fixture({
      "media/server/storage.ts": 'import "aws4fetch";\nimport "sharp";\n',
      "media/server/mixed.ts": 'import "aws4fetch";\nimport "node:fs/promises";\n',
      "media/server/prepare.ts": 'import "sharp";\n',
      "media/server/og.ts": 'import sharp from "sharp";\n',
    });
    expect(run(root, "L7.one-store")).toEqual([
      violation("L7.one-store", "media/server/mixed.ts", "imports more than one media provider", 2),
      violation("L7.one-store", "media/server/storage.ts", "aws4fetch", 1),
      violation("L7.one-store", "media/server/storage.ts", "sharp", 2),
    ]);
    expect(run(fixture({
      "media/server/storage.ts": 'import { createS3Bucket } from "./r2.ts";\n',
      "media/server/fs-store.ts": 'import { readFile } from "node:fs/promises";\n',
      "media/server/prepare.ts": 'import sharp from "sharp";\n',
      "media/server/r2.ts": 'import { AwsClient } from "aws4fetch";\n',
    }), "L7.one-store")).toEqual([]);
  });
  it("L7.identity-domain: rejects a production identity domain import of site", () => {
    const root = fixture({
      "site/domain/origin.ts": "export const PRODUCTION_ORIGIN = 'https://example.invalid';",
      "kernel/brand-ids.ts": "export const AUTH_COOKIE_PREFIX = 'x';",
      "identity/domain/settings.ts": 'import { PRODUCTION_ORIGIN } from "../../site/domain/origin.ts";\nexport const origin = PRODUCTION_ORIGIN;',
      "identity/domain/alias.ts": 'import { PRODUCTION_ORIGIN } from "@/site/domain/origin";\nexport const origin = PRODUCTION_ORIGIN;',
      "identity/domain/typed.ts": 'import type { PRODUCTION_ORIGIN as Origin } from "../../site/domain/origin.ts";\nexport type AuthOrigin = Origin;',
      "identity/domain/reexport.ts": 'export { PRODUCTION_ORIGIN } from "../../site/domain/origin.ts";',
      "identity/domain/dynamic.ts": 'export const load = () => import("../../site/domain/origin.ts");',
      "identity/domain/local.ts": 'import { AUTH_COOKIE_PREFIX } from "../../kernel/brand-ids.ts";\nexport const prefix = AUTH_COOKIE_PREFIX;',
      "identity/domain/settings.test.ts": 'import { PRODUCTION_ORIGIN } from "../../site/domain/origin.ts";\nexport const origin = PRODUCTION_ORIGIN;',
    });
    const detail = "identity domain does not import site";
    expect(run(root, "L7.identity-domain")).toEqual([
      violation("L7.identity-domain", "identity/domain/alias.ts", detail),
      violation("L7.identity-domain", "identity/domain/dynamic.ts", detail),
      violation("L7.identity-domain", "identity/domain/reexport.ts", detail),
      violation("L7.identity-domain", "identity/domain/settings.ts", detail),
      violation("L7.identity-domain", "identity/domain/typed.ts", detail),
    ]);
    expect(run(fixture({ "identity/domain/local.ts": 'import { AUTH_COOKIE_PREFIX } from "../../kernel/brand-ids.ts";', "kernel/brand-ids.ts": "export const AUTH_COOKIE_PREFIX = 'x';" }), "L7.identity-domain")).toEqual([]);
  });
});
