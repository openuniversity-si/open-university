import { afterEach, expect, it, vi } from "vitest";
import { errorSummary } from "../../kernel/errors.ts";
import { logStructured } from "./logger.ts";
afterEach(() => { vi.restoreAllMocks(); });
it("preserves the documented fallback line byte for byte", () => {
  const log = vi.spyOn(console, "error").mockImplementation(() => undefined);
  logStructured("error", "CATALOG_FALLBACK");
  expect(log).toHaveBeenCalledExactlyOnceWith('{"event":"CATALOG_FALLBACK"}');
});
it("writes one JSON line, event first, requestId second and only primitives", () => {
  const log = vi.spyOn(console, "log").mockImplementation(() => undefined);
  logStructured("info", "CATALOG_ADMIN", { status: 200, noop: true, entity: null }, { requestId: "request-1" });
  expect(log).toHaveBeenCalledExactlyOnceWith('{"event":"CATALOG_ADMIN","requestId":"request-1","status":200,"noop":true,"entity":null}');
});
it("does not emit an unknown error's message or stack", () => {
  const log = vi.spyOn(console, "warn").mockImplementation(() => undefined);
  const error = Object.assign(new Error("private connection password"), { code: "ECONNRESET" });
  logStructured("warn", "CATALOG_PREVIEW_FAILED", { error: errorSummary(error) });
  expect(log).toHaveBeenCalledExactlyOnceWith('{"event":"CATALOG_PREVIEW_FAILED","error":"Error ECONNRESET"}');
});
