import type { ReactNode } from "react";
import { aboutThisCourse, editionLabel, formatLabel, languageLabel, lengthLabel, levelLabel } from "@/site/domain/reader-copy.ts";
import styles from "./CourseAbout.module.css";

export function CourseAbout({ author, text, level, length, language, format, edition }: {
  readonly author: { readonly name: string; readonly monogram: string; readonly role: string };
  readonly text: string;
  readonly level: string;
  readonly length: ReactNode;
  readonly language: string;
  readonly format: string;
  /** The "Edition" row (desktop), only for a course with more than one edition (ADR-21). */
  readonly edition?: ReactNode;
}) {
  const facts: [string, ReactNode][] = [[levelLabel, level], [lengthLabel, length], [languageLabel, language], [formatLabel, format], ...(edition === undefined ? [] : [[editionLabel, edition] as [string, ReactNode]])];
  return (
    <aside className={styles.panel} aria-labelledby="course-about-heading" data-testid="course-about">
      <h2 id="course-about-heading">{aboutThisCourse}</h2>
      <div className={styles.author}>
        <span className={styles.monogram} aria-hidden="true">{author.monogram}</span>
        <div><p className={styles.name}>{author.name}</p><p className={styles.role}>{author.role}</p></div>
      </div>
      <p className={styles.description}>{text}</p>
      <dl className={styles.facts}>
        {facts.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}
      </dl>
    </aside>
  );
}
