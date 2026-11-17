import { fromDatabaseError } from "../../platform/db/errors.ts";

const SLUG_CONSTRAINTS = new Set(["courses_slug_unique", "authors_slug_unique", "lessons_course_slug", "licenses_pkey", "content_sources_pkey", "content_sources_playlist", "slug_redirects_pkey"]);

export const databaseError = (error: unknown) => fromDatabaseError(error, { slugConstraints: SLUG_CONSTRAINTS });
