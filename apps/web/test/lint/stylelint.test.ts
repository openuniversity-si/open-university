import path from "node:path";
import stylelint from "stylelint";
import { describe, expect, it } from "vitest";

const root = path.resolve(import.meta.dirname, "../..");

/** Lints `code` as if it lived at `file`, resolving the project's real stylelint config. */
async function lint(code: string, file: string): Promise<string[]> {
  const result = await stylelint.lint({ code, codeFilename: path.join(root, file) });
  return result.results.flatMap((r) => r.warnings.map((w) => w.rule));
}

describe("stylelint token policy (ADR-02, §8.1)", () => {
  const outside = "src/app/example.module.css";
  const tokens = "src/ui/tokens/tokens.css";

  it.each([
    ["hex colour", ".a { color: #fff; }", "color-no-hex"],
    ["rgb()", ".a { color: rgb(0 0 0); }", "function-disallowed-list"],
    ["rgba()", ".a { color: rgba(0, 0, 0, 0.5); }", "function-disallowed-list"],
    ["named colour", ".a { color: white; }", "color-named"],
    ["px length", ".a { margin: 4px; }", "unit-disallowed-list"],
    ["rem length", ".a { padding: 1rem; }", "unit-disallowed-list"],
    ["em length", ".a { letter-spacing: 0.03em; }", "unit-disallowed-list"],
    ["raw font weight", ".a { font-weight: 600; }", "declaration-property-value-allowed-list"],
  ])("rejects a %s outside src/ui/tokens/", async (_label, code, rule) => {
    expect(await lint(code, outside)).toContain(rule);
  });

  it("accepts token references outside src/ui/tokens/", async () => {
    expect(await lint(".a { color: var(--tower-ink); }", outside)).toEqual([]);
  });

  it("allows literals inside src/ui/tokens/", async () => {
    expect(await lint(":root {\n  --tower-x: #fff;\n  --tower-y: 4px;\n  --tower-z: rgb(0 0 0);\n}\n", tokens)).toEqual([]);
  });
});
