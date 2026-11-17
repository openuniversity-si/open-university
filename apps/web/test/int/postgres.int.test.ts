import pg from "pg";
import { afterAll, beforeAll, describe, expect, it } from "vitest";

/**
 * Integration tests run against a real Postgres (service container in CI,
 * local server in development). They never fall back to a mock.
 */
const connectionString = process.env.TEST_DATABASE_URL;

describe("Postgres integration harness", () => {
  let client: pg.Client | undefined;

  function db(): pg.Client {
    if (client === undefined) throw new Error("not connected");
    return client;
  }

  beforeAll(async () => {
    if (connectionString === undefined || connectionString === "") {
      throw new Error("TEST_DATABASE_URL is not set; pnpm test:int needs a real Postgres.");
    }
    client = new pg.Client({ connectionString });
    await client.connect();
  });

  afterAll(async () => {
    await client?.end();
  });

  it("reaches a Postgres 18+ server", async () => {
    const { rows } = await db().query<{ server_version_num: string }>("show server_version_num");
    expect(Number(rows[0]?.server_version_num)).toBeGreaterThanOrEqual(180000);
  });

  it("round-trips rows inside a transaction that is rolled back", async () => {
    await db().query("begin");
    try {
      await db().query("create temp table harness_probe (id int primary key, label text not null)");
      await db().query("insert into harness_probe (id, label) values ($1, $2), ($3, $4)", [1, "a", 2, "b"]);
      const { rows } = await db().query<{ id: number; label: string }>("select id, label from harness_probe order by id");
      expect(rows).toEqual([
        { id: 1, label: "a" },
        { id: 2, label: "b" },
      ]);
    } finally {
      await db().query("rollback");
    }
  });
});
