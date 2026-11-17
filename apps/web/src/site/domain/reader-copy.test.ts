import { describe, expect, it } from "vitest";
import {
  authorsDescription,
  authorsTitle,
  billboardFeatured,
  billboardSelected,
  continueWatchingTitle,
  continuingWithGoogle,
  creditsNote,
  fill,
  freeInOrderSuffix,
  homeTitle,
  lessonBackgroundLabel,
  lessonLabLabel,
  lessonTrailerLabel,
  metaDot,
  metaGap,
  playLecture,
  signInError,
  universitiesDescription,
  universitiesTitle,
  universityCoverKind,
} from "./reader-copy.ts";

describe("reader chrome copy", () => {
  it("keeps the measured words", () => {
    expect(continueWatchingTitle).toBe("Continue Watching");
    expect(universitiesTitle).toBe("Universities");
    expect(authorsTitle).toBe("Authors");
    expect(metaDot).toBe(" · ");
    expect(metaGap).toBe("  ·  ");
    expect(billboardSelected).toBe("Selected");
    expect(billboardFeatured).toBe("Featured");
    expect(universityCoverKind).toBe("University cover");
    expect(creditsNote).toBe("Every cover is modified for Open University: cropped, toned warm black-and-white, with a gradient and title added.");
    expect(universitiesDescription).toBe("Complete university courses from MIT, Yale, Harvard, Stanford, Carnegie Mellon and Cornell, free and in order.");
    expect(authorsDescription).toBe("Lecture series by individual scholars, complete, free and in order.");
    expect(freeInOrderSuffix).toBe(", free and in order.");
    expect(lessonBackgroundLabel).toBe("Background");
    expect(lessonTrailerLabel).toBe("Trailer");
    expect(lessonLabLabel).toBe("Lab");
    expect(homeTitle).toBe("Home");
    expect(playLecture).toBe("Play lecture");
    expect(signInError).toBe("Couldn\u2019t sign in.");
    expect(continuingWithGoogle).toBe("Continuing with Google\u2026");
    expect(fill("Account for {name}", { name: "Ada" })).toBe("Account for Ada");
    expect(fill("Account for {name}", {})).toBe("Account for {name}");
  });
});
