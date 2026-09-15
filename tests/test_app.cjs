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

/** 真 DOM 的 .children 是 HTMLCollection：能索引、能取 length、能迭代，
 *  但没有 find / map / filter / at。基座照做——否则"在 HTMLCollection 上调用
 *  数组方法"这种错只有到了真浏览器才会炸（export.js 就这么炸过一次）。 */
function childrenOf(items) {
  // 每次访问都重造一份，所以取到的总是当前的子节点（真 HTMLCollection 是活的）
  const wrapper = { length: items.length, item: (index) => items[index] ?? null };
  Object.defineProperty(wrapper, Symbol.iterator, { value: () => items[Symbol.iterator]() });
  for (let index = 0; index < items.length; index += 1) wrapper[index] = items[index];
  return wrapper;
}

/** 要数组方法时先摊平——测试里到处用，收成一个函数。 */
function kids(element) { return [...element.children]; }

class Element {
  constructor(tag = 'div') {
    this.tagName = tag.toUpperCase();
    this._children = [];
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
    this.hidden = false;
    const classes = new Set();
    this.classList = {
      add: (...names) => names.forEach((name) => classes.add(name)),
      remove: (...names) => names.forEach((name) => classes.delete(name)),
      contains: (name) => classes.has(name),
      toggle: (name, enabled) => enabled ? classes.add(name) : classes.delete(name),
    };
  }

  set textContent(value) { this.text = value; this._children = []; }
  get textContent() { return this.text || ''; }
  // 真 DOM 的 input.value 只接受字符串，赋数组会被 String() 成 "a,b"。
  // 基座照做——否则"把数组直接塞进 textarea"这种错在测试里看不出来。
  set value(value) { this._value = value == null ? '' : String(value); }
  get value() { return this._value; }
  get children() { return childrenOf(this._children); }
  append(...children) { this._children.push(...children); }
  appendChild(child) { this._children.push(child); }
  setAttribute(name, value) { this.attributes[name] = value; }
  getAttribute(name) { return this.attributes[name]; }
  querySelector(selector) {
    if (selector === 'button') {
      return this._children.find((el) => el.tagName === 'BUTTON') || null;
    }
    return null;
  }
  remove() { this.removed = true; }
  focus() { this.focused = true; this.scrolled = true; }
  scrollIntoView() { this.scrolled = true; }
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

/** 一个够用的 localStorage：草稿那套逻辑要有地方读写。 */
function memoryStorage() {
  const store = new Map();
  return {
    getItem: (key) => (store.has(key) ? store.get(key) : null),
    setItem: (key, value) => { store.set(key, String(value)); },
    removeItem: (key) => { store.delete(key); },
    _store: store,
  };
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
    window: { addEventListener() {}, localStorage: memoryStorage() },
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
        blob: async () => new Blob([JSON.stringify(payload)]),
      });
    }),
    console: { log() {} },
  });
  // 与 index.html 里的 <script> 顺序一致——顺序错了会在加载期就撞上未定义的名字。
  const files = ['ui.js', 'form.js', 'preview.js', 'export.js', 'files.js', 'app.js'];
  const sources = files.map((file) => fs.readFileSync(path.join(root, 'webui', file), 'utf8'));
  vm.runInContext(sources.join('\n') + '\nglobalThis.app = {state, el, touched, schedule, '
    + 'preview, updateActions, dialog, api, fromInput, toInput, buildForm, '
    + 'emptyContent, openFile, newFile, saveFile, saveAsFile, showHistory, '
    + 'fieldElement, toggleBlankList, jumpToBlank, updateBadge, relativeTime, '
    + 'showBlanks, window, showBuildDialog, runBuild, showResults, saveArtifactTo, '
    + 'revealArtifact, canPickFiles};', context);
  requests.shift().reply({
    ...info, files: [], themes: ['theme.toml'],
    default_theme: 'theme.toml', default_content: null,
    default_content_name: 'content.toml', out_dir: '/tmp/build',
    content_dir: '/tmp/content', png: true,
  });
  await new Promise((resolve) => setImmediate(resolve));
  return { ...context.app, requests, timers, document: context.document };
}

/** 让 async 函数里那几层 await 跑完，请求才会真的发出去。 */
async function flush(rounds = 6) {
  for (let index = 0; index < rounds; index += 1) {
    await new Promise((resolve) => setImmediate(resolve));
  }
}

function previewResult(overrides = {}) {
  return { html: 'approximate', preview_html: 'current PDF', pages: 1, blanks: [],
    preview_mode: 'pdf', shown_pages: 1, width: 794, height: 1123, ...overrides };
}

/** 找到最后弹出的那个对话框，按文字点一个按钮。 */
function clickDialog(app, label) {
  const box = kids(app.document.body).at(-1);
  const buttons = buttonsIn(box);
  const button = buttons.find((item) => item.textContent === label);
  assert.ok(button, `对话框里没有「${label}」：${buttons.map((item) => item.textContent)}`);
  button.dispatch('click');
}

/** 服务端读一份内容文件的正常回应。 */
function contentReply(overrides = {}) {
  return {
    name: 'content.toml', content: structuredClone(info.example), blanks: [],
    locations: [], writable: true, reason: '', extends: null, revision: 'rev-1',
    ...overrides,
  };
}

test('switching files with unsaved edits asks first', async () => {
  const app = await createApp();
  app.state.ready = true;
  app.state.fileName = 'content.toml';
  app.state.dirty = true;

  const cancelled = app.openFile('content.other.toml');
  await flush();
  assert.equal(app.requests.length, 0, '还没问完就不该去读文件');
  const labels = buttonsIn(kids(app.document.body).at(-1)).map((item) => item.textContent);
  assert.deepEqual(labels, ['取消', '放弃改动', '保存后切换']);
  clickDialog(app, '取消');
  await cancelled;
  assert.equal(app.state.fileName, 'content.toml', '取消就不该换文件');
  assert.equal(app.requests.length, 0);

  const switched = app.openFile('content.other.toml');
  await flush();
  clickDialog(app, '放弃改动');
  await flush();
  app.requests.shift().reply(contentReply({ name: 'content.other.toml', revision: 'rev-2' }));
  await flush(10);
  assert.equal(app.state.fileName, 'content.other.toml');
  assert.equal(app.state.dirty, false);
});

test('untitled save opens save-as instead of inventing a name', async () => {
  const app = await createApp();
  assert.equal(app.state.fileName, null);
  app.touched();

  const pending = app.saveFile();
  await flush();
  const box = kids(app.document.body).at(-1);
  assert.equal(box.tagName, 'DIALOG');
  assert.match(box.children[0].textContent, /另存为/);
  // 还没起名字：输入框空着，主按钮是禁用的，也没必要去问服务端
  const input = kids(box).find((child) => child.className === 'dialog-input');
  assert.equal(input.value, '');
  assert.equal(input.placeholder, 'content.toml');
  assert.equal(buttonsIn(box).find((item) => item.className === 'primary').disabled, true);
  clickDialog(app, '取消');
  await pending;
  assert.equal(app.state.fileName, null, '取消之后还是未命名');
});

test('a modified conflict offers reload or save-as, never force', async () => {
  const app = await createApp();
  app.state.ready = true;
  app.state.fileName = 'content.toml';
  app.state.fileRevision = 'old-revision';
  app.touched();

  const pending = app.saveFile();
  await flush();
  app.requests.shift().reply({
    error: 'content.toml 在你读取之后被改过', code: 'modified',
    name: 'content.toml', revision: 'now',
  }, 409);
  await pending;

  const banners = kids(app.el.banners);
  assert.equal(banners.length, 1);
  const actions = kids(banners[0]).find((child) => child.className === 'banner-actions');
  const labels = kids(actions).map((item) => item.textContent);
  assert.deepEqual(labels, ['重新读取（丢掉我的改动）', '另存为…']);
  assert.ok(!labels.some((label) => /强制|直接覆盖/.test(label)),
    '不许给"强制覆盖"这条路：那会盖掉别人刚写进去的内容');
  assert.equal(app.state.dirty, true, '冲突之后改动仍然是未保存状态');
});

test('draft is restored only after the user says so', async () => {
  const app = await createApp();
  const draft = structuredClone(info.example);
  draft.summary.text = '草稿里那一版';
  app.window.localStorage.setItem('onepage-resume:draft:content.toml', JSON.stringify({
    content: draft, theme: 'theme.toml', savedRevision: 'rev-1', time: Date.now(),
  }));

  // 点「丢弃」：留在文件里的那一版
  const first = app.openFile('content.toml');
  await flush();
  app.requests.shift().reply(contentReply());
  await flush(10);
  const box = kids(app.document.body).at(-1);
  assert.equal(box.tagName, 'DIALOG');
  assert.match(box.children[0].textContent, /没保存的改动/);
  clickDialog(app, '丢弃');
  await first;
  assert.equal(app.state.content.summary.text, info.example.summary.text);
  assert.equal(app.state.dirty, false);
  assert.equal(app.window.localStorage.getItem('onepage-resume:draft:content.toml'), null,
    '说了丢弃就该把草稿清掉');

  // 再来一次，这回点「恢复」
  app.window.localStorage.setItem('onepage-resume:draft:content.toml', JSON.stringify({
    content: draft, theme: 'theme.toml', savedRevision: 'rev-1', time: Date.now(),
  }));
  const second = app.openFile('content.toml', { force: true });
  await flush();
  app.requests.shift().reply(contentReply());
  await flush(10);
  clickDialog(app, '恢复');
  await second;
  assert.equal(app.state.content.summary.text, '草稿里那一版');
  assert.equal(app.state.dirty, true, '恢复出来的草稿是未保存状态');
});

test('blank list click focuses the matching input', async () => {
  const app = await createApp();
  app.state.content = structuredClone(info.example);
  app.buildForm();

  const location = {
    block: 'experiences', index: 1, field: 'bullets', item: null, section: false,
    message: '[[experiences]] 第 2 条的 bullets —— 你做了什么',
  };
  const field = app.fieldElement(location);
  assert.ok(field, '应当能按位置找回输入框');
  assert.equal(field.tagName, 'TEXTAREA');

  app.showBlanks([location.message], [location]);
  assert.equal(app.el.blanks.textContent, '空白 1 处');
  app.toggleBlankList();
  assert.equal(app.el.blankList.hidden, false);
  assert.equal(app.el.blankList.children.length, 1);

  app.el.blankList.children[0].dispatch('click');
  assert.equal(field.focused, true, '点一条就该跳到那个输入框');
  assert.equal(field.classList.contains('flash'), true);

  app.toggleBlankList();
  assert.equal(app.el.blankList.hidden, true, '再点一下收起');
});

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
  const pending = app.saveFile();
  await app.saveFile();
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

test('save-as on an existing name asks before overwriting', async () => {
  const app = await createApp();
  app.state.ready = true;
  app.state.fileName = null;                  // 未命名 → 保存就是另存为
  app.touched();

  const pending = app.saveFile();
  await flush();

  const box = kids(app.document.body).at(-1);
  const input = kids(box).find((child) => child.className === 'dialog-input');
  assert.ok(input, '另存为对话框里应当有一个文件名输入框');
  input.value = 'acme';
  input.dispatch('input');
  // 基座里的 setTimeout 不会自己跑（好几条用例依赖这一点），手动踢一脚防抖
  app.state.statTimer();
  await flush();

  const stat = app.requests.shift();
  assert.match(stat.url, /^\/api\/stat\?kind=content&name=/);
  assert.match(decodeURIComponent(stat.url), /name=acme/);
  stat.reply({ name: 'content.acme.toml', exists: true, writable: true, reason: '' });
  await flush();

  const primary = buttonsIn(box).find((button) => button.className === 'primary');
  assert.equal(primary.textContent, '覆盖', '目标已存在时主按钮应当说「覆盖」');
  primary.dispatch('click');
  await flush();

  const save = app.requests.shift();
  const body = JSON.parse(save.options.body);
  assert.equal(body.mode, 'overwrite');
  assert.equal(body.name, 'content.acme.toml');
  save.reply({ name: 'content.acme.toml', path: '/tmp/content.acme.toml', revision: 'r2',
    snapshot: '20260101T000000Z-deadbeef.toml', unchanged: false, blanks: [] });
  await pending;
  assert.equal(app.state.fileName, 'content.acme.toml');
  assert.equal(app.state.dirty, false);
});

test('loading does not discard edits made while the request was pending', async () => {
  const app = await createApp();
  const original = app.state.content;
  const pending = app.openFile('content.other.toml');
  await flush();
  app.touched();
  app.requests.shift().reply({ name: 'content.other.toml', content: {}, revision: 'other' });
  await pending;
  assert.equal(app.state.content, original);
  assert.equal(app.state.dirty, true);
});

test('stale build results do not offer old files or re-enable generation', async () => {
  const app = await createApp();
  app.state.previewReady = true;
  app.state.pages = 1;
  app.updateActions();
  const pending = app.runBuild('resume', 'overwrite', false);
  app.touched();
  app.requests.shift().reply({
    basename: 'resume', files: { pdf: 'old.pdf' }, out_dir: '/tmp/build',
  });
  await pending;
  // 结果照给，但必须说清这是改动之前那一版——静默给一份错的更糟
  assert.equal(kids(app.el.results).filter((c) => c.className === 'result-row').length, 1);
  assert.match(kids(kids(app.el.banners).at(-1))[0].textContent, /改动之前那一版/);
  assert.equal(app.el.render.disabled, true);
  assert.equal(app.state.building, false);
});

test('results offer view, download, save-to and reveal, but never an inline HTML', async () => {
  const app = await createApp();
  app.state.previewReady = true;
  app.state.pages = 1;
  app.updateActions();
  const pending = app.runBuild('简历', 'overwrite', false);
  app.requests.shift().reply({
    basename: '简历',
    files: { pdf: '简历.pdf', png: '简历.png', html: '简历.html' },
    out_dir: '/tmp/build',
  });
  await pending;

  // 只数文件行；缺 PNG 时会另外多一条说明
  const rows = kids(app.el.results).filter((child) => child.className === 'result-row');
  assert.equal(rows.length, 3);
  assert.deepEqual(rows.map((row) => row.children[0].textContent), ['PDF', 'PNG', 'HTML']);
  assert.deepEqual(rows.map((row) => row.children[1].textContent),
    ['简历.pdf', '简历.png', '简历.html']);

  const actionsOf = (row) => kids(kids(row)[2]);
  assert.deepEqual(actionsOf(rows[0]).map((item) => item.textContent),
    ['查看', '下载', '另存到…', '在文件夹中显示']);
  // HTML 不给「查看」：内联打开等于让生成的页面脚本跑在本服务的源下
  assert.deepEqual(actionsOf(rows[2]).map((item) => item.textContent),
    ['下载', '另存到…', '在文件夹中显示']);

  const view = actionsOf(rows[0])[0];
  assert.match(view.href, /inline=1$/);
  assert.equal(view.target, '_blank');
  assert.equal(view.rel, 'noopener');
  assert.ok(!actionsOf(rows[0])[1].href.includes('inline'));
  assert.ok(!actionsOf(rows[2])[0].href.includes('inline'));

  // 浏览器没有 File System Access API 时，「另存到…」明说为什么按不了
  const saveTo = actionsOf(rows[0])[2];
  assert.equal(saveTo.disabled, true);
  assert.match(saveTo.title, /不支持选择保存位置/);
});

test('generate dialog asks on conflict and sends the chosen policy', async () => {
  const app = await createApp();
  app.state.previewReady = true;
  app.state.pages = 1;
  app.state.blanks = [];
  app.state.content = structuredClone(info.example);
  app.updateActions();

  const pending = app.showBuildDialog();
  await flush();
  const box = kids(app.document.body).at(-1);
  assert.equal(box.children[0].textContent, '生成 PDF');
  // 预填 [document].output_basename
  const input = kids(box).find((child) => child.className === 'dialog-input');
  assert.equal(input.value, info.example.document.output_basename);

  let stat = app.requests.shift();
  assert.match(stat.url, /^\/api\/stat\?kind=artifact&name=/);
  stat.reply({ name: 'resume', exists: true, conflict: 'resume.pdf', suggested: 'resume-2' });
  await flush();

  const choice = kids(box).find((child) => child.className === 'dialog-choice');
  assert.equal(choice.hidden, false);
  const radios = kids(choice).map((item) => kids(item)[0]);
  assert.deepEqual(radios.map((radio) => radio.value), ['rename', 'overwrite']);
  assert.equal(radios[0].checked, true, '默认应当是改名，不是覆盖');
  radios[1].checked = true;
  radios[1].dispatch('change');
  await flush();

  clickDialog(app, '生成');
  await flush();
  const render = app.requests.shift();
  const body = JSON.parse(render.options.body);
  assert.equal(body.if_exists, 'overwrite');
  assert.equal(body.basename, 'resume');
  render.reply({ basename: 'resume', files: { pdf: 'resume.pdf' }, out_dir: '/tmp/build' });
  await pending;
});

test('generate dialog sends fail when nothing is in the way', async () => {
  const app = await createApp();
  app.state.previewReady = true;
  app.state.pages = 1;
  app.state.content = structuredClone(info.example);
  app.updateActions();

  const pending = app.showBuildDialog();
  await flush();
  app.requests.shift().reply({ name: 'resume', exists: false, suggested: 'resume-2' });
  await flush();
  clickDialog(app, '生成');
  await flush();
  const render = app.requests.shift();
  assert.equal(JSON.parse(render.options.body).if_exists, 'fail',
    '没撞名也要传 fail：万一这几秒里别人也生成了同名文件，宁可被拒一次');
  render.reply({ basename: 'resume', files: { pdf: 'resume.pdf' }, out_dir: '/tmp/build' });
  await pending;
});



// 把一棵假 DOM 子树摊平成数组，便于按值反查某个输入框
function descendants(root) {
  const out = [];
  const walk = (element) => {
    for (const child of kids(element)) { out.push(child); walk(child); }
  };
  walk(root);
  return out;
}

// 找到某个元素底下的全部按钮（对话框的按钮在 .dialog-actions 里）
function buttonsIn(box) {
  const row = kids(box).find((child) => child.className === 'dialog-actions');
  return row ? kids(row).filter((child) => child.tagName === 'BUTTON') : [];
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
  const first = kids(app.document.body).at(-1);
  assert.equal(first.tagName, 'DIALOG');
  assert.equal(first.open, true, '对话框应当被 showModal() 打开');

  const buttons = buttonsIn(first);
  assert.deepEqual(buttons.map((button) => button.textContent), ['取消', '放弃改动并读取']);
  buttons[1].dispatch('click');
  assert.equal((await clicked).label, '放弃改动并读取');
  assert.equal(first.removed, true, '关闭后应当从 DOM 里摘掉');

  // ESC（<dialog> 的 cancel 事件）= 点那个 kind: 'cancel' 的按钮，不能让 Promise 悬着
  const escaped = app.dialog({
    title: 't', message: 'm',
    buttons: [{ label: '取消', kind: 'cancel' }, { label: '继续', kind: 'primary' }],
  });
  const second = kids(app.document.body).at(-1);
  second.dispatch('cancel', { preventDefault() {} });
  const escapedAnswer = await escaped;
  assert.equal(escapedAnswer.label, '取消');
  assert.equal(escapedAnswer.value, null, '没有输入框时 value 应当是 null');
});

test('every POST carries a JSON content type, or the server refuses it', async () => {
  // 这条守的是一个真实踩过的坑：api() 少写了 Content-Type，浏览器就按 text/plain 发，
  // 服务端的 body_json() 只收 application/json，于是预览、保存、生成全部 400。
  const app = await createApp();

  app.state.fileName = 'content.toml';
  app.state.fileRevision = 'revision';
  app.touched();
  const saving = app.saveFile();
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

/** 一个假的保存对话框：把写进去的字节记下来。 */
function fakePicker(app, written) {
  app.window.showSaveFilePicker = async (options) => ({
    name: options.suggestedName,
    createWritable: async () => ({
      write: async (blob) => { written.push({ name: options.suggestedName, size: blob.size }); },
      close: async () => {},
    }),
  });
}

test('save-to writes the served bytes through the browser picker', async () => {
  const app = await createApp();
  const written = [];
  fakePicker(app, written);
  assert.equal(app.canPickFiles(), true);

  const pending = app.saveArtifactTo('简历.pdf');
  await flush();
  const request = app.requests.shift();
  assert.match(request.url, /^\/api\/artifact\?name=/);
  assert.ok(!request.url.includes('inline'), '另存到… 要的是附件，不是内联');
  request.reply('PDF-BYTES');
  await pending;

  assert.equal(written.length, 1);
  assert.equal(written[0].name, '简历.pdf');
  assert.ok(written[0].size > 0, '写出去的应当是有内容的 blob');
  assert.match(app.el.toast.textContent, /已保存到 简历.pdf/);
});

test('save-to says nothing when you cancel the picker', async () => {
  const app = await createApp();
  app.window.showSaveFilePicker = async () => {
    const error = new Error('The user aborted a request.');
    error.name = 'AbortError';
    throw error;
  };
  await app.saveArtifactTo('简历.pdf');
  assert.equal(app.el.banners.children.length, 0, '自己点了取消不该弹错');
  assert.equal(app.requests.length, 0, '取消了就别去下载');
});

test('save-to explains itself when the browser wants a fresh gesture', async () => {
  // 生成要渲一遍 PDF，等回来时"用户刚点过"的有效期可能已经过了。
  // Chrome 按规范抛 SecurityError——这不是错，得说清下一步该点哪。
  const app = await createApp();
  app.window.showSaveFilePicker = async () => {
    const error = new Error("Failed to execute 'showSaveFilePicker': "
      + 'Must be handling a user gesture to show a file picker.');
    error.name = 'SecurityError';
    throw error;
  };
  await app.saveArtifactTo('简历.pdf');
  const banner = kids(app.el.banners).at(-1);
  assert.match(kids(banner)[0].textContent, /亲手点一下「另存到…」/);
});

test('save-to is offered only when the browser can pick a location', async () => {
  const app = await createApp();
  assert.equal(app.canPickFiles(), false, '基座默认没有 File System Access API');
  app.state.previewReady = true;
  app.state.pages = 1;
  app.showResults({ basename: 'x', out_dir: '/tmp/build', files: { pdf: 'x.pdf' } });
  // 只有 PDF 时下面还会多一条"没有 PNG"的说明，所以按类名找那一行
  const row = kids(app.el.results).find((child) => child.className === 'result-row');
  const saveTo = kids(row)[2];
  const button = [...kids(saveTo)].find((item) => item.textContent === '另存到…');
  assert.equal(button.disabled, true);
  assert.match(button.title, /不支持选择保存位置/);
});
