import { describe, expect, it } from "vitest";
import { parseReturnUI } from "./return-ui.ts";

const valid = { route: "/", scrollX: 0, scrollY: 120.5, selection: { home: "course-2" }, rails: [{ id: "rail-row-x", left: 228 }] };

describe("return UI parsing", () => {
  it("accepts the saved shape and drops unknown keys", () => {
    expect(parseReturnUI({ ...valid, extra: 1, rails: [{ id: "a", left: 0, top: 3 }] })).toEqual({ ...valid, rails: [{ id: "a", left: 0 }] });
    expect(parseReturnUI({ ...valid, selection: {} })).toEqual({ ...valid, selection: {} });
  });

  it.each([
    null, "x", [], { ...valid, route: 1 }, { ...valid, scrollX: -1 }, { ...valid, scrollY: Number.POSITIVE_INFINITY }, { ...valid, scrollY: "1" },
    { ...valid, selection: [] }, { ...valid, selection: { home: 2 } }, { ...valid, rails: {} }, { ...valid, rails: [{ id: "a", left: -4 }] }, { ...valid, rails: [null] },
  ])("rejects %j", (value) => {
    expect(parseReturnUI(value)).toBeNull();
  });
});
