const assert = require('node:assert/strict');
const { execFileSync } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const root = path.resolve(__dirname, '..');
const info = JSON.parse(execFileSync(process.env.PYTHON || path.join(root, '.venv/bin/python'), ['-c', `
import json, schema, tomllib
from pathlib import Path
cases = ['a' + space + '/b / https://example.com/a/b' for space in schema.INPUT_WHITESPACE]
content = tomllib.loads(Path('content.example.toml').read_text())
samples = []
for block in schema.BLOCKS:
    rows = content[block.key] if block.repeat else [content[block.key]]
    for row in rows:
        for field in block.fields:
            if field.kind == 'list':
                samples.append(row.get(field.key, []))
print(json.dumps({'blocks': schema.describe(), 'input_rules': schema.input_rules(),
                 'cases': [{'text': text, 'expected': schema.split_list(text)} for text in cases],
                 'samples': samples}))
`], { cwd: root, encoding: 'utf8' }));

class Element {
  constructor(tag = 'div') {
    this.tagName = tag.toUpperCase();
    this.children = [];
    this.value = '';
    this.disabled = false;
    this.srcdoc = '';
    this.clientWidth = 900;
    this.style = { setProperty() {} };
    const classes = new Set();
    this.classList = {
      add: (...names) => names.forEach((name) => classes.add(name)),
      remove: (...names) => names.forEach((name) => classes.delete(name)),
      contains: (name) => classes.has(name),
      toggle: (name, enabled) => enabled ? classes.add(name) : classes.delete(name),
    };
  }

  set textContent(value) { this.text = value; this.children = []; }
  get textContent() { return this.text || ''; }
  append(...children) { this.children.push(...children); }
  addEventListener() {}
}

async function createApp() {
  const elements = new Map();
  const requests = [];
  const timers = new Set();
  const context = vm.createContext({
    document: {
      getElementById: (name) => {
        if (!elements.has(name)) elements.set(name, new Element());
        return elements.get(name);
      },
      createElement: (tag) => new Element(tag),
    },
    window: { addEventListener() {} },
    confirm: () => true,
    setTimeout: (callback) => { timers.add(callback); return callback; },
    clearTimeout: (callback) => timers.delete(callback),
    fetch: (url, options) => new Promise((resolve) => {
      requests.push({
        url, options,
        reply: (payload, status = 200) => resolve({
          ok: status === 200, status, statusText: 'Error',
          json: async () => payload,
        }),
      });
    }),
  });
  const source = fs.readFileSync(path.join(root, 'webui/app.js'), 'utf8');
  vm.runInContext(source + '\nglobalThis.app = {state, el, fromInput, toInput, touched, schedule, preview, load, save, build, updateActions};', context);
  requests.shift().reply({
    ...info, contents: [], protected: [], themes: ['theme.toml'],
    default_theme: 'theme.toml', default_content: null, out_dir: '/tmp/build', png: true,
  });
  await new Promise((resolve) => setImmediate(resolve));
  return { ...context.app, requests, timers };
}

function previewResult(overrides = {}) {
  return { html: 'approximate', preview_html: 'current PDF', pages: 1, blanks: [],
    preview_mode: 'pdf', shown_pages: 1, width: 794, height: 1123, ...overrides };
}

test('Python and browser share every whitespace separator and preserve example arrays', async () => {
  const app = await createApp();
  for (const { text, expected } of info.cases) {
    assert.deepEqual(Array.from(app.fromInput({ kind: 'list' }, text)), expected);
  }
  for (const items of info.samples) {
    const field = { kind: 'list' };
    assert.deepEqual(Array.from(app.fromInput(field, app.toInput(field, items))), items);
  }
  assert.deepEqual(Array.from(app.fromInput({ kind: 'list' }, 'Python / https://example.com/a/b')),
    ['Python', 'https://example.com/a/b']);
});

test('old preview responses cannot validate or replace newer content', async () => {
  const app = await createApp();
  const pending = app.preview();
  app.touched();
  await app.preview();
  assert.equal(app.requests.length, 1);
  app.requests.shift().reply(previewResult({ preview_html: 'stale PDF' }));
  await pending;
  assert.equal(app.el.sheet.srcdoc, '');
  assert.equal(app.el.render.disabled, true);
  assert.equal(app.state.previewReady, false);
  const latest = app.preview();
  app.requests.shift().reply(previewResult());
  await latest;
  assert.equal(app.el.sheet.srcdoc, 'current PDF');
  assert.equal(app.el.render.disabled, false);
});

test('overflow and preview errors keep PDF generation disabled', async () => {
  const app = await createApp();
  const pending = app.preview();
  app.requests.shift().reply(previewResult({ pages: 2 }));
  await pending;
  assert.equal(app.el.render.disabled, true);
  app.schedule();
  const failed = app.preview();
  app.requests.shift().reply({ error: 'failed' }, 500);
  await failed;
  assert.equal(app.el.render.disabled, true);
  assert.equal(app.state.previewReady, false);
});

test('edits during save remain dirty and repeated saves are coalesced', async () => {
  const app = await createApp();
  app.state.fileName = 'content.toml';
  app.state.fileRevision = 'old-revision';
  app.touched();
  const pending = app.save();
  await app.save();
  assert.equal(app.requests.length, 1);
  const request = app.requests.shift();
  assert.equal(JSON.parse(request.options.body).revision, 'old-revision');
  app.state.content.summary.text = 'new edit';
  app.touched();
  request.reply({ name: 'content.toml', path: '/tmp/content.toml', revision: 'saved-revision', blanks: [] });
  await pending;
  assert.equal(app.state.dirty, true);
  assert.equal(app.state.fileRevision, 'saved-revision');
  assert.equal(app.el.save.classList.contains('dirty'), true);
});

test('save as never borrows the revision of a different file', async () => {
  const app = await createApp();
  app.state.fileName = 'content.toml';
  app.state.fileRevision = 'old-revision';
  app.el.name.value = 'content.other.toml';
  app.touched();
  const pending = app.save();
  const request = app.requests.shift();
  assert.equal(JSON.parse(request.options.body).revision, null);
  request.reply({ error: 'already exists' }, 409);
  await pending;
  assert.equal(app.state.dirty, true);
  assert.equal(app.state.fileName, 'content.toml');
});

test('loading does not discard edits made while the request was pending', async () => {
  const app = await createApp();
  const original = app.state.content;
  const pending = app.load('content.other.toml');
  app.touched();
  app.requests.shift().reply({ name: 'content.other.toml', content: {}, revision: 'other' });
  await pending;
  assert.equal(app.state.content, original);
  assert.equal(app.state.dirty, true);
});

test('stale build results do not offer old downloads or re-enable generation', async () => {
  const app = await createApp();
  app.state.previewReady = true;
  app.state.pages = 1;
  app.updateActions();
  const pending = app.build();
  app.touched();
  app.requests.shift().reply({ files: { pdf: 'old.pdf' }, out_dir: '/tmp/build' });
  await pending;
  assert.equal(app.el.downloads.children.length, 0);
  assert.equal(app.el.render.disabled, true);
  assert.equal(app.state.building, false);
});
