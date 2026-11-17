/**
 * D-032. A YouTube video may be a lesson of more than one course only when each course
 * names the other in `sharedWith`. One course still holds the video at most once (D-003).
 */
export interface VideoUse {
  readonly courseId: string;
  readonly youtubeId: string;
}

export interface UnsharedVideo {
  readonly courseId: string;
  readonly otherCourseId: string;
  readonly youtubeId: string;
}

function mutual(shares: ReadonlyMap<string, readonly string[]>, left: string, right: string): boolean {
  return (shares.get(left) ?? []).includes(right) && (shares.get(right) ?? []).includes(left);
}

/**
 * Pairs that use one video without a mutual declaration. A pair is reported only when at least
 * one of the courses is in `declared` (the courses this write is changing).
 */
export function unsharedVideoPairs(
  uses: readonly VideoUse[],
  shares: ReadonlyMap<string, readonly string[]>,
  declared: ReadonlySet<string>,
): UnsharedVideo[] {
  const byVideo = new Map<string, Set<string>>();
  for (const use of uses) {
    const courses = byVideo.get(use.youtubeId) ?? new Set<string>();
    courses.add(use.courseId);
    byVideo.set(use.youtubeId, courses);
  }
  const problems: UnsharedVideo[] = [];
  for (const [youtubeId, courses] of byVideo) {
    const ids = [...courses];
    for (let left = 0; left < ids.length; left += 1) {
      for (let right = left + 1; right < ids.length; right += 1) {
        const a = ids[left] ?? "";
        const b = ids[right] ?? "";
        if ((!declared.has(a) && !declared.has(b)) || mutual(shares, a, b)) continue;
        const named = declared.has(a) ? a : b;
        const other = named === a ? b : a;
        problems.push({ courseId: named, otherCourseId: other, youtubeId });
        if (declared.has(a) && declared.has(b)) problems.push({ courseId: b, otherCourseId: a, youtubeId });
      }
    }
  }
  return problems;
}
