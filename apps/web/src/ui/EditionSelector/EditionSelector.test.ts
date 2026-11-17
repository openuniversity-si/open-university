import { describe, expect, it } from "vitest";
import { editionFromSearch, urlWithEdition } from "./EditionScope";
import { nextTab } from "./EditionSelector";
import { editionPanelId, editionTabId } from "./ids";

const slugs = ["spring-2025", "fall-2024", "2023"];

describe("EditionSelector (ADR-21)", () => {
  it("moves with the arrow keys, wrapping, and jumps with Home/End", () => {
    expect([nextTab("ArrowRight", 0, 3), nextTab("ArrowDown", 2, 3), nextTab("ArrowLeft", 0, 3), nextTab("ArrowUp", 1, 3)]).toEqual([1, 0, 2, 0]);
    expect([nextTab("Home", 2, 3), nextTab("End", 0, 3), nextTab("Enter", 0, 3), nextTab("a", 1, 3)]).toEqual([0, 2, null, null]);
    expect([editionTabId("fall-2024"), editionPanelId("fall-2024")]).toEqual(["edition-tab-fall-2024", "edition-panel-fall-2024"]);
  });

  it("reads ?edition= only for another known edition, and writes it only for a non-default one", () => {
    expect(editionFromSearch("?edition=fall-2024", slugs)).toBe("fall-2024");
    expect(editionFromSearch("?edition=spring-2025", slugs)).toBeNull();
    expect(editionFromSearch("?edition=1999", slugs)).toBeNull();
    expect(editionFromSearch("", slugs)).toBeNull();
    expect(urlWithEdition("https://www.thetower.si/c/x?y=1#top", "2023", slugs)).toBe("/c/x?y=1&edition=2023#top");
    expect(urlWithEdition("https://www.thetower.si/c/x?edition=2023", "spring-2025", slugs)).toBe("/c/x");
  });
});
