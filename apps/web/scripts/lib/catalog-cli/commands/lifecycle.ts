import { buildCrossEnvironmentInventory, markOrExecuteMediaGc } from "../../../../src/media/domain/figure-exit.ts";
import type { LifecycleDeps, LifecycleEnvironment, LifecycleJobs, LifecycleStorage, StoragePage } from "../../../../src/media/domain/figure-ports.ts";
import type { ApiClient } from "../client.ts";
import type { CommandSpec, Context } from "../context.ts";
import { UsageError } from "../errors.ts";

function unavailable(name: "prod" | "preview"): LifecycleEnvironment {
  return {
    name,
    listInventory: () => Promise.resolve({ environment: name, complete: false, references: [] }),
    markOrphan: () => Promise.resolve("referenced"),
    clearOrphan: () => Promise.resolve(),
    barrier: () => Promise.resolve(false),
    revalidate: () => Promise.resolve(false),
    snapshot: () => Promise.resolve(null),
    restore: () => Promise.resolve(false),
    reset: () => Promise.resolve(false),
    rehearse: () => Promise.resolve(false),
    deleteRow: () => Promise.resolve(false),
  };
}

function httpEnvironment(client: ApiClient, name: "prod" | "preview"): LifecycleEnvironment {
  return {
    name,
    async listInventory() {
      const result = await client.call("POST /lifecycle/inventory", {});
      const data = result.data as { environment?: string; complete?: boolean; references?: [] };
      return { environment: name, complete: data.complete === true && data.environment === name, references: data.references ?? [] };
    },
    async markOrphan(sha256) {
      const result = await client.call("POST /lifecycle/gc", { body: { op: "mark", sha256 } });
      const status = (result.data as { status?: string }).status;
      return status === "marked" || status === "already" ? status : "referenced";
    },
    async clearOrphan(sha256) { await client.call("POST /lifecycle/gc", { body: { op: "clear", sha256 } }); },
    async barrier() { return ((await client.call("POST /lifecycle/gc", { body: { op: "barrier" } })).data as { ok?: boolean }).ok === true; },
    async revalidate() { return ((await client.call("POST /lifecycle/gc", { body: { op: "revalidate" } })).data as { ok?: boolean }).ok === true; },
    snapshot: () => Promise.resolve(null),
    restore: () => Promise.resolve(false),
    reset: () => Promise.resolve(false),
    rehearse: () => Promise.resolve(false),
    async deleteRow(sha256) { return ((await client.call("POST /lifecycle/gc", { body: { op: "delete-row", sha256 } })).data as { deleted?: boolean }).deleted === true; },
  };
}

function httpStorage(client: ApiClient): LifecycleStorage {
  return {
    async list(cursor) {
      const result = await client.call("POST /lifecycle/gc", { body: { op: "storage-list", cursor } });
      const data = result.data as Partial<StoragePage>;
      return { keys: data.keys ?? [], cursor: data.cursor ?? null, complete: data.complete === true };
    },
    async copyAside(sha256) { return ((await client.call("POST /lifecycle/gc", { body: { op: "copy-aside", sha256 } })).data as { ok?: boolean }).ok === true; },
    async remove(sha256) { return ((await client.call("POST /lifecycle/gc", { body: { op: "remove", sha256 } })).data as { ok?: boolean }).ok === true; },
    async exists(sha256) { return ((await client.call("POST /lifecycle/gc", { body: { op: "exists", sha256 } })).data as { present?: boolean }).present === true; },
  };
}

function memoryJobs(): LifecycleJobs {
  const receipts: string[] = [];
  return {
    claim: () => Promise.resolve({ acquired: true, token: "lifecycle" }),
    receipt: (_token, sha256) => { receipts.push(sha256); return Promise.resolve(); },
    complete: () => Promise.resolve(),
  };
}

function depsFor(context: Context): LifecycleDeps {
  let prod = unavailable("prod");
  let preview = unavailable("preview");
  if (context.target === "prod") prod = httpEnvironment(context.client, "prod");
  else preview = httpEnvironment(context.client, "preview");
  try {
    const peer = context.peers()[0]?.client;
    if (peer && context.target === "prod") preview = httpEnvironment(peer, "preview");
    if (peer && context.target !== "prod") prod = httpEnvironment(peer, "prod");
  } catch { /* a missing peer keeps the inventory incomplete and blocks mark/apply */ }
  return { environments: ["prod", "preview"], now: context.deps.now, ports: { prod, preview }, storage: httpStorage(context.client), jobs: memoryJobs() };
}

function modeOf(context: Context): "dry-run" | "mark" | "apply" {
  const mark = context.args.options.mark === true;
  const apply = context.args.options.apply === true;
  if (mark && apply) throw new UsageError("Pass only one of --mark or --apply.");
  if (apply) return "apply";
  if (mark) return "mark";
  return "dry-run";
}

export const lifecycleCommands: CommandSpec[] = [
  {
    name: "lifecycle inventory",
    usage: "lifecycle inventory",
    summary: "read the cross-environment media inventory; a failed source stays incomplete",
    options: {},
    positionals: { min: 0, max: 0 },
    routes: ["POST /lifecycle/inventory", "POST /lifecycle/gc"],
    async run(context) {
      const report = await buildCrossEnvironmentInventory(depsFor(context));
      context.out.line(`Inventory ${report.generation.slice(0, 12)} complete=${String(report.complete)} refs=${String(report.references.length)}`);
    },
  },
  {
    name: "lifecycle gc",
    usage: "lifecycle gc [--mark|--apply]",
    summary: "dry-run, mark or apply media retention; apply stays closed unless every source is complete",
    options: {
      mark: { type: "boolean", help: "set orphaned_at without deleting bytes" },
      apply: { type: "boolean", help: "delete bytes that have been unmarked for 30 days" },
    },
    positionals: { min: 0, max: 0 },
    routes: ["POST /lifecycle/inventory", "POST /lifecycle/gc"],
    async run(context) {
      const mode = modeOf(context);
      if (mode === "apply") await context.confirm("Apply media retention deletes bytes", true);
      const report = await markOrExecuteMediaGc(depsFor(context), { mode });
      context.out.line(`GC ${report.generation.slice(0, 12)} marked=${String(report.marked)} deleted=${String(report.deleted)} skipped=${String(report.skipped)}`);
    },
  },
  {
    name: "lifecycle preview-reset",
    usage: "lifecycle preview-reset [--apply]",
    summary: "reset preview only after a verified snapshot; production is rejected",
    options: { apply: { type: "boolean", help: "clear the preview deletion queue after the snapshot rehearses" } },
    positionals: { min: 0, max: 0 },
    routes: ["POST /lifecycle/preview-reset"],
    async run(context) {
      if (context.target === "prod") throw new UsageError("Production preview reset is rejected.");
      const apply = context.args.options.apply === true;
      if (apply) await context.confirm("Reset the preview environment", true);
      const result = await context.client.call("POST /lifecycle/preview-reset", { body: { dryRun: !apply } });
      const report = result.data as { verified?: boolean; snapshotId?: string | null };
      context.out.line(`Preview reset verified=${String(report.verified === true)} snapshot=${report.snapshotId ?? "none"}`);
    },
  },
];
