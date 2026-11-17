import { describe, expect, it } from "vitest";
import { SIGNED_IN_HOME_PATH } from "../../src/site/domain/home-routing.ts";
import { staticHomeFailures } from "./static-home.ts";

describe("static Home guardian (ADR-16)", () => {
  it("passes an ISR Home with a dynamic signed-in Home", () => {
    expect(staticHomeFailures({ routes: { "/": { initialRevalidateSeconds: 300 }, "/about": { initialRevalidateSeconds: false } } }, SIGNED_IN_HOME_PATH)).toEqual([]);
  });
  it("fails a dynamic, never-revalidating or slow Home", () => {
    expect(staticHomeFailures({ routes: {} }, SIGNED_IN_HOME_PATH)).toHaveLength(1);
    expect(staticHomeFailures({ routes: { "/": { initialRevalidateSeconds: false } } }, SIGNED_IN_HOME_PATH)).toHaveLength(1);
    expect(staticHomeFailures({ routes: { "/": { initialRevalidateSeconds: 3600 } } }, SIGNED_IN_HOME_PATH)).toHaveLength(1);
  });
  it("fails a cacheable signed-in Home", () => {
    expect(staticHomeFailures({ routes: { "/": { initialRevalidateSeconds: 300 }, [SIGNED_IN_HOME_PATH]: { initialRevalidateSeconds: 300 } } }, SIGNED_IN_HOME_PATH)).toHaveLength(1);
  });
});
