import { CACHE } from "@/kernel/cache.ts";
import { LessonView, lessonViewMetadata } from "./view";

/** Signed-out lesson page, static (ISR on first visit, kept until a release activation). A session cookie or `?t=` is rewritten to /signed-in-c by proxy.ts. */
export const revalidate = false satisfies typeof CACHE.untilTagged;
export const dynamicParams = true;
export function generateStaticParams(): { courseSlug: string; lessonSlug: string }[] { return []; }

export const generateMetadata = lessonViewMetadata;

export default async function PlayerPage({ params }: { readonly params: Promise<{ courseSlug: string; lessonSlug: string }> }) {
  const { courseSlug, lessonSlug } = await params;
  return <LessonView courseSlug={courseSlug} lessonSlug={lessonSlug} t={undefined} viewerProgress={null} />;
}
