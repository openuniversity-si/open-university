import { EXTENT } from "../../kernel/extent.ts";
import { slugify as kernelSlugify } from "../../kernel/slug.ts";

// The lesson's address and the title it suggests (BRIEF-P7 §1, docs/catalog/slugs.md): pure, no I/O.
// Manual add, the received list and curation use this address. The watcher does not suggest a title or a trailer.
// The YouTube title stays intact in lessons.youtube_title; this only makes the URL segment.

export const LESSON_SLUG_MAX = 60;
/** The CHECK of lessons.slug (src/db/schema.ts). */
export const SLUG_PATTERN = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;

export interface LessonSlugInput {
  readonly youtubeTitle: string;
  /** The approved display title; it wins over the YouTube title when present. */
  readonly displayTitle?: string | null;
  readonly courseTitle: string;
  readonly courseSlug: string;
  /** Institution or channel name, removed when a title repeats it. */
  readonly institution?: string | null;
  readonly edition?: { readonly label: string; readonly term?: string | null; readonly year?: number | null } | null;
  /** 1-based position in the edition; names the fallback `<kind>-NN`. */
  readonly position: number;
  readonly kind: string;
}

const STOPWORDS = new Set(["a", "an", "and", "the", "of", "to", "in", "on", "for", "with", "at", "by", "or", "vs"]);
const NOISE_WORDS = new Set(["lecture", "lectures", "lec", "lab", "labs", "class", "course", "series", "university",
  "january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"]);
const TERM_YEAR = /\b(?:fall|spring|summer|winter|autumn)\s*'?(?:\d{4}|\d{2})\b/g;
const TERM_CODE = /\b(?:fa|sp|su|wi|f|s|w)(?:\d{4}|\d{2})\b/g;
// "Lecture 3", "Lec 01.", "Class10", "Week 2", "Demo 4", "Lab 1", "#07", optionally "Bonus"/"Guest" first.
const MARKER = /(?:^|[^a-z0-9])((?:bonus|guest)[\s-]+)?(lecture|lec|class|session|week|demo|lab|#)[\s.-]*(\d{1,3})(?:\.(\d))?(?![a-z0-9])/;
// "L1 - …", "D3: …", "L1.5 - …": the one-letter codes only when a separator follows.
const CODE_MARKER = /(?:^|[^a-z0-9])(l|d)(\d{1,3})(?:\.(\d))?(?=\s*[:–—]|\s+-|\s*$)/;
// "1: …", "01 Task-based …", "7. …" at the very start.
const BARE_MARKER = /^\s*(\d{1,3})(?:\.(\d))?(?=\s*[:.)]\s|\s+[a-z])/;
const MARKER_NOUN: Readonly<Record<string, string | undefined>> = { lecture: "lecture", lec: "lecture", class: "lecture", session: "lecture", "#": "lecture", l: "lecture", week: "week", demo: "demo", d: "demo", lab: "lab" };

interface Marker { readonly slug: string; readonly start: number; readonly end: number; readonly compact: boolean }

function words(text: string): string[] {
  return text.match(/[a-z0-9]+/g) ?? [];
}

function slugWords(text: string): string {
  return words(text).join("-");
}

function pad(number: number): string {
  return String(number).padStart(2, "0");
}

function normalize(text: string): string {
  // "Hacker's" → "hackers", "U.S." → "us", "I/O" → "io".
  return text.normalize("NFKD").replace(/\p{M}/gu, "").toLowerCase().replace(/['‘’`´"“”]/g, "")
    .replace(/\b([a-z])\.([a-z])\.?(?![a-z0-9])/g, "$1$2").replace(/\b([a-z])\/([a-z])\b/g, "$1$2");
}

function numbered(word: string | undefined, number: string | undefined, decimal: string | undefined): string {
  return `${String(MARKER_NOUN[String(word)])}-${pad(Number(number))}${decimal ? `-${decimal}` : ""}`;
}

/** Where a match starts once its one-character left boundary is skipped. */
function startOf(match: RegExpExecArray): number {
  return match.index + (/^[a-z0-9#]/.test(match[EXTENT.first]) ? 0 : 1);
}

function findMarker(text: string): Marker | null {
  const bare = BARE_MARKER.exec(text);
  if (bare) return { slug: numbered("#", bare[1], bare[2]), start: EXTENT.first, end: bare[EXTENT.first].length, compact: true };
  const word = MARKER.exec(text);
  const code = CODE_MARKER.exec(text);
  if (word && (!code || word.index <= code.index)) {
    const prefix = word[1] ? `${slugWords(word[1])}-` : "";
    return { slug: prefix + numbered(word[2], word[3], word[4]), start: startOf(word), end: word.index + word[EXTENT.first].length, compact: word[2] === "#" };
  }
  if (code) return { slug: numbered(code[1], code[2], code[3]), start: startOf(code), end: code.index + code[EXTENT.first].length, compact: true };
  return null;
}

/** The words that, alone, only repeat the course, its institution or its edition. */
function noiseVocabulary(input: LessonSlugInput): Set<string> {
  const edition = input.edition;
  return new Set([
    ...words(normalize(input.courseTitle)), ...words(normalize(input.courseSlug)), ...words(normalize(input.institution ?? "")),
    ...words(normalize(edition?.label ?? "")), ...words(normalize(edition?.term ?? "")), ...(edition?.year == null ? [] : [String(edition.year), String(edition.year % 100)]),
  ]);
}

function isNoise(segment: string, vocabulary: ReadonlySet<string>): boolean {
  const tokens = words(segment);
  return tokens.some((token) => !STOPWORDS.has(token)) && tokens.every((token) => STOPWORDS.has(token) || NOISE_WORDS.has(token) || vocabulary.has(token));
}

/** Drops the segments that only name the course, institution, channel or edition; keeps the first meaningful `|` segment. */
function topicOf(text: string, vocabulary: ReadonlySet<string>): string {
  const pipes = text.split("\u2738", 1).join("").split("|").filter((segment) => words(segment).length > EXTENT.empty);
  let topic = pipes.find((segment) => !isNoise(segment, vocabulary)) ?? pipes.slice(EXTENT.first, 1).join("");
  const dashes = topic.split(/\s[-–—]\s|\s·\s|[–—]/);
  while (dashes.length > 1 && isNoise(String(dashes[EXTENT.first]), vocabulary)) dashes.shift();
  while (dashes.length > 1 && isNoise(String(dashes[dashes.length - 1]), vocabulary)) dashes.pop();
  topic = dashes.join(" ");
  const colon = /^([^:]*):\s(.*)$/.exec(topic);
  if (colon && isNoise(String(colon[1]), vocabulary) && words(String(colon[2])).length > EXTENT.empty) topic = String(colon[2]);
  // "Oil Lecture" → "Oil"; "Transportation Lecture Part 1" → "Transportation Part 1".
  const tokens = words(topic);
  return tokens.filter((token, index) => !(token === "lecture" && tokens.length > 1 && (index === tokens.length - 1 || tokens[index + 1] === "part"))).join(" ");
}

/** At most `max` characters, cut between words, without a trailing stopword. */
function fit(slug: string, max: number): string {
  let cut = slug.length <= max ? slug : slug.slice(EXTENT.first, max + 1);
  if (cut.length > max) cut = cut.includes("-") ? cut.slice(EXTENT.first, cut.lastIndexOf("-")) : cut.slice(EXTENT.first, max);
  const parts = cut.split("-");
  while (parts.length > 1 && STOPWORDS.has(String(parts[parts.length - 1]))) parts.pop();
  return parts.join("-");
}

/** The slug the rule gives before uniqueness. */
export function baseLessonSlug(input: LessonSlugInput): string {
  const source = input.displayTitle?.trim() ? input.displayTitle : input.youtubeTitle;
  const vocabulary = noiseVocabulary(input);
  const editionLabel = normalize(input.edition?.label ?? "");
  let text = normalize(source).replace(/\[[^\]]*\]/g, " ").replace(TERM_YEAR, " ").replace(TERM_CODE, " ");
  if (/[a-z]/.test(editionLabel)) text = text.split(editionLabel).join(" ");
  text = text.replace(/\(([^()]*)\)/g, (_, inner: string) => (isNoise(inner, vocabulary) ? " " : ` ${inner} `)).replace(/\s+/g, " ").trim();
  const marker = findMarker(text);
  let rest = text;
  if (marker) {
    const before = text.slice(EXTENT.first, marker.start);
    // A prefix before the lecture number is the series name ("CS50x - Lecture 0 - …", "Intro to Android L1 - …").
    const prefix = marker.compact || /[:,|·.\-–—]\s*$/.test(before) || words(before).length === EXTENT.empty || isNoise(before, vocabulary) ? "" : before;
    rest = `${prefix} ${text.slice(marker.end).replace(/^[\s:.,\-–—|·)]+/, "")}`.trim();
  }
  const topic = slugWords(topicOf(rest, vocabulary));
  const slug = [marker?.slug, topic].filter((part) => part).join("-");
  if (!marker && words(topic).join("").length < 3) return fallbackSlug(input);
  return fit(slug, LESSON_SLUG_MAX);
}

function fallbackSlug(input: LessonSlugInput): string {
  return `${slugWords(normalize(input.kind)) || "lecture"}-${pad(Math.max(0, Math.trunc(input.position)))}`;
}

/** `base`, else `base-2`, `base-3`… (cut between words to stay within the length) — the first one `taken` does not hold. */
export function uniqueLessonSlug(base: string, taken: ReadonlySet<string>): string {
  if (!taken.has(base)) return base;
  for (let suffix = 2; ; suffix += 1) {
    const candidate = `${fit(base, LESSON_SLUG_MAX - String(suffix).length - 1)}-${String(suffix)}`;
    if (!taken.has(candidate)) return candidate;
  }
}

/**
 * The clean slug of a lesson: deterministic, ≤ 60 characters, matching the CHECK, unique against `taken`
 * (the course's slugs). It never renames: callers only use it for lessons that have no slug yet.
 */
export function cleanLessonSlug(input: LessonSlugInput, taken: ReadonlySet<string>): string {
  return uniqueLessonSlug(baseLessonSlug(input), taken);
}

const TITLE_PREFIX = /^\s*(?:(?:lecture|lec|episode|ep|class|session|part|video)\.?\s*\d+[a-z]?|\d{1,3})\s*[-–—:.|)]\s*/i;
const TITLE_SUFFIX = /\s*[|]\s*[^|]+$/;

/** "Lecture 3 – Freud | Yale" → "Freud". Falls back to the trimmed title when cleaning would leave nothing. */
export function cleanTitle(title: string): string {
  const cleaned = title.replace(TITLE_SUFFIX, "").replace(TITLE_PREFIX, "").trim();
  return cleaned.length > EXTENT.empty ? cleaned : title.trim();
}

/** A short slug for a suggested title. The lesson address itself is `cleanLessonSlug`. */
export const slugify = (text: string, max = 160): string => kernelSlugify(text, { max, fallback: "lesson" });

/** `base`, else `base-2`, `base-3`… — the first one `taken` does not hold. */
export function uniqueSlug(base: string, taken: ReadonlySet<string>, max = 160): string {
  if (!taken.has(base)) return base;
  for (let suffix = 2; ; suffix += 1) {
    const candidate = `${base.slice(EXTENT.first, max - String(suffix).length - 1).replace(/-+$/g, "")}-${String(suffix)}`;
    if (!taken.has(candidate)) return candidate;
  }
}

/** A short first item named like a trailer or an intro. */
export function looksLikeTrailer(title: string, durationSeconds: number | null | undefined, index: number): boolean {
  return index === EXTENT.first && (durationSeconds ?? Infinity) < 300 && /\b(trailer|intro|introduction|preview)\b/i.test(title);
}
