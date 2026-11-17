import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { requestAddress, sessionAddressHeaders } from "./request-address.ts";

describe("request address", () => {
  it("uses the first forwarded address and trims it", () => {
    expect(requestAddress(new Headers({ "x-forwarded-for": " 192.0.2.4 , 10.0.0.1" }))).toBe("192.0.2.4");
  });

  it("falls back to the single-address header, then unknown", () => {
    expect(requestAddress(new Headers({ "x-real-ip": "192.0.2.5" }))).toBe("192.0.2.5");
    expect(requestAddress(new Headers())).toBe("unknown");
  });

  it("names only the header the host rewrites", () => {
    expect(sessionAddressHeaders()).toEqual(["x-forwarded-for"]);
  });
});

describe("forwarding header", () => {
  it("stays in the host adapter", () => {
    const root = new URL("../../../", import.meta.url);
    const files = ["src/admin/auth.ts", "src/identity/server/config.ts"];
    const leaks = files.filter((file) => readFileSync(new URL(file, root), "utf8").includes("x-forwarded-for"));
    expect(leaks).toEqual([]);
  });
});
