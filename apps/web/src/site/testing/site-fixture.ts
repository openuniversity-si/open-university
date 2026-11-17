/** A minimal valid v2 document and the v1 bag that upcasts to the same countries and titles. */
export const siteFixtureV2 = {
  schemaVersion: 2 as const,
  metadata: { siteName: "Open University", defaultTitle: "Open University", titleTemplate: "%s · Open University", defaultDescription: "A catalog.", ogImageAlt: "Mark" },
  legal: { updated: "1 January 2020", publicContactEmails: ["desk@example.com"] as [string, ...string[]] },
  homeIntro: { text: "Intro", link: "About", href: "/about" },
  pages: {
    about: { slug: "about", kicker: "About", title: "About", description: "About the catalog.", lead: "Lead", metaTitle: "About", cta: { label: "Home", href: "/" } },
    privacy: { slug: "privacy", kicker: "Privacy", title: "Privacy", description: "Privacy.", lead: "Lead" },
    terms: { slug: "terms", kicker: "Terms", title: "Terms", description: "Terms.", lead: "Lead" },
    contact: { slug: "contact", kicker: "Contact", title: "Contact", description: "Contact.", lead: "Lead", cardLabel: "Desk", cta: "Write" },
    credits: { slug: "credits", kicker: "Credits", title: "Credits", description: "Credits.", lead: "Lead" },
  },
  footer: { links: [{ label: "About", href: "/about" }] },
  topNav: { back: { home: "Home", course: "Course" } },
  countries: [{ id: "si", name: "Testland", rank: 1, placeEndings: ["a"] }],
  flags: { si: { width: 3, height: 2, shapes: [{ kind: "rect" as const, x: 0, y: 0, width: 3, height: 2 }] } },
};

export const siteFixtureV1 = {
  SITE_NAME: siteFixtureV2.metadata.siteName,
  DEFAULT_TITLE: siteFixtureV2.metadata.defaultTitle,
  TITLE_TEMPLATE: siteFixtureV2.metadata.titleTemplate,
  DEFAULT_DESCRIPTION: siteFixtureV2.metadata.defaultDescription,
  OG_IMAGE_ALT: siteFixtureV2.metadata.ogImageAlt,
  LEGAL_UPDATED: siteFixtureV2.legal.updated,
  PUBLIC_CONTACT_EMAILS: siteFixtureV2.legal.publicContactEmails,
  HOME_INTRO: siteFixtureV2.homeIntro,
  ABOUT_PAGE: siteFixtureV2.pages.about,
  PRIVACY_PAGE: siteFixtureV2.pages.privacy,
  TERMS_PAGE: siteFixtureV2.pages.terms,
  CONTACT_PAGE: siteFixtureV2.pages.contact,
  CREDITS_PAGE: siteFixtureV2.pages.credits,
  FOOTER_LINKS: siteFixtureV2.footer.links,
  TOP_NAV_BACK_HOME: siteFixtureV2.topNav.back.home,
  TOP_NAV_BACK_COURSE: siteFixtureV2.topNav.back.course,
  COUNTRIES: siteFixtureV2.countries,
  flags: siteFixtureV2.flags,
};
