/** One event of a text/event-stream body: the `event:` name and the joined `data:` lines. */
export interface RawSseEvent {
  event: string;
  data: string;
}

/** Parses an SSE body (the fixture events.sse). Comment lines (":") are skipped. */
export function parseSse(body: string): RawSseEvent[] {
  const events: RawSseEvent[] = [];
  for (const block of body.replace(/\r\n?/g, '\n').split(/\n{2,}/)) {
    let event = 'message';
    const data: string[] = [];
    for (const line of block.split('\n')) {
      if (line === '' || line.startsWith(':')) continue;
      const colon = line.indexOf(':');
      const field = colon === -1 ? line : line.slice(0, colon);
      const value = colon === -1 ? '' : line.slice(colon + 1).replace(/^ /, '');
      if (field === 'event') event = value;
      else if (field === 'data') data.push(value);
    }
    if (data.length > 0) events.push({ event, data: data.join('\n') });
  }
  return events;
}
