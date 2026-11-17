/** D-052. The theme document is the visual identity. A foundation owns one literal. */

export type FoundationFamily = "color" | "type" | "radius" | "shadow" | "space" | "breakpoint" | "focus";

export interface ThemeVariable {
  readonly value: string;
  readonly source: string;
  readonly codeSyntax: string;
  readonly description?: string;
}

/** Foundations. Two foundations may share a literal on purpose (accent and ink are both white). */
export const FOUNDATIONS: Readonly<Record<string, FoundationFamily>> = {
  "tower-accent": "color",
  "tower-ink": "color",
  "tower-muted": "color",
  "tower-scrim": "color",
  "tower-silver": "color",
  "tower-hairline": "color",
  "tower-surface": "color",
  "tower-surface-raised": "color",
  "tower-selection": "color",
  "tower-selection-ink": "color",
  "tower-font-ui": "type",
  "tower-font-display": "type",
  "tower-radius": "radius",
  "tower-radius-full": "radius",
  "tower-radius-md": "radius",
  "tower-radius-sm": "radius",
  "tower-shadow": "shadow",
  "tower-shadow-lift": "shadow",
  "tower-gap": "space",
  "tower-gap-tight": "space",
  "tower-gap-loose": "space",
  "tower-space-fluid": "space",
  "tower-breakpoint-desktop": "breakpoint",
  "tower-breakpoint-narrow": "breakpoint",
  "tower-breakpoint-present": "breakpoint",
  "tower-breakpoint-tablet": "breakpoint",
  "tower-breakpoint-wide": "breakpoint",
  "tower-focus-ring": "focus",
  "tower-focus-ring-width": "focus",
  "tower-focus-ring-offset": "focus",
  "tower-focus-ring-radius": "focus",
};

/**
 * Readers that need the concrete literal. A media attribute, image `sizes`, the poster margin,
 * and `theme-color` cannot follow `var()`. Those keys stay the place.
 */
export const CONCRETE_READERS = new Set([
  "tower-breakpoint-desktop",
  "tower-course-thumb-width",
  "tower-lesson-stage-inset",
  "tower-viewport-width",
  "tower-poster-near-margin",
  "tower-surface",
  "tower-layout-gutter-mobile",
  "tower-layout-gutter-tablet",
  "tower-layout-gutter-desktop",
  "tower-course-column-gap",
  "tower-course-about-width",
]);

const BINDING = /^var\(--tower-[a-z0-9-]+\)$/;

/** A theme value that is only a reference to another theme key. */
export function isThemeBinding(value: string): boolean {
  return BINDING.test(value);
}

function normalize(value: string): string {
  return value.replace(/\s+/g, " ").trim();
}

/** Family of a key that may bind to a foundation. Foundations report their own family. */
export function keyFamily(name: string): FoundationFamily | null {
  if (Object.hasOwn(FOUNDATIONS, name)) return FOUNDATIONS[name] ?? null;
  if (/(^|-)(gap|padding|margin|gutter)(-|$)/.test(name)) return "space";
  if (/radius/.test(name)) return "radius";
  if (/shadow|glow/.test(name)) return "shadow";
  if (/breakpoint/.test(name)) return "breakpoint";
  if (/color|background/.test(name)) return "color";
  return null;
}

/** Component keys whose whole value is the one foundation of that family. The key is the component; the value is not. */
export function foundationAliases(variables: Readonly<Record<string, ThemeVariable>>): ReadonlyMap<string, string> {
  const count = new Map<string, number>();
  for (const [name, family] of Object.entries(FOUNDATIONS)) {
    const token = variables[name];
    if (!token) continue;
    const key = `${family}\0${normalize(token.value)}`;
    count.set(key, (count.get(key) ?? 0) + 1);
  }
  const unique = new Map<string, string>();
  for (const [name, family] of Object.entries(FOUNDATIONS)) {
    const token = variables[name];
    if (!token) continue;
    const key = `${family}\0${normalize(token.value)}`;
    if (count.get(key) === 1) unique.set(key, name);
  }
  const aliases = new Map<string, string>();
  for (const [name, token] of Object.entries(variables)) {
    if (Object.hasOwn(FOUNDATIONS, name) || CONCRETE_READERS.has(name) || isThemeBinding(token.value)) continue;
    const family = keyFamily(name);
    if (!family) continue;
    const canonical = unique.get(`${family}\0${normalize(token.value)}`);
    if (!canonical || canonical === name) continue;
    aliases.set(name, canonical);
  }
  return aliases;
}

/** Same keys. A duplicated foundation literal becomes `var(--foundation)`. */
export function applyFoundationAliases<T extends ThemeVariable>(variables: Readonly<Record<string, T>>): Record<string, T> {
  return applyAliases(variables, foundationAliases(variables));
}

/** Text elements. A size of 13px on a title is not the size of 13px on a label. */
export const TEXT_ELEMENTS = ["title", "body", "label", "meta"] as const;
export type TextElement = (typeof TEXT_ELEMENTS)[number];

const TEXT_PREFIXES: readonly [TextElement, readonly string[]][] = [
  ["body", ["tower-type-ui-body-", "tower-text-body"]],
  ["label", [
    "tower-type-ui-label-", "tower-type-ui-overline-", "tower-type-ui-quiet-", "tower-label-transform",
    "tower-continue-label-", "tower-type-display-kicker-", "tower-text-kicker",
  ]],
  ["meta", ["tower-type-ui-meta-", "tower-type-ui-playlist-meta-", "tower-continue-meta-", "tower-continue-left-"]],
  ["title", [
    "tower-type-display-title-", "tower-type-display-hero-", "tower-type-display-lesson-title-", "tower-type-display-cover-",
    "tower-card-name-", "tower-type-ui-title-", "tower-type-ui-section-", "tower-type-ui-row-title-", "tower-continue-title-",
  ]],
];

const METRICS = [
  "line-height", "font-size", "font-weight", "letter-spacing", "underline-offset", "text-decoration",
  "tracking", "transform", "size", "weight", "line", "color", "radius", "gap", "padding", "margin", "width", "height", "opacity",
] as const;

/** Title, body, label, or meta. Every other key stays out of this pass. */
export function textElement(name: string): TextElement | null {
  for (const [element, prefixes] of TEXT_PREFIXES) {
    if (prefixes.some((prefix) => name.startsWith(prefix))) return element;
  }
  return null;
}

/** The metric inside a key, so a line-height does not bind to a font size of the same number. */
export function metricOf(name: string): string {
  for (const metric of METRICS) {
    const needle = `-${metric}`;
    let from = 0;
    while (from < name.length) {
      const at = name.indexOf(needle, from);
      if (at < 0) break;
      const after = at + needle.length;
      if (after === name.length || name[after] === "-") return metric;
      from = at + 1;
    }
  }
  return "value";
}

const ELEMENT_PREFIXES: readonly [string, readonly string[]][] = [
  ["glass", ["tower-header-glass", "tower-cover-glass"]],
  ["mark", ["tower-footer-mark", "tower-topnav-mark", "tower-type-display-footer-mark", "tower-type-display-brand-"]],
  ["author", ["tower-type-display-author-", "tower-author-"]],
  ["shortcut", ["tower-skip-link"]],
  ["focus", ["tower-focus-"]],
  ["tap", ["tower-tap-"]],
  ["page-space", ["tower-layout-gutter"]],
  ["foundation-breakpoint", ["tower-breakpoint-"]],
  ["foundation-screen", ["tower-viewport-"]],
  ["foundation-space", ["tower-gap", "tower-space-fluid"]],
  ["foundation-radius", ["tower-radius"]],
  ["foundation-elevation", ["tower-shadow"]],
  ["foundation-type", ["tower-font-", "tower-transform-none", "tower-text-decoration-none", "tower-text-underline"]],
  ["foundation-color", ["tower-accent", "tower-ink", "tower-muted", "tower-scrim", "tower-surface", "tower-silver", "tower-hairline", "tower-metal", "tower-select"]],
  ["foundation-motion", ["tower-transition"]],
  ["selection", ["tower-selection"]],
  ["halo", ["tower-silver-glow", "tower-silver-check", "tower-silver-cta", "tower-silver-star"]],
  ["skeleton", ["tower-skeleton-"]],
  ["empty", ["tower-not-found", "tower-empty"]],
  ["legal", ["tower-legal-"]],
  ["credits", ["tower-credits"]],
  ["progress", ["tower-progress", "tower-completion"]],
  ["playlist", ["tower-playlist"]],
  ["edition", ["tower-edition-"]],
  ["account", ["tower-account-", "tower-auth-", "tower-signin-", "tower-type-ui-account-"]],
  ["reader", ["tower-player-", "tower-scrubber-", "tower-type-ui-player-", "tower-mobile-lecture-list", "tower-hit-area"]],
  ["university", ["tower-u-", "tower-university"]],
  ["course", ["tower-course-", "tower-about-", "tower-details-", "tower-start-", "tower-secondary-"]],
  ["hero", ["tower-billboard-", "tower-hero-"]],
  ["portal", ["tower-portal-"]],
  ["home", ["tower-home-"]],
  ["row", ["tower-rail-", "tower-type-display-rail-", "tower-continue-"]],
  ["nav", ["tower-type-ui-nav", "tower-topnav", "tower-header-", "tower-nav-", "tower-bottom-fade"]],
  ["cover", ["tower-cover-", "tower-poster-", "tower-card-card-data-selected", "tower-card-selected", "tower-card-cover"]],
  ["glass", ["tower-glass-", "tower-cover-glass", "tower-veil-", "tower-support-blur"]],
  ["card", ["tower-card-", "tower-type-ui-card-", "tower-continue-card"]],
  ["button", ["tower-cta-", "tower-graphite-cta", "tower-type-ui-button", "tower-type-ui-link"]],
  ["footer", ["tower-footer-"]],
  ["lesson", ["tower-lesson"]],
  ["legacy-type", ["tower-text-"]],
];

/** Every theme key belongs to one census class. Text wins over a broader prefix. */
export function elementOf(name: string): string | null {
  return textElement(name) ?? ELEMENT_PREFIXES.find(([, prefixes]) => prefixes.some((prefix) => name.startsWith(prefix)))?.[0] ?? null;
}

/** Within one element, keys that repeat one metric and one value share the first key. */
export function elementAliases(variables: Readonly<Record<string, ThemeVariable>>, elements: ReadonlySet<string>): ReadonlyMap<string, string> {
  const groups = new Map<string, string[]>();
  for (const [name, token] of Object.entries(variables)) {
    const element = elementOf(name);
    if (!element || !elements.has(element) || Object.hasOwn(FOUNDATIONS, name) || CONCRETE_READERS.has(name) || isThemeBinding(token.value)) continue;
    const key = `${element}\0${metricOf(name)}\0${normalize(token.value)}`;
    const names = groups.get(key);
    if (names) names.push(name);
    else groups.set(key, [name]);
  }
  const aliases = new Map<string, string>();
  for (const names of groups.values()) {
    if (names.length < 2) continue;
    const canonical = [...names].sort((left, right) => left.localeCompare(right, "en"))[0];
    if (!canonical) continue;
    for (const name of names) if (name !== canonical) aliases.set(name, canonical);
  }
  return aliases;
}

/** Same keys. A repeated text metric becomes `var(--canonical)` inside its element. */
export function applyElementAliases<T extends ThemeVariable>(variables: Readonly<Record<string, T>>, elements: ReadonlySet<string>): Record<string, T> {
  return applyAliases(variables, elementAliases(variables, elements));
}

/**
 * Sheet literals that are the same decision wherever they paint.
 * The value is today's pixel. A component reads the key and does not keep a private copy.
 */
export const SHEET_SLOTS = {
  "tower-el-frame-wide": "16 / 9",
  "tower-el-frame-tall": "9 / 16",
  "tower-el-radius-round": "50%",
  "tower-el-object-fit-cover": "cover",
  "tower-el-opacity-off": "0",
  "tower-el-opacity-full": "1",
  "tower-el-opacity-quiet": "0.8",
  "tower-el-opacity-dim": "0.55",
  "tower-el-clear": "transparent",
  "tower-el-scrim-span": "72%",
  "tower-el-color-scheme": "dark",
  "tower-el-inset-ring": "inset 0 0 0",
  "tower-el-ease-out": "ease-out",
  "tower-el-spinner-dash": "25 75",
  "tower-el-spinner-duration": "1s",
  "tower-el-spinner-timing": "linear",
  "tower-el-icon-stroke": "2",
  "tower-el-mark-complete-stroke": "1.833",
  "tower-el-mark-open-stroke": "1.65",
} as const;

function applyAliases<T extends ThemeVariable>(variables: Readonly<Record<string, T>>, aliases: ReadonlyMap<string, string>): Record<string, T> {
  const next: Record<string, T> = {};
  for (const [name, token] of Object.entries(variables)) {
    const canonical = aliases.get(name);
    next[name] = canonical ? { ...token, value: `var(--${canonical})` } : token;
  }
  return next;
}

function bindingTarget(value: string): string | null {
  const match = /^var\(--(tower-[a-z0-9-]+)\)$/.exec(value);
  return match?.[1] ?? null;
}

/** Follow bindings from `name` until a literal. A cycle returns null. */
function literalPlace(values: Readonly<Record<string, string>>, name: string): string | null {
  const seen = new Set<string>();
  let place = name;
  while (!seen.has(place)) {
    seen.add(place);
    const value = values[place];
    if (value === undefined) return null;
    const next = bindingTarget(value);
    if (!next) return place;
    place = next;
  }
  return null;
}

/** One literal place for each census class. A class that only binds follows that binding. */
export function classPlaces(values: Readonly<Record<string, string>>): ReadonlyMap<string, string> {
  const places = new Map<string, string>();
  for (const name of Object.keys(values).sort((left, right) => left.localeCompare(right, "en"))) {
    const element = elementOf(name);
    if (!element || places.has(element)) continue;
    const place = literalPlace(values, name);
    if (place && !isThemeBinding(values[place] ?? "")) places.set(element, place);
  }
  return places;
}

/** Keys that read `place`, including `place`. A chain of bindings counts. */
export function themeReaders(values: Readonly<Record<string, string>>, place: string): ReadonlySet<string> {
  const readers = new Set<string>([place]);
  let grew = true;
  while (grew) {
    grew = false;
    for (const [name, value] of Object.entries(values)) {
      if (readers.has(name)) continue;
      const target = bindingTarget(value);
      if (target && readers.has(target)) {
        readers.add(name);
        grew = true;
      }
    }
  }
  return readers;
}

/** Follow single-key bindings. The default identity must come back to the snapshot literal. */
export function resolveTheme(values: Readonly<Record<string, string>>): Record<string, string> {
  const resolved: Record<string, string> = {};
  const visiting = new Set<string>();
  const walk = (name: string): string => {
    const ready = resolved[name];
    if (ready !== undefined) return ready;
    if (visiting.has(name)) throw new Error(`Theme cycle at ${name}.`);
    visiting.add(name);
    const value = values[name];
    if (value === undefined) throw new Error(`Missing theme key ${name}.`);
    const match = /^var\(--(tower-[a-z0-9-]+)\)$/.exec(value);
    const concrete = match?.[1] ? walk(match[1]) : value;
    visiting.delete(name);
    resolved[name] = concrete;
    return concrete;
  };
  for (const name of Object.keys(values)) walk(name);
  return resolved;
}
