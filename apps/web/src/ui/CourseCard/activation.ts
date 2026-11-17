interface CardActivation {
  readonly button: number;
  readonly ctrlKey: boolean;
  readonly metaKey: boolean;
  readonly shiftKey: boolean;
  readonly altKey: boolean;
}

/** Spec 07: native modified/new-tab activation bypasses the first-click selection. */
export function shouldSelectCard(event: CardActivation, selected: boolean): boolean {
  return !selected && event.button === 0 && !event.ctrlKey && !event.metaKey && !event.shiftKey && !event.altKey;
}
