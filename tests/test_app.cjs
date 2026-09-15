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
                 'samples': samples, 'example': content}))
`], { cwd: root, encoding: 'utf8' }));

class Element {
  constructor(tag = 'div') {
    this.tagName = tag.toUpperCase();
    this.children = [];
    this._value = '';
    this.disabled = false;
    this.srcdoc = '';
    this.clientWidth = 900;
    this.id = '';
    this.className = '';
    this.htmlFor = '';
    this.href = '';
    this.target = '';
    this.rel = '';
    this.title = '';
    this.type = '';
    this.required = false;
    this.placeholder = '';
    this.rows = 0;
    this.maxLength = Infinity;
    this.selected = false;
    this.label = '';
    this.style = { setProperty() {} };
    this.attributes = {};
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
  // 真 DOM 的 input.value 只接受字符串，赋数组会被 String() 成 "a,b"。
  // 基座照做——否则"把数组直接塞进 textarea"这种错在测试里看不出来。
  set value(value) { this._value = value == null ? '' : String(value); }
  get value() { return this._value; }
  append(...children) { this.children.push(...children); }
  appendChild(child) { this.children.push(child); }
  setAttribute(name, value) { this.attributes[name] = value; }
  getAttribute(name) { return this.attributes[name]; }
  querySelector(selector) {
    if (selector === 'button') {
      return this.children.find(el => el.tagName === 'BUTTON');
    }
    return null;
  }
  remove() { this.removed = true; }
  focus() {}
  showModal() { this.open = true; }
  close() { this.open = false; }
  addEventListener(type, handler) {
    if (!this.listeners) this.listeners = new Map();
    if (!this.listeners.has(type)) this.listeners.set(type, []);
    this.listeners.get(type).push(handler);
  }
  dispatch(type, event = {}) {
    for (const handler of (this.listeners?.get(type) || [])) handler(event);
  }
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
      body: new Element('body'),
    },
    window: { addEventListener() {} },
    setTimeout: (callback) => { timers.add(callback); return callback; },
    clearTimeout: (callback) => timers.delete(callback),
    fetch: (url, options = {}) => new Promise((resolve) => {
      const headers = options.headers || {};
      const isPost = String(options.method || 'GET').toUpperCase() === 'POST';
      const entry = { url, options, headers, json: /^application\/json/.test(headers['Content-Type'] || '') };
      requests.push(entry);
      if (isPost && !entry.json) {
        // webui.body_json() 只收 application/json。基座也照这个来：少了这个头
        // 就直接 400，好过"少写一个头而所有用例照样绿"。
        resolve({
          ok: false, status: 400, statusText: 'Bad Request',
          json: async () => ({ error: '只接受 application/json 请求。', code: 'bad_request' }),
        });
        return;
      }
      entry.reply = (payload, status = 200) => resolve({
        ok: status === 200, status, statusText: 'Error',
        json: async () => payload,
      });
    }),
    console: { log() {} },
  });
  // 与 index.html 里的 <script> 顺序一致——顺序错了会在加载期就撞上未定义的名字。
  const files = ['ui.js', 'form.js', 'preview.js', 'export.js', 'files.js', 'app.js'];
  const sources = files.map((file) => fs.readFileSync(path.join(root, 'webui', file), 'utf8'));
  vm.runInContext(sources.join('\n') + '\nglobalThis.app = {state, el, touched, schedule, '
    + 'preview, load, save, build, updateActions, dialog, api, fromInput, toInput, '
    + 'buildForm, emptyContent};', context);
  requests.shift().reply({
    ...info, contents: [], protected: [], themes: ['theme.toml'],
    default_theme: 'theme.toml', default_content: null,
    default_content_name: 'content.toml', out_dir: '/tmp/build', png: true,
  });
  await new Promise((resolve) => setImmediate(resolve));
  return { ...context.app, requests, timers, document: context.document };
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

test('build offers view and download links, but never an inline HTML', async () => {
  const app = await createApp();
  app.state.previewReady = true;
  app.state.pages = 1;
  app.updateActions();
  const pending = app.build();
  app.requests.shift().reply({
    files: { pdf: '简历.pdf', png: '简历.png', html: '简历.html' },
    out_dir: '/tmp/build',
  });
  await pending;
  const links = app.el.downloads.children.map((link) => ({
    text: link.textContent, href: link.href, target: link.target, rel: link.rel,
  }));
  assert.deepEqual(links.map((link) => link.text),
    ['PDF 查看', 'PDF 下载', 'PNG 查看', 'PNG 下载', 'HTML 下载']);
  assert.match(links[0].href, /inline=1$/);
  assert.equal(links[0].target, '_blank');
  assert.equal(links[0].rel, 'noopener');
  assert.ok(!links[1].href.includes('inline'));
  assert.ok(!links[4].href.includes('inline'));
});


// 把一棵假 DOM 子树摊平成数组，便于按值反查某个输入框
function descendants(root) {
  const out = [];
  const walk = (element) => {
    for (const child of element.children || []) { out.push(child); walk(child); }
  };
  walk(root);
  return out;
}

// 找到某个元素底下的全部按钮（对话框的按钮在 .dialog-actions 里）
function buttonsIn(box) {
  const row = box.children.find((child) => child.className === 'dialog-actions');
  return row ? row.children.filter((child) => child.tagName === 'BUTTON') : [];
}

test('dialog resolves with the pressed button, and ESC counts as the cancel button', async () => {
  const app = await createApp();

  const clicked = app.dialog({
    title: '当前改动还没保存',
    message: '读取 content.other.toml 会丢掉这些改动。',
    buttons: [
      { label: '取消', kind: 'cancel' },
      { label: '放弃改动并读取', kind: 'primary' },
    ],
  });
  const first = app.document.body.children.at(-1);
  assert.equal(first.tagName, 'DIALOG');
  assert.equal(first.open, true, '对话框应当被 showModal() 打开');

  const buttons = buttonsIn(first);
  assert.deepEqual(buttons.map((button) => button.textContent), ['取消', '放弃改动并读取']);
  buttons[1].dispatch('click');
  assert.equal(await clicked, '放弃改动并读取');
  assert.equal(first.removed, true, '关闭后应当从 DOM 里摘掉');

  // ESC（<dialog> 的 cancel 事件）= 点那个 kind: 'cancel' 的按钮，不能让 Promise 悬着
  const escaped = app.dialog({
    title: 't', message: 'm',
    buttons: [{ label: '取消', kind: 'cancel' }, { label: '继续', kind: 'primary' }],
  });
  const second = app.document.body.children.at(-1);
  second.dispatch('cancel', { preventDefault() {} });
  assert.equal(await escaped, '取消');
});

test('every POST carries a JSON content type, or the server refuses it', async () => {
  // 这条守的是一个真实踩过的坑：api() 少写了 Content-Type，浏览器就按 text/plain 发，
  // 服务端的 body_json() 只收 application/json，于是预览、保存、生成全部 400。
  const app = await createApp();

  app.state.fileName = 'content.toml';
  app.state.fileRevision = 'revision';
  app.touched();
  const saving = app.save();
  const saveRequest = app.requests.shift();
  assert.equal(saveRequest.options.method, 'POST');
  assert.equal(saveRequest.options.headers['Content-Type'], 'application/json');
  saveRequest.reply({
    name: 'content.toml', path: '/tmp/content.toml', revision: 'saved', blanks: [],
  });
  await saving;

  const previewing = app.preview();
  const previewRequest = app.requests.shift();
  assert.equal(previewRequest.options.headers['Content-Type'], 'application/json');
  previewRequest.reply(previewResult());
  await previewing;
});

test('server error codes reach the caller instead of being flattened to a message', async () => {
  const app = await createApp();
  const pending = app.api('/api/save', { method: 'POST', body: '{}' })
    .then(() => null, (reason) => reason);
  app.requests.shift().reply(
    { error: '已被别的窗口改过', code: 'modified', name: 'content.toml', revision: 'now' },
    409,
  );
  const error = await pending;
  assert.equal(error.message, '已被别的窗口改过');
  assert.equal(error.code, 'modified');
  assert.equal(error.status, 409);
  assert.equal(error.detail.name, 'content.toml');
  assert.equal(error.detail.revision, 'now');
});

test('list and lines fields render as text, so what you see is what gets stored', async () => {
  // 这条守的是另一半：字段必须以"人看到的样子"进输入框。list 用「空格 / 空格」、
  // lines 一行一条；把数组直接赋给 textarea 会被 String() 成 "a,b"，纸面上才发现。
  const app = await createApp();
  app.state.content = structuredClone(info.example);
  app.buildForm();
  const fields = descendants(app.el.form);

  // 用只在 bullet 里出现的词：技能行里也有 "GSC"，会先撞上那个单行输入框
  const bullets = fields.find((element) => /月报/.test(element.value));
  assert.equal(bullets.tagName, 'TEXTAREA');
  assert.ok(bullets.value.includes('\n'), 'bullet 应当一行一条');
  assert.ok(!bullets.value.includes(','), '不该留下数组被 String() 连起来的痕迹');

  const crumbs = fields.find((element) => /2025\.09/.test(element.value));
  assert.equal(crumbs.tagName, 'INPUT');
  assert.ok(crumbs.value.includes(' / '), '面包屑应当用「空格 / 空格」分隔');

  const summary = fields.find((element) => /两年英文网站内容/.test(element.value));
  assert.equal(summary.tagName, 'TEXTAREA', '概况天生要写成几行字');
});
