import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { legalSegments } from "./legal.ts";
import { installSiteData, parseSiteData } from "./site-data.ts";

const data = parseSiteData(JSON.parse(readFileSync(new URL("../../../content/site/site-data.v2.json", import.meta.url), "utf8")));
installSiteData(data);
const ABOUT_PAGE = data.pages.about;
const LEGAL_EMAIL = data.legal.publicContactEmails[0];
const LEGAL_PAGES = [data.pages.privacy, data.pages.terms, data.pages.contact] as const;
const LEGAL_UPDATED = data.legal.updated;
const PUBLIC_CONTACT_EMAILS = data.legal.publicContactEmails;

const manifestoStrings = (value: unknown, out: string[] = []): string[] => {
  if (typeof value === "string") out.push(value);
  else if (Array.isArray(value)) for (const item of value) manifestoStrings(item, out);
  else if (value !== null && typeof value === "object") for (const item of Object.values(value)) manifestoStrings(item, out);
  return out;
};
const allText = (page: (typeof LEGAL_PAGES)[number]) => [page.kicker, page.title, page.description, page.lead, ...(page.sections ?? []).flatMap((section) => [section.h, ...("p" in section ? section.p ?? [] : []), ...("ul" in section ? section.ul ?? [] : []), ...("after" in section ? section.after ?? [] : [])])];

/** Every public word of the About page. */
const aboutText = () => [ABOUT_PAGE.kicker, ABOUT_PAGE.title, ABOUT_PAGE.description, ABOUT_PAGE.lead, ...(ABOUT_PAGE.body ?? []), ABOUT_PAGE.wink, ABOUT_PAGE.closing];

describe("legal pages copy", () => {
  it("keeps the date and the single contact address", () => {
    expect(LEGAL_UPDATED).toMatch(/^\d{1,2} [A-Z][a-z]+ \d{4}$/);
    expect(LEGAL_EMAIL).toBe("contact@openuniversity.si");
  });

  for (const page of LEGAL_PAGES) {
    it(`${page.slug} has a title, a short description, a lead and non-empty sections`, () => {
      expect(page.title).not.toBe("");
      expect(page.description.length).toBeGreaterThan(0);
      expect(page.description.length).toBeLessThanOrEqual(160);
      expect(page.lead).not.toBe("");
      expect((page.sections ?? []).length).toBeGreaterThanOrEqual(1);
      for (const section of page.sections ?? []) {
        expect(section.h).not.toBe("");
        const body = [...("p" in section ? section.p ?? [] : []), ...("ul" in section ? section.ul ?? [] : []), ...("after" in section ? section.after ?? [] : [])];
        expect(body.length).toBeGreaterThan(0);
        for (const text of body) expect(text.trim()).not.toBe("");
      }
    });

    it(`${page.slug} mentions no email address other than ${LEGAL_EMAIL}`, () => {
      const addresses = allText(page).flatMap((text) => text.match(/[\w.+-]*@[\w.-]*/g) ?? []).map((address) => address.replace(/\.$/, ""));
      for (const address of addresses) expect(address).toBe(LEGAL_EMAIL);
    });
  }

  it("privacy and terms point to the address", () => {
    expect(allText(LEGAL_PAGES[0]).join(" ")).toContain(LEGAL_EMAIL);
    expect(allText(LEGAL_PAGES[1]).join(" ")).toContain(LEGAL_EMAIL);
  });
});

// 2026-10-11: the lecture embed plays from www.youtube.com (youtube-nocookie.com stops background play on Opera Android), so the Privacy must say
// plainly that YouTube's player may set YouTube cookies, and must not name nocookie. See youtube-engine.test.ts.
describe("privacy: YouTube cookies", () => {
  const privacy = LEGAL_PAGES[0];
  const section = (heading: string) => (privacy.sections ?? []).filter((entry) => entry.h === heading).flatMap((entry) => ("p" in entry ? entry.p ?? [] : [])).join(" ");
  it("says the embedded YouTube player may set YouTube cookies, in both the cookies and the YouTube sections", () => {
    expect(section("Cookies and storage")).toMatch(/embedded YouTube player.*may set YouTube cookies/);
    expect(section("YouTube videos")).toMatch(/embedded player, which may set YouTube cookies/);
  });
  it("cites the session cookie prefix of the product, never the old one", () => {
    const text = section("Cookies and storage");
    expect(text).toContain("prefixed “open-university”"); expect(text).not.toMatch(/“tower”/);
  });
  it("never names youtube-nocookie nor promises that there are no cookies at all", () => {
    for (const text of manifestoStrings(data)) { expect(text).not.toMatch(/nocookie/i); expect(text).not.toMatch(/no cookie banner/i); }
  });
});

describe("about page and home intro copy", () => {
  it("about has the site name as title, a lead, at least one paragraph, a short description and no sections", () => {
    expect(ABOUT_PAGE.title).toBe("Open University");
    expect(ABOUT_PAGE.metaTitle).toBe("About");
    expect(ABOUT_PAGE.lead).not.toBe("");
    expect((ABOUT_PAGE.body ?? []).length).toBeGreaterThanOrEqual(1);
    expect(ABOUT_PAGE.description.length).toBeLessThanOrEqual(160);
    expect("sections" in ABOUT_PAGE).toBe(false);
    expect(JSON.stringify(ABOUT_PAGE)).not.toContain("Last updated");
  });

  it("approved content hashes match approvals.json", () => {
    const raw = JSON.parse(readFileSync(new URL("../../../content/site/site-data.v2.json", import.meta.url), "utf8")) as { pages: { about: unknown }; homeIntro: unknown };
    const approvals = JSON.parse(readFileSync(new URL("../../../content/site/approvals.json", import.meta.url), "utf8")) as { about: string; homeIntro: string };
    const hash = (value: unknown) => createHash("sha256").update(JSON.stringify(value)).digest("hex");
    expect(hash(raw.pages.about)).toBe(approvals.about);
    expect(hash(raw.homeIntro)).toBe(approvals.homeIntro);
  });

  it("about keeps a two-line lead, three body paragraphs and the wink and the commitment each on a line of their own", () => {
    expect(ABOUT_PAGE.lead.split("\n")).toHaveLength(2);
    expect(ABOUT_PAGE.body).toHaveLength(3);
    expect(ABOUT_PAGE.wink).toBe("One library to rule them all.");
    expect(ABOUT_PAGE.closing).toContain("free, permanently");
    expect(ABOUT_PAGE.description.length).toBeLessThanOrEqual(160);
  });

  it("about uses an institutional voice: no community or social wording, no first-person singular, no claim of tie to a university", () => {
    const text = aboutText().join(" ");
    expect(text).not.toMatch(/communit|\bjoin\b|follow us|\bshare\b|\bfriends?\b|\bI\b|\bmy\b/i);
    expect(text).toContain("There is no affiliation with, and no endorsement from, any of them.");
    expect(text).not.toMatch(/partner|official|accredited|certificat|degree/i);
  });

});

describe("public static copy", () => {
  const texts = manifestoStrings(data);
  const emailsIn = (text: string) => text.match(/[\w.+-]+@[\w-]+(?:\.[\w-]+)+/g) ?? [];
  const allowed: readonly string[] = PUBLIC_CONTACT_EMAILS;
  // Role mailboxes only: a person's name before @openuniversity.si is never public.
  const ROLE_MAILBOXES = ["contact", "privacy", "legal", "support", "hello", "info"];
  const PERSONAL_DOMAINS = /@(?:gmail|googlemail|hotmail|outlook|live|icloud|me|yahoo)\./i;
  const unexpectedEmails = (text: string) => emailsIn(text).filter((email) => !allowed.includes(email));
  const personalEmails = (text: string) => emailsIn(text).filter((email) => PERSONAL_DOMAINS.test(email) || (email.toLowerCase().endsWith("@openuniversity.si") && !ROLE_MAILBOXES.includes(email.split("@")[0]?.toLowerCase() ?? "")));

  it("lists only role addresses as public contact emails", () => {
    expect(PUBLIC_CONTACT_EMAILS).toEqual(["contact@openuniversity.si"]);
    for (const email of PUBLIC_CONTACT_EMAILS) expect(personalEmails(email)).toEqual([]);
  });

  it("mentions no email other than the public contact address", () => {
    expect(unexpectedEmails("write to first.last@openuniversity.si or x@example.com")).toEqual(["first.last@openuniversity.si", "x@example.com"]);
    for (const text of texts) expect(unexpectedEmails(text), text).toEqual([]);
  });

  it("mentions no personal-domain email and no person's name before @openuniversity.si", () => {
    expect(personalEmails("a@gmail.com, b@hotmail.com, c@outlook.com, d@icloud.com, e@yahoo.com, someone@openuniversity.si, contact@openuniversity.si")).toEqual(["a@gmail.com", "b@hotmail.com", "c@outlook.com", "d@icloud.com", "e@yahoo.com", "someone@openuniversity.si"]);
    for (const text of texts) expect(personalEmails(text), text).toEqual([]);
  });

  // The 2026-10-11 rebrand removed the footer slogan everywhere, and the repository is private: neither claim may come back through copy.
  it("never carries the retired slogan nor claims to be open source", () => {
    for (const text of texts) {
      expect(text, text).not.toMatch(/great again/i);
      expect(text, text).not.toMatch(/open[- ]source|código aberto/i);
    }
  });

  // Author names stay free on course and lesson pages (they come from the catalog), never in the institutional copy.
  it.each(["Peterson", "Vervaeke", "Bello", "Daniel", "personal project", "solo"])("never mentions %s", (word) => {
    for (const text of texts) expect(text.toLowerCase()).not.toContain(word.toLowerCase());
  });
});

// Open University (openuniversity.si) is the name of the site: an initiative of The Tower, never an educational institution. The brand never
// claims a tie with any university, nor with The Open University (UK). Institutions appear only as sources, in the catalog.
describe("Open University copy", () => {
  const published = manifestoStrings(data);
  const ALLOWED = ["openuniversity.si", "Open University", "The Open University (United Kingdom)", "any other university or institution whose lectures appear here",
    "full university courses", "The world's great universities", "Universities publish", "licenses of the university and author cover images",
    // The session-cookie prefix (src/kernel/brand-ids.ts), a technical identifier the Privacy cites.
    "“open-university”"];
  const withoutAllowed = (text: string) => ALLOWED.reduce((rest, phrase) => rest.replaceAll(phrase, ""), text);
  const joined = (page: (typeof LEGAL_PAGES)[number]) => allText(page).join(" ");

  it("names Open University in About, Terms, Privacy and Contact and The Tower as the organization behind it", () => {
    for (const text of [aboutText().join(" "), joined(LEGAL_PAGES[1]), joined(LEGAL_PAGES[2])]) {
      expect(text).toContain("Open University");
      expect(text).toMatch(/initiative of The Tower/);
    }
    expect(joined(LEGAL_PAGES[1])).toContain("at openuniversity.si");
  });

  // Approved by Daniel on 14 October 2026: the data controller is Open University itself, reached at contact@openuniversity.si.
  it("names Open University alone as the data controller in Privacy", () => {
    expect(joined(LEGAL_PAGES[0])).toContain("Open University is responsible for the data described here. For anything about your data, write to contact@openuniversity.si.");
    expect(joined(LEGAL_PAGES[0])).not.toMatch(/The Tower/);
  });

  it("says the word university only inside the Open University name, the address or the non-affiliation notice", () => {
    for (const text of published) expect(withoutAllowed(text), text).not.toMatch(/universit/i);
  });

  // The About names universities as the SOURCE of the lectures (plural, "world's great universities", "Universities publish"): never in the singular, which would
  // read as Open University calling itself one.
  it("lets the About name universities as sources but never call Open University one", () => {
    // "full university courses" (meta description) describes the courses, which come from universities.
    const brandOnly = ["openuniversity.si", "Open University"];
    const about = brandOnly.reduce((rest, phrase) => rest.replaceAll(phrase, ""), aboutText().join(" ")).replaceAll("full university courses", "");
    expect(about).not.toMatch(/\buniversity\b/i);
    expect(about).toMatch(/universities/i);
    expect(about).not.toMatch(/(?:is|are|as) an? (?:\w+ )?universit/i);
  });

  it("states the non-affiliation with The Open University (United Kingdom) in the Terms", () => {
    const terms = joined(LEGAL_PAGES[1]);
    expect(terms).toContain("Open University is not affiliated with, or endorsed by, The Open University (United Kingdom) or any other university or institution whose lectures appear here.");
    expect(terms).toContain("not of an educational institution");
  });

  it("claims no partnership, endorsement, accreditation, degree or certificate", () => {
    for (const text of published) {
      expect(text, text).not.toMatch(/partner|accredit|certificat|official|in association with/i);
      for (const match of text.matchAll(/\b(endorsed|affiliated|degrees?)\b/gi)) {
        const sentence = text.split(/(?<=\.)\s/).find((part) => part.includes(match[0])) ?? "";
        expect(sentence, text).toMatch(/\b(not|no|nor|does not|without)\b/i);
      }
    }
  });

  // DELIBERATE REWRITE (2026-10-11, Daniel's decision). This guardian used to forbid every fixed promise ("always", "forever", "never charge")
  // in the Open University paragraphs, because "free" was only "free to use today". The founder now makes ONE permanent public commitment:
  // Open University is free, permanently: no ads, no paywall, no charge to watch. It is deliberately narrow, so this test no longer bans
  // "permanently"; it pins where the word may appear and what it may promise:
  //   1. only the approved commitment sentences contain "permanently", "will not change" or "committed never" (Terms description,
  //       the Terms section "Free, permanently" and its heading, Privacy "committed never to");
  //   2. it covers cost and access only, and the Terms say in the same section that it is NOT a promise that every lecture stays online;
  //   3. every other fixed promise stays forbidden ("forever", "guarantee", "100%", "never charge"), and "always" appears only in No warranty.
  // Changing the commitment means changing About, Terms and Privacy together, and this test with them. (The About commitment line from the v3 draft is not
  // in the interim About; it returns with the rewritten About, and this test then lists it too.)
  describe("the permanent free commitment", () => {
    const terms = LEGAL_PAGES[1];
    const freeSection = (terms.sections ?? []).find((section) => section.h === "Free, permanently");
    const COMMITMENT_TEXTS = [
      ABOUT_PAGE.description,
      ABOUT_PAGE.closing ?? "",
      terms.description,
      "Free, permanently",
      ...(freeSection?.p ?? []),
      "Open University shows no advertising and has committed never to.",
    ];
    const isCommitment = (text: string) => COMMITMENT_TEXTS.some((allowed) => text.includes(allowed));

    it("appears only in the approved commitment sentences", () => {
      expect(freeSection).toBeDefined();
      for (const text of published) {
        if (/permanently|will not change|committed never/i.test(text)) expect(isCommitment(text), text).toBe(true);
      }
    });

    it("is limited to cost and access, and says it is not a promise that every lecture stays online", () => {
      const text = (freeSection?.p ?? []).join(" ");
      expect(text).toContain("Open University is free to use, permanently.");
      expect(text).toContain("We will not show ads, put lectures behind a paywall or charge anyone to watch.");
      expect(text).toContain("This is a commitment about cost and access; it is not a promise that every lecture will stay online (see No warranty).");
      expect(joined(terms)).toContain("with no promise that it will always be available or error-free, or that any lecture will stay online");
    });

    it("keeps every other fixed promise forbidden", () => {
      for (const text of published) {
        expect(text, text).not.toMatch(/\b(forever|guarantee[sd]?|100 ?%|never charge)\b/i);
        expect(text.replace("no promise that it will always be available", ""), text).not.toMatch(/\balways\b/i);
      }
    });
  });
});

describe("legalSegments", () => {
  it("round-trips every string of the manifesto", () => {
    for (const text of manifestoStrings(data)) expect(legalSegments(text).map((segment) => segment.text).join("")).toBe(text);
  });

  it("links the email as mailto without the sentence's final period", () => {
    expect(legalSegments("write to contact@openuniversity.si.")).toEqual([
      { kind: "text", text: "write to " },
      { kind: "link", text: "contact@openuniversity.si", href: "mailto:contact@openuniversity.si", external: false },
      { kind: "text", text: "." },
    ]);
  });

  it("links https URLs inside parentheses as external links", () => {
    expect(legalSegments("Policy (https://policies.google.com/privacy) and")).toEqual([
      { kind: "text", text: "Policy (" },
      { kind: "link", text: "https://policies.google.com/privacy", href: "https://policies.google.com/privacy", external: true },
      { kind: "text", text: ") and" },
    ]);
  });

  it("leaves plain text alone", () => {
    expect(legalSegments("No links here.")).toEqual([{ kind: "text", text: "No links here." }]);
  });
});

describe("legal guards reject a mutated manifesto", () => {
  const emailsIn = (text: string) => text.match(/[\w.+-]+@[\w-]+(?:\.[\w-]+)+/g) ?? [];
  const draft = () => structuredClone(data) as { homeIntro: { text: string; link: string; href: string }; metadata: { defaultDescription: string } };
  it("fails when any string names an email outside publicContactEmails", () => {
    const next = draft();
    next.homeIntro = { ...data.homeIntro, text: `${data.homeIntro.text} secret@gmail.com` };
    expect(() => {
      for (const text of manifestoStrings(next)) for (const email of emailsIn(text)) expect(data.legal.publicContactEmails).toContain(email);
    }).toThrow();
  });
  it("fails when any string states a forbidden affiliation", () => {
    const next = draft();
    next.metadata = { ...data.metadata, defaultDescription: `${data.metadata.defaultDescription} We are a partner of a university.` };
    expect(() => {
      for (const text of manifestoStrings(next)) expect(text).not.toMatch(/partner|in association with/i);
    }).toThrow();
  });
});
