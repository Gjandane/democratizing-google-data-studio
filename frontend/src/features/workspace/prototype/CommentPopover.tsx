import { useLayoutEffect, useRef, useState } from 'react';
import { Button } from '../../../components/Button';
import { Popover } from '../../../components/Popover';
import { TextArea } from '../../../components/Input';

export interface Anchor {
  /** Box of the commented element in the outer (scaled) coordinates. */
  left: number;
  top: number;
  bottom: number;
}

interface CommentPopoverProps {
  label: string;
  anchor: Anchor;
  outerWidth: number;
  outerHeight: number;
  onAdd: (text: string) => void;
  onClose: () => void;
}

/** Width of the card (w-80), used until it is measured. */
const FALLBACK_WIDTH = 320;
/** Gap between the element and the card (spacing step 2). */
const GAP = 8;

/**
 * The dark comment card. It sits below the element, or above when the bottom would run past the
 * canvas and there is room above; it never overlaps the element's box vertically.
 */
export function CommentPopover({ label, anchor, outerWidth, outerHeight, onAdd, onClose }: CommentPopoverProps) {
  const [text, setText] = useState('');
  const area = useRef<HTMLTextAreaElement>(null);
  const content = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ w: 0, h: 0 });

  // Measure the card (the dialog is this content's parent) so the placement can use its height.
  useLayoutEffect(() => {
    const card = content.current?.parentElement;
    if (!card) return;
    const { width, height } = card.getBoundingClientRect();
    if (width !== size.w || height !== size.h) setSize({ w: width, h: height });
  });

  const width = size.w || FALLBACK_WIDTH;
  const below = anchor.bottom + GAP;
  const above = anchor.top - size.h - GAP;
  const top = below + size.h > outerHeight && above >= 0 ? above : below;
  const left = outerWidth > 0 ? Math.min(Math.max(anchor.left, 0), Math.max(0, outerWidth - width)) : anchor.left;

  const blank = text.trim() === '';
  const add = () => {
    if (!blank) onAdd(text.trim());
  };

  return (
    <Popover open onClose={onClose} label={`Comment on ${label}`} initialFocus={area} className="absolute w-80" style={{ left, top }}>
      <div ref={content} className="flex flex-col gap-2">
        <p className="text-caption text-surface/70">“{label}”</p>
        <TextArea
          ref={area}
          label="Comment"
          hideLabel
          placeholder="What should change here?"
          value={text}
          onChange={(event) => setText(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {
              event.preventDefault();
              add();
            }
          }}
        />
        <div className="flex justify-end gap-2">
          <Button variant="inverse" size="sm" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="accent" size="sm" disabled={blank} onClick={add}>
            Add
          </Button>
        </div>
      </div>
    </Popover>
  );
}
