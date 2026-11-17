import type { Metadata } from "next";
import { toMetadata } from "@/app/to-metadata";
import { staticPageMetadata } from "@/site/domain/metadata";
import { siteData } from "@/site/server/site-data";
import { LegalPage } from "@/ui/LegalPage/LegalPage";
import { PrimaryCTA } from "@/ui/PrimaryCTA/PrimaryCTA";

export const metadata: Metadata = toMetadata(staticPageMetadata("/about"));

export default function AboutPage() {
  const about = siteData().pages.about;
  return <LegalPage page={about} action={<PrimaryCTA href={about.cta.href}>{about.cta.label}</PrimaryCTA>} variant="about" />;
}
