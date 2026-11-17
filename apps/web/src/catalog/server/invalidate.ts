import "server-only";
import { expirePath, expireTag } from "../../platform/freshness/next.ts";
import { CACHE } from "../../kernel/cache.ts";
import { CATALOG_PATHS } from "../../site/domain/catalog-paths.ts";
import { MEDIA_TAG } from "../../media/domain/tags.ts";
import { CATALOG_TAG } from "./read.ts";

/**
 * A release was activated: expire every cached catalog read now, and every static page that rendered them (ADR-16/17):
 * Home, sitemap, the Universities tab (counts, rails, area pages), Authors and Credits. The tag alone did not refresh the
 * prerendered pages on the previous host (/universities kept a stale course count), so each is purged by path too. Every media read
 * goes too: uploads to a course outside the release expire nothing (src/media/domain/tags.ts), so a newly published course
 * must not render from a list read cached before its covers existed.
 */
/** Purge catalog caches. Pass a transaction participant to run only after it commits. */
function isParticipant(value: { onAfterCommit(effect: () => void): void } | readonly string[]): value is { onAfterCommit(effect: () => void): void } {
  return !Array.isArray(value);
}

export function invalidateCatalog(participantOrCourses?: { onAfterCommit(effect: () => void): void } | readonly string[]): void {
  const participant = participantOrCourses !== undefined && isParticipant(participantOrCourses) ? participantOrCourses : undefined;
  const courseIds: readonly string[] = Array.isArray(participantOrCourses) ? participantOrCourses : [];
  const purge = () => {
    expireTag(CATALOG_TAG, { expire: CACHE.immediateExpiry });
    expireTag(`${CATALOG_TAG}:index`, { expire: CACHE.immediateExpiry });
    for (const courseId of courseIds) expireTag(`${CATALOG_TAG}:course:${courseId}`, { expire: CACHE.immediateExpiry });
    expireTag(MEDIA_TAG, { expire: CACHE.immediateExpiry });
    for (const [path, type] of CATALOG_PATHS) expirePath(path, type);
  };
  if (participant) participant.onAfterCommit(purge);
  else purge();
}
