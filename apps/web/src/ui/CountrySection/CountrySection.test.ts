import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { OTHER_COUNTRIES_TITLE } from "../../catalog/domain/config/index.ts";
import { CountrySection } from "./CountrySection.tsx";

describe("CountrySection", () => {
  it("reads the residual title from domain config", () => {
    const html = renderToStaticMarkup(CountrySection({ country: null, meta: "9 courses", children: null }));
    expect(html).toContain(OTHER_COUNTRIES_TITLE);
    expect(html).toContain("9 courses");
    expect(html).toContain('data-testid="country-section-other"');
  });

  it("uses the country name when a country claims the group", () => {
    const html = renderToStaticMarkup(CountrySection({
      country: { id: "us", name: "United States", rank: 1, placeEndings: ["MA"] },
      meta: "9 courses",
      children: null,
    }));
    expect(html).toContain("United States");
    expect(html).not.toContain(OTHER_COUNTRIES_TITLE);
  });
});
