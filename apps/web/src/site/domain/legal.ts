/**
 * Structure of the institutional pages. The words live in content/site/site-data.v2.json.
 * Render order inside a section: `p…`, `ul`, `after…`. URLs and the email address become links.
 */
export interface LegalSection {
  readonly h: string;
  readonly p?: readonly string[];
  readonly ul?: readonly string[];
  readonly after?: readonly string[];
}

export interface LegalPageContent {
  readonly slug: string;
  readonly kicker: string;
  readonly title: string;
  readonly description: string;
  readonly lead: string;
  /** Plain paragraphs right after the lead (About); legal pages use `sections`. */
  readonly body?: readonly string[];
  /** About only: a quiet line of its own after the last paragraph, then the closing commitment. */
  readonly wink?: string;
  readonly closing?: string;
  readonly sections?: readonly LegalSection[];
}

export type LegalSegment = { readonly kind: "text"; readonly text: string } | { readonly kind: "link"; readonly text: string; readonly href: string; readonly external: boolean };

const LINK_PATTERN = /https:\/\/[^\s)]+[^\s).,;:]|[\w.+-]+@[\w-]+(?:\.[\w-]+)+/g;

/** Splits copy into text and link segments: `https://…` opens in a new tab, an email address becomes `mailto:`. */
export function legalSegments(text: string): readonly LegalSegment[] {
  const segments: LegalSegment[] = [];
  let last = 0;
  for (const match of text.matchAll(LINK_PATTERN)) {
    const value = match[0];
    if (match.index > last) segments.push({ kind: "text", text: text.slice(last, match.index) });
    const external = value.startsWith("https://");
    segments.push({ kind: "link", text: value, href: external ? value : `mailto:${value}`, external });
    last = match.index + value.length;
  }
  if (last < text.length) segments.push({ kind: "text", text: text.slice(last) });
  return segments;
}
