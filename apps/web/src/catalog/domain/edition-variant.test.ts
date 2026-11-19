import { describe, expect, it } from "vitest";
import { columnsToVariant, editionLanguageProblems, indistinctEditionMessage, indistinctEditions, offeringKey } from "./edition-variant.ts";

// Verifies: D-035
const edition = (id: string, year: number | null, variant?: { kind: string; label: string } | null) => ({ id, year, variant });

describe("edition variant (D-034)", () => {
  it("D-034: two editions of one year fail unless the variant differs", () => {
    const same = indistinctEditions([
      edition("it", 2024, null),
      edition("en", 2024),
    ]);
    expect(same).toEqual([{ year: 2024, ids: ["it", "en"] }]);
    expect(indistinctEditionMessage(2024, ["it", "en"])).toBe("Editions it, en share the year 2024 without a distinct variant.");
    expect(indistinctEditions([
      edition("it", 2024, { kind: "language", label: "Italiano" }),
      edition("en", 2024, { kind: "language", label: "English" }),
    ])).toEqual([]);
    expect(indistinctEditions([
      edition("ss", 2024, { kind: "term", label: "SS" }),
      edition("ws", 2024, { kind: "term", label: "WS" }),
    ])).toEqual([]);
    expect(indistinctEditions([
      edition("room", 2024, { kind: "group", label: "presencial" }),
      edition("blend", 2024, { kind: "group", label: "semipresencial" }),
    ])).toEqual([]);
    expect(indistinctEditions([
      edition("a", 2024, { kind: "language", label: "Italiano" }),
      edition("b", 2024, { kind: "language", label: "Italiano" }),
    ])).toEqual([{ year: 2024, ids: ["a", "b"] }]);
    expect(indistinctEditions([
      edition("a", 2024, { kind: "language", label: "SS" }),
      edition("b", 2024, { kind: "term", label: "SS" }),
    ])).toEqual([]);
    expect(indistinctEditions([edition("a", 2024), edition("b", 2025)])).toEqual([]);
    expect(indistinctEditions([edition("a", null), edition("b", null)])).toEqual([]);
    expect(offeringKey(2024, null)).toBe(offeringKey(2024, undefined));
    expect(columnsToVariant(null, null)).toBeNull();
    expect(columnsToVariant("language", "Italiano")).toEqual({ kind: "language", label: "Italiano" });
    expect(columnsToVariant("season", "fall")).toBeNull();
    expect(columnsToVariant("language", null)).toBeNull();
  });

  it("D-035: the course language is the default edition language", () => {
    const english = { id: "en", position: 1, language: "English", variant: { kind: "language", label: "English" } };
    const italian = { id: "it", position: 2, language: "Italiano", variant: { kind: "language", label: "Italiano" } };
    expect(editionLanguageProblems("English", [italian, english])).toEqual([]);
    expect(editionLanguageProblems("English", [{ id: "en", position: 1, language: "Italiano" }])).toEqual([
      "The course language is English; its default edition is Italiano.",
    ]);
    expect(editionLanguageProblems("English", [{ id: "en", position: 1 }])).toEqual([
      "The course language is English; its default edition has none.",
    ]);
    expect(editionLanguageProblems(undefined, [{ id: "en", position: 1, language: "English" }])).toEqual([]);
    expect(editionLanguageProblems("English", [{ id: "ss", position: 1, language: "English", variant: { kind: "term", label: "SS" } }])).toEqual([]);
    expect(editionLanguageProblems(undefined, [{ id: "it", position: 1, variant: { kind: "language", label: "Italiano" } }])).toEqual([
      "Edition it names a language variant without edition.language.",
    ]);
    expect(editionLanguageProblems(undefined, [{ id: "it", position: 1, language: "English", variant: { kind: "language", label: "Italiano" } }])).toEqual([
      "Edition it language variant is Italiano; edition.language is English.",
    ]);
  });
});
