/** Icons exported from Figma as SVG (24×24 viewBox); they inherit `currentColor` and are decorative. */
interface IconProps {
  readonly className?: string;
}

const iconProps = { viewBox: "0 0 24 24", fill: "none", "aria-hidden": true, focusable: false } as const;

/** icon/ChevronRight 20:22 (RailHeader and secondary PrimaryCTA). */
export function ChevronRightIcon({ className }: IconProps) {
  return <svg className={className} {...iconProps}><path d="M9.5 5.5L16 12L9.5 18.5" stroke="currentColor" strokeWidth="var(--tower-el-icon-stroke)" strokeLinecap="round" strokeLinejoin="round" /></svg>;
}

/** icon/ChevronLeft 20:21 (TopNav back, D10). */
export function ChevronLeftIcon({ className }: IconProps) {
  return (
    <svg className={className} {...iconProps}>
      <path d="M15.4 5.4L8.8 12L15.4 18.6L14 20L6 12L14 3.2L15.4 4.4V5.4Z" fill="currentColor" />
    </svg>
  );
}

/** Icon/Play 20:27 (PrimaryCTA). */
export function PlayIcon({ className }: IconProps) {
  return (
    <svg className={className} {...iconProps}>
      <path d="M7 4.6V19.4C7 20.1 7.8 20.6 8.4 20.2L20 12.8C20.6 12.4 20.6 11.6 20 11.2L8.4 3.8C7.8 3.4 7 3.9 7 4.6Z" fill="currentColor" />
    </svg>
  );
}

