import { CACHE } from "@/kernel/cache.ts";
import { CourseView, courseViewMetadata } from "./view";

/** Signed-out course page, static (ISR on first visit, kept until a release activation). A session cookie is rewritten to /signed-in-c by proxy.ts. */
export const revalidate = false satisfies typeof CACHE.untilTagged;
export const dynamicParams = true;
export function generateStaticParams(): { courseSlug: string }[] { return []; }

export const generateMetadata = courseViewMetadata;

export default async function CoursePage({ params }: { readonly params: Promise<{ courseSlug: string }> }) {
  return <CourseView courseSlug={(await params).courseSlug} viewerProgress={null} />;
}
