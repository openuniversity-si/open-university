import pg from "pg";
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";

vi.mock("server-only", () => ({}));

import { runMigrations } from "../../../scripts/lib/migrations.ts";
import { codeLimits } from "../domain/documents.ts";
import { LIMITS } from "../../kernel/limits.ts";
import { testDatabaseUrl } from "../../../test/fixtures/admin-catalog.ts";
import { configRepository } from "./repository.ts";

describe("configuration revisions", () => {
  let pool: pg.Pool;

  beforeAll(async () => {
    const url = testDatabaseUrl();
    await runMigrations(url, false);
    pool = new pg.Pool({ connectionString: url });
  });

  afterAll(async () => {
    await pool.end();
  });

  it("appends a revision, keeps history, and refuses a stale expected revision", async () => {
    const repo = configRepository(pool);
    expect(await repo.read("limits")).toBeNull();
    expect(await repo.history("limits")).toEqual([]);
    await expect(repo.commit({
      kind: "limits",
      expectedRevision: 0,
      body: { ...codeLimits(), courseTitle: LIMITS.courseTitle + 1 },
      actor: "cli:test",
      note: null,
    })).rejects.toThrow(/outside the contract/);

    const created = await repo.commit({
      kind: "limits",
      expectedRevision: 0,
      body: codeLimits(),
      actor: "cli:test",
      note: null,
    });
    expect(created.revision).toBe(1);
    expect(created.body).toEqual(codeLimits());

    const lowered = { ...codeLimits(), courseTitle: 10 };
    const updated = await repo.commit({
      kind: "limits",
      expectedRevision: 1,
      body: lowered,
      actor: "cli:test",
      note: "lower",
    });
    expect(updated.revision).toBe(2);
    expect(updated.note).toBe("lower");
    await expect(repo.read("limits")).resolves.toMatchObject({ revision: 2, body: lowered });
    await expect(repo.history("limits")).resolves.toMatchObject([
      { revision: 1, body: codeLimits() },
      { revision: 2, body: lowered },
    ]);
    await expect(repo.commit({
      kind: "limits",
      expectedRevision: 0,
      body: codeLimits(),
      actor: "cli:test",
      note: null,
    })).rejects.toThrow(/current revision is 2/);

    const absent = await pool.query<{ n: number }>("SELECT count(*)::int AS n FROM config_document_revisions WHERE revision = 0");
    expect(absent.rows[0]?.n).toBe(0);
    await expect(pool.query("INSERT INTO config_documents (kind, revision, body, actor) VALUES ('nope', 1, '{}', 'cli')")).rejects.toMatchObject({ code: "23514" });
    await expect(pool.query("INSERT INTO config_documents (kind, revision, body, actor) VALUES ('copy', 0, '{}', 'cli')")).rejects.toMatchObject({ code: "23514" });
  });
});
