import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { classPlaces, isThemeBinding, resolveTheme, SHEET_SLOTS, themeReaders } from "../../../scripts/lib/identity.ts";
import { courseStatus } from "../../catalog/domain/course-status.ts";
import { LIMITS } from "../../kernel/limits.ts";
import { universitiesTitle } from "../../site/domain/reader-copy.ts";
import {
  codeCopy, codeDocument, codeEditorial, codeLimits, codeTheme, exportNameToToken, matchConfigRequest, nextStoredRevision, parseCopy, parseDocument, parseEditorial, parseLimits, parseTheme, servedShell, themeOverrideBlock,
} from "./documents.ts";

describe("configuration documents", () => {
  it("D-051: the day-one documents are the keys already in code", () => {
    const css = readFileSync(new URL("../../ui/tokens/tokens.css", import.meta.url), "utf8");
    const theme = codeTheme();
    for (const line of css.split("\n")) {
      const match = /^\s*--(tower-[a-z0-9-]+):\s*(.*);$/.exec(line);
      if (!match?.[1] || match[2] === undefined) continue;
      expect(theme[match[1]], match[1]).toBe(match[2]);
    }
    expect(Object.keys(theme).length).toBeGreaterThan(100);
    expect(exportNameToToken("towerAccountPanelRight2")).toBe("tower-account-panel-right-2");
    expect(codeCopy().universitiesTitle).toBe(universitiesTitle);
    expect(codeCopy().universitiesTitle).toBe("Universities");
    expect(codeLimits()).toEqual(LIMITS);
    expect(codeEditorial().courseStatus).toEqual(courseStatus);
    expect(codeEditorial().statusTransitions[courseStatus.published]).toEqual([]);
    expect(codeDocument("theme")).toEqual(theme);
  });

  it("rejects a document that leaves the contract", () => {
    const theme = { ...codeTheme(), "tower-accent": "#ffffff" };
    expect(parseTheme(theme)["tower-accent"]).toBe("#ffffff");
    expect(themeOverrideBlock(codeTheme(), theme)).toBe("");
    const recolored = { ...theme, "tower-accent": "#000000" };
    expect(parseTheme(recolored)["tower-accent"]).toBe("#000000");
    expect(themeOverrideBlock(codeTheme(), recolored)).toBe(":root {\n  --tower-accent: #000000;\n}\n");
    expect(() => parseTheme({ ...theme, "tower-accent": "red; color: blue" })).toThrow(/outside the contract/);
    expect(() => parseTheme({ ...theme, extra: "nope" })).toThrow(/code keys/);

    const copy = { ...codeCopy(), universitiesTitle: "Schools" };
    expect(parseCopy(copy).universitiesTitle).toBe("Schools");
    expect(() => parseCopy({ ...codeCopy(), universitiesTitle: "" })).toThrow(/outside the contract/);

    expect(parseLimits({ ...codeLimits(), courseTitle: LIMITS.courseTitle }).courseTitle).toBe(LIMITS.courseTitle);
    expect(parseLimits({ ...codeLimits(), courseTitle: 10 }).courseTitle).toBe(10);
    expect(() => parseLimits({ ...codeLimits(), courseTitle: LIMITS.courseTitle + 1 })).toThrow(/outside the contract/);

    const editorial = codeEditorial();
    expect(parseEditorial(editorial).lessonKind).toEqual(editorial.lessonKind);
    expect(parseDocument("editorial", {
      ...editorial,
      statusTransitions: { ...editorial.statusTransitions, [courseStatus.draft]: [courseStatus.archived] },
    })).toMatchObject({ statusTransitions: { draft: ["archived"] } });
    expect(() => parseEditorial({ ...editorial, courseStatus: { ...editorial.courseStatus, published: "live" } })).toThrow(/code words/);
    expect(() => parseEditorial({
      ...editorial,
      statusTransitions: { ...editorial.statusTransitions, [courseStatus.published]: [courseStatus.draft] },
    })).toThrow(/no exit/);
  });

  it("D-052: a stored revision may change a foundation and may not replace a binding", () => {
    const theme = codeTheme();
    expect(theme["tower-account-name-color"]).toBe("var(--tower-muted)");
    expect(() => parseTheme({ ...theme, "tower-account-name-color": "#111111" })).toThrow(/binding/);
    expect(() => parseTheme({ ...theme, "tower-account-name-color": "var(--tower-ink)" })).toThrow(/binding/);
    const moved = parseTheme({ ...theme, "tower-muted": "#111111" });
    expect(moved["tower-account-name-color"]).toBe("var(--tower-muted)");
    expect(themeOverrideBlock(theme, moved)).toBe(":root {\n  --tower-muted: #111111;\n}\n");
    const before = resolveTheme(theme);
    const after = resolveTheme(moved);
    expect(after["tower-account-name-color"]).toBe("#111111");
    expect(after["tower-card-name-gap"]).toBe(before["tower-card-name-gap"]);
    expect(after["tower-ink"]).toBe(before["tower-ink"]);
    expect(servedShell(theme, codeCopy()).style).toBe("");
  });

  it("D-052: a stored revision may change a title place and the body stays", () => {
    const theme = codeTheme();
    expect(theme["tower-continue-title-size-mobile"]).toBe("var(--tower-card-name-size-mobile)");
    expect(() => parseTheme({ ...theme, "tower-continue-title-size-mobile": "21px" })).toThrow(/binding/);
    const moved = parseTheme({ ...theme, "tower-card-name-size-mobile": "21px" });
    expect(themeOverrideBlock(theme, moved)).toBe(":root {\n  --tower-card-name-size-mobile: 21px;\n}\n");
    const before = resolveTheme(theme);
    const after = resolveTheme(moved);
    expect(after["tower-continue-title-size-mobile"]).toBe("21px");
    expect(after["tower-type-ui-body-small-size"]).toBe(before["tower-type-ui-body-small-size"]);
    expect(after["tower-card-name-size-desktop"]).toBe("15px");
    expect(servedShell(theme, codeCopy()).style).toBe("");
  });

  it("D-052: a stored revision may change a home gap and a title stays", () => {
    const theme = codeTheme();
    expect(theme["tower-home-rail-gap"]).toBe("var(--tower-home-intro-gap-desktop)");
    expect(() => parseTheme({ ...theme, "tower-home-rail-gap": "28px" })).toThrow(/binding/);
    const moved = parseTheme({ ...theme, "tower-home-intro-gap-desktop": "28px" });
    expect(themeOverrideBlock(theme, moved)).toBe(":root {\n  --tower-home-intro-gap-desktop: 28px;\n}\n");
    const before = resolveTheme(theme);
    const after = resolveTheme(moved);
    expect(after["tower-home-rail-gap"]).toBe("28px");
    expect(after["tower-card-name-size-mobile"]).toBe(before["tower-card-name-size-mobile"]);
    expect(servedShell(theme, codeCopy()).style).toBe("");
  });

  it("D-052: a stored revision may change one sheet slot and another stays", () => {
    const theme = codeTheme();
    expect(theme["tower-el-object-fit-cover"]).toBe("cover");
    expect(theme["tower-el-frame-wide"]).toBe("16 / 9");
    const moved = parseTheme({ ...theme, "tower-el-object-fit-cover": "contain" });
    expect(themeOverrideBlock(theme, moved)).toBe(":root {\n  --tower-el-object-fit-cover: contain;\n}\n");
    const before = resolveTheme(theme);
    const after = resolveTheme(moved);
    expect(after["tower-el-object-fit-cover"]).toBe("contain");
    expect(after["tower-el-frame-wide"]).toBe(before["tower-el-frame-wide"]);
    expect(after["tower-el-frame-tall"]).toBe("9 / 16");
    expect(after["tower-el-opacity-quiet"]).toBe(before["tower-el-opacity-quiet"]);
    expect(servedShell(theme, codeCopy()).style).toBe("");
  });

  it("D-052: a stored revision may change the clear fill and the scrim span stays", () => {
    const theme = codeTheme();
    expect(theme["tower-el-clear"]).toBe("transparent");
    expect(theme["tower-el-scrim-span"]).toBe("72%");
    expect(theme["tower-el-opacity-dim"]).toBe("0.55");
    expect(theme["tower-el-color-scheme"]).toBe("dark");
    expect(theme["tower-el-inset-ring"]).toBe("inset 0 0 0");
    expect(theme["tower-cta-disabled-opacity"]).toBe("0.4");
    const moved = parseTheme({ ...theme, "tower-el-clear": "proof-place" });
    expect(themeOverrideBlock(theme, moved)).toBe(":root {\n  --tower-el-clear: proof-place;\n}\n");
    const after = resolveTheme(moved);
    expect(after["tower-el-clear"]).toBe("proof-place");
    expect(after["tower-el-scrim-span"]).toBe("72%");
    expect(after["tower-el-opacity-dim"]).toBe("0.55");
    expect(after["tower-cta-disabled-opacity"]).toBe(theme["tower-cta-disabled-opacity"]);
    expect(servedShell(theme, codeCopy()).style).toBe("");
  });

  it("D-052: a stored revision of one place in every census class stays that one key", () => {
    const theme = codeTheme();
    expect(servedShell(theme, codeCopy()).style).toBe("");
    const before = resolveTheme(theme);
    const places = [...classPlaces(theme).entries()];
    for (const name of Object.keys(SHEET_SLOTS)) places.push([name, name]);
    const seen = new Set<string>();
    for (const [element, place] of places) {
      if (seen.has(place)) continue;
      seen.add(place);
      const readers = themeReaders(theme, place);
      const binding = [...readers].find((name) => name !== place && isThemeBinding(theme[name] ?? ""));
      if (binding) expect(() => parseTheme({ ...theme, [binding]: "proof-place" }), `${element} ${binding}`).toThrow(/binding/);
      const moved = parseTheme({ ...theme, [place]: "proof-place" });
      expect(themeOverrideBlock(theme, moved), element).toBe(`:root {\n  --${place}: proof-place;\n}\n`);
      const after = resolveTheme(moved);
      for (const name of readers) expect(after[name], `${element} ${name}`).toBe("proof-place");
      for (const name of Object.keys(theme)) {
        if (!readers.has(name)) expect(after[name], `${element} ${name}`).toBe(before[name]);
      }
    }
    expect(seen.size).toBeGreaterThan(Object.keys(SHEET_SLOTS).length);
  });

  it("keeps the shell unchanged until a served value differs", () => {
    const theme = codeTheme();
    const copy = codeCopy();
    expect(servedShell(theme, copy)).toEqual({ style: "", copyChanged: false });
    expect(servedShell({ ...theme, "tower-accent": "#000000" }, copy).style).toBe(":root {\n  --tower-accent: #000000;\n}\n");
    expect(servedShell(theme, { ...copy, universitiesTitle: "Schools" }).copyChanged).toBe(true);
  });

  it("names the admin path for one kind", () => {
    expect(matchConfigRequest("GET", "/api/admin/config/limits")).toEqual({ kind: "limits", action: "read" });
    expect(matchConfigRequest("PUT", "/api/admin/config/copy")).toEqual({ kind: "copy", action: "write" });
    expect(matchConfigRequest("GET", "/api/admin/config/theme/history")).toEqual({ kind: "theme", action: "history" });
    expect(matchConfigRequest("POST", "/api/admin/config/editorial/rollback")).toEqual({ kind: "editorial", action: "rollback" });
    expect(matchConfigRequest("POST", "/api/admin/config/limits")).toEqual({ kind: "limits", action: null });
    expect(matchConfigRequest("GET", "/api/admin/config/nope")).toBeNull();
    expect(matchConfigRequest("GET", "/api/admin/catalog/courses")).toBeNull();
  });

  it("stores the next revision and refuses a stale one", () => {
    expect(nextStoredRevision(0, 0)).toBe(1);
    expect(nextStoredRevision(2, 2)).toBe(3);
    expect(() => nextStoredRevision(1, 0)).toThrow(/current revision is 1/);
    expect(() => nextStoredRevision(-1, 0)).toThrow(/whole number/);
  });
});
