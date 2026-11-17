import type { Queryable } from "../../platform/db/uow.ts";

/** D-024: a course placed on a University row without an institution takes that row's institution. */
export async function adoptRowInstitutions(db: Queryable, rowIds: readonly string[]): Promise<void> {
  await db.query(`UPDATE courses c SET institution_id = r.institution_id
    FROM home_row_items i JOIN home_rows r ON r.id = i.row_id AND r.kind = 'curated'
    WHERE i.course_id = c.id AND c.institution_id IS NULL AND i.row_id = ANY($1::text[])`, [rowIds]);
}
