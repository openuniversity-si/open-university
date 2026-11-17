import { readdirSync, readFileSync, statSync } from "node:fs";
import { extname, join, relative } from "node:path";
import { MEDIA_BYTE_BUDGETS } from "../../../../src/media/domain/budget.ts";
import { prepareMedia } from "../../../../src/media/server/prepare.ts";
import { mediaContentType } from "../../../../src/media/server/storage.ts";
export { prepareMedia };
import type { MediaKind } from "../../../../src/media/domain/types.ts";
import { flag, intOption, positional, requireOption, stringOption } from "../args.ts";
import type { PreparedMedia } from "../client.ts";
import type { CommandSpec, Context } from "../context.ts";
import { CliError, EXIT, UsageError } from "../errors.ts";
import { preconditionLines, table } from "../render.ts";
import { mediaKeyFor, uploadPrepared, type MediaIntent } from "./media.ts";
import { getCourse } from "./shared.ts";

/** File names of a covers folder (plan §4.4) and the media kind each one fills; `lessons/NN` is the lesson's 16:9 cover. */
export const COURSE_COVER_FILES = {
  poster: "poster_9x16",
  "hero-desktop": "hero_desktop_16x9",
  "hero-present": "hero_present",
  "hero-mobile": "hero_mobile_9x16",
  still: "still_16x9",
} as const satisfies Record<string, MediaKind>;
export const LESSON_COVER_KIND = "cover_16x9" satisfies MediaKind;
/** What the media API ingests (src/media/server/prepare.ts: JPEG, PNG, WebP, AVIF; it re-encodes and strips metadata). */
export const COVER_EXTENSIONS = [".jpg", ".jpeg", ".png", ".webp", ".avif"] as const;

export interface CoverFile { readonly path: string; readonly owner: "course" | "lesson"; readonly position: number | null; readonly kind: MediaKind; readonly bytes: number; readonly variant?: string; readonly source?: Uint8Array }

/** The course's 1200×630 JPEG link preview, rendered in memory from its hero-desktop and uploaded as `hero_desktop_16x9/og`. */
export async function ogCoverFile(hero: CoverFile): Promise<CoverFile> {
  const { renderOgImage, OG_VARIANT } = await import("../../../../src/media/server/og.ts");
  const bytes = await renderOgImage(Buffer.from(hero.source ?? readFileSync(hero.path)), "cover");
  return { path: "og.jpg", owner: "course", position: null, kind: hero.kind, bytes: bytes.length, variant: OG_VARIANT, source: bytes };
}

/** Reads and checks a covers folder; unknown names, bad extensions, duplicates and files over budget are all listed. */
export function planCovers(directory: string, allowOversize = false): { files: CoverFile[]; warnings: string[] } {
  const files: CoverFile[] = [];
  const problems: string[] = [];
  const warnings: string[] = [];
  const seen = new Map<string, string>();
  const add = (path: string, owner: "course" | "lesson", position: number | null, kind: MediaKind) => {
    const key = `${owner}:${String(position)}:${kind}`;
    const other = seen.get(key);
    if (other) { problems.push(`${relative(directory, path)} and ${other} fill the same cover`); return; }
    seen.set(key, relative(directory, path));
    const bytes = statSync(path).size;
    const budget = MEDIA_BYTE_BUDGETS[kind];
    if (bytes > budget) (allowOversize ? warnings : problems).push(`${relative(directory, path)} is ${String(Math.ceil(bytes / 1024))} KiB, over the ${String(budget / 1024)} KiB budget of ${kind} (src/media/domain/budget.ts)`);
    files.push({ path, owner, position, kind, bytes });
  };
  let entries: string[];
  try { entries = readdirSync(directory); } catch { throw new UsageError(`Cannot read --dir ${directory}.`); }
  for (const name of entries.sort()) {
    const full = join(directory, name);
    if (name === "lessons" && statSync(full).isDirectory()) {
      for (const lessonFile of readdirSync(full).sort()) {
        const match = /^(\d{2,3})(\.[a-z0-9]+)$/i.exec(lessonFile);
        if (!match || !(COVER_EXTENSIONS as readonly string[]).includes((match[2] ?? "").toLowerCase())) { problems.push(`lessons/${lessonFile}: expected lessons/NN.{${COVER_EXTENSIONS.map((ext) => ext.slice(1)).join(",")}}`); continue; }
        add(join(full, lessonFile), "lesson", Number(match[1]), LESSON_COVER_KIND);
      }
      continue;
    }
    const extension = extname(name).toLowerCase();
    const base = name.slice(0, name.length - extension.length) as keyof typeof COURSE_COVER_FILES;
    if (!Object.hasOwn(COURSE_COVER_FILES, base) || !(COVER_EXTENSIONS as readonly string[]).includes(extension)) { problems.push(`${name}: expected ${Object.keys(COURSE_COVER_FILES).join("|")}.{${COVER_EXTENSIONS.map((ext) => ext.slice(1)).join(",")}} or lessons/NN.*`); continue; }
    add(full, "course", null, COURSE_COVER_FILES[base]);
  }
  if (problems.length) throw new UsageError(`The covers folder has ${String(problems.length)} problem(s); nothing was uploaded:\n  ${problems.join("\n  ")}`);
  if (files.length === 0) throw new UsageError(`No cover files in ${directory}.`);
  return { files, warnings };
}

export const coverCommands: CommandSpec[] = [
  {
    name: "covers", usage: "covers <course> --dir <folder> [--force-oversize] [--parallel <n>]", summary: "upload poster, heroes, still and lessons/NN with tower-media put; --dry-run lists the plan",
    options: { dir: { type: "string", required: true, help: "poster.*, hero-desktop.*, hero-present.*, hero-mobile.*, still.*, lessons/NN.*", value: "<folder>" }, "force-oversize": { type: "boolean", help: "upload past the kind budget" }, parallel: { type: "string", help: "uploads at once (1–32, default 16)", value: "<n>" } },
    positionals: { min: 1, max: 1 }, routes: ["GET /courses/:id", "media:POST /check", "media:POST /objects", "media:POST /attach"],
    async run(context) {
      const id = positional(context.args, 0, "course");
      if (context.target === "staging") throw new UsageError("tower-media has no staging target (prod|preview); upload covers on preview or prod.");
      const { files: planned, warnings } = planCovers(requireOption(context.args, "dir"), flag(context.args, "force-oversize"));
      // Every hero-desktop upload brings its link preview (og:image), so new courses get one with no extra step.
      const hero = planned.find((file) => file.owner === "course" && file.kind === "hero_desktop_16x9");
      let plan = planned;
      if (hero) {
        try { plan = [...planned, await ogCoverFile(hero)]; }
        catch (error) { context.out.note(`warning: link preview of ${id} skipped (${error instanceof Error ? error.message : "render failed"}); upload the hero and re-run tower-catalog og ${id}`); }
      }
      for (const warning of warnings) context.out.note(`warning: --force-oversize: ${warning}`);
      const detail = await getCourse(context, id);
      const byPosition = new Map(detail.lessons.map((lesson) => [lesson.position, lesson.id]));
      const unknown = plan.filter((file) => file.owner === "lesson" && !byPosition.has(file.position ?? 0)).map((file) => `lessons/${String(file.position).padStart(2, "0")}`);
      if (unknown.length) throw new UsageError(`${id} has no lesson at ${unknown.join(", ")} (it has ${String(detail.lessons.length)}).`);
      const ownerId = (file: CoverFile) => (file.owner === "course" ? id : byPosition.get(file.position ?? 0) ?? "");
      context.out.lines(table(["owner", "kind", "KiB", "budget", "file"], plan.map((file) => [ownerId(file), file.variant ? `${file.kind}/${file.variant}` : file.kind, String(Math.ceil(file.bytes / 1024)), String(MEDIA_BYTE_BUDGETS[file.kind] / 1024), relative(process.cwd(), file.path)])));
      const fallback = detail.lessons.filter((lesson) => !plan.some((file) => file.owner === "lesson" && file.position === lesson.position)).length;
      if (fallback) context.out.line(`${String(fallback)} lesson(s) without a file keep the course fallback (nothing to upload).`);
      if (context.dryRun) { context.out.note("DRY-RUN: nothing uploaded."); return; }
      await context.confirm(`Upload ${String(plan.length)} cover(s) of ${id}`);
      const parallel = intOption(context.args, "parallel") ?? 16;
      if (parallel < 1 || parallel > 32) throw new UsageError("--parallel must be 1–32.");
      // Uploads are independent and idempotent (identical bytes reuse their version), so they run `parallel` at a time;
      // the first failure stops new uploads and is reported once the running ones finish.
      const failures: string[] = [];
      let next = 0;
      let done = 0;
      const worker = async () => {
        while (failures.length === 0 && next < plan.length) {
          const file = plan[next] as CoverFile;
          next += 1;
          try {
            await putCover(context, file, ownerId(file), id);
            done += 1;
          } catch (error) { failures.push(`${file.path} (${error instanceof Error ? error.message : "upload failed"})`); }
        }
      };
      await Promise.all(Array.from({ length: Math.min(parallel, plan.length) }, worker));
      if (failures.length) throw new CliError(`cover upload failed for ${failures.join(", ")}; ${String(done)} of ${String(plan.length)} uploaded. Fix it and re-run: identical files reuse their version.`, EXIT.api);
      const after = await getCourse(context, id);
      const review = after.preconditions?.review ?? [];
      context.out.lines([`Uploaded ${String(plan.length)} cover(s).`, review.length ? `Still missing for review (${String(review.length)}):` : `Nothing missing for review: tower-catalog status ${id} review.`, ...preconditionLines(review)]);
    },
  },
];

/** The active default hero URL from a structured media list. */
export function activeHeroUrl(versions: readonly { active?: boolean; kind: string; variant: string; url: string }[]): string | null {
  return versions.find((row) => row.active === true && row.kind === "hero_desktop_16x9" && row.variant === "default")?.url ?? null;
}

async function putCover(context: Context, file: CoverFile, ownerId: string, courseId: string): Promise<void> {
  const prepared = await prepareMedia(file.source ?? file.path);
  const media: PreparedMedia = { bytes: prepared.bytes, sha256: prepared.sha256, extension: prepared.extension as PreparedMedia["extension"], contentType: mediaContentType(`file.${prepared.extension}`), width: prepared.width, height: prepared.height };
  const intent: MediaIntent = { target: context.target === "prod" ? "prod" : "preview", owner: file.owner, ownerId, kind: file.kind, variant: file.variant ?? "default", alt: `${courseId} ${file.kind}`, forceOversize: flag(context.args, "force-oversize") };
  await uploadPrepared({
    client: { call: (input, decode) => context.client.adminCall(input, decode) },
    prepare: () => Promise.resolve(media),
    confirm: () => Promise.resolve(),
    keyFor: mediaKeyFor,
  }, { media, intent, dryRun: false, attach: true });
}

coverCommands.push({
  name: "og", usage: "og <course>... [--file <hero>]", summary: "render and upload the 1200×630 JPEG link preview (hero_desktop_16x9/og) from the course hero",
  options: { file: { type: "string", help: "hero to render from (one course only); default: the active hero_desktop_16x9, fetched from the media host", value: "<hero>" } },
  positionals: { min: 1, max: 400 }, routes: ["GET /courses/:id", "media:GET /", "media:POST /check", "media:POST /objects", "media:POST /attach"],
  async run(context) {
    if (context.target === "staging") throw new UsageError("tower-media has no staging target (prod|preview).");
    const ids = context.args.positionals;
    const local = stringOption(context.args, "file");
    if (local && ids.length !== 1) throw new UsageError("--file renders one course; pass one course id.");
    await context.confirm(`Render and upload the link preview of ${String(ids.length)} course(s)`);
    const failures: string[] = [];
    // One at a time: decoding a hero is the memory peak, and uploads are quick.
    for (const id of ids) {
      await getCourse(context, id); // an unknown course is a usage error before anything renders
      let source: Uint8Array | undefined;
      if (local) source = readFileSync(local);
      else {
        const listing = await context.client.adminCall({ routeId: "media:GET /", params: {}, query: { owner: "course", ownerId: id, kind: "hero_desktop_16x9", variant: "default" }, payload: { kind: "none" } }, (raw) => raw as { versions?: { active?: boolean; kind: string; variant: string; url: string }[] });
        const url = activeHeroUrl(listing.data.versions ?? []);
        if (!url) { failures.push(`${id} (no active hero_desktop_16x9)`); continue; }
        const response = await (context.deps.fetchPublic ?? fetch)(url);
        if (!response.ok) { failures.push(`${id} (hero HTTP ${String(response.status)})`); continue; }
        source = new Uint8Array(await response.arrayBuffer());
      }
      const og = await ogCoverFile({ path: local ?? "hero", owner: "course", position: null, kind: "hero_desktop_16x9", bytes: source.length, source });
      if (context.dryRun) { context.out.line(`${id}: ${String(Math.ceil(og.bytes / 1024))} KiB 1200×630 (not uploaded)`); continue; }
      try {
        await putCover(context, og, id, id);
        context.out.line(`${id}: link preview uploaded (${String(Math.ceil(og.bytes / 1024))} KiB)`);
      } catch (error) { failures.push(`${id} (${error instanceof Error ? error.message : "upload failed"})`); }
    }
    if (failures.length) throw new CliError(`Link preview failed for ${failures.join(", ")}; re-run for those: identical files reuse their version.`, EXIT.api);
  },
});
