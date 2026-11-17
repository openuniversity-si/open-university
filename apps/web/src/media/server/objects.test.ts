import { createHash } from "node:crypto";
import sharp from "sharp";
import { expect, it } from "vitest";
import { inspectObject, objectKey } from "./objects.ts";
import { objectUrl } from "../domain/objects.ts";
import { mediaPublicHost, productionMediaPolicy } from "../domain/types.ts";

it("uses only the full SHA-256 and verified extension as object identity", () => {
  const sha256 = "a".repeat(64);
  expect(objectKey(sha256, "webp")).toBe(`m/${sha256}.webp`);
  expect(objectUrl({ sha256, ext: "webp" }, productionMediaPolicy)).toBe(`https://${mediaPublicHost({})}/m/${sha256}.webp`);
  expect(() => objectKey("a".repeat(40), "webp")).toThrow();
  expect(() => objectKey(sha256, "../jpg")).toThrow();
});
it("verifies actual bytes, dimensions and format, rejecting an equal-size corruption and a wrong extension", async () => {
  const bytes = await sharp({ create: { width: 16, height: 9, channels: 3, background: "silver" } }).webp().toBuffer();
  const sha256 = createHash("sha256").update(bytes).digest("hex");
  expect(await inspectObject(bytes, sha256, "webp")).toEqual({ sha256, ext: "webp", contentType: "image/webp", bytes: bytes.length, width: 16, height: 9 });
  const corrupt = Buffer.from(bytes); corrupt[corrupt.length - 1] = (corrupt.at(-1) ?? 0) ^ 1;
  await expect(inspectObject(corrupt, sha256, "webp")).rejects.toThrow("checksum mismatch");
  await expect(inspectObject(bytes, sha256, "jpg")).rejects.toThrow("format mismatch");
});
