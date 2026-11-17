import { describe, expect, it, vi } from "vitest";
vi.mock("server-only", () => ({}));
import type { DbPool } from "../../platform/db/uow.ts";
import { catalogAdminJournal } from "./admin-journal.ts";

function pool() {
  const events: string[] = [];
  const query = vi.fn((sql: string) => {
    events.push(sql);
    if (sql.startsWith("SELECT route")) return Promise.resolve({ rows: [] });
    return Promise.resolve({ rows: [] });
  });
  const db: DbPool = { query, connect: () => Promise.resolve({ query, release: () => {} }) };
  return { events, db };
}

const claim = { key: "key-1", route: "POST /api/admin/media/attach", requestSha256: "a".repeat(64), requestId: "req-1", actor: "ada", action: "media.attach" };

describe("catalogAdminJournal", () => {
  it("writes the media change and the catalog journal in one transaction", async () => {
    const { events, db } = pool();
    const journal = catalogAdminJournal(() => db);
    const outcome = await journal.enclose?.(claim, async (participant) => {
      await participant.query("UPDATE catalog_media SET is_active = false");
      return { data: { version: 2 } };
    });
    expect(outcome).toEqual({ data: { version: 2 }, status: 200 });
    const commit = events.indexOf("COMMIT");
    expect(events[0]).toBe("BEGIN");
    expect(events.some((sql) => sql.startsWith("UPDATE catalog_media"))).toBe(true);
    expect(events.some((sql) => sql.startsWith("INSERT INTO catalog_audit"))).toBe(true);
    expect(events.some((sql) => sql.startsWith("INSERT INTO admin_idempotency"))).toBe(true);
    expect(commit).toBeGreaterThan(events.findIndex((sql) => sql.startsWith("INSERT INTO admin_idempotency")));
  });

  it("rolls the media statement back when the handler throws, and writes no journal", async () => {
    const { events, db } = pool();
    const journal = catalogAdminJournal(() => db);
    await expect(journal.enclose?.(claim, async (participant) => {
      await participant.query("UPDATE catalog_media SET is_active = false");
      throw new Error("storage");
    })).rejects.toThrow("storage");
    expect(events).toContain("ROLLBACK");
    expect(events.some((sql) => sql.includes("catalog_audit"))).toBe(false);
    expect(events).not.toContain("COMMIT");
  });
});
