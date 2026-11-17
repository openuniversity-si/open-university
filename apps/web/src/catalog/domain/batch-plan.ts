import type { PreconditionFailure } from "../../kernel/errors.ts";
import { canonicalJson } from "../../kernel/canonical.ts";
import { coverKindAllowed, type CoverOwner } from "../../media/domain/cover-choice.ts";
import { authorKind } from "./schema/fields.ts";
import { bundleProblems } from "./schema/bundle.ts";
import { coverDeclarationProblem, coverOwner, missingCoverKinds } from "./cover-source.ts";
import { taxonomyCoverEntries, type BatchCourse, type CatalogBatchV2 } from "./schema/batch-v2.ts";
import {
  BATCH_COURSE, BATCH_COVER, BATCH_COVER_KIND, BATCH_DUPLICATE, BATCH_HOME_ROW, BATCH_INSTITUTION_KIND, BATCH_REFERENCE, BATCH_REF_CONFLICT, COVER_DECLARED,
} from "./rules/batch-v2.ts";

/** The stored rows a batch reaches (S08 loads them in one round trip; tests hand them in memory). */
export interface BatchRefs {
  readonly sources: ReadonlyMap<string, Readonly<Record<string, unknown>>>;
  readonly authors: ReadonlyMap<string, { readonly slug: string; readonly name: string; readonly monogram: string; readonly kind: string }>;
  readonly areas: ReadonlyMap<string, { readonly title: string }>;
  readonly subareas: ReadonlyMap<string, { readonly areaId: string; readonly title: string }>;
  readonly homeRows: ReadonlyMap<string, { readonly institutionId: string | null; readonly title: string | null }>;
  readonly courses: ReadonlyMap<string, { readonly slug: string; readonly institutionId: string | null }>;
  readonly licenses: ReadonlySet<string>;
  /** Active default cover kinds already stored, keyed `course:<id>`, `area:<id>` or `subarea:<id>`. */
  readonly covers: ReadonlyMap<string, readonly string[]>;
  /** Registered media objects, by sha. */
  readonly media: ReadonlySet<string>;
}

export type PlanStep = "license" | "source" | "institution" | "lecturer" | "area" | "subarea" | "home-row" | "media" | "course" | "placement" | "release";
export interface PlanOp { readonly step: PlanStep; readonly action: "create" | "update" | "noop" | "attach"; readonly id: string }
export interface BatchPlan { readonly ops: readonly PlanOp[]; readonly failures: readonly PreconditionFailure[] }

/** G-4: the order is the core's, not the client's: refs → nodes → media → courses → placements → release. */
const ORDER: readonly PlanStep[] = ["license", "source", "institution", "lecturer", "area", "subarea", "home-row", "media", "course", "placement", "release"];

/**
 * Plan one CatalogBatchV2 against the stored refs: the ordered operations and every failure (G-5). Pure; S08 runs the
 * ops inside one transaction. A stored reference with the same content is a no-op, with different content a conflict
 * unless `updateRefs`, and absent is created. Nothing is deleted by omission.
 */
export function planBatch(batch: CatalogBatchV2, refs: BatchRefs): BatchPlan {
  const ops: PlanOp[] = [];
  const failures: PreconditionFailure[] = [];
  const fail = (failure: PreconditionFailure) => failures.push(failure);

  const unique = <T>(kind: string, items: readonly T[], key: (item: T) => string) => {
    const seen = new Set<string>();
    for (const item of items) {
      const id = key(item);
      if (seen.has(id)) fail(BATCH_DUPLICATE.fail(`${kind}:${id}`, `${kind} ${id} appears twice in the batch.`));
      seen.add(id);
    }
  };
  unique("license", batch.licenses, (item) => item.code);
  unique("source", batch.sources, (item) => item.id);
  unique("institution", [...batch.institutions, ...batch.lecturers], (item) => item.id);
  unique("author-slug", [...batch.institutions, ...batch.lecturers], (item) => item.slug);
  unique("area", batch.areas, (item) => item.id);
  unique("subarea", batch.subareas, (item) => item.id);
  unique("home_row", batch.homeRows, (item) => item.id);
  unique("course", batch.courses, (item) => item.course.id);
  unique("course-slug", batch.courses, (item) => item.course.slug);

  const upsert = (step: PlanStep, id: string, wanted: Record<string, unknown>, stored: Readonly<Record<string, unknown>> | undefined) => {
    if (!stored) return ops.push({ step, action: "create", id });
    const same = Object.keys(wanted).filter((key) => wanted[key] !== undefined).every((key) => canonicalJson(wanted[key] ?? null) === canonicalJson(stored[key] ?? null));
    if (same) return ops.push({ step, action: "noop", id });
    if (batch.updateRefs) return ops.push({ step, action: "update", id });
    fail(BATCH_REF_CONFLICT.fail(`${step}:${id}`, `Stored ${step} ${id} differs from the batch; set updateRefs to overwrite it.`));
  };

  const licenseCodes = new Set(refs.licenses);
  for (const license of batch.licenses) {
    if (licenseCodes.has(license.code)) ops.push({ step: "license", action: "noop", id: license.code });
    else ops.push({ step: "license", action: "create", id: license.code });
    licenseCodes.add(license.code);
  }
  for (const source of batch.sources) upsert("source", source.id, { ...source }, refs.sources.get(source.id));
  const institutions = new Set<string>(batch.institutions.map((item) => item.id));
  const lecturers = new Set<string>(batch.lecturers.map((item) => item.id));
  for (const [id, author] of refs.authors) (author.kind === "institution" ? institutions : lecturers).add(id);
  for (const item of batch.institutions) {
    const stored = refs.authors.get(item.id);
    if (stored && stored.kind !== "institution") fail(BATCH_INSTITUTION_KIND.fail(`institution:${item.id}`, `${item.id} is stored as a ${stored.kind}, not an institution.`));
    else upsert("institution", item.id, { slug: item.slug, name: item.name, monogram: item.monogram, kind: item.kind }, stored);
  }
  for (const item of batch.lecturers) {
    const stored = refs.authors.get(item.id);
    if (stored?.kind === "institution") fail(BATCH_INSTITUTION_KIND.fail(`author:${item.id}`, `${item.id} is stored as an institution, not a lecturer.`));
    else upsert("lecturer", item.id, { slug: item.slug, name: item.name, monogram: item.monogram, kind: item.kind }, stored);
  }
  const areas = new Set([...refs.areas.keys(), ...batch.areas.map((item) => item.id)]);
  for (const area of batch.areas) upsert("area", area.id, { title: area.title }, refs.areas.get(area.id));
  const subareas = new Map<string, string>([...refs.subareas].map(([id, row]) => [id, row.areaId]));
  for (const subarea of batch.subareas) {
    if (!areas.has(subarea.areaId)) fail(BATCH_REFERENCE.fail(`subarea:${subarea.id}`, `Area ${subarea.areaId} does not exist.`));
    upsert("subarea", subarea.id, { areaId: subarea.areaId, title: subarea.title }, refs.subareas.get(subarea.id));
    subareas.set(subarea.id, subarea.areaId);
  }

  const rowOwner = new Map<string, string | null>([...refs.homeRows].map(([id, row]) => [id, row.institutionId]));
  const owned = new Map<string, string>();
  for (const [id, row] of refs.homeRows) if (row.institutionId) owned.set(row.institutionId, id);
  for (const row of batch.homeRows) {
    const entity = `home_row:${row.id}`;
    if (!institutions.has(row.institutionId)) {
      fail(lecturers.has(row.institutionId)
        ? BATCH_INSTITUTION_KIND.fail(entity, `${row.institutionId} is a lecturer; a University row belongs to an institution.`)
        : BATCH_REFERENCE.fail(entity, `Institution ${row.institutionId} does not exist.`));
    }
    const other = owned.get(row.institutionId);
    if (other && other !== row.id) fail(BATCH_HOME_ROW.fail(entity, `Institution ${row.institutionId} already has row ${other}.`));
    if (row.after && !rowOwner.has(row.after) && !batch.homeRows.some((item) => item.id === row.after)) fail(BATCH_REFERENCE.fail(entity, `Row ${row.after} does not exist.`));
    upsert("home-row", row.id, { institutionId: row.institutionId, title: row.title }, refs.homeRows.get(row.id));
    owned.set(row.institutionId, row.id);
    rowOwner.set(row.id, row.institutionId);
  }

  const attach = (entity: string, sha: string | null | undefined) => {
    if (!sha) return;
    if (refs.media.has(sha)) ops.push({ step: "media", action: "attach", id: `${entity}@${sha.slice(0, 12)}` });
    else fail(BATCH_COVER.fail(entity, `Cover ${sha} is not a registered media object; upload it first.`));
  };
  const attachOwned = (owner: CoverOwner, entity: string, kind: string, sha: string | null | undefined) => {
    if (!sha) return;
    if (!coverKindAllowed(owner, kind)) {
      fail(BATCH_COVER_KIND.fail(entity, `${owner} does not accept cover kind ${kind}.`));
      return;
    }
    attach(entity, sha);
  };
  for (const item of batch.institutions) {
    attachOwned("institution", `institution:${item.id}:poster_9x16`, "poster_9x16", item.cover.poster);
    attachOwned("institution", `institution:${item.id}:og`, "og", item.cover.og);
  }
  for (const row of batch.homeRows) {
    attachOwned("institution", `home_row:${row.id}:university_cover_9x16`, "university_cover_9x16", row.cover.sha);
    attachOwned("institution", `home_row:${row.id}:og`, "og", row.og);
  }
  for (const node of [...batch.areas.map((item) => ["area", item] as const), ...batch.subareas.map((item) => ["subarea", item] as const)]) {
    for (const cover of taxonomyCoverEntries(node[0], node[1].cover)) attachOwned(node[0], `${node[0]}:${node[1].id}:${cover.kind}`, cover.kind, cover.sha);
  }
  for (const item of batch.courses) for (const cover of item.covers) attachOwned("course", `course:${item.course.id}:${cover.kind}`, cover.kind, cover.sha);

  for (const item of batch.courses) planCourse(item);
  for (const item of batch.courses) if (item.homeRowId) ops.push({ step: "placement", action: "attach", id: `${item.homeRowId}/${item.course.id}` });
  ops.push({ step: "release", action: "create", id: "release" });

  function planCourse(item: BatchCourse) {
    const { course } = item;
    const entity = `course:${course.id}`;
    for (const message of bundleProblems({ version: 1, author: { id: course.authorId, slug: course.authorId, name: course.authorId, monogram: "x", kind: authorKind.person },
      course, editions: item.editions, lessons: item.lessons, texts: item.texts, home: null, covers: [] })) fail(BATCH_COURSE.fail(entity, message));
    if (!institutions.has(item.institutionId)) {
      fail(lecturers.has(item.institutionId)
        ? BATCH_INSTITUTION_KIND.fail(entity, `${item.institutionId} is a lecturer; a course is offered by an institution (D-024).`)
        : BATCH_REFERENCE.fail(entity, `Institution ${item.institutionId} does not exist.`));
    }
    if (!lecturers.has(course.authorId) && !institutions.has(course.authorId)) fail(BATCH_REFERENCE.fail(entity, `Lecturer ${course.authorId} does not exist.`));
    if (course.areaId && !areas.has(course.areaId)) fail(BATCH_REFERENCE.fail(entity, `Area ${course.areaId} does not exist.`));
    if (typeof course.subareaId === "string" && subareas.get(course.subareaId) !== course.areaId) fail(BATCH_REFERENCE.fail(entity, `Subarea ${course.subareaId} is not in ${course.areaId ?? "its area"}.`));
    if (course.licenseCode && !licenseCodes.has(course.licenseCode)) fail(BATCH_REFERENCE.fail(entity, `License ${course.licenseCode} does not exist.`));
    const declared = coverDeclarationProblem({ id: course.id, areaId: course.areaId ?? null, subareaId: course.subareaId ?? null }, course.coverFrom);
    if (declared) fail(COVER_DECLARED.fail(entity, declared));
    else {
      const owner = coverOwner(course.coverFrom, course.id);
      if (owner) {
        const missing = missingCoverKinds(ownerKinds(owner));
        if (missing.length > 0) fail(COVER_DECLARED.fail(entity, `Declared ${course.coverFrom} lacks ${missing.join(", ")}.`));
      }
    }
    if (course.sourceId && !refs.sources.has(course.sourceId) && !batch.sources.some((source) => source.id === course.sourceId)) fail(BATCH_REFERENCE.fail(entity, `Source ${course.sourceId} does not exist.`));
    for (const [id, stored] of refs.courses) if (stored.slug === course.slug && id !== course.id) fail(BATCH_DUPLICATE.fail(entity, `Slug ${course.slug} belongs to course ${id}.`));
    const stored = refs.courses.get(course.id);
    if (stored?.institutionId && stored.institutionId !== item.institutionId) fail(BATCH_HOME_ROW.fail(entity, `Course ${course.id} is offered by ${stored.institutionId}.`));
    if (item.homeRowId) {
      if (!rowOwner.has(item.homeRowId)) fail(BATCH_REFERENCE.fail(entity, `Row ${item.homeRowId} does not exist.`));
      else if (rowOwner.get(item.homeRowId) !== item.institutionId) fail(BATCH_HOME_ROW.fail(entity, `Row ${item.homeRowId} belongs to ${rowOwner.get(item.homeRowId) ?? "no institution"}.`));
    }
    ops.push({ step: "course", action: stored ? "update" : "create", id: course.id });
  }

  function ownerKinds(owner: { kind: "course" | "subarea" | "area"; id: string }): Set<string> {
    const kinds = new Set(refs.covers.get(`${owner.kind}:${owner.id}`) ?? []);
    if (owner.kind === "course") {
      for (const cover of batch.courses.find((item) => item.course.id === owner.id)?.covers ?? []) kinds.add(cover.kind);
    } else {
      const node = owner.kind === "area" ? batch.areas.find((item) => item.id === owner.id) : batch.subareas.find((item) => item.id === owner.id);
      for (const cover of taxonomyCoverEntries(owner.kind, node?.cover)) if (cover.allowed) kinds.add(cover.kind);
    }
    return kinds;
  }

  const rank = new Map(ORDER.map((step, index) => [step, index]));
  return { ops: [...ops].sort((a, b) => (rank.get(a.step) ?? 0) - (rank.get(b.step) ?? 0)), failures };
}
