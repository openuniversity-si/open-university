import type { Metadata } from "next";
import { headers } from "next/headers";
import { LessonView, lessonViewMetadata } from "@/app/c/[courseSlug]/[lessonSlug]/view";
import { getViewerProgress } from "@/progress/server/viewer";

/** /c/[courseSlug]/[lessonSlug] with a session cookie or `?t=` (proxy.ts rewrite, ADR-16); per request, so never cached. */
export const dynamic = "force-dynamic";

export async function generateMetadata(props: { readonly params: Promise<{ courseSlug: string; lessonSlug: string }> }): Promise<Metadata> {
  return { ...(await lessonViewMetadata(props)), robots: { index: false, follow: false } };
}

export default async function SignedInPlayerPage({ params, searchParams }: {
  readonly params: Promise<{ courseSlug: string; lessonSlug: string }>;
  readonly searchParams: Promise<{ t?: string | string[] }>;
}) {
  const [{ courseSlug, lessonSlug }, { t }] = await Promise.all([params, searchParams]);
  return <LessonView courseSlug={courseSlug} lessonSlug={lessonSlug} t={t} viewerProgress={await getViewerProgress(await headers())} />;
}
