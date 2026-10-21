import test from 'node:test';
import assert from 'node:assert/strict';
import { safeWebUrl, renderSearchResult, RealtimeWebSearch } from './realtime-web-search.js';

function documentStub() {
  const doc = { createElement: tag => new Element(tag), createTextNode: text => ({ textContent: text }) };
  class Element {
    constructor(tag) { this.tag = tag; this.children = []; this.ownerDocument = doc; }
    append(...children) { this.children.push(...children); }
    replaceChildren(...children) { this.children = children; }
    setAttribute(key, value) { this[key] = value; }
  }
  return doc;
}

test('citation links replace annotations while HTML and unicode remain plain text', () => {
  const doc = documentStub();
  const host = doc.createElement('div');
  const prefix = '☀️ <img src=x onerror=alert(1)> ';
  const start = Array.from(prefix).length;
  renderSearchResult(host, { answer: prefix + '[cite] Ende', citations: [
    { start, end: start + 6, url: 'https://example.com/weather', title: '<b>Weather</b>' },
  ] });
  const nodes = host.children[0].children;
  assert.equal(nodes[0].textContent, prefix);
  assert.equal(nodes[1].tag, 'a');
  assert.equal(nodes[1].href, 'https://example.com/weather');
  assert.equal(nodes[1].textContent, '[1]');
  assert.equal(nodes[2].textContent, ' Ende');
  assert.equal(nodes.filter(node => node.tag === 'img').length, 0);
  for (const url of ['javascript:alert(1)', 'data:text/html,test', '//evil.test',
    'https://user:password@example.com', 'https://example.com\\@evil.test']) {
    assert.equal(safeWebUrl(url), false);
  }
});

test('stopping the call aborts a pending fetch and late results do not render', async () => {
  const savedFetch = globalThis.fetch;
  let resolve;
  let signal;
  globalThis.fetch = async (_url, options) => {
    signal = options.signal;
    return await new Promise(done => { resolve = done; });
  };
  try {
    const host = documentStub().createElement('section');
    const client = new RealtimeWebSearch(host);
    const pending = client.search('Aktuelles Wetter');
    const rejected = assert.rejects(pending, /abgebrochen/);
    client.stop();
    assert.equal(signal.aborted, true);
    resolve({ ok: true, json: async () => ({ status: 'ok', answer: 'Late result', citations: [] }) });
    await rejected;
    assert.equal(host.children[0].children[2].children.length, 0);
    assert.equal(client.pending.size, 0);
  } finally { globalThis.fetch = savedFetch; }
});

test('search without a UI host still returns model results and supports cancellation', async () => {
  const savedFetch = globalThis.fetch;
  try {
    const result = { status: 'ok', answer: 'Current result', citations: [] };
    globalThis.fetch = async () => ({ ok: true, json: async () => result });
    const client = new RealtimeWebSearch();
    client.reset();
    assert.equal(await client.search('Current weather'), result);
    assert.equal(client.pending.size, 0);
    let finish;
    let signal;
    globalThis.fetch = async (_url, options) => {
      signal = options.signal;
      return new Promise(resolve => { finish = resolve; });
    };
    const pending = client.search('Next query');
    const rejected = assert.rejects(pending, /abgebrochen/);
    client.stop();
    assert.equal(signal.aborted, true);
    finish({ ok: true, json: async () => result });
    await rejected;
    client.reset();
    assert.equal(client.pending.size, 0);
  } finally { globalThis.fetch = savedFetch; }
});
