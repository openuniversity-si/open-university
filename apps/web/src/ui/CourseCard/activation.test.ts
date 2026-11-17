import { describe, expect, it } from "vitest";
import { shouldSelectCard } from "./activation.ts";

const click = { button: 0, ctrlKey: false, metaKey: false, shiftKey: false, altKey: false };

describe("CourseCard activation (Spec 07)", () => {
  it("selects on the first ordinary activation and navigates on the second", () => {
    expect(shouldSelectCard(click, false)).toBe(true);
    expect(shouldSelectCard(click, true)).toBe(false);
  });
  it.each(["ctrlKey", "metaKey", "shiftKey", "altKey"] as const)("preserves native %s activation", (key) => {
    expect(shouldSelectCard({ ...click, [key]: true }, false)).toBe(false);
  });
  it("preserves middle and secondary activation", () => {
    expect(shouldSelectCard({ ...click, button: 1 }, false)).toBe(false);
    expect(shouldSelectCard({ ...click, button: 2 }, false)).toBe(false);
  });
});
