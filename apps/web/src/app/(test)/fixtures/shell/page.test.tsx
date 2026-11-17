import styles from "./shell.module.css";

/**
 * Test build only. Until the Home content lands (F06), this stands in for the Home signed-out Scroll
 * content above the footer, with its exact Figma height (Billboard + Rails): 1256 px in 154:16779
 * (mobile) and 1466 px in 154:16671 / 154:16879 (desktop). The F05 fidelity frames measure the
 * TopNav and Footer regions against those frames here; F06 moves them to `/`.
 */
export default function ShellFixturePage() {
  return (
    <>
      <div className={styles.mobile} style={{ height: 1256 }} data-testid="shell-fixture-content" />
      <div className={styles.desktop} style={{ height: 1466 }} data-testid="shell-fixture-content" />
    </>
  );
}
