import { universityCourseCount, type University } from "./universities.ts";

/**
 * Universities grouped by country (Daniel 17/10/2026; Figma CountryHeader 655:3545, live frames 622:2813 / 622:3121).
 * The countries, their names and their order are data: `rank` is the only hierarchy (1 first), never a visual tier.
 * A university belongs to the country its release `place` ends with ("Cambridge, MA" -> a U.S. state code;
 * "Oxford, United Kingdom" -> the United Kingdom; "Chennai, India" -> "India"). Adding a country is a matter of
 * publishing universities whose place ends with one of its `placeEndings`; no code change. A country with no published
 * university is not shown.
 */
export interface Country {
  readonly id: string;
  readonly name: string;
  readonly rank: number;
  /** The last comma-separated part of a university's place that puts it in this country (case-insensitive). */
  readonly placeEndings: readonly string[];
}

export interface CountryGroup {
  /** null: universities whose place names no configured country; shown last, without a flag, never hidden. */
  readonly country: Country | null;
  readonly universities: readonly University[];
  /** Published universities in the group. */
  readonly universityCount: number;
  /** Published courses in the group, each course once. */
  readonly courseCount: number;
}

export function countryOf(place: string, countries: readonly Country[]): Country | null {
  const ending = place.split(",").at(-1)?.trim().toLowerCase() ?? "";
  if (ending === "") return null;
  return countries.find((country) => country.placeEndings.some((value) => value.toLowerCase() === ending)) ?? null;
}

/** The universities by country in rank order, each keeping its Home row order; empty countries are left out. */
export function groupByCountry(universities: readonly University[], countries: readonly Country[]): CountryGroup[] {
  const ranked = [...countries].sort((a, b) => a.rank - b.rank);
  const slots: (Country | null)[] = [...ranked, null];
  return slots.flatMap((country) => {
    const members = universities.filter((entry) => countryOf(entry.place, ranked) === country);
    if (members.length === 0) return [];
    return [{ country, universities: members, universityCount: members.length, courseCount: universityCourseCount(members) }];
  });
}
