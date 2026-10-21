/** A box in canvas coordinates (the prototype's own 1200 px space, before any zoom). */
export interface Box {
  left: number;
  top: number;
  width: number;
  height: number;
}

/** One commentable `[data-cid]` element of the prototype page. */
export interface Target {
  cid: string;
  label: string;
  kind: string;
  /** Position of its page section in the canvas; null when the page has no sections. */
  page: number | null;
  box: Box;
}

/** One `<section data-page>` of the canvas (contracts/api.md 2.0, Prototype HTML). */
export interface Page {
  /** Position among the sections, top to bottom. */
  index: number;
  /** Its `data-page` number. */
  n: number;
  /** Its `data-page-name`, or "Page <n>". */
  name: string;
  /** Canvas coordinates of the section. */
  top: number;
  height: number;
}

export interface PendingComment {
  id: number;
  component_id: string;
  label: string;
  text: string;
}

/** Comments per batch (contracts/api.md). */
export const MAX_COMMENTS = 20;
