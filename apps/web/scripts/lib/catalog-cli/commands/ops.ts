import { relative, resolve } from "node:path";
import { writeSnapshot } from "../../catalog-export.ts";
import { requireOption, stringOption } from "../args.ts";
import type { CommandSpec } from "../context.ts";
import { CliError, EXIT, UsageError } from "../errors.ts";
import { table } from "../render.ts";
import { getCourse, listAllCourses } from "./shared.ts";

const SEVERITIES = ["error", "warning", "info"] as const;

export const opsCommands: CommandSpec[] = [
  {
    name: "doctor", usage: "doctor", summary: "the consistency report by severity; exit 1 if any error", options: {}, positionals: { min: 0, max: 0 }, routes: ["GET /doctor"],
    async run(context) {
      const result = await context.client.call("GET /doctor");
      const { data } = result;
      context.out.line(`Doctor: ${data.ok ? "ok" : "ERRORS"} · active release #${String(data.activeRelease?.number ?? "none")} ${data.activeRelease?.sha.slice(0, 12) ?? ""}`.trimEnd());
      for (const severity of SEVERITIES) {
        const findings = data.findings.filter((finding) => finding.severity === severity);
        if (findings.length === 0) continue;
        context.out.line(`${severity} (${String(findings.length)}):`);
        for (const finding of findings) context.out.line(`  ${finding.code} ×${String(finding.count)}: ${finding.message}${finding.sample.length ? ` e.g. ${JSON.stringify(finding.sample.slice(0, 3))}` : ""}`);
      }
      if (data.findings.length === 0) context.out.line("No findings.");
      context.out.result(result.envelope);
      if (!data.ok) throw new CliError("The doctor found errors.", EXIT.api);
    },
  },
  {
    name: "check", usage: "check --embeds [<course>]", summary: "manual oEmbed check of every YouTube video (a course, or all published); never scheduled",
    options: { embeds: { type: "boolean", required: true, help: "check YouTube embeds with oEmbed" }, pause: { type: "string", help: "milliseconds between videos (default 1000)", value: "<ms>" } },
    positionals: { min: 0, max: 1 }, routes: ["GET /courses", "GET /courses/:id"],
    async run(context) {
      const pause = Number(stringOption(context.args, "pause") ?? "1000");
      if (!Number.isInteger(pause) || pause < 0) throw new UsageError("--pause must be milliseconds ≥ 0.");
      const one = context.args.positionals[0];
      const ids = one !== undefined ? [one] : (await listAllCourses(context, { status: "published" })).map((course) => course.id);
      const rows: string[][] = [];
      const report: { courseId: string; lessonId: string; youtubeId: string; recorded: string; oembed: string }[] = [];
      let first = true;
      for (const id of ids) {
        const detail = await getCourse(context, id);
        for (const lesson of detail.lessons) {
          for (const video of lesson.videos.filter((entry) => entry.provider === "youtube")) {
            if (!first) await context.deps.sleep(pause);
            first = false;
            let status: string;
            try { status = (await context.deps.oembed(video.externalId)).status; } catch (error) { status = `failed (${error instanceof Error ? error.message : "network"})`; }
            rows.push([id, lesson.id, video.externalId, video.status, status]);
            report.push({ courseId: id, lessonId: lesson.id, youtubeId: video.externalId, recorded: video.status, oembed: status });
          }
        }
      }
      const bad = report.filter((entry) => entry.oembed !== "ok");
      context.out.lines([...table(["course", "lesson", "youtube", "recorded", "oembed"], rows), `${String(report.length - bad.length)}/${String(report.length)} embeds ok.`,
        "Report only: the admin API has no route that records oEmbed results; publish re-checks videos older than 7 days, and a lesson can be hidden with lesson set --visible false."]);
      const message = `${String(bad.length)} embed(s) not ok.`;
      context.out.result(bad.length === 0 ? { ok: true, data: { videos: report } } : { ok: false, error: { code: "embeds_not_ok", message, details: { videos: report } } });
      if (bad.length) throw new CliError(message, EXIT.api);
    },
  },
  {
    name: "snapshot", usage: "snapshot --dir <path>", summary: "export the active release and tables outside git (2× = no diff)",
    options: { dir: { type: "string", required: true, help: "output directory outside git", value: "<path>" } },
    positionals: { min: 0, max: 0 }, routes: ["GET /tables", "GET /releases/:n"],
    async run(context) {
      const directory = resolve(requireOption(context.args, "dir"));
      const exported = await context.client.call("GET /tables");
      const active = exported.data.activeRelease;
      if (active === null) throw new CliError("There is no active release to snapshot.", EXIT.api);
      const release = (await context.client.call("GET /releases/:n", { params: { n: String(active.number) } })).data.release;
      if (release.sha !== active.sha) throw new CliError(`Release #${String(active.number)} changed between reads; run snapshot again.`, EXIT.conflict);
      const changed = writeSnapshot(directory, release.payload, exported.data.tables);
      context.out.line(`Snapshot of release #${String(active.number)} (sha256 ${active.sha.slice(0, 12)}) in ${relative(process.cwd(), directory) || "."}: ${changed.length ? `${String(changed.length)} file(s) changed (${changed.join(", ")})` : "no change"}.`);
      context.out.result({ ok: true, data: { release: active, directory, changed } });

    },
  },
];
