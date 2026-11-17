import type { FidelityRegion } from "./regions.ts";

/**
 * A product screen compared against the active reference set (tower_tooling + private Blob).
 * The reference PNG is the set's image for (`figmaNodeId`, `<viewport>@<dpr>x`); region boxes come
 * from the set's geometry, so a Figma re-sync never requires a repository change here.
 */
export interface FidelityFrame {
  /** Unique, stable id used for capture files and the report, e.g. `home-signed-out-390-dpr2`. */
  readonly id: string;
  /** Registering phase, for `pnpm fidelity --phase FNN`. */
  readonly phase: string;
  /** Later phases whose gate re-runs this frame unchanged (F09: PlayerFrame without the play-button mask). */
  readonly gates?: readonly string[];
  /** Exported root: a screen frame (`capture: "viewport"`) or its "Scroll content" child (`capture: "fullPage"`). */
  readonly figmaNodeId: string;
  readonly capture: "viewport" | "fullPage";
  readonly route: string;
  readonly viewport: 390 | 1366 | 1920;
  readonly dpr: 1 | 2;
  readonly authState?: "signed-in" | "continuing";
  /** Signed-in viewer's lesson_progress before capture (F11: Spec 06, `e2e/fixtures/progress.ts`). */
  readonly progress?: "spec06";
  /** Real UI actions needed to reach an approved state before capture. */
  readonly actions?: readonly { readonly click: string }[];
  /** Background inherited from the screen when exporting a transparent Scroll content child. */
  readonly referenceBackground?: string;
  readonly regions: readonly FidelityRegion[];
}

export const VIEWPORT_HEIGHTS = { 390: 844, 1366: 768, 1920: 1080 } as const;

/**
 * F05 shell frames: the Home signed-out screens (TopNav) and their Scroll content (Footer).
 * Includes the whole Footer (the "Easter egg / MEGA" slogan of Addendum 2.8 was removed in the 2026-10-11 rebrand).
 */
const SHELL_SCREENS = [
  {
    viewport: 390, screen: "154:16778", scroll: "154:16779", topNav: "154:16804",
    footer: "154:16802",
  },
  {
    viewport: 1366, screen: "154:16878", scroll: "154:16879", topNav: "154:16903",
    footer: "154:16902",
  },
  {
    viewport: 1920, screen: "154:16670", scroll: "154:16671", topNav: "154:16695",
    footer: "154:16694",
  },
] as const;

const SHELL_FRAMES: readonly FidelityFrame[] = SHELL_SCREENS.flatMap((screen) => ([1, 2] as const).flatMap((dpr): FidelityFrame[] => [
  {
    id: `shell-topnav-${String(screen.viewport)}-dpr${String(dpr)}`,
    phase: "F05",
    figmaNodeId: screen.screen,
    capture: "viewport",
    route: "/",
    viewport: screen.viewport,
    dpr,
    regions: [
      { name: "TopNav", figmaNodeId: screen.topNav, selector: '[data-testid="tower-topnav"]', colorSamples: [{ x: 4, y: 4 }] },
    ],
  },
  {
    id: `shell-footer-${String(screen.viewport)}-dpr${String(dpr)}`,
    phase: "F05",
    figmaNodeId: screen.scroll,
    capture: "fullPage",
    route: "/fixtures/shell",
    viewport: screen.viewport,
    dpr,
    regions: [
      { name: "Footer", figmaNodeId: screen.footer, selector: '[data-testid="tower-footer"]', colorSamples: [{ x: 4, y: 4 }] },
    ],
  },
]));


/** Home and real first-activation states (F06), approved active set 4. */
const HOME_SCREENS = [
  {
    viewport: 1920,
    screen: "154:16670",
    scroll: "154:16671",
    selected: false,
    topNav: "154:16695",
    footer: "154:16694",
    text: "I154:16672;23:34",
    cta: "I154:16672;23:40",
    secondary: "I154:16672;23:44",
    headers: [
      "154:16683",
      "154:16690"
    ],
    cards: [
      "154:16685",
      "154:16686",
      "154:16687",
      "154:16692",
      "154:16693"
    ]
  },
  {
    viewport: 1366,
    screen: "154:16878",
    scroll: "154:16879",
    selected: false,
    topNav: "154:16903",
    footer: "154:16902",
    text: "I154:16880;23:34",
    cta: "I154:16880;23:40",
    secondary: "I154:16880;23:44",
    headers: [
      "154:16891",
      "154:16898"
    ],
    cards: [
      "154:16893",
      "154:16894",
      "154:16895",
      "154:16900",
      "154:16901"
    ]
  },
  {
    viewport: 390,
    screen: "154:16778",
    scroll: "154:16779",
    selected: false,
    topNav: "154:16804",
    footer: "154:16802",
    text: "I154:16780;23:51",
    cta: "I154:16780;23:57",
    secondary: "I154:16780;23:61",
    headers: [
      "154:16791",
      "154:16798"
    ],
    cards: [
      "154:16793",
      "154:16794",
      "154:16795",
      "154:16800",
      "154:16801"
    ]
  },
  {
    viewport: 1920,
    screen: "154:17570",
    scroll: "154:17571",
    selected: true,
    topNav: "154:17595",
    footer: "154:17594",
    text: "I154:17572;23:34",
    cta: "I154:17572;23:40",
    secondary: "I154:17572;23:44",
    headers: [
      "154:17583",
      "154:17590"
    ],
    cards: [
      "154:17585",
      "154:17586",
      "154:17587",
      "154:17592",
      "154:17593"
    ]
  },
  {
    viewport: 390,
    screen: "154:17678",
    scroll: "154:17679",
    selected: true,
    topNav: "154:17704",
    footer: "154:17702",
    text: "I154:17680;23:51",
    cta: "I154:17680;23:57",
    secondary: "I154:17680;23:61",
    headers: [
      "154:17691",
      "154:17698"
    ],
    cards: [
      "154:17693",
      "154:17694",
      "154:17695",
      "154:17700",
      "154:17701"
    ]
  },
  {
    viewport: 1366,
    screen: "154:17778",
    scroll: "154:17779",
    selected: true,
    topNav: "154:17803",
    footer: "154:17802",
    text: "I154:17780;23:34",
    cta: "I154:17780;23:40",
    secondary: "I154:17780;23:44",
    headers: [
      "154:17791",
      "154:17798"
    ],
    cards: [
      "154:17793",
      "154:17794",
      "154:17795",
      "154:17800",
      "154:17801"
    ]
  }
] as const;

const HOME_FRAMES: readonly FidelityFrame[] = HOME_SCREENS.flatMap((screen) => ([1, 2] as const).flatMap((dpr): FidelityFrame[] => {
  const state = screen.selected ? "tap1" : "home";
  const common = { phase: "F06", route: "/", viewport: screen.viewport, dpr, ...(screen.selected ? { actions: [{ click: '[data-testid="course-card-course-1"]' }] } : {}) };
  return [
    {
      ...common, id: `${state}-signed-out-${String(screen.viewport)}-dpr${String(dpr)}`,
      figmaNodeId: screen.screen, capture: "viewport",
      regions: [
        { name: "Billboard", figmaNodeId: screen.text.slice(1, screen.text.indexOf(";")), selector: '[data-testid="tower-billboard"]', colorSamples: [{ x: 0, y: screen.viewport === 390 ? 619 : 539 }] },
        { name: "TopNav", figmaNodeId: screen.topNav, selector: '[data-testid="tower-topnav"]', colorSamples: [{ x: 4, y: 4 }] },
        { name: "BillboardText", figmaNodeId: screen.text, selector: '[data-testid="tower-billboard-text"]', colorSamples: [{ x: 0, y: screen.viewport === 390 ? 160 : 250 }] },
        { name: "PrimaryCTA/Start", figmaNodeId: screen.cta, selector: '[data-testid="tower-primary-cta"]', colorSamples: [{ x: 4, y: 4 }] },
        { name: "PrimaryCTA/Course details", figmaNodeId: screen.secondary, selector: '[data-testid="tower-secondary-cta"]', colorSamples: [{ x: 0, y: 0 }] },
      ],
    },
    {
      ...common, id: `${state}-rails-signed-out-${String(screen.viewport)}-dpr${String(dpr)}`,
      figmaNodeId: screen.scroll, capture: "fullPage",
      regions: [
        ...screen.headers.map((id, index) => ({ name: `RailHeader/${String(index + 1)}`, figmaNodeId: id, selector: `[data-testid="rail-header-${index === 0 ? "jordan-b-peterson" : "john-vervaeke"}"]`, colorSamples: [{ x: 0, y: 0 }], precedingLabelRows: index })),
        // Sample the solid dark bottom interior, away from the glass hairline and printed lettering.
        ...screen.cards.map((id, index) => ({ name: `CourseCard/${String(index + 1)}`, figmaNodeId: id, selector: `[data-testid="course-card-course-${String(index + 1)}"] [data-testid="tower-card-poster"]`, colorSamples: [{ x: 20, y: screen.viewport === 390 ? 230 : 350 }], posterBox: true, precedingLabelRows: index < 3 ? 0 : 1, ...(screen.viewport === 390 && index === 2 ? { clipToFrame: true } : {}) })),
        { name: "Footer", figmaNodeId: screen.footer, selector: '[data-testid="tower-footer"]', colorSamples: [{ x: 4, y: 4 }], precedingLabelRows: 2 },
      ],
    },
  ];
}));

const ACCOUNT_SCREENS = [
  { viewport: 390, screen: "154:18521", region: "258:3906", kind: "error" },
  { viewport: 390, screen: "154:18503", region: "258:3901", kind: "cancelled" },
  { viewport: 390, screen: "154:18539", region: "I250:9410;250:9388", kind: "menu" },
  { viewport: 1920, screen: "154:18415", region: "258:3895", kind: "error" },
  { viewport: 1920, screen: "154:18433", region: "I250:9450;250:9395", kind: "menu" },
] as const;

const ACCOUNT_FRAMES: readonly FidelityFrame[] = ACCOUNT_SCREENS.flatMap((screen) => ([1, 2] as const).map((dpr): FidelityFrame => ({
  id: `account-${screen.kind}-${String(screen.viewport)}-dpr${String(dpr)}`,
  phase: "F06",
  figmaNodeId: screen.screen,
  capture: "viewport",
  route: `/fixtures/account?kind=${screen.kind}&capture=1`,
  viewport: screen.viewport,
  dpr,
  regions: [{
    name: screen.kind === "menu" ? "AccountMenu" : "SignInFeedback",
    figmaNodeId: screen.region,
    selector: screen.kind === "menu" ? '[data-testid="tower-account-menu"]' : '[data-testid="tower-signin-feedback"]',
    colorSamples: [{ x: 16, y: 8 }],
  }],
})));


/** F07 Course signed out, viewport and Scroll content from active set 4. */
const COURSE_SCREENS = [
  { viewport: 390, screen: "154:17200", scroll: "154:17201", hero: "154:17202", text: "I154:17202;23:51", cta: "I154:17202;23:57", nav: "154:17227", panel: "154:17203", header: "213:4563", list: "154:17207", first: "154:17208", footer: "154:17225" },
  { viewport: 1366, screen: "154:17356", scroll: "154:17357", hero: "154:17358", text: "I154:17358;23:34", cta: "I154:17358;23:40", nav: "154:17414", panel: "154:17360", header: "213:4653", list: "154:17367", first: "154:17368", footer: "154:17413", about: "287:12686", more: "154:17409", cards: ["154:17411", "154:17412"] },
  { viewport: 1920, screen: "154:16986", scroll: "154:16987", hero: "154:16988", text: "I154:16988;23:34", cta: "I154:16988;23:40", nav: "154:17044", panel: "154:16990", header: "213:4473", list: "154:16997", first: "154:16998", footer: "154:17043", about: "287:12664", more: "154:17039", cards: ["154:17041", "154:17042"] },
] as const;

const COURSE_FRAMES: readonly FidelityFrame[] = COURSE_SCREENS.flatMap((screen) => ([1, 2] as const).flatMap((dpr): FidelityFrame[] => {
  const common = { phase: "F07", route: "/c/biblical-series-genesis", viewport: screen.viewport, dpr };
  const content: FidelityRegion[] = [
    { name: "Lectures", figmaNodeId: screen.panel, selector: '[data-testid="course-lectures"]', colorSamples: [{ x: 4, y: 4 }] },
    { name: "LecturesHeader", figmaNodeId: screen.header, selector: '[data-testid="course-lectures-header"]', colorSamples: [{ x: 0, y: 40 }] },
    { name: "PlaylistItem/1", figmaNodeId: screen.first, selector: '[data-testid="playlist-item-lesson-1"]', colorSamples: [{ x: 0, y: 0 }] },
  ];
  if ("about" in screen) content.push({ name: "CourseAbout", figmaNodeId: screen.about, selector: '[data-testid="course-about"]', colorSamples: [{ x: 4, y: 4 }] });
  return [
    { ...common, id: `course-signed-out-${String(screen.viewport)}-dpr${String(dpr)}`, figmaNodeId: screen.screen, capture: "viewport", regions: [
      { name: "Billboard", figmaNodeId: screen.hero, selector: '[data-testid="tower-billboard"]', colorSamples: [{ x: 0, y: screen.viewport === 390 ? 619 : 539 }] },
      { name: "TopNav", figmaNodeId: screen.nav, selector: '[data-testid="tower-topnav"]', colorSamples: [{ x: 4, y: 4 }] },
      { name: "BillboardText", figmaNodeId: screen.text, selector: '[data-testid="tower-billboard-text"]', colorSamples: [{ x: 0, y: 160 }] },
      { name: "PrimaryCTA/Start", figmaNodeId: screen.cta, selector: '[data-testid="tower-primary-cta"]', colorSamples: [{ x: 4, y: 4 }] },
    ] },
    { ...common, id: `course-content-signed-out-${String(screen.viewport)}-dpr${String(dpr)}`, figmaNodeId: screen.scroll, capture: "fullPage", regions: [
      ...content,
      ...("more" in screen ? [
        { name: "MoreFromAuthor", figmaNodeId: screen.more, selector: '[data-testid="rail-header-more-from-author"]', colorSamples: [{ x: 0, y: 0 }] },
        ...screen.cards.map((id, index) => ({ name: `CourseCard/${String(index + 2)}`, figmaNodeId: id, selector: `[data-testid="course-card-course-${String(index + 2)}"] [data-testid="tower-card-poster"]`, colorSamples: [{ x: 20, y: 350 }], posterBox: true })),
      ] : []),
      { name: "Footer", figmaNodeId: screen.footer, selector: '[data-testid="tower-footer"]', colorSamples: [{ x: 4, y: 4 }], precedingLabelRows: screen.viewport === 390 ? 0 : 1 },
    ] },
  ];
}));

/** F03 foundation and all implemented screen phases. */
const AUTH_NAV_SCREENS = [
  { viewport: 390, screen: "29:399", nav: "29:525", avatar: "I29:525;21:45" },
  { viewport: 1366, screen: "53:1391", nav: "53:1428", avatar: "I53:1428;21:16" },
  { viewport: 1920, screen: "24:2", nav: "24:145", avatar: "I24:145;21:16" },
] as const;
const AUTH_CONTINUING_SCREENS = [
  { viewport: 390, screen: "224:4302", veil: "224:4303", message: "224:4304" },
  { viewport: 1366, screen: "224:4306", veil: "224:4307", message: "224:4308" },
  { viewport: 1920, screen: "224:4298", veil: "224:4299", message: "224:4300" },
] as const;
const AUTH_FRAMES: readonly FidelityFrame[] = [
  ...AUTH_NAV_SCREENS.flatMap((screen) => ([1, 2] as const).map((dpr): FidelityFrame => ({
    id: `auth-topnav-${String(screen.viewport)}-dpr${String(dpr)}`, phase: "F10", figmaNodeId: screen.screen,
    route: "/", capture: "viewport", viewport: screen.viewport, dpr, authState: "signed-in",
    regions: [
      { name: "TopNav", figmaNodeId: screen.nav, selector: '[data-testid="tower-topnav"]', colorSamples: [{ x: 4, y: 4 }] },
      { name: "Avatar", figmaNodeId: screen.avatar, selector: '[data-testid="tower-avatar-circle"]', colorSamples: [{ x: 16, y: 4 }] },
    ],
  }))),
  ...AUTH_CONTINUING_SCREENS.flatMap((screen) => ([1, 2] as const).map((dpr): FidelityFrame => ({
    id: `auth-continuing-${String(screen.viewport)}-dpr${String(dpr)}`, phase: "F10", figmaNodeId: screen.screen,
    route: "/", capture: "viewport", viewport: screen.viewport, dpr, authState: "continuing",
    regions: [
      { name: "ContinuingVeil", figmaNodeId: screen.veil, selector: '[data-testid="auth-continuing"]', colorSamples: [{ x: 4, y: 4 }] },
      { name: "ContinuingMessage", figmaNodeId: screen.message, selector: '[data-testid="auth-continuing-message"]', colorSamples: [{ x: 0, y: 0 }] },
    ],
  }))),
  ...[...ACCOUNT_SCREENS, { viewport: 1920, screen: "154:18397", region: "258:3890", kind: "cancelled" } as const]
    .flatMap((screen) => ([1, 2] as const).map((dpr): FidelityFrame => ({
      id: `auth-${screen.kind}-${String(screen.viewport)}-dpr${String(dpr)}`, phase: "F10", figmaNodeId: screen.screen,
      route: screen.kind === "menu" ? "/fixtures/auth-account" : `/?error=${screen.kind === "error" ? "oauth_failed" : "access_denied"}`,
      capture: "viewport", viewport: screen.viewport, dpr,
      ...(screen.kind === "menu" ? { authState: "signed-in", actions: [{ click: '[data-testid="tower-topnav-avatar"]' }] } as const : {}),
      regions: [{ name: screen.kind === "menu" ? "AccountMenu" : "SignInFeedback", figmaNodeId: screen.region,
        selector: screen.kind === "menu" ? '[data-testid="tower-account-menu"]' : '[data-testid="tower-signin-feedback"]', colorSamples: [{ x: 16, y: 8 }] },
      ],
    }))),
];

const PLAYER_SCREENS = [
  { viewport: 390, screen: "154:18053", scroll: "154:18054", player: "287:12555", time: "287:12437", scrubber: "287:12438", nav: "154:18063", header: "154:18070", actions: "154:18074", rail: "287:15030", railHeader: "287:13685", first: "287:13693", playing: "287:13696", last: "287:13709", footer: "154:18103" },
  { viewport: 1366, screen: "154:18201", scroll: "154:18202", player: "287:12507", time: "287:12430", scrubber: "287:12431", nav: "154:18213", header: "154:18220", actions: "154:18224", about: "287:12811", rail: "287:14638", railHeader: "287:13652", section: "287:13662", first: "287:13666", playing: "287:13669", footer: "154:18262" },
  { viewport: 1920, screen: "154:17886", scroll: "154:17887", player: "287:12458", time: "287:12423", scrubber: "287:12424", nav: "154:17898", header: "154:17905", actions: "154:17909", about: "287:12799", rail: "287:14246", railHeader: "287:13619", section: "287:13629", first: "287:13633", playing: "287:13636", footer: "154:17947" },
] as const;
const PLAYER_FRAMES: readonly FidelityFrame[] = PLAYER_SCREENS.flatMap((screen) => ([1, 2] as const).map((dpr): FidelityFrame => ({
  id: `player-signed-out-${String(screen.viewport)}-dpr${String(dpr)}`, phase: "F08", gates: ["F09"], figmaNodeId: screen.scroll,
  referenceBackground: "#0c0c0d", capture: "fullPage", route: "/c/biblical-series-genesis/biblical-series-iv-adam-and-eve-self-consciousness-evil-and-death", viewport: screen.viewport, dpr,
  regions: [
    { name: "PlayerFrame", figmaNodeId: screen.player, selector: '[data-testid="player-frame"]', colorSamples: [{ x: 0, y: 0 }], signedOutMasks: [`I${screen.player};${screen.time}`, `I${screen.player};${screen.scrubber}`] },
    { name: "PlayerNavigation", figmaNodeId: screen.nav, selector: '[data-testid="player-navigation"]', colorSamples: [{ x: 0, y: 0 }] },
    { name: "LessonHeader", figmaNodeId: screen.header, selector: '[data-testid="player-lesson-header"]', colorSamples: [{ x: 0, y: 0 }] },
    { name: "PlayerActions", figmaNodeId: screen.actions, selector: '[data-testid="player-actions"]', colorSamples: [{ x: 0, y: 0 }] },
    { name: "PlayerRail", figmaNodeId: screen.rail, selector: '[data-testid="player-rail"]', colorSamples: [{ x: 4, y: 4 }], signedOutMasks: [0, 1, 2].map((index) => `I${screen.rail};287:${String(Number(screen.first.split(":")[1]) + index)};39:64`) },
    { name: "PlayerRailHeader", figmaNodeId: `I${screen.rail};${screen.railHeader}`, selector: '[data-testid="player-rail-header"]', colorSamples: [{ x: 0, y: 0 }] },
    { name: "PlaylistNowPlaying", figmaNodeId: `I${screen.rail};${screen.playing}`, selector: '[data-now-playing="true"]', colorSamples: [{ x: 4, y: 4 }] },
    ...("last" in screen ? [{ name: "PlayerRailEnd", figmaNodeId: `I${screen.rail};${screen.last}`, selector: '[data-testid="player-lecture-list"] > :last-child', colorSamples: [{ x: 4, y: 4 }] }] : []),
    ...("about" in screen ? [{ name: "LectureAbout", figmaNodeId: screen.about, selector: '[data-testid="lecture-about"]', colorSamples: [{ x: 0, y: 0 }] }] : []),
    { name: "Footer", figmaNodeId: screen.footer, selector: '[data-testid="tower-footer"]', colorSamples: [{ x: 4, y: 4 }] },
  ],
})));

/** F11 signed-in screens (Spec 06 progress fixture): Home + Tap 1, Course and Player, set 4. */
const PROGRESS_HOME_SCREENS = [
  { viewport: 390, screen: "29:399", scroll: "29:400", hero: "29:401", header: "29:454", cards: ["29:425", "29:434", "29:443"], selected: false },
  { viewport: 1366, screen: "53:1391", scroll: "53:1392", hero: "53:1393", header: "53:1397", cards: ["53:1399", "53:1400", "53:1401"], selected: false },
  { viewport: 1920, screen: "24:2", scroll: "24:3", hero: "24:4", header: "24:69", cards: ["24:31", "24:40", "24:49"], selected: false },
  { viewport: 390, screen: "64:1666", scroll: "64:1667", hero: "64:1668", header: "64:1672", cards: ["64:1674", "64:1675", "64:1676"], selected: true },
  { viewport: 1366, screen: "53:1429", scroll: "53:1430", hero: "53:1431", header: "53:1435", cards: ["53:1437", "53:1438", "53:1439"], selected: true },
  { viewport: 1920, screen: "29:241", scroll: "29:242", hero: "29:243", header: "29:247", cards: ["29:249", "29:250", "29:251"], selected: true },
] as const;
const CONTINUE_ORDER = ["course-2", "course-1", "course-4"] as const;
const heroText = (viewport: number, hero: string) => viewport === 390 ? { text: `I${hero};23:51`, cta: `I${hero};23:57` } : { text: `I${hero};23:34`, cta: `I${hero};23:40` };
const PROGRESS_HOME_FRAMES: readonly FidelityFrame[] = PROGRESS_HOME_SCREENS.flatMap((screen) => ([1, 2] as const).flatMap((dpr): FidelityFrame[] => {
  const state = screen.selected ? "tap1" : "home";
  const common = { phase: "F11", route: "/", viewport: screen.viewport, dpr, authState: "signed-in", progress: "spec06",
    ...(screen.selected ? { actions: [{ click: '#content [data-testid="rail-continue-watching"] [data-testid="course-card-course-1"]' }] } : {}) } as const;
  const { text, cta } = heroText(screen.viewport, screen.hero);
  return [
    { ...common, id: `${state}-signed-in-${String(screen.viewport)}-dpr${String(dpr)}`, figmaNodeId: screen.screen, capture: "viewport", regions: [
      { name: "Billboard", figmaNodeId: screen.hero, selector: '[data-testid="tower-billboard"]', colorSamples: [{ x: 0, y: screen.viewport === 390 ? 619 : 539 }] },
      { name: "BillboardText", figmaNodeId: text, selector: '[data-testid="tower-billboard-text"]', colorSamples: [{ x: 0, y: screen.viewport === 390 ? 160 : 250 }] },
      { name: "PrimaryCTA/Resume", figmaNodeId: cta, selector: '[data-testid="tower-billboard"] [data-testid="tower-primary-cta"]', colorSamples: [{ x: 4, y: 4 }] },
    ] },
    { ...common, id: `${state}-rails-signed-in-${String(screen.viewport)}-dpr${String(dpr)}`, figmaNodeId: screen.scroll, capture: "fullPage", regions: [
      { name: "RailHeader/ContinueWatching", figmaNodeId: screen.header, selector: '[data-testid="rail-header-continue-watching"]', colorSamples: [{ x: 0, y: 0 }] },
      ...screen.cards.flatMap((id, index) => {
        const card = `[data-testid="rail-continue-watching"] [data-testid="course-card-${CONTINUE_ORDER[index] ?? ""}"]`;
        const clip = screen.viewport === 390 && index === 2 ? { clipToFrame: true } : {};
        return [
          { name: `CourseCard/Continue/${String(index + 1)}`, figmaNodeId: id, figmaChild: "Cover 9:16", selector: `${card} [data-testid="tower-card-poster"]`, colorSamples: [{ x: 20, y: 20 }], ...clip },
          { name: `CourseCard/ContinueMeta/${String(index + 1)}`, figmaNodeId: id, figmaChild: "Meta", selector: `${card} [data-testid="tower-card-continue"]`, colorSamples: [{ x: 0, y: 0 }], ...clip },
        ];
      }),
    ] },
  ];
}));

const PROGRESS_COURSE_SCREENS = [
  { viewport: 390, screen: "29:551", scroll: "29:552", hero: "29:553", panel: "29:570", header: "211:4309", track: "211:4314", rows: ["29:574", "29:604", "29:614"] },
  { viewport: 1366, screen: "53:1467", scroll: "53:1468", hero: "53:1469", panel: "53:1471", header: "213:4377", track: "213:4382", rows: ["53:1478", "53:1481", "53:1482"] },
  { viewport: 1920, screen: "26:124", scroll: "26:125", hero: "26:126", panel: "26:145", header: "213:4281", track: "213:4286", rows: ["26:152", "26:183", "26:193"] },
] as const;
const PROGRESS_COURSE_FRAMES: readonly FidelityFrame[] = PROGRESS_COURSE_SCREENS.flatMap((screen) => ([1, 2] as const).flatMap((dpr): FidelityFrame[] => {
  const common = { phase: "F11", route: "/c/biblical-series-genesis", viewport: screen.viewport, dpr, authState: "signed-in", progress: "spec06" } as const;
  const { text, cta } = heroText(screen.viewport, screen.hero);
  return [
    { ...common, id: `course-signed-in-${String(screen.viewport)}-dpr${String(dpr)}`, figmaNodeId: screen.screen, capture: "viewport", regions: [
      { name: "Billboard", figmaNodeId: screen.hero, selector: '[data-testid="tower-billboard"]', colorSamples: [{ x: 0, y: screen.viewport === 390 ? 619 : 539 }] },
      { name: "BillboardText", figmaNodeId: text, selector: '[data-testid="tower-billboard-text"]', colorSamples: [{ x: 0, y: 160 }] },
      { name: "PrimaryCTA/Resume", figmaNodeId: cta, selector: '[data-testid="tower-primary-cta"]', colorSamples: [{ x: 4, y: 4 }] },
    ] },
    { ...common, id: `course-content-signed-in-${String(screen.viewport)}-dpr${String(dpr)}`, figmaNodeId: screen.scroll, capture: "fullPage", regions: [
      { name: "Lectures", figmaNodeId: screen.panel, selector: '[data-testid="course-lectures"]', colorSamples: [{ x: 4, y: 4 }] },
      { name: "LecturesHeader", figmaNodeId: screen.header, selector: '[data-testid="course-lectures-header"]', colorSamples: [{ x: 0, y: 40 }] },
      { name: "CourseProgress", figmaNodeId: screen.track, selector: '[data-testid="course-lectures"] [data-testid="course-progress-bar"]', colorSamples: [{ x: 1, y: 1 }] },
      { name: "PlaylistItem/Watched", figmaNodeId: screen.rows[0], selector: '[data-testid="playlist-item-lesson-1"]', colorSamples: [{ x: 0, y: 0 }] },
      { name: "PlaylistItem/Current", figmaNodeId: screen.rows[1], selector: '[data-testid="playlist-item-lesson-4"]', colorSamples: [{ x: 60, y: 2 }] },
      { name: "PlaylistItem/Next", figmaNodeId: screen.rows[2], selector: '[data-testid="playlist-item-lesson-5"]', colorSamples: [{ x: 0, y: 0 }] },
    ] },
  ];
}));

const PROGRESS_PLAYER_SCREENS = [
  { viewport: 390, scroll: "43:663", player: "287:12540", header: "43:682", actions: "43:686", rail: "287:14146", railHeader: "287:13518", progress: "287:13523", playing: "287:13529", footer: "43:741" },
  { viewport: 1366, scroll: "53:1519", player: "287:12491", header: "53:1537", actions: "53:1541", rail: "287:13966", railHeader: "287:13485", progress: "287:13488", playing: "287:13502", footer: "53:1578" },
  { viewport: 1920, scroll: "42:555", player: "287:12442", header: "42:576", actions: "42:580", rail: "287:13786", railHeader: "287:13452", progress: "287:13455", playing: "287:13469", footer: "42:695" },
] as const;
const PROGRESS_PLAYER_FRAMES: readonly FidelityFrame[] = PROGRESS_PLAYER_SCREENS.flatMap((screen) => ([1, 2] as const).map((dpr): FidelityFrame => ({
  id: `player-signed-in-${String(screen.viewport)}-dpr${String(dpr)}`, phase: "F11", figmaNodeId: screen.scroll, referenceBackground: "#0c0c0d", capture: "fullPage",
  route: "/c/biblical-series-genesis/biblical-series-iv-adam-and-eve-self-consciousness-evil-and-death", viewport: screen.viewport, dpr, authState: "signed-in", progress: "spec06",
  regions: [
    { name: "PlayerFrame", figmaNodeId: screen.player, selector: '[data-testid="player-frame"]', colorSamples: [{ x: 0, y: 0 }] },
    { name: "LessonHeader", figmaNodeId: screen.header, selector: '[data-testid="player-lesson-header"]', colorSamples: [{ x: 0, y: 0 }] },
    { name: "PlayerActions", figmaNodeId: screen.actions, selector: '[data-testid="player-actions"]', colorSamples: [{ x: 0, y: 0 }] },
    { name: "PlayerRail", figmaNodeId: screen.rail, selector: '[data-testid="player-rail"]', colorSamples: [{ x: 4, y: 4 }] },
    { name: "PlayerRailHeader", figmaNodeId: `I${screen.rail};${screen.railHeader}`, selector: '[data-testid="player-rail-header"]', colorSamples: [{ x: 0, y: 0 }] },
    { name: "PlayerRailProgress", figmaNodeId: `I${screen.rail};${screen.progress}`, selector: screen.viewport === 390 ? '[data-testid="player-rail"] > [data-testid="course-progress-bar"]' : '[data-testid="player-rail-progress"]', colorSamples: [{ x: 1, y: 1 }] },
    { name: "PlaylistNowPlaying", figmaNodeId: `I${screen.rail};${screen.playing}`, selector: '[data-now-playing="true"]', colorSamples: [{ x: 4, y: 4 }] },
    { name: "Footer", figmaNodeId: screen.footer, selector: '[data-testid="tower-footer"]', colorSamples: [{ x: 4, y: 4 }] },
  ],
})));

export const FIDELITY_FRAMES: readonly FidelityFrame[] = [...SHELL_FRAMES, ...HOME_FRAMES, ...ACCOUNT_FRAMES, ...COURSE_FRAMES, ...AUTH_FRAMES, ...PLAYER_FRAMES,
  ...PROGRESS_HOME_FRAMES, ...PROGRESS_COURSE_FRAMES, ...PROGRESS_PLAYER_FRAMES];

/**
 * The 154:* static frames predate Daniel's approved course names. In locked prototype
 * 443:46858 (cards 443:46875/443:46877), the desktop row adds 8 + 38 = 46px;
 * 443:46317 has 8 + 32 = 40px on mobile. Only regions after those rows are aligned.
 */
export const COURSE_NAME_ROW_DELTA = { mobile: 40, desktop: 46 } as const;
