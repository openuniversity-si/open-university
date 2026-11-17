import { coverKindsByOwner } from "../../kernel/cover-kinds.ts";
import type { MediaAsset, MediaOwner } from "../../media/domain/types.ts";
import { coverOwner, resolveCover } from "./cover-resolve.ts";

export interface CoverReadCourse {
  readonly id: string;
  readonly coverFrom?: string;
}

export interface CoverReadLesson {
  readonly id: string;
  readonly courseId: string;
}

export interface OwnedPublicAsset {
  readonly owner: MediaOwner;
  readonly asset: MediaAsset;
}

const courseReadKinds = [
  ...coverKindsByOwner.course.map((kind) => [kind, "default"] as const),
  ["hero_desktop_16x9", "og"] as const,
];

/** Owners whose rows the read needs. The course's own row is always requested; the declaration adds one other. */
export function ownerRefsForCourses(courses: readonly CoverReadCourse[], courseIds: readonly string[]): { owner: MediaOwner; ownerId: string }[] {
  const ids = [...new Set(courseIds)];
  const byId = new Map(courses.map((course) => [course.id, course]));
  const owners: { owner: MediaOwner; ownerId: string }[] = ids.map((id) => ({ owner: "course", ownerId: id }));
  for (const id of ids) {
    const course = byId.get(id);
    const inherited = course?.coverFrom ? coverOwner(course.coverFrom, course.id) : undefined;
    if (inherited && inherited.kind !== "course") owners.push({ owner: inherited.kind, ownerId: inherited.id });
  }
  const seen = new Set<string>();
  return owners.filter((owner) => {
    const key = `${owner.owner}:${owner.ownerId}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function assetsOf(rows: readonly OwnedPublicAsset[]): (owner: MediaOwner, id: string) => readonly MediaAsset[] | undefined {
  const grouped = new Map<string, MediaAsset[]>();
  for (const row of rows) {
    const key = `${row.owner}:${row.asset.ownerId}`;
    const list = grouped.get(key) ?? [];
    list.push(row.asset);
    grouped.set(key, list);
  }
  return (owner, id) => grouped.get(`${owner}:${id}`);
}

/** The course figures `resolveCover` already chose, in the same order the read returns today. */
export function courseCoverAssets(courses: readonly CoverReadCourse[], courseIds: readonly string[], rows: readonly OwnedPublicAsset[]): Map<string, readonly MediaAsset[]> {
  const ids = new Set(courseIds);
  const of = assetsOf(rows);
  const resolved = new Map<string, readonly MediaAsset[]>();
  for (const course of courses) {
    if (!ids.has(course.id)) continue;
    const owner = course.coverFrom ? coverOwner(course.coverFrom, course.id) : undefined;
    const own = of("course", course.id);
    const sources = {
      area: owner?.kind === "area" ? of("area", owner.id) : undefined,
      course: own,
      subarea: owner?.kind === "subarea" ? of("subarea", owner.id) : undefined,
      coverFrom: course.coverFrom,
      courseId: course.id,
    };
    const assets: MediaAsset[] = [];
    for (const [kind, variant] of courseReadKinds) {
      const asset = resolveCover(sources, { target: "course", kind, variant });
      if (asset) assets.push(asset.kind === kind && asset.variant === variant ? asset : { ...asset, kind, variant });
    }
    assets.push(...(own ?? []).filter((asset) => asset.variant !== "default" && !(asset.kind === "hero_desktop_16x9" && asset.variant === "og")));
    if (assets.length) resolved.set(course.id, assets);
  }
  return resolved;
}

/** Lesson rows, plus the declared owner's frame when the lesson has none of its own. */
export function lessonCoverAssets(lessons: readonly CoverReadLesson[], courseId: string, lessonRows: readonly MediaAsset[], inherited: readonly MediaAsset[], coverFrom: string | undefined): Map<string, readonly MediaAsset[]> {
  const owner = coverFrom ? coverOwner(coverFrom, courseId) : undefined;
  const own = owner?.kind === "course" ? inherited : [];
  const shared = owner?.kind === "subarea" ? inherited : [];
  const area = owner?.kind === "area" ? inherited : [];
  const resolved = new Map<string, MediaAsset[]>(lessonRows.map((asset) => [asset.ownerId, []]));
  for (const asset of lessonRows) resolved.get(asset.ownerId)?.push(asset);
  for (const lesson of lessons) {
    if (lesson.courseId !== courseId) continue;
    const rows = resolved.get(lesson.id) ?? [];
    const asset = resolveCover({ lesson: rows, course: own, subarea: shared, area, coverFrom, courseId }, { target: "lesson" });
    if (asset && !rows.includes(asset)) resolved.set(lesson.id, [...rows, { ...asset, kind: "cover_16x9", variant: "default" }]);
  }
  return resolved;
}
