import { aboutThisLecture } from "@/site/domain/reader-copy.ts";
import styles from "./LectureAbout.module.css";

export function LectureAbout({ text }: { readonly text: string | null }) {
  if (!text) return null;
  return <section className={styles.about} aria-labelledby="lecture-about-heading" data-testid="lecture-about"><h2 id="lecture-about-heading">{aboutThisLecture}</h2><p>{text}</p></section>;
}
