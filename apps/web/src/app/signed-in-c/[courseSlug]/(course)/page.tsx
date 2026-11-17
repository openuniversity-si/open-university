import type { Metadata } from "next";
import { headers } from "next/headers";
import { CourseView, courseViewMetadata } from "@/app/c/[courseSlug]/(course)/view";
import { getViewerProgress } from "@/progress/server/viewer";

/** /c/[courseSlug] for a request with a session cookie (proxy.ts rewrite, ADR-16); per viewer, so never cached. */
export const dynamic = "force-dynamic";

export async function generateMetadata(props: { readonly params: Promise<{ courseSlug: string }> }): Promise<Metadata> {
  return { ...(await courseViewMetadata(props)), robots: { index: false, follow: false } };
}

export default async function SignedInCoursePage({ params }: { readonly params: Promise<{ courseSlug: string }> }) {
  return <CourseView courseSlug={(await params).courseSlug} viewerProgress={await getViewerProgress(await headers())} />;
}
