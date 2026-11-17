/** Home row kinds. Continue is derived from progress; author and curated name a shelf. The database CHECK reads `homeRowKinds`. */
export const homeRowKind = {
  continue: "continue",
  author: "author",
  curated: "curated",
} as const;

export const homeRowKinds = [homeRowKind.continue, homeRowKind.author, homeRowKind.curated] as const;
