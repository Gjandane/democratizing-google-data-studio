// Fake screencast frames for the mock build run: base64 JPEG without the data-URL prefix.
// The colors below are fake engine output, not UI, so raw hex is fine here.

/** A 1x1 JPEG, used where there is no canvas (jsdom). */
const PLACEHOLDER =
  '/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAP//////////////////////////////////////////////////////////////////////////////////////wgALCAABAAEBAREA/8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABPxA=';

/** Draws a 640x400 frame for `line` (the recipe op) at `index`; falls back to a constant without a canvas 2d context. */
export function mockFrame(line: string, index: number): string {
  // jsdom has no canvas and logs when asked for one.
  if (typeof document === 'undefined' || /jsdom/i.test(navigator.userAgent)) return PLACEHOLDER;
  let ctx: CanvasRenderingContext2D | null = null;
  const canvas = document.createElement('canvas');
  try {
    canvas.width = 640;
    canvas.height = 400;
    ctx = canvas.getContext('2d');
  } catch {
    ctx = null;
  }
  if (!ctx) return PLACEHOLDER;
  ctx.fillStyle = '#F1F5F9';
  ctx.fillRect(0, 0, 640, 400);
  ctx.fillStyle = '#FFFFFF';
  ctx.fillRect(24, 56, 592, 320);
  ctx.fillStyle = '#1E40AF';
  ctx.fillRect(0, 0, 640, 40);
  ctx.fillStyle = '#FFFFFF';
  ctx.font = '600 16px sans-serif';
  ctx.fillText('Data Studio', 16, 26);
  // Bars grow with the op index, so each frame differs.
  ctx.fillStyle = '#93C5FD';
  for (let i = 0; i < 6; i++) {
    const h = 40 + ((index * 37 + i * 53) % 120);
    ctx.fillRect(48 + i * 60, 340 - h, 40, h);
  }
  ctx.fillStyle = '#0F172A';
  ctx.font = '14px monospace';
  ctx.fillText(`op ${index + 1}: ${line}`.slice(0, 70), 48, 90);
  const url = canvas.toDataURL('image/jpeg', 0.7);
  const comma = url.indexOf(',');
  return comma >= 0 && url.startsWith('data:image/jpeg') ? url.slice(comma + 1) : PLACEHOLDER;
}
