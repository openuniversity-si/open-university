import { createHash } from "node:crypto";
import { afterAll, beforeAll, beforeEach, describe, expect, it } from "vitest";
import { TEXT_FIELDS } from "../../src/catalog/domain/fields.ts";
import { REQUIRED_COVERS } from "../../src/catalog/domain/rules/status.ts";
import { batchV2Hash, chunkBatchV2, type ApplyBatchData } from "../../src/catalog/domain/batch-v2.ts";
import { catalogBatchV2Schema, taxonomyCoverEntries, type CatalogBatchV2 } from "../../src/catalog/domain/schema/batch-v2.ts";
import { call, createHarness, seedCatalog, slotText, type Harness, type Seed } from "../fixtures/admin-catalog.ts";

// Verifies: D-053, REQ-contract-g-1, REQ-contract-g-2, REQ-contract-g-3, REQ-contract-g-4, REQ-contract-g-5
/** POST /batches/apply on PostgreSQL 18 (S08): the CONTRACT §5 guarantees G-1 … G-5. No network. */

const sha = (seed: string) => createHash("sha256").update(seed).digest("hex");
const NOW = "2026-10-22T12:00:00.000Z";

export function course(id: string, institutionId: string, homeRowId: string | null, authorId = "ana-lima") {
  const texts = [
    ...Object.keys(TEXT_FIELDS.course).map((field) => ({ entityKind: "course", entityId: id, field, text: slotText(field, id.slice(-6)), approved: true, approvedBy: "Reviewer", approvedAt: NOW })),
    ...[1, 2].map((n) => ({ entityKind: "lesson", entityId: `${id}-l${String(n)}`, field: "displayTitle", text: `Aula ${String(n)}`, approved: true, approvedBy: "Reviewer", approvedAt: NOW })),
  ];
  return {
    institutionId, homeRowId,
    course: { id, slug: id, title: `Course ${id}`, authorId, areaId: "computer-science", coverFrom: "own", sharedWith: [], sourceId: "src-test", licenseCode: "youtube-standard", canonicalUrl: `https://example.org/${id}`, rightsStatus: "accepted-risk" },
    editions: [{ id: `${id}-e`, slug: "2021", label: "2021", position: 1, year: 2021 }],
    lessons: [1, 2].map((n) => ({ id: `${id}-l${String(n)}`, editionId: `${id}-e`, slug: `aula-${String(n)}`, title: `Aula ${String(n)}`, position: n, youtubeId: createHash("sha256").update(`${id}${String(n)}`).digest("base64url").slice(0, 11), durationSeconds: 600 })),
    texts,
    covers: REQUIRED_COVERS.map((kind) => ({ kind, sha: sha(`${id}/${kind}`) })),
  };
}

export function institution(id: string, after: string) {
  return {
    institution: { id, slug: id, name: id.toUpperCase(), monogram: id.slice(0, 3).toUpperCase(), kind: "institution", cover: { poster: sha(`${id}/poster`), og: sha(`${id}/og`) } },
    row: { id, institutionId: id, title: id.toUpperCase(), fullName: `Universidade ${id}`, place: "Brazil", after, cover: { sha: sha(`${id}/row`), alt: id, credit: `Photo: ${id}`, sourceUrl: "https://example.org", license: "CC BY 4.0" }, og: sha(`${id}/row-og`) },
  };
}

export function shas(batch: CatalogBatchV2): string[] {
  return [...new Set([
    ...batch.institutions.flatMap((item) => [item.cover.poster, item.cover.og ?? ""]),
    ...batch.homeRows.flatMap((row) => [row.cover.sha, row.og ?? ""]),
    ...batch.areas.flatMap((node) => taxonomyCoverEntries("area", node.cover).map((cover) => cover.sha)),
    ...batch.subareas.flatMap((node) => taxonomyCoverEntries("subarea", node.cover).map((cover) => cover.sha)),
    ...batch.courses.flatMap((item) => item.covers.map((cover) => cover.sha)),
  ].filter(Boolean))];
}

export async function register(h: Harness, hashes: readonly string[]): Promise<void> {
  await h.pool.query(`INSERT INTO media_objects (sha256, ext, content_type, bytes, width, height)
    SELECT s, 'webp', 'image/webp', 100, 1080, 1920 FROM unnest($1::text[]) AS s ON CONFLICT (sha256) DO NOTHING`, [hashes]);
}

let keys = 0;
export async function apply(h: Harness, batch: CatalogBatchV2, options: { dryRun?: boolean; draft?: boolean; maxBytes?: number } = {}) {
  const parts = chunkBatchV2(batch, options.maxBytes ?? 1024 * 1024);
  let last;
  for (const [chunk, part] of parts.entries()) {
    keys += 1;
    last = await call<ApplyBatchData>(h, "POST", "/batches/apply", { key: `batch-${String(keys)}`, body: {
      batchHash: batchV2Hash(batch), chunk, chunks: parts.length, dryRun: options.dryRun ?? false, draft: options.draft ?? false, part,
    } });
  }
  if (!last) throw new Error("no part");
  return last;
}

const fingerprint = async (h: Harness) => (await h.pool.query(`SELECT
  (SELECT count(*)::int FROM authors) AS authors, (SELECT count(*)::int FROM courses) AS courses, (SELECT count(*)::int FROM home_rows) AS rows,
  (SELECT count(*)::int FROM catalog_media WHERE is_active) AS media, (SELECT count(*)::int FROM catalog_releases) AS releases,
  (SELECT count(*)::int FROM home_row_items) AS items`)).rows[0] as Record<string, number>;

describe("POST /batches/apply (CONTRACT §5)", () => {
  let h: Harness;
  let seed: Seed;
  let base: CatalogBatchV2;
  beforeAll(() => { h = createHarness(); });
  beforeEach(async () => {
    seed = await seedCatalog(h);
    const usp = institution("usp", "picks");
    base = catalogBatchV2Schema.parse({
      version: 2, institutions: [usp.institution], homeRows: [usp.row],
      lecturers: [{ id: "ana-lima", slug: "ana-lima", name: "Ana Lima", monogram: "AL", kind: "person" }],
      courses: [course("usp-mecanica", "usp", "usp"), course("usp-calculo", "usp", "usp")],
    });
    await register(h, shas(base));
  });
  afterAll(async () => { await h.close(); });

  it("G-4: a new institution, its row and courses with own covers apply in one request and one release", async () => {
    const result = await apply(h, base);
    expect(result.status, JSON.stringify(result.body)).toBe(201);
    expect(result.data).toMatchObject({ status: "committed", courses: ["usp-mecanica", "usp-calculo"], release: { number: 2, created: true },
      plan: { institution: { create: 1 }, lecturer: { create: 1 }, "home-row": { create: 1 }, course: { create: 2 }, placement: { attach: 2 } } });
    expect((await h.pool.query<{ id: string; institution_id: string | null }>("SELECT id, institution_id FROM home_rows ORDER BY position")).rows.map((row) => [row.id, row.institution_id]))
      .toEqual([["continue", null], ["picks", seed.institution], ["usp", "usp"]]);
    expect((await h.pool.query("SELECT id, status, author_id, institution_id FROM courses WHERE id LIKE 'usp-%' ORDER BY id")).rows)
      .toEqual([{ id: "usp-calculo", status: "published", author_id: "ana-lima", institution_id: "usp" }, { id: "usp-mecanica", status: "published", author_id: "ana-lima", institution_id: "usp" }]);
    const release = (await h.pool.query<{ payload: unknown }>("SELECT payload FROM catalog_releases WHERE number = 2")).rows[0]?.payload as { home: { rows: { id: string; courseIds: string[]; cover?: { credit: string } }[] } };
    expect(release.home.rows.find((row) => row.id === "usp")).toMatchObject({ courseIds: ["usp-calculo", "usp-mecanica"], cover: { credit: "Photo: usp" } });
  });

  it("D-053: a draft writes the rows and does not publish the course or cut a release", async () => {
    const before = await fingerprint(h);
    const result = await apply(h, base, { draft: true });
    expect(result.status, JSON.stringify(result.body)).toBe(201);
    expect(result.data).toMatchObject({ status: "committed", draft: true, release: null, courses: ["usp-mecanica", "usp-calculo"] });
    expect((await h.pool.query("SELECT id, status FROM courses WHERE id LIKE 'usp-%' ORDER BY id")).rows)
      .toEqual([{ id: "usp-calculo", status: "draft" }, { id: "usp-mecanica", status: "draft" }]);
    const after = await fingerprint(h);
    expect(after.releases ?? 0).toBe(before.releases ?? 0);
    expect(after.courses ?? 0).toBe((before.courses ?? 0) + 2);
  });

  it("G-1: a fault after the last write leaves nothing, not even the batch's institution or covers", async () => {
    const before = await fingerprint(h);
    await h.pool.query(`CREATE FUNCTION fail_release() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'injected fault'; END; $$;
      CREATE TRIGGER fail_release BEFORE INSERT ON catalog_releases FOR EACH ROW EXECUTE FUNCTION fail_release();`);
    try {
      expect((await apply(h, base)).status).toBeGreaterThanOrEqual(500);
    } finally {
      await h.pool.query("DROP TRIGGER fail_release ON catalog_releases; DROP FUNCTION fail_release();");
    }
    expect(await fingerprint(h)).toEqual(before);
  });

  it("G-2: the same content hash twice returns the first result and writes nothing", async () => {
    const first = await apply(h, base);
    const after = await fingerprint(h);
    const again = await apply(h, base);
    expect(again.status).toBe(200);
    expect(again.data).toEqual(first.data);
    expect(await fingerprint(h)).toEqual(after);
  });

  it("G-3: a dry run is the write rolled back; its report equals the committed one, in several chunks", async () => {
    const before = await fingerprint(h);
    const dry = await apply(h, base, { dryRun: true, maxBytes: 9000 });
    expect(dry.status, JSON.stringify(dry.body)).toBe(200);
    expect(await fingerprint(h)).toEqual(before);
    expect(h.recorder.events).not.toContain("invalidate");
    const write = await apply(h, base, { maxBytes: 9000 });
    expect(write.status).toBe(201);
    expect({ ...dry.data, status: "committed" }).toEqual(write.data);
  });

  it("G-3: a dry run meets the commit-time rules a write would (deferred own-cover trigger)", async () => {
    const broken = catalogBatchV2Schema.parse({ ...base, homeRows: [{ ...base.homeRows[0], visible: true }], institutions: [] });
    await h.pool.query("INSERT INTO authors (id, slug, name, monogram, kind) VALUES ('usp', 'usp', 'USP', 'USP', 'institution')");
    await register(h, shas(base));
    const dry = await apply(h, broken, { dryRun: true });
    const write = await apply(h, broken);
    expect([dry.status, dry.body.error?.code]).toEqual([write.status, write.body.error?.code]);
    expect(dry.status).toBe(422);
  });

  it("G-5: a rejected batch lists every failing rule by id and entity, and writes nothing", async () => {
    const before = await fingerprint(h);
    const broken = catalogBatchV2Schema.parse({
      ...base,
      homeRows: [{ ...base.homeRows[0], institutionId: "ana-lima" }],
      courses: [course("usp-mecanica", "ana-lima", "usp"), { ...course("usp-calculo", "usp", null), covers: [{ kind: "poster_9x16", sha: sha("never uploaded") }] }],
    });
    const result = await apply(h, broken);
    expect(result.status).toBe(412);
    const failed = (result.body.error?.details as { failed: { rule: string; entity: string }[] }).failed;
    expect(failed.map((failure) => `${failure.rule} ${failure.entity}`)).toEqual([
      "batch.institution-kind home_row:usp",
      "batch.cover course:usp-calculo:poster_9x16",
      "batch.institution-kind course:usp-mecanica",
      "cover.declared course:usp-calculo",
    ]);
    expect(await fingerprint(h)).toEqual(before);
  });

  it("Brazil-shaped: 4 institutions and 80 own-cover courses pass dry run and write with equal reports", async () => {
    const names = ["usp", "unicamp", "ufrj", "ufmg"];
    const nodes = names.map((name, index) => institution(name, index === 0 ? "picks" : names[index - 1] ?? "picks"));
    const brazil = catalogBatchV2Schema.parse({
      version: 2, institutions: nodes.map((node) => node.institution), homeRows: nodes.map((node) => node.row),
      lecturers: [{ id: "ana-lima", slug: "ana-lima", name: "Ana Lima", monogram: "AL", kind: "person" }],
      courses: Array.from({ length: 80 }, (_, index) => {
        const name = names[index % names.length] ?? "usp";
        return course(`${name}-c${String(index).padStart(2, "0")}`, name, name);
      }),
    });
    await register(h, shas(brazil));
    const before = await fingerprint(h);
    const dry = await apply(h, brazil, { dryRun: true, maxBytes: 200_000 });
    expect(dry.status, JSON.stringify(dry.body).slice(0, 500)).toBe(200);
    expect(await fingerprint(h)).toEqual(before);
    // The dry run left the parts staged: the write's first chunk completes the batch, later chunks replay its result.
    const write = await apply(h, brazil, { maxBytes: 200_000 });
    expect([200, 201]).toContain(write.status);
    expect({ ...dry.data, status: "committed" }).toEqual(write.data);
    expect(write.data).toMatchObject({ plan: { institution: { create: 4 }, "home-row": { create: 4 }, course: { create: 80 }, placement: { attach: 80 } }, release: { created: true } });
    expect((await h.pool.query<{ id: string }>("SELECT id FROM home_rows WHERE kind = 'curated' ORDER BY position")).rows.map((row) => row.id)).toEqual(["picks", ...names]);
    expect(Number((await h.pool.query<{ n: string }>("SELECT count(*) AS n FROM courses WHERE status = 'published' AND institution_id = ANY($1)", [names])).rows[0]?.n)).toBe(80);
  });
});
