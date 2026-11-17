import { requiredCoverKinds } from "../../kernel/cover-kinds.ts";
import { courseStatus } from "./course-status.ts";

/** The four kinds a published course's declared owner must have. Status rules re-export this list. */
export const REQUIRED_COVERS = requiredCoverKinds;

/**
 * D-031. A course names the one owner of its covers. `own` is the course. `subarea:<id>` is legal only for the
 * course's own subarea. `area:<id>` is legal only when the course has no subarea, and only for its own area.
 * Nothing walks from that owner to another, and a course never names its institution.
 */
export const COVER_FROM_PATTERN = /^(own|subarea:[a-z0-9]+(?:-[a-z0-9]+)*|area:[a-z0-9]+(?:-[a-z0-9]+)*)$/;

export type CoverOwnerKind = "course" | "subarea" | "area";

export interface CoverOwner {
  readonly kind: CoverOwnerKind;
  readonly id: string;
}

/** The owner a declaration names. `courseId` is the id used when the declaration is `own`. */
export function coverOwner(token: string, courseId: string): CoverOwner | undefined {
  if (token === "own") return { kind: "course", id: courseId };
  const subarea = /^subarea:([a-z0-9]+(?:-[a-z0-9]+)*)$/.exec(token);
  const subareaId = subarea?.[1];
  if (subareaId) return { kind: "subarea", id: subareaId };
  const area = /^area:([a-z0-9]+(?:-[a-z0-9]+)*)$/.exec(token);
  const areaId = area?.[1];
  if (areaId) return { kind: "area", id: areaId };
  return undefined;
}

/**
 * Why this declaration is illegal for this course, or null when it is the course's own subarea, its area when it
 * has none, or `own`.
 */
export function coverDeclarationProblem(
  course: { readonly id: string; readonly areaId?: string | null; readonly subareaId?: string | null },
  token: string,
): string | null {
  const owner = coverOwner(token, course.id);
  if (!owner) return `Course ${course.id} coverFrom must be own, subarea:<id> or area:<id>.`;
  if (owner.kind === "course") return null;
  if (owner.kind === "subarea") {
    if (course.subareaId !== owner.id) return `Course ${course.id} declares ${token}, which is not its subarea.`;
    return null;
  }
  if (course.subareaId) return `Course ${course.id} has subarea ${course.subareaId} and cannot declare ${token}.`;
  if (course.areaId !== owner.id) return `Course ${course.id} declares ${token}, which is not its area.`;
  return null;
}

/** Required kinds the declared owner does not have. */
export function missingCoverKinds(kinds: ReadonlySet<string>): string[] {
  return REQUIRED_COVERS.filter((kind) => !kinds.has(kind));
}

export interface CoverBackfillInput {
  readonly id: string;
  readonly status: string;
  readonly areaId: string | null;
  readonly subareaId: string | null;
  readonly coverProvisional: boolean;
  /** Active default kinds on the course, its subarea and its area. Institution kinds are not an input. */
  readonly ownKinds: readonly string[];
  readonly subareaKinds: readonly string[];
  readonly areaKinds: readonly string[];
}

export interface CoverBackfill {
  readonly coverFrom: string;
  /** A published course whose declared owner lacks a required kind is unpublished. */
  readonly held: boolean;
  /** Set when the declared owner lacks a required kind, whether or not the course was published. */
  readonly reason: string | null;
}

/**
 * The reviewed backfill (D-031). The old `cover_provisional` flag is the declaration, not a hint to walk:
 * provisional with a subarea declares that subarea; provisional without one declares the area; anything else
 * declares `own`. A missing kind on that owner holds a published course. The area is not consulted when the
 * declaration is the subarea, and the institution is never consulted.
 */
export function reviewedCoverBackfill(course: CoverBackfillInput): CoverBackfill {
  const coverFrom = course.coverProvisional && course.subareaId
    ? `subarea:${course.subareaId}`
    : course.coverProvisional && course.areaId
      ? `area:${course.areaId}`
      : "own";
  const kinds = coverFrom === "own"
    ? course.ownKinds
    : coverFrom.startsWith("subarea:")
      ? course.subareaKinds
      : course.areaKinds;
  const missing = missingCoverKinds(new Set(kinds));
  const reason = missing.length > 0 ? `missing ${missing.join(",")}` : null;
  return { coverFrom, held: course.status === courseStatus.published && reason !== null, reason };
}
