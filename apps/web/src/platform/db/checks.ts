import { courseStatuses } from "../../kernel/course-status.ts";
import { homeRowKinds } from "../../kernel/home-row-kind.ts";
import { lessonKinds } from "../../kernel/lesson-kind.ts";
import { TEXT_FIELDS } from "../../kernel/text-fields.ts";

function quoted(words: readonly string[]): string {
  return words.map((word) => `'${word}'`).join(", ");
}

/** CHECK for courses.status. The words and the order are courseStatuses. */
export function coursesStatusSql(): string {
  return `"courses"."status" IN (${quoted(courseStatuses)})`;
}

/** CHECK for lessons.kind. The words and the order are lessonKinds. */
export function lessonsKindSql(): string {
  return `"lessons"."kind" IN (${quoted(lessonKinds)})`;
}

/** CHECK for home_rows.kind. The words and the order are homeRowKinds. */
export function homeRowsKindSql(): string {
  return `"home_rows"."kind" IN (${quoted(homeRowKinds)})`;
}

/** CHECK for catalog_texts.field. Entity order and field order are TEXT_FIELDS. */
export function catalogTextsFieldSql(): string {
  const table = "catalog_texts";
  return (Object.keys(TEXT_FIELDS) as (keyof typeof TEXT_FIELDS)[])
    .map((kind) => `("${table}"."entity_kind" = '${kind}' AND "${table}"."field" IN (${quoted(Object.keys(TEXT_FIELDS[kind]))}))`)
    .join(" OR ");
}
