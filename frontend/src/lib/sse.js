/**
 * SSE client for /api/ask/stream.
 *
 * We use fetch() with a streaming ReadableStream rather than EventSource,
 * because EventSource is GET-only and we need POST with JSON body and cookies.
 *
 * Calls `onEvent({ event, data })` for every SSE event. Awaits completion.
 */
export async function streamAsk({ url, body, onEvent, signal }) {
  const res = await fetch(url, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    body: JSON.stringify(body),
    signal
  });

  if (!res.ok || !res.body) {
    let detail = '';
    try {
      detail = (await res.json())?.detail || '';
    } catch {
      /* noop */
    }
    throw new Error(detail || `Request failed (${res.status})`);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = '';

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });

    // SSE messages are separated by a blank line
    let sepIndex;
    while ((sepIndex = buf.indexOf('\n\n')) !== -1) {
      const raw = buf.slice(0, sepIndex);
      buf = buf.slice(sepIndex + 2);

      let event = 'message';
      const dataLines = [];
      for (const line of raw.split('\n')) {
        if (line.startsWith('event: ')) event = line.slice(7).trim();
        else if (line.startsWith('data: ')) dataLines.push(line.slice(6));
      }
      if (dataLines.length === 0) continue;
      let data;
      try {
        data = JSON.parse(dataLines.join('\n'));
      } catch {
        data = dataLines.join('\n');
      }
      onEvent({ event, data });
    }
  }
}
