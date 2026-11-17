import { z } from "zod";
import { authorCreate, importCreate, parseEditionLabel, type ImportDraft } from "../../../../src/catalog/domain/contracts.ts";
import { listOption, positional, requireOption, stringOption } from "../args.ts";
import { issueList } from "../client.ts";
import { parseJsonFile, type CommandSpec } from "../context.ts";
import { UsageError } from "../errors.ts";
import { duration, table } from "../render.ts";
import { resolveCourseId } from "./editions.ts";

/** `--items`: the POST /imports body as the extractor writes it; the playlist URL comes from the command line. */
const itemsFile = z.union([importCreate.omit({ playlistUrl: true }).extend({ playlistUrl: z.string().optional() }), z.array(z.unknown())]);

/** `--author new:"Name"`: a new author with a slug and monogram derived from the name (override with --author-slug/--author-monogram). */
export function newAuthor(name: string, kind: string, slug?: string, monogram?: string) {
  const clean = name.trim();
  const derivedSlug = clean.normalize("NFKD").replace(/[̀-ͯ]/g, "").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
  const initials = clean.split(/\s+/).map((word) => word[0] ?? "").join("").toUpperCase().slice(0, 3);
  if (!clean || !(slug ?? derivedSlug) || !(monogram ?? initials)) throw new UsageError("--author new:\"Name\" needs a name with letters.");
  const parsed = authorCreate.safeParse({ slug: slug ?? derivedSlug, name: clean, monogram: monogram ?? initials, kind });
  if (!parsed.success) throw new UsageError("--author-kind must declare person, institution or channel.");
  return parsed.data;
}

export const importCommands: CommandSpec[] = [
  {
    name: "import", usage: "import <playlist-url> (--slug <s> --author <id|new:\"Name\"> | --course <course>) [--edition \"Fall 2025\"] [--part lectures|labs] --items <file.json> [--exclude <ids>] [--tool yt-dlp|api] [--title …] [--source-id …] [--license-code …] [--canonical-url …]",
    summary: "store an extracted playlist (POST /imports), print the full report, draft a new course or an edition of an existing one", positionals: { min: 1, max: 1 },
    options: {
      slug: { type: "string", help: "slug of a new course", value: "<s>" }, author: { type: "string", help: "author id, or new:\"Name\" (new course)", value: "<a>" },
      course: { type: "string", help: "an existing course (id or slug): the playlist becomes an edition of it", value: "<course>" },
      edition: { type: "string", help: "the edition, e.g. \"Fall 2025\" (required with --course; an existing one is extended)", value: "<label>" },
      part: { type: "string", help: "lectures | labs for every lesson (default: the import's suggestion)", value: "<part>" },
      items: { type: "string", help: "the extracted POST /imports body (yt-dlp extraction itself is P6)", value: "<path>" },
      exclude: { type: "string", help: "YouTube ids to leave out", value: "<ids>" }, tool: { type: "string", help: "extractor label stored with the import (yt-dlp | api)", value: "<t>" },
      title: { type: "string", help: "course title (default: playlist title)", value: "<t>" }, "lesson-noun": { type: "string", help: "Lecture | Episode", value: "<n>" },
      "source-id": { type: "string", help: "content source", value: "<id>" }, "license-code": { type: "string", help: "license", value: "<code>" },
      "canonical-url": { type: "string", help: "canonical course URL", value: "<url>" }, "author-slug": { type: "string", help: "slug of a new author", value: "<s>" },
      "author-kind": { type: "string", help: "required for a new author: person | institution | channel", value: "<kind>" },
      "author-monogram": { type: "string", help: "monogram of a new author", value: "<AB>" },
    },
    routes: ["POST /imports", "POST /imports/:id/draft"],
    async run(context) {
      const playlistUrl = positional(context.args, 0, "playlist-url");
      const tool = stringOption(context.args, "tool");
      if (tool !== undefined && tool !== "yt-dlp" && tool !== "api") throw new UsageError("--tool must be yt-dlp or api.");
      const file = stringOption(context.args, "items");
      if (file === undefined) throw new UsageError(`yt-dlp${tool === "api" ? " / YouTube Data API" : ""} extraction arrives in P6; pass --items <file.json> (the POST /imports body, already extracted).`);
      const parsed = itemsFile.safeParse(parseJsonFile(context, file));
      if (!parsed.success) throw new UsageError(`${file} does not match POST /imports: ${issueList(parsed.error.issues)}`);
      if (Array.isArray(parsed.data)) throw new UsageError(`${file} must be the POST /imports object ({items: […], playlistTitle?, channelId?…}), not a bare array.`);
      if (parsed.data.playlistUrl !== undefined && parsed.data.playlistUrl !== playlistUrl) throw new UsageError(`${file} was extracted from another playlist URL.`);
      const createBody = { ...parsed.data, playlistUrl, ...(tool === undefined ? {} : { tool }) };
      const editionLabel = stringOption(context.args, "edition");
      const edition = editionLabel === undefined ? undefined : parseEditionLabel(editionLabel);
      if (editionLabel !== undefined && edition === null) throw new UsageError(`--edition "${editionLabel}" names no year (e.g. "Fall 2025", "2026").`);
      const part = stringOption(context.args, "part");
      if (part !== undefined && part !== "lectures" && part !== "labs") throw new UsageError("--part must be lectures or labs.");
      const courseRef = stringOption(context.args, "course");
      let target: Pick<ImportDraft, "slug" | "authorId" | "newAuthor" | "courseId">;
      if (courseRef !== undefined) {
        const courseOnly = ["slug", "author", "title", "lesson-noun", "source-id", "license-code", "canonical-url"].filter((name) => stringOption(context.args, name) !== undefined);
        if (courseOnly.length > 0) throw new UsageError(`--course drafts into an existing course: drop ${courseOnly.map((name) => `--${name}`).join(", ")}.`);
        if (edition === undefined) throw new UsageError("--course needs --edition (e.g. --edition \"Fall 2025\").");
        target = { courseId: await resolveCourseId(context, courseRef) };
      } else {
        const author = requireOption(context.args, "author");
        target = { slug: requireOption(context.args, "slug"), ...(author.startsWith("new:") ? { newAuthor: newAuthor(author.slice(4).replace(/^"|"$/g, ""), requireOption(context.args, "author-kind"), stringOption(context.args, "author-slug"), stringOption(context.args, "author-monogram")) } : { authorId: author }) };
      }
      const draftBody: ImportDraft = {
        ...target, ...(edition ? { edition } : {}), ...(part === undefined ? {} : { part }),
        ...(listOption(context.args, "exclude") === undefined ? {} : { exclude: listOption(context.args, "exclude") }),
        ...(stringOption(context.args, "title") === undefined ? {} : { title: stringOption(context.args, "title") }),
        ...(stringOption(context.args, "lesson-noun") === undefined ? {} : { lessonNoun: stringOption(context.args, "lesson-noun") as "Lecture" }),
        ...(stringOption(context.args, "source-id") === undefined ? {} : { sourceId: stringOption(context.args, "source-id") }),
        ...(stringOption(context.args, "license-code") === undefined ? {} : { licenseCode: stringOption(context.args, "license-code") }),
        ...(stringOption(context.args, "canonical-url") === undefined ? {} : { canonicalUrl: stringOption(context.args, "canonical-url") }),
      };
      await context.confirm(`Import ${String(createBody.items.length)} item(s) into ${draftBody.courseId === undefined ? `a draft course ${draftBody.slug ?? ""}` : draftBody.courseId}${edition ? `, edition ${edition.label}` : ""}`);
      const stored = await context.client.call("POST /imports", { body: createBody });
      const { report } = stored.data.import;
      context.out.lines([
        `Import ${stored.data.import.id} (playlist ${report.playlist.id}${report.playlist.title ? `, ${report.playlist.title}` : ""}): ${String(report.accepted.length)} accepted, ${String(report.excluded.length)} excluded, ${String(report.warnings.length)} warning(s).`,
        "Accepted:", ...table(["#", "youtube", "kind", "part", "duration", "slug", "title"], report.accepted.map((item) => [String(item.position), item.id, item.suggestedKind, part ?? item.suggestedPart ?? "lectures", duration(item.durationSeconds), item.suggestedSlug, item.suggestedTitle])).map((line) => `  ${line}`),
        "Excluded:", ...(report.excluded.length ? report.excluded.map((item) => `  ${item.id}: ${item.reason}${item.courseId ? ` (in ${item.courseId})` : ""}`) : ["  none"]),
        "Warnings:", ...(report.warnings.length ? report.warnings.map((item) => `  ${item.id}: ${item.reason}`) : ["  none"]),
      ]);
      const drafted = await context.client.call("POST /imports/:id/draft", { params: { id: stored.data.import.id }, body: draftBody });
      context.out.line(`${draftBody.courseId === undefined ? "Draft course" : "Course"} ${drafted.data.course.id} (/c/${drafted.data.course.slug}), edition ${drafted.data.edition.label} (${drafted.data.edition.id}, position ${String(drafted.data.edition.position)}): ${String(drafted.data.lessons.length)} lesson(s). Next: tower-catalog draft-copy ${drafted.data.course.id}.`);
      context.out.result({ ok: true, data: { import: stored.data.import, draft: drafted.data }, requestId: drafted.envelope.requestId });
    },
  },
];
