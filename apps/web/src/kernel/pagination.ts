/**
 * Page sizes (D-050). A page is how many rows one read returns before the caller asks for the next cursor.
 * `LIMIT 1` is the one row, not a page. An empty result (`rows.length === 0`) is a bare 0 and stays
 * for the remainder domain. That deferral is not an exemption: the absolute gate still counts it.
 * The same number with a different job is a different key.
 * `COURSE_LIST_LIMIT` remains the page of GET /courses.
 */
export const PAGINATION = {
  /** One page of media object keys, walked in sha256 order. A full page means another cursor follows. */
  objectListPage: 500,
  /** One cleanup batch of admin idempotency keys older than 30 days. Not the object-list page. */
  idempotencySweep: 500,
  /** Safety cap on how many storage pages the lifecycle walk follows. Past this, the inventory is incomplete. */
  maxStoragePages: 10_000,
} as const;
