import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { readerPhrases } from "../../src/site/domain/reader-copy.ts";
import { ABSOLUTE_GATE, absoluteOffenders, absoluteSources, DOM_KEYS, valueLiterals } from "./absolute-literals.ts";

const repo = fileURLToPath(new URL("../../../..", import.meta.url));
const snapshot = JSON.parse(readFileSync(new URL("../../design/figma-tokens.snapshot.json", import.meta.url), "utf8")) as {
  readonly variables: Readonly<Record<string, { readonly value: string }>>;
};
const options = {
  catalogValues: new Set(Object.values(snapshot.variables).map((token) => token.value)),
  phrases: new Set(readerPhrases),
};

describe("absolute reading", () => {
  it("counts a string, a number inside it, and a boolean, and skips a template", () => {
    const literals = valueLiterals('const name = "room 2"; const open = true; const label = `room ${name}`; // "hidden"');
    expect(literals.filter((literal) => literal.kind === "string").map((literal) => literal.text)).toEqual(["room 2"]);
    expect(literals.filter((literal) => literal.kind === "number").map((literal) => literal.text)).toEqual(["2"]);
    expect(literals.filter((literal) => literal.kind === "boolean").map((literal) => literal.text)).toEqual(["true"]);
  });

  it("keeps a slash inside a string and drops a real comment", () => {
    const literals = valueLiterals('const url = "https://example.test"; // true 9');
    expect(literals.map((literal) => `${literal.kind}:${literal.text}`)).toEqual(["string:https://example.test"]);
  });
});

describe("absolute door", () => {
  const file = "apps/web/src/example.ts";
  const owner = "apps/web/src/catalog/server/example.ts";

  it("names the exceptions and refuses a value outside them", () => {
    expect(DOM_KEYS).toContain("Home");
    expect(absoluteOffenders([{ path: file, text: 'const name = "hello"' }], options)).toEqual([`${file}: string hello`]);
    expect(absoluteOffenders([{ path: file, text: 'import { read } from "./read.ts"' }], options)).toEqual([]);
    expect(absoluteOffenders([{ path: file, text: '"use client";\n"use server";' }], options)).toEqual([]);
    expect(absoluteOffenders([{ path: file, text: 'const color = "var(--tower-ink)"' }], options)).toEqual([]);
    expect(absoluteOffenders([{ path: "apps/web/src/example.css", text: "@media (min-width: 768px) { }" }], options)).toEqual([]);
    expect(absoluteOffenders([{ path: "apps/web/src/example.css", text: "@media (min-width: 1234px) { }" }], options)).toEqual(["apps/web/src/example.css: number 1234"]);
    expect(absoluteOffenders([{ path: file, text: 'if (key === "Home") {}' }], options)).toEqual([]);
    expect(absoluteOffenders([{ path: file, text: 'const title = "Home"' }], options)).toEqual([`${file}: string Home`]);
    expect(absoluteOffenders([{ path: "apps/web/src/example.css", text: '[data-page="Home"] {}' }], options)).toEqual([]);
    expect(absoluteOffenders([{ path: file, text: 'if (lock.key === "catalog:release") {}' }], options)).toEqual([`${file}: string catalog:release`]);
    expect(absoluteOffenders([{ path: owner, text: "db.query(`SELECT id FROM courses WHERE n = 4`)" }], options)).toEqual([]);
    expect(absoluteOffenders([{ path: file, text: "db.query(`SELECT id FROM courses WHERE n = 4`)" }], options)).toEqual([`${file}: number 4`]);
    expect(absoluteOffenders([{ path: file, text: "const one = `LIMIT 1`" }], options)).toEqual([]);
    expect(absoluteOffenders([{ path: "apps/web/src/kernel/limits.ts", text: 'const cap = "hello"' }], options)).toEqual([]);
  });

  it("keeps the door off while a production value remains outside the catalogs and the exceptions", () => {
    const offenders = absoluteOffenders(absoluteSources(repo), options);
    expect(ABSOLUTE_GATE).toBe(false);
    expect(offenders.length).toBeGreaterThan(0);
  });
});
