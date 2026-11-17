/**
 * Empty results, the first element, and the non-empty floor of one (D-050).
 * The same number with a different job is a different key.
 * A zero that starts a paint, or a coefficient, is not one of these.
 * `LIMIT 1` is the one row and stays a literal.
 */
export const EXTENT = {
  /** A length or a count with nothing in it. */
  empty: 0,
  /** The first element of a row list, a match, or a string. */
  first: 0,
  /** The smallest non-empty size. Not the one row of `LIMIT 1`. */
  one: 1,
} as const;
