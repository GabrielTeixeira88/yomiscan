/**
 * Identity of the document a Study selection was made on.
 *
 * Single-page readers change chapters with history.pushState, which neither unloads the
 * page nor fires pagehide. A capture or result from another document must be discarded.
 * The hash is ignored: readers commonly rewrite it while the same images stay on screen.
 */
export function documentKey(location: Pick<Location, "origin" | "pathname" | "search">): string {
  return location.origin + location.pathname + location.search;
}

export const STALE_SELECTION_MESSAGE =
  "The page changed while this selection was being read, so the result was discarded. Select the text again.";
