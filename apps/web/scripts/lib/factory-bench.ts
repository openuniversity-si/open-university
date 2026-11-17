import { createHash } from "node:crypto";
import { pathToFileURL } from "node:url";
import { batchV2Hash, chunkBatchV2, type ApplyBatchData } from "../../src/catalog/domain/batch-v2.ts";
import { TEXT_FIELDS } from "../../src/catalog/domain/fields.ts";
import { REQUIRED_COVERS } from "../../src/catalog/domain/rules/status.ts";
import { catalogBatchV2Schema, taxonomyCoverEntries, type CatalogBatchV2 } from "../../src/catalog/domain/schema/batch-v2.ts";
import { runMutation, type AdminPool } from "../../src/catalog/server/mutation.ts";
import { publishRelease } from "../../src/catalog/server/releases.ts";
import { call, createHarness, seedCatalog, slotText, type Harness } from "../../test/fixtures/admin-catalog.ts";

/** G-6 budgets. Above these the bench warns and still exits 0 (ADR-34 style). */
export const BENCH_LIMITS = { dryRunMs: 30_000, writeMs: 60_000 } as const;

export interface BenchPhase {
  readonly name: "dryRun" | "write" | "releaseMs";
  readonly ms: number;
}

export interface BenchReport {
  readonly courses: number;
  readonly phases: readonly BenchPhase[];
  readonly warnings: readonly string[];
}

const sha = (seed: string) => createHash("sha256").update(seed).digest("hex");
const NOW = "2026-10-22T12:00:00.000Z";

function course(id: string, institutionId: string, homeRowId: string, authorId: string) {
  const texts = [
    ...Object.keys(TEXT_FIELDS.course).map((field) => ({
      entityKind: "course" as const, entityId: id, field, text: slotText(field, id.slice(-6)),
      approved: true, approvedBy: "Reviewer", approvedAt: NOW,
    })),
    ...[1, 2].map((n) => ({
      entityKind: "lesson" as const, entityId: `${id}-l${String(n)}`, field: "displayTitle", text: `Aula ${String(n)}`,
      approved: true, approvedBy: "Reviewer", approvedAt: NOW,
    })),
  ];
  return {
    institutionId, homeRowId,
    course: {
      id, slug: id, title: `Course ${id}`, authorId, areaId: "computer-science", coverFrom: "own", sharedWith: [], sourceId: "src-test",
      licenseCode: "youtube-standard", canonicalUrl: `https://example.org/${id}`, rightsStatus: "accepted-risk" as const,
    },
    editions: [{ id: `${id}-e`, slug: "2021", label: "2021", position: 1, year: 2021 }],
    lessons: [1, 2].map((n) => ({
      id: `${id}-l${String(n)}`, editionId: `${id}-e`, slug: `aula-${String(n)}`, title: `Aula ${String(n)}`, position: n,
      youtubeId: createHash("sha256").update(`${id}:${String(n)}`).digest("base64url").slice(0, 11), durationSeconds: 600,
    })),
    texts,
    covers: REQUIRED_COVERS.map((kind) => ({ kind, sha: sha(`${id}/${kind}`) })),
  };
}

/** One new institution and `count` courses. Ids stay inside the catalog limits. `prefix` separates a resident catalog from the timed batch. */
export function syntheticBatch(count: number, prefix = "b"): CatalogBatchV2 {
  if (!Number.isInteger(count) || count < 1) throw new Error("factory-bench: course count must be a positive integer");
  if (!/^[a-z]$/.test(prefix)) throw new Error("factory-bench: prefix must be one letter");
  const id = prefix === "b" ? "bench-u" : `bench-${prefix}`;
  const lecturer = prefix === "b" ? "bench-lecturer" : `lecturer-${prefix}`;
  return catalogBatchV2Schema.parse({
    version: 2,
    institutions: [{
      id, slug: id, name: "Bench University", monogram: "BU", kind: "institution",
      cover: { poster: sha(`${id}/poster`), og: sha(`${id}/og`) },
    }],
    lecturers: [{ id: lecturer, slug: lecturer, name: "Bench Lecturer", monogram: "BL", kind: "person" }],
    homeRows: [{
      id, institutionId: id, title: "Bench University", fullName: "Bench University", place: "Brazil", after: "picks",
      cover: { sha: sha(`${id}/row`), alt: "Bench", credit: "Photo: Bench", sourceUrl: "https://example.org/bench", license: "CC BY 4.0" },
      og: sha(`${id}/row-og`),
    }],
    courses: Array.from({ length: count }, (_, index) => course(`${prefix}${String(index).padStart(4, "0")}`, id, id, lecturer)),
  });
}

/** Every media sha the batch names, so the bench can register them before apply. */
export function batchShas(batch: CatalogBatchV2): string[] {
  return [...new Set([
    ...batch.institutions.flatMap((item) => [item.cover.poster, item.cover.og ?? ""]),
    ...batch.homeRows.flatMap((row) => [row.cover.sha, row.og ?? ""]),
    ...batch.areas.flatMap((node) => taxonomyCoverEntries("area", node.cover).map((cover) => cover.sha)),
    ...batch.subareas.flatMap((node) => taxonomyCoverEntries("subarea", node.cover).map((cover) => cover.sha)),
    ...batch.courses.flatMap((item) => item.covers.map((cover) => cover.sha)),
  ].filter(Boolean))];
}

/**
 * The bench report. A phase over its budget is a warning, not a failure:
 * the nightly stage stays green and prints the warning (G-6, ADR-34 style).
 */
export function benchReport(courses: number, phases: readonly BenchPhase[]): BenchReport {
  const ms = (name: BenchPhase["name"]) => phases.find((phase) => phase.name === name)?.ms;
  const warnings: string[] = [];
  const dryRun = ms("dryRun");
  const write = ms("write");
  if (dryRun !== undefined && dryRun > BENCH_LIMITS.dryRunMs) warnings.push(`dry run ${String(dryRun)}ms exceeds ${String(BENCH_LIMITS.dryRunMs)}ms`);
  if (write !== undefined && write > BENCH_LIMITS.writeMs) warnings.push(`write ${String(write)}ms exceeds ${String(BENCH_LIMITS.writeMs)}ms`);
  return { courses, phases, warnings };
}

async function applyBatch(harness: Harness, batch: CatalogBatchV2, dryRun: boolean, label: string): Promise<void> {
  const parts = chunkBatchV2(batch, 700_000);
  const hash = batchV2Hash(batch);
  for (const [chunk, part] of parts.entries()) {
    const result = await call<ApplyBatchData>(harness, "POST", "/batches/apply", {
      key: `bench-${label}-${dryRun ? "dry" : "write"}-${String(chunk)}`,
      body: { batchHash: hash, chunk, chunks: parts.length, dryRun, draft: false, part },
    });
    if (result.status >= 400) throw new Error(`factory-bench: apply failed (${String(result.status)}) ${JSON.stringify(result.body.error ?? result.body)}`);
  }
}

async function registerShas(harness: Harness, batch: CatalogBatchV2): Promise<void> {
  await harness.pool.query(`INSERT INTO media_objects (sha256, ext, content_type, bytes, width, height)
    SELECT s, 'webp', 'image/webp', 100, 1080, 1920 FROM unnest($1::text[]) AS s ON CONFLICT (sha256) DO NOTHING`, [batchShas(batch)]);
}

/**
 * Dry run, write, then one changed course. Uses the local test database and leaves it reset.
 * `existing` publishes that many courses first, outside the timer, so the timed batch lands on a resident catalog.
 */
export async function runBench(courses: number, existing = 0): Promise<BenchReport> {
  const batch = syntheticBatch(courses);
  const harness = createHarness();
  try {
    await seedCatalog(harness);
    if (existing > 0) {
      const resident = syntheticBatch(existing, "e");
      await registerShas(harness, resident);
      await applyBatch(harness, resident, false, "resident");
    }
    await registerShas(harness, batch);
    const dryStarted = Date.now();
    await applyBatch(harness, batch, true, "timed");
    const dryRunMs = Date.now() - dryStarted;
    const writeStarted = Date.now();
    await applyBatch(harness, batch, false, "timed");
    const writeMs = Date.now() - writeStarted;
    const courseId = batch.courses[0]?.course.id;
    if (!courseId) throw new Error("factory-bench: the batch has no course");
    const updated = await harness.pool.query("UPDATE catalog_texts SET text = 'Renamed lesson', approved_sha256 = catalog_text_sha256('Renamed lesson') WHERE entity_id = $1 AND field = 'displayTitle'", [`${courseId}-l1`]);
    if (updated.rowCount !== 1) throw new Error("factory-bench: the lesson text did not update");
    const releaseStarted = Date.now();
    await runMutation(harness.pool as unknown as AdminPool, { requestId: "bench-release", actor: "bench" }, null, async (tx) => {
      const publication = await publishRelease(tx, { note: "bench one course", actor: "bench", fresh: new Set([courseId]), now: new Date("2026-10-22T13:00:00.000Z") });
      return { data: publication, entity: `course:${courseId}` };
    });
    return benchReport(courses, [
      { name: "dryRun", ms: dryRunMs }, { name: "write", ms: writeMs }, { name: "releaseMs", ms: Date.now() - releaseStarted },
    ]);
  } finally {
    await harness.close();
  }
}

async function main(): Promise<void> {
  const flag = process.argv.indexOf("--courses");
  const courses = flag === -1 ? 1000 : Number(process.argv[flag + 1]);
  const resident = process.argv.indexOf("--existing");
  const existing = resident === -1 ? 0 : Number(process.argv[resident + 1]);
  const report = await runBench(courses, existing);
  for (const warning of report.warnings) process.stderr.write(`WARN factory-bench: ${warning}\n`);
  process.stdout.write(`${JSON.stringify(report)}\n`);
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main().catch((error: unknown) => {
    process.stderr.write(`factory-bench: ${error instanceof Error ? error.message : "failed"}\n`);
    process.exit(1);
  });
}
