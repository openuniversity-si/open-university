/** Course lifecycle statuses. A release contains only `published`. The database CHECK reads `courseStatuses`. */
export const courseStatus = {
  draft: "draft",
  review: "review",
  published: "published",
  archived: "archived",
} as const;

export const courseStatuses = [courseStatus.draft, courseStatus.review, courseStatus.published, courseStatus.archived] as const;

/** Statuses one course body may request. Publishing is a different route. */
export const courseBodyStatuses = [courseStatus.review, courseStatus.draft, courseStatus.archived] as const;

/** Statuses a bulk unpublish body may request. */
export const courseBulkStatuses = [courseStatus.draft, courseStatus.archived] as const;
