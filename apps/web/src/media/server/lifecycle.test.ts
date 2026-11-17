import { describe, expect, it } from "vitest";
import { clearOrphaned, listLifecycleRows, markOrphaned, retentionEligible } from "./lifecycle.ts";
import { RETENTION_MS } from "../domain/figure-exit.ts";

const sha = "b".repeat(64);

function db(marked: string | null, referenced = false) {
  const state = { orphanedAt: marked, writes: 0 };
  return {
    state,
    query: (sql: string) => {
      if (sql.includes("catalog_media") || sql.includes("UNION ALL") || sql.includes("UNION SELECT")) return Promise.resolve({ rows: referenced ? [{ sha256: sha, hit: 1 }] : [] });
      if (sql.startsWith("SELECT sha256, orphaned_at")) return Promise.resolve({ rows: [{ sha256: sha, orphaned_at: state.orphanedAt }] });
      if (sql.startsWith("UPDATE") && sql.includes("orphaned_at = now()")) {
        if (state.orphanedAt) return Promise.resolve({ rows: [] });
        state.orphanedAt = "2026-09-20T00:00:00.000Z";
        state.writes += 1;
        return Promise.resolve({ rows: [{ sha256: sha }] });
      }
      if (sql.startsWith("UPDATE") && sql.includes("NULL")) { state.orphanedAt = null; return Promise.resolve({ rows: [] }); }
      if (sql.startsWith("SELECT orphaned_at")) return Promise.resolve({ rows: [{ orphaned_at: state.orphanedAt }] });
      return Promise.resolve({ rows: [] });
    },
  };
}

describe("lifecycle SQL adapter", () => {
  it("marks once, keeps the original deadline, and clears it when a link returns", async () => {
    const store = db(null);
    expect(await markOrphaned(store, sha)).toBe("marked");
    expect(await markOrphaned(store, sha)).toBe("already");
    expect(store.state.writes).toBe(1);
    expect(store.state.orphanedAt).toBe("2026-09-20T00:00:00.000Z");
    await clearOrphaned(store, sha);
    expect(store.state.orphanedAt).toBeNull();
    expect(await markOrphaned(store, sha)).toBe("marked");
    expect(store.state.writes).toBe(2);
  });

  it("does not treat a reference without bytes as an orphan and holds young markers", async () => {
    const rows = await listLifecycleRows(db(null), [{ sha256: sha, retainedRelease: true }]);
    expect(rows[0]).toMatchObject({ sha256: sha, bytesPresent: true, retainedRelease: true });
    const missing = await listLifecycleRows({ query: () => Promise.resolve({ rows: [] }) }, [{ sha256: "c".repeat(64), retainedRelease: false }]);
    expect(missing[0]).toMatchObject({ bytesPresent: false, referenced: true });
    const now = new Date("2026-10-20T00:00:00.000Z");
    const young = new Date(now.getTime() - (RETENTION_MS - 60_000)).toISOString();
    const eligible = db(new Date(now.getTime() - RETENTION_MS).toISOString());
    expect(await retentionEligible(db(young), `m/${sha}.jpg`, now)).toBe(false);
    expect(await retentionEligible(eligible, `m/${sha}.jpg`, now)).toBe(true);
    expect(await retentionEligible(eligible, "covers/legacy.jpg", now)).toBe(false);
    expect(await markOrphaned(db(null, true), sha)).toBe("referenced");
  });
});
