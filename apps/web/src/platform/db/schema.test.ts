import { getSchema } from "better-auth/db";
import { getTableColumns } from "drizzle-orm";
import { describe, expect, it } from "vitest";
import { account, session, user, verification } from "./schema.ts";

describe("Better Auth 1.7.7 database contract", () => {
  const tables = { user, session, account, verification };
  for (const [name, expected] of Object.entries(getSchema({}))) {
    it(`supports every pinned core field in ${name}`, () => {
      const table = tables[name as keyof typeof tables];
      expect(table).toBeDefined();
      const columns = getTableColumns(table);
      expect(columns.id.primary).toBe(true);
      for (const [key, field] of Object.entries(expected.fields)) {
        const column = columns[key as keyof typeof columns];
        expect(column, key).toBeDefined();
        expect(column.dataType, key).toBe(field.type === "string" ? "string" : field.type);
        expect(column.notNull, key).toBe(field.required === true);
        if (field.unique) expect(column.isUnique, key).toBe(true);
      }
    });
  }
});
