import {
  towerBreakpointDesktop,
  towerBreakpointPresent,
  towerBreakpointTablet,
  towerBreakpointWide,
  towerCourseAboutWidth,
  towerCourseColumnGap,
  towerLayoutGutterDesktop,
  towerLayoutGutterMobile,
  towerLayoutGutterTablet,
  towerLessonStageInset,
  towerSurface,
} from "./values.ts";

const px = (value: string): number => {
  const match = /^(-?\d+(?:\.\d+)?)px$/.exec(value);
  if (!match?.[1]) throw new Error(`Expected a px token, received ${value}.`);
  return Number(match[1]);
};

/** Spec 01 (288:49): CSS pixels; full-width regions have no global max-width. */
export const TOWER_LAYOUT = {
  breakpoints: {
    tablet: px(towerBreakpointTablet),
    desktop: px(towerBreakpointDesktop),
    present: px(towerBreakpointPresent),
    wide: px(towerBreakpointWide),
  },
  header: { mobile: 56, desktop: 72 },
  gutter: { mobile: px(towerLayoutGutterMobile), tablet: px(towerLayoutGutterTablet), desktop: px(towerLayoutGutterDesktop) },
  billboard: { mobile: 620, desktop: 540, desktopText: 689, desktopImage: 810 },
  cards: { mobile: 140, desktop: 208, mobileCoverHeight: 249, desktopCoverHeight: 370 },
  rails: { mobileGap: 12, desktopGap: 20, mobileStackGap: 28, desktopStackGap: 40 },
  player: { gutter: 32, gap: 32, rail: 380, mainMax: 1444, mobileListViewport: 440 },
  course: { gutter: px(towerLayoutGutterDesktop), gap: px(towerCourseColumnGap), about: px(towerCourseAboutWidth) },
  aboutMeasure: 720,
  footerHeight: 44,
  tapMinimum: 44,
} as const;

/** `--tower-surface` for the browser chrome (`<meta name="theme-color">`), which cannot read CSS variables. */
export const TOWER_THEME_COLOR = towerSurface;

export function towerPlayerMainWidth(viewport: number): number {
  return viewport < TOWER_LAYOUT.breakpoints.desktop ? viewport : Math.min(viewport - px(towerLessonStageInset), TOWER_LAYOUT.player.mainMax);
}

export function towerCourseLecturesWidth(viewport: number): number {
  if (viewport < TOWER_LAYOUT.breakpoints.desktop) {
    const gutter = viewport < TOWER_LAYOUT.breakpoints.tablet ? TOWER_LAYOUT.gutter.mobile : TOWER_LAYOUT.gutter.tablet;
    return viewport - 2 * gutter;
  }
  return viewport - 2 * TOWER_LAYOUT.gutter.desktop - TOWER_LAYOUT.course.gap - TOWER_LAYOUT.course.about;
}

/** Spec 05: recompute this angle for every hug width and height. */
export function towerSilverCtaAngle(width: number, height: number): number {
  if (width <= 0 || height <= 0) throw new Error("CTA dimensions must be positive.");
  return Math.atan2(0.94 / width, -0.34 / height) * 180 / Math.PI;
}
