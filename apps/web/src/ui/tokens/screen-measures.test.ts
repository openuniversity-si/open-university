import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const root = new URL("../../..", import.meta.url);
const snapshot = JSON.parse(readFileSync(new URL("design/figma-tokens.snapshot.json", root), "utf8")) as {
  readonly variables: Readonly<Record<string, { readonly value: string }>>;
};
const catalog = new Set(Object.values(snapshot.variables).map((token) => token.value));

/** A length inside a media or supports condition. Declarations stay out: only the condition cannot call var(). */
function conditionLengths(css: string): string[] {
  const withoutComments = css.replace(/\/\*[\s\S]*?\*\//g, "");
  const found: string[] = [];
  for (const match of withoutComments.matchAll(/@(?:media|supports)\b([^{]*)\{/g)) {
    const condition = match[1] ?? "";
    for (const length of condition.matchAll(/(?<![.\w])-?\d+(?:\.\d+)?(?:px|vw|vh|dvh|svh|dvw|svw|rem|em|%)/g)) found.push(length[0]);
  }
  return found;
}

function outsideCatalog(lengths: readonly string[]): string[] {
  return lengths.filter((length) => !catalog.has(length));
}

function source(path: string): string {
  return readFileSync(new URL(path, root), "utf8");
}

/** Screen CSS from the measure table. A @media length may stay only when it equals a catalog value. */
const SCREEN_CSS = [
  "src/app/globals.css",
  "src/app/not-found.module.css",
  "src/ui/glass.css",
  "src/ui/Billboard/Billboard.module.css",
  "src/ui/Footer/Footer.module.css",
  "src/ui/TopNav/TopNav.module.css",
  "src/ui/HomeIntro/HomeIntro.module.css",
  "src/ui/HomePortals/HomePortals.module.css",
  "src/ui/LegalPage/LegalPage.module.css",
  "src/ui/playback/PlayerFrame.module.css",
  "src/ui/PrimaryCTA/PrimaryCTA.module.css",
  "src/ui/Rail/Rail.module.css",
  "src/ui/Universities/Universities.module.css",
  "src/app/c/[courseSlug]/(course)/page.module.css",
  "src/app/c/[courseSlug]/[lessonSlug]/page.module.css",
  "src/app/status.module.css",
  "src/ui/Billboard/BillboardSelection.module.css",
  "src/ui/CountrySection/CountrySection.module.css",
  "src/ui/CourseCard/CourseCard.module.css",
  "src/ui/CourseCardSkeleton/CourseCardSkeleton.module.css",
  "src/ui/CoverPlayButton/CoverPlayButton.module.css",
  "src/ui/CreditsList/CreditsList.module.css",
  "src/ui/EditionSelector/EditionSelector.module.css",
  "src/ui/EmptyCatalog/EmptyCatalog.module.css",
  "src/ui/focus.css",
  "src/ui/playback/LectureAbout.module.css",
  "src/ui/playback/PlayerRail.module.css",
  "src/ui/PlaylistItem/CoursePlaylist.module.css",
  "src/ui/lesson-row/CourseProgress.module.css",
  "src/ui/RailHeader/RailHeader.module.css",
  "src/ui/identity/AccountMenu.module.css",
  "src/ui/identity/ContinuingWithGoogle.module.css",
  "src/ui/identity/SignInFeedback.module.css",
] as const;

const CALL_SITES = [
  "src/app/c/[courseSlug]/[lessonSlug]/view.tsx",
  "src/app/c/[courseSlug]/(course)/view.tsx",
  "src/ui/Billboard/Billboard.tsx",
  "src/ui/LazyPoster/near.ts",
  "src/ui/tokens/layout.ts",
] as const;

const SPELLED = ["1024px", "96px", "476px", "200px", "100vw"] as const;

describe("D-050 screen measures", () => {
  it("D-050: a screen length outside the catalog is refused", () => {
    expect(outsideCatalog(conditionLengths("@media (width >= 900px) { .x { width: 1px; } }"))).toEqual(["900px"]);
    expect(outsideCatalog(conditionLengths("@media (width >= 1024px) { .x {} }"))).toEqual([]);
    for (const file of SCREEN_CSS) {
      expect(outsideCatalog(conditionLengths(source(file))), file).toEqual([]);
    }
    for (const file of CALL_SITES) {
      const text = source(file);
      for (const spelling of SPELLED) expect(text, `${file} ${spelling}`).not.toContain(spelling);
    }
    expect(source("src/app/globals.css")).toContain("min-height: var(--tower-viewport-dynamic)");
    expect(source("src/app/globals.css")).not.toContain("100dvh");
    expect(source("src/app/not-found.module.css")).toContain("var(--tower-viewport-small)");
    expect(source("src/app/not-found.module.css")).not.toContain("100svh");
  });
});
