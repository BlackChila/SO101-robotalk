// Web content is rendered as text and validated links, never HTML.
export function safeWebUrl(value) {
  if (typeof value !== 'string' || value.length > 1600 || /[\s\\]/.test(value)) return false;
  try {
    const url = new URL(value);
    return ['http:', 'https:'].includes(url.protocol) && Boolean(url.hostname) && !url.username && !url.password;
  } catch { return false; }
}

export function renderSearchResult(host, result) {
  const doc = host.ownerDocument;
  const paragraph = doc.createElement('p');
  const chars = Array.from(result.answer || '');
  let cursor = 0;
  const citations = (result.citations || []).filter(cite => safeWebUrl(cite.url)
    && Number.isInteger(cite.start) && Number.isInteger(cite.end)
    && cite.start >= 0 && cite.start <= cite.end && cite.end <= chars.length)
    .sort((a, b) => a.start - b.start);
  for (const [index, cite] of citations.entries()) {
    if (cite.start < cursor) continue;
    paragraph.append(doc.createTextNode(chars.slice(cursor, cite.start).join('')));
    const link = doc.createElement('a');
    link.href = cite.url;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    link.textContent = `[${index + 1}]`;
    link.title = cite.title || cite.url;
    link.setAttribute('aria-label', `Quelle ${index + 1}: ${cite.title || cite.url}`);
    paragraph.append(link);
    cursor = cite.end;
  }
  paragraph.append(doc.createTextNode(chars.slice(cursor).join('')));
  host.replaceChildren(paragraph);
}

export class RealtimeWebSearch {
  constructor(host = null) {
    this.host = host;
    this.pending = new Map();
  }

  stop() {
    for (const [controller, status] of this.pending) {
      if (status) status.textContent = 'Internetsuche abgebrochen.';
      controller.abort();
    }
    this.pending.clear();
  }

  reset() {
    this.stop();
    this.host?.replaceChildren();
    if (this.host) this.host.hidden = true;
  }

  async search(query) {
    if (typeof query !== 'string' || !query.trim() || query.length > 500) {
      throw new Error('Bitte eine Suchanfrage mit 1 bis 500 Zeichen angeben.');
    }
    let status = null;
    let answer = null;
    if (this.host) {
      const doc = this.host.ownerDocument;
      const card = doc.createElement('details');
      card.open = true;
      const title = doc.createElement('summary');
      title.textContent = `Internetsuche · ${query}`;
      status = doc.createElement('p');
      status.setAttribute('role', 'status');
      status.textContent = 'Ich suche im Internet …';
      answer = doc.createElement('div');
      card.append(title, status, answer);
      this.host.append(card);
      this.host.hidden = false;
      while (this.host.children.length > 5) this.host.firstElementChild.remove();
    }
    const controller = new AbortController();
    this.pending.set(controller, status);
    const timeout = setTimeout(() => controller.abort(), 40_000);
    try {
      const response = await fetch('/api/conversation/realtime/search', {
        method: 'POST', headers: { 'Content-Type': 'application/json', 'X-SO101-Conversation': 'realtime-tool' },
        body: JSON.stringify({ query }), signal: controller.signal,
      });
      const result = await response.json();
      if (controller.signal.aborted) throw new Error('Internetsuche abgebrochen.');
      if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : 'Internetsuche fehlgeschlagen.');
      if (result.status !== 'ok' || typeof result.answer !== 'string' || !Array.isArray(result.citations)) {
        throw new Error('Ungültiges Suchergebnis.');
      }
      if (answer) renderSearchResult(answer, result);
      if (status) status.textContent = 'Suchergebnis · Quellen sind im Text verlinkt.';
      return result;
    } catch (error) {
      const message = controller.signal.aborted ? 'Internetsuche abgebrochen oder Zeitlimit erreicht.' : error.message;
      if (status) status.textContent = message;
      throw new Error(message);
    } finally {
      clearTimeout(timeout);
      this.pending.delete(controller);
    }
  }
}
