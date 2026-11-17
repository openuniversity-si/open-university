import Link from "next/link";
import styles from "./HomeIntro.module.css";

/** ◆ Home intro (Mobile 390 | Desktop 1920): the value line and "About Open University ›" between the hero and the first rail, for everyone. */
export function HomeIntro({ text, link, href }: { readonly text: string; readonly link: string; readonly href: string }) {
  return (
    <div className={styles.intro} data-testid="tower-home-intro">
      <p className={styles.text}>{text}</p>
      <Link className={styles.link} href={href}>{link} ›</Link>
    </div>
  );
}
