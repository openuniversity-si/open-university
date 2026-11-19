import { readFile } from "node:fs/promises";
import { describe, expect, it } from "vitest";
import { applyElementAliases, applyFoundationAliases, classPlaces, elementOf, foundationAliases, isThemeBinding, resolveTheme, SHEET_SLOTS, TEXT_ELEMENTS, themeReaders, type ThemeVariable } from "./identity.ts";

// Verifies: D-052
const snapshot = JSON.parse(await readFile(new URL("../../design/figma-tokens.snapshot.json", import.meta.url), "utf8")) as {
  readonly variables: Readonly<Record<string, ThemeVariable>>;
};

describe("visual identity", () => {
  it("D-052: a foundation literal is the one place and the default identity resolves to the snapshot", () => {
    const aliases = foundationAliases(snapshot.variables);
    expect(aliases.get("tower-account-name-color")).toBe("tower-muted");
    expect(aliases.get("tower-card-name-gap")).toBe("tower-gap-tight");
    expect(aliases.get("tower-auth-avatar-radius")).toBe("tower-radius-full");
    expect(aliases.has("tower-accent")).toBe(false);
    expect(aliases.has("tower-ink")).toBe(false);
    expect(aliases.has("tower-radius")).toBe(false);
    expect(aliases.has("tower-radius-md")).toBe(false);
    expect(aliases.has("tower-layout-gutter-tablet")).toBe(false);
    expect(aliases.has("tower-breakpoint-desktop")).toBe(false);
    expect(aliases.size).toBeGreaterThan(30);

    const applied = applyFoundationAliases(snapshot.variables);
    expect(applied["tower-account-name-color"]?.value).toBe("var(--tower-muted)");
    expect(applied["tower-muted"]?.value).toBe(snapshot.variables["tower-muted"]?.value);
    expect(applied["tower-layout-gutter-tablet"]?.value).toBe("32px");

    const before = resolveTheme(Object.fromEntries(Object.entries(snapshot.variables).map(([name, token]) => [name, token.value])));
    const flat = Object.fromEntries(Object.entries(applied).map(([name, token]) => [name, token.value]));
    const resolved = resolveTheme(flat);
    for (const name of Object.keys(snapshot.variables)) {
      expect(resolved[name], name).toBe(before[name]);
    }

    const moved = { ...flat, "tower-muted": "#111111" };
    const next = resolveTheme(moved);
    expect(next["tower-account-name-color"]).toBe("#111111");
    expect(next["tower-card-name-gap"]).toBe(snapshot.variables["tower-card-name-gap"]?.value);
    expect(next["tower-ink"]).toBe("#ffffff");
  });

  it("D-052: two titles that share a size share one place and a body does not follow", () => {
    const themed = applyElementAliases(applyFoundationAliases(snapshot.variables), new Set(TEXT_ELEMENTS));
    expect(themed["tower-card-name-size-mobile"]?.value).toBe("13px");
    expect(themed["tower-continue-title-size-mobile"]?.value).toBe("var(--tower-card-name-size-mobile)");
    expect(themed["tower-continue-label-size-mobile"]?.value).not.toBe("var(--tower-card-name-size-mobile)");
    expect(themed["tower-type-ui-body-billboard-mobile-size"]?.value).toBe("15px");
    expect(themed["tower-type-ui-body-small-size"]?.value).toBe("var(--tower-type-ui-body-billboard-mobile-size)");
    expect(themed["tower-card-name-size-desktop"]?.value).toBe("15px");

    const before = resolveTheme(Object.fromEntries(Object.entries(snapshot.variables).map(([name, token]) => [name, token.value])));
    const flat = Object.fromEntries(Object.entries(themed).map(([name, token]) => [name, token.value]));
    const resolved = resolveTheme(flat);
    for (const name of Object.keys(snapshot.variables)) expect(resolved[name], name).toBe(before[name]);

    const moved = { ...flat, "tower-card-name-size-mobile": "21px" };
    const next = resolveTheme(moved);
    expect(next["tower-continue-title-size-mobile"]).toBe("21px");
    expect(next["tower-type-ui-body-small-size"]).toBe("15px");
    expect(next["tower-card-name-size-desktop"]).toBe("15px");
    expect(next["tower-continue-label-size-mobile"]).toBe(before["tower-continue-label-size-mobile"]);
  });

  it("D-052: every census class has one place and a home gap does not follow a title", () => {
    const classes = new Set<string>();
    for (const name of Object.keys(snapshot.variables)) {
      const element = elementOf(name);
      expect(element, name).toBeTruthy();
      if (element) classes.add(element);
    }
    for (const element of ["title", "body", "label", "meta", "cover", "button", "card", "hero", "home", "reader"]) {
      expect(classes.has(element), element).toBe(true);
    }

    const themed = applyElementAliases(applyFoundationAliases(snapshot.variables), classes);
    expect(themed["tower-continue-title-size-mobile"]?.value).toBe("var(--tower-card-name-size-mobile)");
    expect(themed["tower-home-rail-gap"]?.value).toBe("var(--tower-home-intro-gap-desktop)");
    expect(themed["tower-home-intro-gap-desktop"]?.value).toBe("20px");
    expect(themed["tower-topnav-mark-width-desktop"]?.value).toBe("44.8px");

    const literals = new Map<string, number>();
    for (const [name, token] of Object.entries(themed)) {
      const element = elementOf(name);
      if (!element || token.value.startsWith("var(--")) continue;
      literals.set(element, (literals.get(element) ?? 0) + 1);
    }
    for (const element of classes) {
      if ((literals.get(element) ?? 0) > 0) continue;
      const keys = Object.entries(themed).filter(([name]) => elementOf(name) === element);
      expect(keys.length, element).toBeGreaterThan(0);
      for (const [, token] of keys) expect(token.value.startsWith("var(--"), element).toBe(true);
    }

    const before = resolveTheme(Object.fromEntries(Object.entries(snapshot.variables).map(([name, token]) => [name, token.value])));
    const flat = Object.fromEntries(Object.entries(themed).map(([name, token]) => [name, token.value]));
    const resolved = resolveTheme(flat);
    for (const name of Object.keys(snapshot.variables)) expect(resolved[name], name).toBe(before[name]);

    const moved = { ...flat, "tower-home-intro-gap-desktop": "28px" };
    const next = resolveTheme(moved);
    expect(next["tower-home-rail-gap"]).toBe("28px");
    expect(next["tower-card-name-size-mobile"]).toBe(before["tower-card-name-size-mobile"]);
    expect(next["tower-type-ui-body-small-size"]).toBe("15px");
  });

  it("D-052: a sheet literal has one slot and does not collide with the snapshot", () => {
    expect(SHEET_SLOTS["tower-el-frame-wide"]).toBe("16 / 9");
    expect(SHEET_SLOTS["tower-el-frame-tall"]).toBe("9 / 16");
    expect(SHEET_SLOTS["tower-el-object-fit-cover"]).toBe("cover");
    expect(SHEET_SLOTS["tower-el-ease-out"]).toBe("ease-out");
    expect(SHEET_SLOTS["tower-el-opacity-quiet"]).toBe("0.8");
    expect(SHEET_SLOTS["tower-el-opacity-dim"]).toBe("0.55");
    expect(SHEET_SLOTS["tower-el-clear"]).toBe("transparent");
    expect(SHEET_SLOTS["tower-el-scrim-span"]).toBe("72%");
    expect(SHEET_SLOTS["tower-el-color-scheme"]).toBe("dark");
    expect(SHEET_SLOTS["tower-el-inset-ring"]).toBe("inset 0 0 0");
    for (const name of Object.keys(SHEET_SLOTS)) expect(snapshot.variables[name], name).toBeUndefined();
  });

  it("D-052: every census class has a literal place", () => {
    const classes = new Set<string>();
    for (const name of Object.keys(snapshot.variables)) {
      const element = elementOf(name);
      expect(element, name).toBeTruthy();
      if (element) classes.add(element);
    }
    const themed = applyElementAliases(applyFoundationAliases(snapshot.variables), classes);
    const flat = Object.fromEntries(Object.entries(themed).map(([name, token]) => [name, token.value]));
    const places = classPlaces(flat);
    expect([...places.keys()].sort((left, right) => left.localeCompare(right, "en"))).toEqual(
      [...classes].sort((left, right) => left.localeCompare(right, "en")),
    );
    for (const element of classes) {
      const place = places.get(element);
      const value = place === undefined ? undefined : flat[place];
      expect(place, element).toBeTruthy();
      expect(value, element).toBeTruthy();
      expect(isThemeBinding(value ?? ""), element).toBe(false);
      const first = Object.keys(flat)
        .filter((name) => elementOf(name) === element)
        .sort((left, right) => left.localeCompare(right, "en"))[0];
      expect(first, element).toBeTruthy();
      expect(themeReaders(flat, place ?? "").has(first ?? ""), element).toBe(true);
    }
  });

  it("D-052: a revision of one place in every census class moves its readers only", () => {
    const classes = new Set<string>();
    for (const name of Object.keys(snapshot.variables)) {
      const element = elementOf(name);
      if (element) classes.add(element);
    }
    const themed = applyElementAliases(applyFoundationAliases(snapshot.variables), classes);
    const flat = Object.fromEntries(Object.entries(themed).map(([name, token]) => [name, token.value]));
    const before = resolveTheme(flat);
    const seen = new Set<string>();
    for (const [element, place] of classPlaces(flat)) {
      if (seen.has(place)) continue;
      seen.add(place);
      const readers = themeReaders(flat, place);
      const moved = { ...flat, [place]: "proof-place" };
      const after = resolveTheme(moved);
      for (const name of readers) expect(after[name], `${element} ${name}`).toBe("proof-place");
      for (const name of Object.keys(flat)) {
        if (!readers.has(name)) expect(after[name], `${element} ${name}`).toBe(before[name]);
      }
    }
    expect(seen.size).toBeGreaterThan(0);
    expect(resolveTheme(flat)).toEqual(before);
  });
});
