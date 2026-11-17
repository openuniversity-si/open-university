import type { OEmbedResolverPort } from "../../playback/ports/oembed.ts";
import { createOEmbedResolver } from "../../playback/server/oembed-resolver.ts";
import { diffCourseBundle, exportCourseBundle, validateCourseBundle, bundleHash, type CourseBundleV1 } from "../domain/bundle.ts";
import type { HandlerContext } from "./http.ts";
import { applyCourseBundle, prepareCourseBundle } from "./bundle-apply.ts";
import type { Outcome } from "./mutation.ts";

function bundleOf(input: unknown): CourseBundleV1 {
  const parsed = validateCourseBundle(input);
  if (!parsed.ok) throw parsed.error;
  return parsed.value;
}

function resolverFor(context: HandlerContext<unknown, unknown, { bundle: unknown; replayKey?: string }>): OEmbedResolverPort {
  return createOEmbedResolver({
    now: context.deps.now,
    transport: async (identity) => {
      const result = await context.deps.oembed(identity.externalId);
      const verifiedAt = context.deps.now().toISOString();
      if (result.status === "ok") return { status: "resolved", verifiedAt, ...(result.title ? { title: result.title } : {}), ...(result.authorName ? { authorName: result.authorName } : {}) };
      if (result.status === "embed-disabled") return { status: "unsupported", verifiedAt };
      return { status: "unavailable", verifiedAt };
    },
  });
}

export function validateBundle(context: HandlerContext<unknown, unknown, { bundle: unknown }>): Promise<Outcome> {
  const bundle = bundleOf(context.body.bundle);
  return Promise.resolve({ data: { hash: bundleHash(bundle), version: bundle.version } });
}

export function diffBundle(context: HandlerContext<unknown, unknown, { bundle: unknown; current?: unknown }>): Promise<Outcome> {
  const next = bundleOf(context.body.bundle);
  const current = context.body.current === undefined ? null : bundleOf(context.body.current);
  return Promise.resolve({ data: diffCourseBundle(current, next) });
}

export function exportBundle(context: HandlerContext<unknown, unknown, { bundle: unknown }>): Promise<Outcome> {
  return Promise.resolve({ data: { bundle: exportCourseBundle(bundleOf(context.body.bundle)) } });
}

export async function applyBundle(context: HandlerContext<unknown, unknown, { bundle: unknown; replayKey?: string }>): Promise<Outcome> {
  const bundle = bundleOf(context.body.bundle);
  const prepared = await prepareCourseBundle(bundle, { resolver: resolverFor(context), now: context.deps.now });
  return context.mutate((tx) => applyCourseBundle(prepared, { uow: tx, actor: context.actor, requestId: context.requestId, replayKey: context.body.replayKey ?? null }));
}
