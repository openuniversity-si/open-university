import { applyElementAliases, applyFoundationAliases, elementOf, SHEET_SLOTS } from "./identity.ts";

export interface TypographyRole {
  readonly figmaStyle: string;
  readonly className: string;
  readonly family: string;
  readonly weight: number;
  readonly size: number;
  readonly lineHeight: string;
  readonly letterSpacing: number;
  readonly textTransform: string;
  readonly textDecoration: string;
}

export interface TokenSnapshot {
  readonly schemaVersion: number;
  readonly figmaVersionId: string | null;
  readonly variables: Readonly<Record<string, { readonly value: string; readonly source: string; readonly codeSyntax: string; readonly description?: string }>>;
  readonly typography: readonly TypographyRole[];
}

function validateTokenSnapshot(snapshot: TokenSnapshot): void {
  for (const [name, token] of Object.entries(snapshot.variables)) {
    if (!/^tower-[a-z0-9-]+$/.test(name) || token.codeSyntax !== `var(--${name})`) {
      throw new Error(`Invalid token name or codeSyntax: ${name}`);
    }
    if (name === "tower-accent" && token.value.toLowerCase() !== "#ffffff") throw new Error("The Tower accent must be white.");
    if (/[;{}]/.test(token.value)) throw new Error(`Invalid token value: ${name}`);
  }
}

/** Snapshot keys, with a duplicated foundation literal written once and referenced everywhere else. */
function identityVariables(snapshot: TokenSnapshot): TokenSnapshot["variables"] {
  validateTokenSnapshot(snapshot);
  const founded = applyFoundationAliases(snapshot.variables);
  const classes = new Set<string>();
  for (const name of Object.keys(founded)) {
    const element = elementOf(name);
    if (element) classes.add(element);
  }
  const themed = applyElementAliases(founded, classes);
  const next: Record<string, TokenSnapshot["variables"][string]> = { ...themed };
  for (const [name, value] of Object.entries(SHEET_SLOTS)) {
    if (Object.hasOwn(next, name)) throw new Error(`Sheet slot collides with snapshot key ${name}.`);
    if (/[;{}]/.test(value)) throw new Error(`Invalid sheet slot ${name}.`);
    next[name] = { value, source: "D-052", codeSyntax: `var(--${name})` };
  }
  return next;
}

export function generateTokenCss(snapshot: TokenSnapshot): string {
  const entries = Object.entries(identityVariables(snapshot)).sort(([a], [b]) => a.localeCompare(b, "en"));
  return `/* Generated from design/figma-tokens.snapshot.json by pnpm tokens:generate. */\n:root {\n${entries.map(([name, token]) => `  --${name}: ${token.value};`).join("\n")}\n}\n`;
}

export function tokenIdentifier(name: string): string {
  const ident = name.replace(/-([a-z0-9])/g, (_, letter: string) => letter.toUpperCase());
  if (!/^[A-Za-z_$][\w$]*$/.test(ident)) throw new Error(`Invalid token export: ${name}`);
  return ident;
}

/** CSS custom-property names keyed by the export. The identifier is not reversible. */
export function generateTokenNames(snapshot: TokenSnapshot): string {
  const entries = Object.entries(identityVariables(snapshot)).sort(([a], [b]) => a.localeCompare(b, "en"));
  const lines = entries.map(([name]) => `  ${tokenIdentifier(name)}: ${JSON.stringify(name)},`);
  return `/* Generated from design/figma-tokens.snapshot.json by pnpm tokens:generate. */\nexport const themeTokenNames = {\n${lines.join("\n")}\n} as const;\n`;
}

/** One named export per snapshot key. Call sites read the export; they do not spell the value. */
export function generateTokenValues(snapshot: TokenSnapshot): string {
  const entries = Object.entries(identityVariables(snapshot)).sort(([a], [b]) => a.localeCompare(b, "en"));
  const seen = new Set<string>();
  const lines = entries.map(([name, token]) => {
    const ident = tokenIdentifier(name);
    if (seen.has(ident)) throw new Error(`Duplicate token export: ${ident}`);
    seen.add(ident);
    return `export const ${ident} = ${JSON.stringify(token.value)};`;
  });
  return `/* Generated from design/figma-tokens.snapshot.json by pnpm tokens:generate. */\n${lines.join("\n")}\n`;
}

export function generateTypographyCss(snapshot: TokenSnapshot): string {
  return `/* Generated from Figma text roles by pnpm tokens:generate. */\n${snapshot.typography.map((role) => {
    const key = role.className.slice(2);
    return `.${role.className} {\n  font-family: var(--tower-font-${role.family === "Inter" ? "ui" : "display"});\n  font-size: var(--tower-type-${key}-size);\n  font-weight: var(--tower-type-${key}-weight);\n  font-synthesis: none;\n  line-height: var(--tower-type-${key}-line-height);\n  letter-spacing: var(--tower-type-${key}-tracking);\n  text-transform: ${role.textTransform};\n  text-decoration: ${role.textDecoration};\n}\n`;
  }).join("\n")}`;
}
