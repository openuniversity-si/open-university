import { afterAll, beforeAll, beforeEach, describe, expect, it } from "vitest";
import { activeRelease, auditRows, call, createHarness, seedCatalog, type DoctorData, type Harness, type PublicationData, type Seed } from "../fixtures/admin-catalog.ts";

// ADR-25: the areas and their order are data. Adding, moving or renaming one is one admin API call; move and rename
// rewrite the order in one transaction and cut one release. The doctor compares the release with the tables.
interface AreaRow { id: string; title: string; position: number }
type AreaData = PublicationData & { area: AreaRow; areas?: AreaRow[] };

describe("admin catalog: areas", () => {
  let h: Harness;
  let seed: Seed;
  let n = 0;
  const key = () => { n += 1; return `area-${String(n)}`; };
  beforeAll(() => { h = createHarness(); });
  afterAll(async () => { await h.close(); });
  beforeEach(async () => {
    seed = await seedCatalog(h);
    // A published course with an area: the release carries `areas` from here on.
    await call(h, "POST", "/courses/classify", { key: key(), body: { items: [{ id: seed.courses.alpha, areaId: "psychology" }] } });
    expect((await call(h, "POST", "/releases", { key: key(), body: { note: "areas" } })).status).toBe(201);
  }, 60_000);

  const stored = async () => (await h.pool.query<AreaRow>("SELECT id, title, position FROM subject_areas ORDER BY position")).rows;
  const released = async () => (await h.pool.query<{ payload: { areas?: { id: string; title: string }[] } }>("SELECT payload FROM catalog_releases WHERE is_active")).rows[0]?.payload.areas ?? [];
  const move = (id: string, position: number) => call<AreaData>(h, "POST", `/areas/${id}/move`, { key: key(), body: { position } });
  const expectContiguous = async () => {
    const rows = await stored();
    expect(rows.map((row) => row.position)).toEqual(rows.map((_row, index) => index + 1));
    expect((await released()).map((area) => area.id)).toEqual(rows.map((row) => row.id));
    return rows.map((row) => row.id);
  };

  it("moves an area to the first, the last and a middle position in one release each, keeping positions 1..n", async () => {
    const initial = (await stored()).map((row) => row.id);
    const release = (await activeRelease(h)).number;

    const first = await move("law", 1);
    expect(first.status).toBe(200);
    expect(first.data.area).toMatchObject({ id: "law", position: 1 });
    expect(first.data.release).toMatchObject({ number: release + 1, created: true });
    expect(await expectContiguous()).toEqual(["law", ...initial.filter((id) => id !== "law")]);
    expect((await auditRows(h, { action: "area.move" }))[0]).toMatchObject({ entity_id: "law", release_number: release + 1 });

    const last = await move("law", initial.length);
    expect(last.data.release.number).toBe(release + 2);
    expect(await expectContiguous()).toEqual([...initial.filter((id) => id !== "law"), "law"]);

    const middle = await move("psychology", 7);
    expect(middle.data.release.number).toBe(release + 3);
    const order = await expectContiguous();
    expect(order.indexOf("psychology")).toBe(6);
    expect(order.filter((id) => id !== "psychology")).toEqual([...initial.filter((id) => id !== "law" && id !== "psychology"), "law"]);
    expect((await h.pool.query("SELECT count(*)::int AS n FROM catalog_releases")).rows[0]).toEqual({ n: release + 3 });
  });

  it("changes nothing and cuts no release for a move to the same position", async () => {
    const before = { order: await stored(), release: await activeRelease(h), audits: (await auditRows(h)).length };
    const same = await move("psychology", 13);
    expect(same.status).toBe(200);
    expect(same.data.noop).toBe(true);
    expect(await stored()).toEqual(before.order);
    expect(await activeRelease(h)).toEqual(before.release);
    expect((await auditRows(h)).length).toBe(before.audits);
  });

  it("refuses an out-of-range position and an unknown area; nothing is written", async () => {
    const before = { order: await stored(), release: await activeRelease(h) };
    const beyond = await move("law", before.order.length + 1);
    expect([beyond.status, beyond.body.error?.code]).toEqual([422, "unprocessable"]);
    expect((await move("law", 0)).status).toBe(400);
    const unknown = await move("no-such-area", 1);
    expect([unknown.status, unknown.body.error?.code]).toEqual([404, "not_found"]);
    expect(await stored()).toEqual(before.order);
    expect(await activeRelease(h)).toEqual(before.release);
    expect(await auditRows(h, { action: "area.move" })).toEqual([]);
  });

  it("serializes concurrent moves; positions stay unique and contiguous", async () => {
    const initial = (await stored()).map((row) => row.id);
    const moved = (order: readonly string[], id: string, position: number) => {
      const rest = order.filter((entry) => entry !== id);
      return [...rest.slice(0, position - 1), id, ...rest.slice(position - 1)];
    };
    const [a, b] = await Promise.all([move("law", 1), move("music", 2)]);
    expect([a.status, b.status]).toEqual([200, 200]);
    // Either move may commit first; the result is exactly one of the two serial orders, never a mix.
    const serial = [moved(moved(initial, "law", 1), "music", 2), moved(moved(initial, "music", 2), "law", 1)];
    expect(serial).toContainEqual(await expectContiguous());
  });

  it("renames an area in one release; the id stays, a taken title is refused", async () => {
    const release = (await activeRelease(h)).number;
    const renamed = await call<AreaData>(h, "PATCH", "/areas/law", { body: { title: "Legal Studies" } });
    expect(renamed.status).toBe(200);
    expect(renamed.data.area).toEqual({ id: "law", title: "Legal Studies", position: 20 });
    expect(renamed.data.release).toMatchObject({ number: release + 1, created: true });
    expect((await released()).find((area) => area.id === "law")).toEqual({ id: "law", title: "Legal Studies" });
    expect((await auditRows(h, { action: "area.update" }))[0]).toMatchObject({ entity_id: "law", release_number: release + 1 });

    const again = await call<AreaData>(h, "PATCH", "/areas/law", { body: { title: "Legal Studies" } });
    expect(again.data.noop).toBe(true);
    const taken = await call(h, "PATCH", "/areas/law", { body: { title: "physics" } });
    expect([taken.status, taken.body.error?.code]).toEqual([409, "slug_taken"]);
    expect((await call(h, "PATCH", "/areas/no-such-area", { body: { title: "Nothing" } })).status).toBe(404);
    expect((await activeRelease(h)).number).toBe(release + 1);
  });

  it("the doctor reports areas the database holds differently from the active release", async () => {
    const drift = async () => (await call<DoctorData>(h, "GET", "/doctor")).data.findings.find((finding) => finding.code === "taxonomy.drift");
    expect(await drift()).toBeUndefined();
    // Move and rename publish themselves: no drift after them.
    await move("law", 1);
    await call(h, "PATCH", "/areas/music", { body: { title: "Music Studies" } });
    expect(await drift()).toBeUndefined();
    // A created area waits for the next release.
    expect((await call(h, "POST", "/areas", { key: key(), body: { id: "design", title: "Design" } })).status).toBe(201);
    expect(await drift()).toMatchObject({ severity: "info", count: 1, sample: ["area:design"] });
    expect((await call(h, "POST", "/releases", { key: key(), body: { note: "design" } })).status).toBe(201);
    expect(await drift()).toBeUndefined();
  });
});
