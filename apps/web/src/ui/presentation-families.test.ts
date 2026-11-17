import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const here = dirname(fileURLToPath(import.meta.url));
const source = (path: string) => readFileSync(join(here, path), "utf8");

/** Showcase modules that paint a view. The assemblers stay beside them and are not this list. */
const SHOWCASE_PAINT = [
  "Billboard/Billboard.tsx",
  "Billboard/BillboardSelection.tsx",
  "HomePortals/HomePortals.tsx",
  "HomeIntro/HomeIntro.tsx",
  "CourseCard/CourseCard.tsx",
  "CourseCardSkeleton/CourseCardSkeleton.tsx",
  "Universities/UniversitiesShowcase.tsx",
  "Universities/UniversityRails.tsx",
  "CountrySection/CountrySection.tsx",
  "CourseAbout/CourseAbout.tsx",
  "EditionSelector/EditionSelector.tsx",
  "Rail/Rail.tsx",
  "RailHeader/RailHeader.tsx",
  "CreditsList/CreditsList.tsx",
  "LazyPoster/LazyPoster.tsx",
  "PlaylistItem/CoursePlaylist.tsx",
  "showcase/AreaGrid.tsx",
] as const;

/** Player modules that paint a gesture the page already chose. */
const PLAYER_PAINT = [
  "playback/PlayerFrame.tsx",
  "playback/PlayerControls.tsx",
  "playback/usePlayback.ts",
  "playback/PlayerRail.tsx",
  "playback/CompletionToggle.tsx",
  "playback/LectureAbout.tsx",
  "playback/LecturesAnchor.tsx",
] as const;

const CATALOG_FACTS = ["catalog/domain/home", "catalog/domain/universities", "catalog/domain/view-model"] as const;

/** The shell the visitor meets: navigation, footer, legal page, missing path, error, and the layout skip link. */
const SHELL_PAINT = [
  "TopNav/TopNav.tsx",
  "Footer/Footer.tsx",
  "LegalPage/LegalPage.tsx",
  "../app/not-found.tsx",
  "../app/error.tsx",
  "../app/layout.tsx",
] as const;

describe("presentation families", () => {
  it("names the showcase and keeps it from importing the player domain", () => {
    expect(SHOWCASE_PAINT).toContain("Billboard/Billboard.tsx");
    expect(SHOWCASE_PAINT).toContain("PlaylistItem/CoursePlaylist.tsx");
    for (const path of SHOWCASE_PAINT) expect(source(path), path).not.toContain("playback/domain");
  });

  it("names the player and keeps it from importing a catalog fact", () => {
    expect(PLAYER_PAINT).toContain("playback/PlayerFrame.tsx");
    expect(PLAYER_PAINT).toContain("playback/PlayerRail.tsx");
    for (const path of PLAYER_PAINT) {
      const text = source(path);
      for (const fact of CATALOG_FACTS) expect(text, `${path} ${fact}`).not.toContain(fact);
    }
  });

  it("names the shell and keeps it from drawing site health", () => {
    expect(SHELL_PAINT).toContain("TopNav/TopNav.tsx");
    expect(SHELL_PAINT).toContain("../app/layout.tsx");
    for (const path of ["TopNav/TopNav.tsx", "Footer/Footer.tsx", "LegalPage/LegalPage.tsx"]) {
      const text = source(path);
      for (const fact of CATALOG_FACTS) expect(text, `${path} ${fact}`).not.toContain(fact);
    }
    for (const path of SHELL_PAINT) expect(source(path), path).not.toContain("site-health");
    const layout = source("../app/layout.tsx");
    expect(layout).toContain("servedShell");
    expect(layout).toContain('shell.style === ""');
    expect(layout).toContain('data-testid="tower-skip-link"');
    expect(layout).toContain("skipToContent");
    expect(layout).toContain("AuthShell");
    expect(source("../app/not-found.tsx")).toContain("notFoundTitle");
    expect(source("../app/about/page.tsx")).toContain('staticPageMetadata("/about")');
    expect(source("../app/privacy/page.tsx")).toContain('staticPageMetadata("/privacy")');
    expect(source("../app/terms/page.tsx")).toContain('staticPageMetadata("/terms")');
    const credits = source("../app/credits/page.tsx");
    expect(credits).toContain("CREDITS_NOTE");
    expect(credits).toContain("LegalPage");
    expect(credits).toContain("CreditsList");
    expect(source("LegalPage/LegalPage.tsx")).not.toContain("CreditsList");
    expect(source("CreditsList/CreditsList.tsx")).not.toContain("LegalPage");
  });
});
