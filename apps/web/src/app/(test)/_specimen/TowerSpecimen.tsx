import type { CSSProperties } from "react";
import snapshot from "../../../../design/figma-tokens.snapshot.json";
import styles from "./specimen.module.css";

export const TOWER_SWATCHES = ["surface", "surface-raised", "hairline", "ink", "muted", "metal", "silver", "scrim"] as const;

/** Private test component; the route adapter uses a test-only page extension. */
export function TowerSpecimen() {
  return (
    <main className={styles.specimen}>
      <h1 className="t-display-rail">Open University typography and colors</h1>
      <section aria-label="Typography roles">
        {snapshot.typography.map((role) => (
          <p key={role.className} className={role.className} data-testid={role.className}>
            {role.figmaStyle}: Open University, 0123456789 — Meaning and wisdom
          </p>
        ))}
      </section>
      <section aria-label="Color swatches" className={styles.swatches}>
        {TOWER_SWATCHES.map((name) => (
          <div key={name}>
            <div className={styles.swatch} data-testid={`swatch-${name}`} style={{ "--tower-swatch-color": `var(--tower-${name})` } as CSSProperties} />
            <p className="t-ui-meta-13">{name}</p>
          </div>
        ))}
      </section>
    </main>
  );
}
