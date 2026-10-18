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
  box: Box;
}

export interface PendingComment {
  id: number;
  component_id: string;
  label: string;
  text: string;
}

/** Comments per batch (contracts/api.md). */
export const MAX_COMMENTS = 20;
