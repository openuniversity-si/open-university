import { CACHE } from "@/kernel/cache.ts";
import { getCatalogState } from "@tower/catalog";
import { getBuildInfo } from "@/site/server/build-info";

export const dynamic = "force-dynamic";

/** Build identity plus the catalog being served: release number, payload SHA-256 and its source (ADR-17). */
export async function GET(request: Request): Promise<Response> {
  const { catalog, sha, source } = await getCatalogState();
  const requested = new URL(request.url).searchParams.getAll("course");
  const courses = requested.map((slug) => ({ slug, present: catalog.courses.some((course) => course.slug === slug) }));
  return Response.json(
    { status: "ok", ...getBuildInfo(), catalog: { release: catalog.number, sha, source }, ...(requested.length ? { courses } : {}) },
    { status: courses.some((course) => !course.present) ? 404 : 200, headers: { "Cache-Control": CACHE.responseNoStore } },
  );
}
