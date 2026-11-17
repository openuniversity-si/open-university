import { inheritedSources, type CoverInheritanceGraph } from "../../media/domain/inheritance.ts";
import { coverOwner } from "./cover-source.ts";
export { coverOwner };
import type { NodeKind } from "./hierarchy.ts";

/** INV-M2/M3/D-031: the only cover decision. It reads the declared owner and does not walk. */
export interface CoverAsset { readonly kind: string; readonly variant?: string; readonly isActive?: boolean }
export type CoverNodeKind = NodeKind;
export interface CoverSources<T extends CoverAsset> {
  readonly institution?: readonly T[];
  readonly area?: readonly T[];
  readonly subarea?: readonly T[];
  readonly course?: readonly T[];
  readonly lesson?: readonly T[];
  /** The course's declaration. Course and lesson targets read only this owner. */
  readonly coverFrom?: string;
  readonly courseId?: string;
}

function active<T extends CoverAsset>(assets: readonly T[] | undefined, kind: string, variant = "default"): T | undefined {
  return assets?.find((asset) => asset.isActive !== false && asset.kind === kind && (asset.variant ?? "default") === variant);
}

/** Assets of the declared owner. A missing or illegal declaration yields none, never an ancestor. */
export function declaredCoverAssets<T extends CoverAsset>(sources: CoverSources<T>): readonly T[] | undefined {
  if (!sources.coverFrom) return undefined;
  const owner = coverOwner(sources.coverFrom, sources.courseId ?? "");
  if (!owner) return undefined;
  if (owner.kind === "course") return sources.course;
  if (owner.kind === "subarea") return sources.subarea;
  return sources.area;
}

export function resolveCover<T extends CoverAsset>(sources: CoverSources<T>, request: { readonly target: CoverNodeKind; readonly kind?: string; readonly variant?: string; readonly presentation?: "share" }): T | undefined {
  if (request.presentation === "share") {
    const candidates = request.target === "institution"
      ? [["og", "default"], ["poster_9x16", "default"]] as const
      : [["hero_desktop_16x9", "og"], ["hero_desktop_16x9", "default"], ["still_16x9", "default"]] as const;
    for (const [kind, variant] of candidates) {
      const asset = resolveCover(sources, { target: request.target, kind, variant });
      if (asset) return asset;
    }
    return undefined;
  }
  const kind = request.kind ?? (request.target === "lesson" ? "cover_16x9" : "poster_9x16");
  const variant = request.variant ?? "default";
  if (request.target === "institution") return active(sources.institution, kind, variant);
  if (request.target === "area") return active(sources.area, kind, variant);
  if (request.target === "subarea") return active(sources.subarea, kind, variant);
  const declared = declaredCoverAssets(sources);
  if (request.target === "lesson" && request.kind === undefined) {
    // The lesson's own frame wins. The fallback is the course's declared owner, one owner, not a walk.
    // still_16x9 and lesson_default are the two stored names of that owner's lesson frame.
    return active(sources.lesson, "cover_16x9") ?? active(declared, "still_16x9") ?? active(declared, "lesson_default");
  }
  if (request.target === "lesson") {
    return active(sources.lesson, kind, variant) ?? active(declared, kind, variant);
  }
  const own = active(declared, kind, variant);
  if (own) return own;
  // Share art asks for the hero's og variant; the same owner may store that frame as kind `og`.
  if (kind === "hero_desktop_16x9" && variant === "og") return active(declared, "og");
  return undefined;
}

/** Lesson frames that repeat the declared owner's frame. The sha set is the doctor's. */
export function redundantLessons(graph: CoverInheritanceGraph) {
  const courses = new Map(graph.courses.map((row) => [row.id, row]));
  const inherited = new Map<string, { asset: CoverInheritanceGraph["lessonAssets"][number]; courseId: string }>();
  for (const lesson of graph.lessons) {
    const course = courses.get(lesson.course_id);
    const asset = course && resolveCover(inheritedSources(graph, course), { target: "lesson" });
    if (asset) inherited.set(lesson.id, { asset, courseId: lesson.course_id });
  }
  return graph.lessonAssets.flatMap((asset) => {
    const fallback = inherited.get(asset.ownerId);
    return asset.kind === "cover_16x9" && asset.variant === "default" && fallback?.asset.sha256 === asset.sha256
      ? [{ asset, inherited: fallback.asset, courseId: fallback.courseId }] : [];
  });
}
