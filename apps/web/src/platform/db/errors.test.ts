import { describe, expect, it } from "vitest";
import { fromDatabaseError } from "./errors.ts";
const databaseError = (error: unknown) => fromDatabaseError(error, { slugConstraints: new Set(["courses_slug_unique"]) });
describe("admin errors", () => {
  it("maps constraint races to API codes without driver text", () => {
    const pg = (code: string, constraint?: string, detail?: string) => Object.assign(new Error("duplicate key value violates … SELECT secret"), { code, constraint, detail });
    expect(databaseError(pg("23505", "courses_slug_unique"))?.code).toBe("slug_taken");
    expect(databaseError(pg("23505", "lessons_course_position"))?.code).toBe("state_conflict");
    expect(databaseError(pg("23503", "courses_author_fk", "Key (id)=(author-1) is still referenced from table courses."))?.code).toBe("has_dependents");
    expect(databaseError(pg("23503", "courses_author_fk", "Key is not present in table authors."))?.code).toBe("unprocessable");
    expect(databaseError(pg("23514", "courses_published_rights"))?.message).toBe("Violates courses_published_rights.");
    expect(databaseError(pg("55000"))?.code).toBe("state_conflict");
    expect(databaseError(pg("57P01"))).toBeNull();
    expect(databaseError(null)).toBeNull();
    for (const code of ["23505", "23503", "23514", "55000"]) expect(databaseError(pg(code))?.message).not.toContain("SELECT");
  });

});
