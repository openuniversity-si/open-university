"use client";

import Link from "next/link";
import { useState, type ReactNode } from "react";
import type { UniversityCard, UniversityGroupView } from "@/catalog/domain/view-model";
import type { FlagGeometry } from "@/ui/CountrySection/flags";
import { courseNoun, fill, freeInOrderSuffix, institutionNoun, metaGap, openNameTemplate, universitiesTitle } from "@/site/domain/reader-copy.ts";
import { Billboard } from "@/ui/Billboard/Billboard";
import { shouldSelectCard } from "@/ui/CourseCard/activation";
import { CountrySection } from "@/ui/CountrySection/CountrySection";
import { CoverGlass } from "@/ui/CoverGlass/CoverGlass";
import { LazyPoster } from "@/ui/LazyPoster/LazyPoster";
import { countryMeta, plural, universityHero } from "@/ui/showcase/shelf-sentences.ts";
import styles from "./Universities.module.css";

/** A country group with the flag already attached. The domain does not import flag geometry. */
export interface UniversityShowcaseGroup extends UniversityGroupView {
  readonly flag?: FlagGeometry;
  readonly universities: readonly UniversityCard[];
}

interface UniversitiesShowcaseProps {
  readonly groups: readonly UniversityShowcaseGroup[];
  readonly courseCount: number;
  /** Rendered after the grid (the cover credits). */
  readonly children?: ReactNode;
}

/**
 * /universities (Figma 622:3121 / 622:2813): the hero shows the selected university (the first one until a card is
 * tapped); the first tap on a cover selects it, the second opens the university, like the Home course cards (Spec 07).
 * The grid is grouped by country (Daniel 17/10/2026): one CountrySection per country with published universities, in
 * `rank` order from src/catalog/domain/countries.ts, each followed by that country's full grid of the same cards.
 * Course counts are computed on the server (D-037). This component paints the country sentence and never receives a course list.
 */
export function UniversitiesShowcase({ groups, courseCount, children }: UniversitiesShowcaseProps) {
  const [selectedSlug, setSelectedSlug] = useState<string | undefined>(undefined);
  const universities = groups.flatMap((group) => group.universities);
  const current = universities.find((entry) => entry.slug === selectedSlug) ?? groups[0]?.universities[0];
  if (!current) return null;
  const hero = universityHero(current);
  return (
    <>
      <Billboard course={hero} selected={selectedSlug !== undefined} meta={{ mobile: hero.metaMobile, desktop: hero.meta }} primary={{ href: `/universities/${current.slug}`, label: fill(openNameTemplate, { name: current.name }) }} />
      <div className={styles.page} data-testid="universities-showcase">
        <header className={styles.heading}>
          <h2 className={styles.title}>{universitiesTitle}</h2>
          <p className={styles.subtitle}>{plural(universities.length, institutionNoun)}{metaGap}{plural(courseCount, courseNoun)}{freeInOrderSuffix}</p>
        </header>
        <div className={styles.countries}>
          {groups.map((group) => (
            <CountrySection key={group.country?.id ?? "other"} country={group.country} flag={group.flag} meta={countryMeta(group)}>
              <ul className={styles.grid} data-testid={`universities-grid-${group.country?.id ?? "other"}`}>
                {group.universities.map((entry) => {
                  const selected = entry.slug === current.slug;
                  return (
                    <li key={entry.slug}>
                      <Link
                        className={`${styles.card ?? ""} tower-focus-rounded`}
                        href={`/universities/${entry.slug}`}
                        prefetch={false}
                        aria-label={`${entry.fullName}, ${plural(entry.courseCount, courseNoun)}`}
                        aria-current={selected ? "true" : undefined}
                        data-testid={`university-card-${entry.slug}`}
                        data-selected={selected}
                        onClick={(event) => {
                          if (shouldSelectCard(event, entry.slug === selectedSlug)) {
                            event.preventDefault();
                            setSelectedSlug(entry.slug);
                          }
                        }}
                      >
                        <span className={styles["cover-frame"]}>
                          <span className={styles.cover}>
                            {entry.cover ? <LazyPoster className={styles.art} src={entry.cover.url} width={entry.cover.width} height={entry.cover.height} /> : <span className={styles.art} data-testid="university-cover-placeholder" />}
                            <CoverGlass />
                          </span>
                          <span className={styles.ring} aria-hidden="true" />
                        </span>
                        <span className={styles.caption}>
                          <span className={styles["caption-title"]}>{entry.fullName}</span>
                          <span className={styles["caption-meta"]}>{[plural(entry.courseCount, courseNoun), entry.place].filter((part) => part !== "").join(metaGap)}</span>
                        </span>
                      </Link>
                    </li>
                  );
                })}
              </ul>
            </CountrySection>
          ))}
        </div>
        {children}
      </div>
    </>
  );
}
