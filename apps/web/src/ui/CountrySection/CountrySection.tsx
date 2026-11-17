import type { ReactNode } from "react";
import { OTHER_COUNTRIES_TITLE } from "@/catalog/domain/config";
import type { Country } from "@/catalog/domain/countries";
import type { FlagGeometry } from "./flags";
import { Flag } from "./Flag";
import styles from "./CountrySection.module.css";

interface CountrySectionProps {
  /** null: the universities no configured country claims (no flag, a neutral title). */
  readonly country: Country | null;
  readonly flag?: FlagGeometry;
  /** "17 universities · 311 courses". */
  readonly meta: string;
  /** The country's grid, unchanged (same cards and layout as the ungrouped page). */
  readonly children: ReactNode;
}

/**
 * One country of the Universities page (Figma CountryHeader 655:3545, H2 "Small dose, true color"): a true-colour lapel
 * flag at its official ratio and the country name in Inter (Display/Rail, the section-title style), the quiet count on the right, a hairline that
 * dissolves on an eased curve, then the country's grid. The same component for every country: the order is the hierarchy.
 */
export function CountrySection({ country, flag, meta, children }: CountrySectionProps) {
  const id = `country-${country?.id ?? "other"}`;
  return (
    <section className={styles.section} aria-labelledby={id} data-testid={`country-section-${country?.id ?? "other"}`}>
      <div className={styles.header}>
        <div className={styles.row}>
          <h3 className={styles.name} id={id}>
            {country && flag ? <Flag id={country.id} flag={flag} className={styles.flag} /> : null}
            <span>{country?.name ?? OTHER_COUNTRIES_TITLE}</span>
          </h3>
          <p className={styles.meta}>{meta}</p>
        </div>
        <span className={styles.rule} aria-hidden="true" />
      </div>
      {children}
    </section>
  );
}
