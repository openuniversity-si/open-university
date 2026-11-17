import { describe, expect, it } from "vitest";
import { catalogTextsFieldSql, coursesStatusSql, homeRowsKindSql, lessonsKindSql } from "./checks.ts";

/**
 * The strings the 0033 snapshot already stores. A later leaf edit changes the function and
 * drizzle asks for one migration; this cut must not.
 */
const STORED_CHECK_SQL = {
  catalog_texts_field: `("catalog_texts"."entity_kind" = 'course' AND "catalog_texts"."field" IN ('displayTitle', 'shelfTitle', 'subtitle', 'billboardDescription', 'billboardDescriptionMobile', 'description', 'descriptionMobile', 'about', 'level', 'format')) OR ("catalog_texts"."entity_kind" = 'lesson' AND "catalog_texts"."field" IN ('displayTitle', 'about')) OR ("catalog_texts"."entity_kind" = 'author' AND "catalog_texts"."field" IN ('bio'))`,
  courses_status: `"courses"."status" IN ('draft', 'review', 'published', 'archived')`,
  home_rows_kind: `"home_rows"."kind" IN ('continue', 'author', 'curated')`,
  lessons_kind: `"lessons"."kind" IN ('lecture', 'background', 'compilation', 'trailer')`,
} as const;

describe("catalog checks read the leaf", () => {
  it("emits the CHECK SQL already stored for texts, status, home rows, and lesson kinds", () => {
    expect(catalogTextsFieldSql()).toBe(STORED_CHECK_SQL.catalog_texts_field);
    expect(coursesStatusSql()).toBe(STORED_CHECK_SQL.courses_status);
    expect(homeRowsKindSql()).toBe(STORED_CHECK_SQL.home_rows_kind);
    expect(lessonsKindSql()).toBe(STORED_CHECK_SQL.lessons_kind);
  });
});
