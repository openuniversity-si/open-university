import { writeFileSync } from "node:fs";
import { bundleHash, validateCourseBundle } from "../../../../src/catalog/domain/bundle.ts";
import { parseJsonFile, type CommandSpec, type Context } from "../context.ts";
import { UsageError } from "../errors.ts";
import { requireOption, stringOption } from "../args.ts";

function loadBundle(context: Context, name = "file") {
  const parsed = validateCourseBundle(parseJsonFile(context, requireOption(context.args, name)));
  if (!parsed.ok) throw new UsageError(parsed.error.message);
  return parsed.value;
}

export const bundleCommands: CommandSpec[] = [
  {
    name: "bundle validate", usage: "bundle validate --file <bundle.json>", summary: "validate a CourseBundleV1 locally and on the admin API",
    options: { file: { type: "string", required: true, help: "CourseBundleV1 JSON", value: "<path>" } }, positionals: { min: 0, max: 0 }, routes: ["POST /bundles/validate"],
    async run(context) {
      const bundle = loadBundle(context);
      const result = await context.client.call("POST /bundles/validate", { body: { bundle } });
      const data = result.data as { hash?: string };
      context.out.line(`${bundle.course.id} ${data.hash ?? bundleHash(bundle)}`);
      context.out.result(result.envelope);
    },
  },
  {
    name: "bundle diff", usage: "bundle diff --file <next.json> [--current <previous.json>]", summary: "diff two bundles; omitted lessons are not deletions",
    options: {
      file: { type: "string", required: true, help: "next CourseBundleV1", value: "<path>" },
      current: { type: "string", help: "previous CourseBundleV1", value: "<path>" },
    },
    positionals: { min: 0, max: 0 }, routes: ["POST /bundles/diff"],
    async run(context) {
      const bundle = loadBundle(context);
      const currentPath = stringOption(context.args, "current");
      const current = currentPath === undefined ? undefined : loadBundle(context, "current");
      const result = await context.client.call("POST /bundles/diff", { body: { bundle, ...(current ? { current } : {}) } });
      const data = result.data as { empty?: boolean };
      context.out.line(data.empty === true ? "empty" : "changed");
      context.out.result(result.envelope);
    },
  },
  {
    name: "bundle apply", usage: "bundle apply --file <bundle.json>", summary: "apply a validated bundle in one transaction; it does not publish",
    options: { file: { type: "string", required: true, help: "CourseBundleV1 JSON", value: "<path>" } }, positionals: { min: 0, max: 0 }, routes: ["POST /bundles/apply"],
    async run(context) {
      const bundle = loadBundle(context);
      await context.confirm(`Apply bundle ${bundle.course.id} (${bundleHash(bundle).slice(0, 12)})`);
      const result = await context.client.call("POST /bundles/apply", { body: { bundle } });
      const data = result.data as { applied?: boolean };
      context.out.line(`${bundle.course.id} applied=${String(data.applied ?? true)}`);
      context.out.result(result.envelope);
    },
  },
  {
    name: "bundle export", usage: "bundle export --file <bundle.json> [--out <path>]", summary: "export a normalized bundle with the same ids",
    options: {
      file: { type: "string", required: true, help: "CourseBundleV1 JSON", value: "<path>" },
      out: { type: "string", help: "write the normalized bundle here", value: "<path>" },
    },
    positionals: { min: 0, max: 0 }, routes: ["POST /bundles/export"],
    async run(context) {
      const bundle = loadBundle(context);
      const result = await context.client.call("POST /bundles/export", { body: { bundle } });
      const data = result.data as { bundle?: unknown };
      const exported = data.bundle ?? bundle;
      const out = stringOption(context.args, "out");
      if (out) writeFileSync(out, JSON.stringify(exported, null, 2));
      context.out.line(bundle.course.id);
      context.out.result(result.envelope);
    },
  },
];
