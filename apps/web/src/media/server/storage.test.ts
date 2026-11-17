import { describe, expect, it } from "vitest";
import { StorageError } from "./storage-error.ts";
import { MEDIA_PUBLIC_HOST } from "./public-hosts.ts";
import { createMediaStore, createWritableMediaStore, optionalReadStore } from "./storage.ts";

const r2Env = {
  R2_ACCOUNT_ID: "a".repeat(32),
  R2_ACCESS_KEY_ID_RW: "id",
  R2_SECRET_ACCESS_KEY_RW: "secret",
  R2_ACCESS_KEY_ID_RO: "ro",
  R2_SECRET_ACCESS_KEY_RO: "secret-ro",
};

describe("media storage selection", () => {
  it("is R2 only: no credential means no store", () => {
    expect(() => createMediaStore({})).toThrow(StorageError);
    expect(optionalReadStore({})).toBeUndefined();
  });

  it("publishes every object on the public media host", () => {
    const published = `https://${MEDIA_PUBLIC_HOST}/m/abc.jpg`;
    expect(createMediaStore(r2Env).publicUrl("m/abc.jpg")).toBe(published);
    expect(createMediaStore(r2Env, "ro").publicUrl("m/abc.jpg")).toBe(published);
    expect(optionalReadStore(r2Env)?.publicUrl("m/abc.jpg")).toBe(published);
  });

  it("ignores a stale MEDIA_STORAGE setting", () => {
    expect(createWritableMediaStore({ ...r2Env, MEDIA_STORAGE: "blob" }).publicUrl("m/abc.jpg")).toBe(`https://${MEDIA_PUBLIC_HOST}/m/abc.jpg`);
  });
});
