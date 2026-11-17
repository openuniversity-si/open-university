import { AppError, unprocessable } from "../../kernel/errors.ts";

// A lesson slug change and its redirects (BRIEF-P7 §2): pure, so the PATCH and its dry-run report share one plan.

export interface Redirect { readonly from: string; readonly to: string }

export interface SlugPlan {
  /** old path → new path. */
  readonly created: Redirect;
  /** Redirects that ended at the old path now end at the new one (A→B→C becomes A→C, B→C). */
  readonly flattened: readonly { readonly from: string; readonly before: string; readonly after: string }[];
  /** Going back to an earlier slug: its redirect would point at itself, so it goes. */
  readonly removed: readonly Redirect[];
}

/**
 * The redirects after the lesson at `oldPath` moves to `newPath`, given every redirect in `slug_redirects`. Because chains
 * are always flattened, every old URL of this lesson redirects straight to `oldPath`; one from `newPath` elsewhere is
 * another page's old URL (409 slug_taken). The result has no chain, no cycle and no self-redirect.
 */
export function planSlugChange(redirects: readonly Redirect[], oldPath: string, newPath: string): SlugPlan {
  const blocking = redirects.find((redirect) => redirect.from === newPath && redirect.to !== oldPath);
  if (blocking) {
    throw new AppError("slug_taken", `${newPath} is the source of a redirect to ${blocking.to}; delete the redirect first.`, { redirect: blocking });
  }
  return {
    created: { from: oldPath, to: newPath },
    flattened: redirects.filter((redirect) => redirect.to === oldPath && redirect.from !== newPath)
      .map((redirect) => ({ from: redirect.from, before: oldPath, after: newPath })),
    removed: redirects.filter((redirect) => redirect.from === newPath),
  };
}


export interface SlugChange { readonly lessonId: string; readonly slug: string }

export interface SlugBatchPlan {
  /** The lessons whose slug changes (a change to the current slug is dropped). */
  readonly changes: readonly { readonly lessonId: string; readonly before: string; readonly after: string }[];
  readonly created: readonly Redirect[];
  readonly flattened: SlugPlan["flattened"];
  readonly removed: readonly Redirect[];
  /** Old paths another lesson of the batch now holds (a swap A↔B): they show that lesson, so no redirect leaves them. */
  readonly reused: readonly string[];
}

/**
 * The batch form of planSlugChange (PUT /lessons/slugs, BRIEF-P7 §2): every change applied at once against the course's
 * final slugs, so swaps and rotations need no free slug. `lessons` is every lesson of the course and `redirects` every
 * redirect from or into the course's lesson paths. Two lessons ending on one slug, or a new path that is another page's
 * old URL, is 409 slug_taken and nothing is planned. The result has no chain, no cycle and no self-redirect.
 */
export function planSlugBatch(coursePath: string, lessons: readonly { readonly id: string; readonly slug: string }[], redirects: readonly Redirect[], changes: readonly SlugChange[]): SlugBatchPlan {
  const current = new Map(lessons.map((lesson) => [lesson.id, lesson.slug]));
  const ids = changes.map((change) => change.lessonId);
  const repeated = ids.find((id, index) => ids.indexOf(id) !== index);
  if (repeated !== undefined) throw unprocessable(`${repeated} appears twice in the batch.`, { lessonId: repeated });
  const moved: { lessonId: string; before: string; after: string }[] = [];
  for (const change of changes) {
    const before = current.get(change.lessonId);
    if (before === undefined) throw unprocessable(`${change.lessonId} is not a lesson of this course.`, { lessonId: change.lessonId });
    if (before !== change.slug) moved.push({ lessonId: change.lessonId, before, after: change.slug });
  }
  const path = (slug: string) => `${coursePath}/${slug}`;
  const final = new Map(current);
  for (const change of moved) final.set(change.lessonId, change.after);
  for (const change of moved) {
    const holders = [...final].filter(([, slug]) => slug === change.after).map(([id]) => id);
    if (holders.length > 1) throw new AppError("slug_taken", `The lesson slug ${change.after} would be taken twice in this course.`, { slug: change.after, lessonIds: holders });
  }

  const live = new Set([...final.values()].map(path));
  const newPaths = new Set(moved.map((change) => path(change.after)));
  const movedFrom = new Map(moved.map((change) => [path(change.before), path(change.after)]));
  const flattened: { from: string; before: string; after: string }[] = [];
  const removed: Redirect[] = [];
  for (const redirect of redirects) {
    const to = movedFrom.get(redirect.to) ?? redirect.to;
    if (newPaths.has(redirect.from)) {
      // Going back to an earlier slug of the same lesson drops its redirect; another page's old URL blocks the batch.
      if (to !== redirect.from) throw new AppError("slug_taken", `${redirect.from} is the source of a redirect to ${redirect.to}; delete the redirect first.`, { redirect });
      removed.push(redirect);
    } else if (to !== redirect.to) {
      flattened.push({ from: redirect.from, before: redirect.to, after: to });
    }
  }
  const created = moved.filter((change) => !live.has(path(change.before))).map((change) => ({ from: path(change.before), to: path(change.after) }));
  const reused = moved.filter((change) => live.has(path(change.before))).map((change) => path(change.before));
  return { changes: moved, created, flattened, removed, reused };
}
