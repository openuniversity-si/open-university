import values from "./values.json" with { type: "json" };

/**
 * Registered copy of the catalog domain (ADR-27). Each value lives in values.json, is named here, and is
 * documented in that ADR. Callers read the export; they do not repeat the value.
 */
export const CONFIG_KEYS = ["otherCountriesTitle"] as const;

type ConfigKey = (typeof CONFIG_KEYS)[number];

function registered(source: object): void {
  const found = Object.keys(source).sort();
  const expected = [...CONFIG_KEYS].sort();
  if (found.length !== expected.length || found.some((key, index) => key !== expected[index])) {
    throw new Error("domain config is not the registered key set");
  }
  const record = source as Record<string, unknown>;
  for (const key of expected) {
    const value = record[key];
    if (typeof value !== "string" || value.length === 0) throw new Error(`domain config ${key} is empty`);
  }
}

registered(values);

/** Title of the universities no configured country claims (ADR-27). */
export const OTHER_COUNTRIES_TITLE: string = values.otherCountriesTitle;

export type { ConfigKey };
