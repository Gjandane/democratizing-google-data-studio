import { Maximize2, Minimize2 } from 'lucide-react';
import { useState } from 'react';
import type { ReferenceItem } from '../../../api/types';
import { Button } from '../../../components/Button';

/** Both frame sizes (w-32 h-20, w-120 h-75) share this width / height. */
const FRAME_ASPECT = 1.6;
const unit = (n: number) => Math.min(1, Math.max(0, n));

/**
 * The recreate screenshot in a fixed frame (no layout shift), with the hovered or focused item's
 * box drawn over it as a 2 px primary outline. The frame can grow to 480 px wide.
 */
export function AnalysisImage({ src, alt, name, box }: { src: string | null; alt: string; name: string; box: ReferenceItem['box'] | null }) {
  const [expanded, setExpanded] = useState(false);
  // The image's own width / height, once loaded: object-contain letterboxes it inside the frame.
  const [aspect, setAspect] = useState<number | null>(null);
  const fw = aspect && aspect < FRAME_ASPECT ? aspect / FRAME_ASPECT : 1;
  const fh = aspect && aspect > FRAME_ASPECT ? FRAME_ASPECT / aspect : 1;
  const x = unit(box?.x ?? 0);
  const y = unit(box?.y ?? 0);
  const outline = box && {
    left: `${((1 - fw) / 2 + x * fw) * 100}%`,
    top: `${((1 - fh) / 2 + y * fh) * 100}%`,
    width: `${Math.min(unit(box.w), 1 - x) * fw * 100}%`,
    height: `${Math.min(unit(box.h), 1 - y) * fh * 100}%`,
  };
  return (
    <li className={`min-w-0 ${expanded ? 'w-120' : 'w-32'}`}>
      <div className={`relative ${expanded ? 'h-75 w-120' : 'h-20 w-32'}`}>
        {src && (
          <img
            src={src}
            alt={alt}
            onLoad={(event) => {
              const { naturalWidth: w, naturalHeight: h } = event.currentTarget;
              if (w > 0 && h > 0) setAspect(w / h);
            }}
            className="size-full rounded-control border border-border bg-surface-muted object-contain"
          />
        )}
        {outline && <span aria-hidden="true" data-reference-box="" className="pointer-events-none absolute outline-2 outline-primary" style={outline} />}
      </div>
      <div className="flex min-w-0 items-center gap-1">
        <p title={name} className="min-w-0 flex-1 truncate text-caption text-text-muted">{name}</p>
        {src && (
          <Button
            size="sm"
            variant="ghost"
            aria-pressed={expanded}
            aria-label="Enlarge the reference image"
            title={expanded ? 'Shrink' : 'Enlarge'}
            icon={expanded ? <Minimize2 aria-hidden="true" /> : <Maximize2 aria-hidden="true" />}
            onClick={() => setExpanded((open) => !open)}
          />
        )}
      </div>
    </li>
  );
}
