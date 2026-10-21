import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFileSync } from 'node:fs';

test('the complete initial UI markup uses English, including hidden controls and accessible names', () => {
  const source = readFileSync(new URL('./main.js', import.meta.url), 'utf8');
  const app = { innerHTML: '' };
  vm.runInNewContext(source.slice(source.indexOf('const cameraGear ='), source.indexOf('const helpTips =')), { app });
  for (const label of ['Conversation settings', 'Conversation with', 'Start conversation',
    'Conversation language', 'German', 'English', 'Local · Qwen', 'Local · Piper',
    'Camera views', 'Reset robot', 'Stop model run', 'Unload model', 'Torque on',
    'Torque off', 'Brightness', 'Exposure', 'Close conversation settings']) {
    assert.ok(app.innerHTML.includes(label), `Missing English UI label: ${label}`);
  }
  assert.doesNotMatch(app.innerHTML,
    /Gespräch|Einstellungen|Helligkeit|Belichtung|Kamera|Stimme|Roboter|Lokal|Deutsch|Suchstart|Drehmoment|übernehmen/);
  assert.match(app.innerHTML, /name="conversation-language" value="German"/);
  assert.match(app.innerHTML, /name="conversation-language" value="English"/);
});

test('the browser document declares English as its interface language', () => {
  const html = readFileSync(new URL('../index.html', import.meta.url), 'utf8');
  assert.match(html, /<html lang="en">/);
  assert.match(html, /<title>SO101 robotalk · Conversation<\/title>/);
});
