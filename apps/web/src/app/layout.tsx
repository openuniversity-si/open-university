import type { Metadata, Viewport } from "next";
import { currentEnv } from "@/kernel/env.ts";
import { indexingFacts } from "@/platform/host/env.ts";
import type { ReactNode } from "react";
import { requestPreview } from "@/app/catalog-preview";
import { previewClaims } from "@/catalog/server/draft";
import { ShellCopyProvider } from "@/config/client/shell-copy.tsx";
import { parseCopy, parseTheme, servedShell } from "@/config/domain/documents.ts";
import { readServed } from "@/config/server/read.ts";
import { robotsMetadata } from "@/site/domain/indexing";
import { toMetadata } from "@/app/to-metadata";
import { siteMetadata } from "@/site/domain/metadata";
import { skipToContent } from "@/site/domain/reader-copy.ts";
import { siteData } from "@/site/server/site-data";
import { towerInter } from "@/ui/fonts";
import { TOWER_THEME_COLOR } from "@/ui/tokens/layout";
import { Footer } from "@/ui/Footer/Footer";
import { TopNav } from "@/ui/TopNav/TopNav";
import { AuthShell } from "@/ui/identity/AuthShell";
import "./globals.css";

export const metadata: Metadata = {
  ...toMetadata(siteMetadata()),
  robots: robotsMetadata(indexingFacts(currentEnv())),
};

/** Dark browser chrome and overscroll from the first paint, so nothing flashes light between screens. */
export const viewport: Viewport = {
  colorScheme: "dark",
  themeColor: TOWER_THEME_COLOR,
};

/**
 * Shell shared by every screen: skip link (D7), fixed TopNav, the page, Footer and BottomFadeScrim. A catalog preview
 * (draft mode with a valid preview cookie, ADR-18) marks the body with `data-preview`; prerenders see draft mode off.
 */
export default async function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  const theme = parseTheme(await readServed("theme"));
  const copy = parseCopy(await readServed("copy"));
  const shell = servedShell(theme, copy);
  const { preview, cookie } = await requestPreview();
  const showingPreview = preview && previewClaims(cookie) !== null;
  const page = (
    <>
      <a className="tower-skip-link t-ui-label-14-medium" href="#content" data-testid="tower-skip-link">
        {copy.skipToContent ?? skipToContent}
      </a>
      <AuthShell><TopNav labels={siteData().topNav.back} />
      <main id="content" tabIndex={-1}>
        {children}
      </main>
      <Footer links={siteData().footer.links} /></AuthShell>
    </>
  );
  return (
    <html lang="en" className={towerInter.variable}>
      <body {...(showingPreview ? { "data-preview": "true" } : {})}>
        {shell.style === "" ? null : <style dangerouslySetInnerHTML={{ __html: shell.style }} />}
        {shell.copyChanged ? <ShellCopyProvider copy={copy}>{page}</ShellCopyProvider> : page}
      </body>
    </html>
  );
}
