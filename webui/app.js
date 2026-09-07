/* 填空表单的前端。
 *
 * 一条主线：表单里的每一次输入都写进 state.content，防抖 400ms 之后 POST 给
 * /api/preview，右边那张纸就是服务器用 render.py 真渲出来的 HTML——不是另写一套
 * 前端排版。所以预览里看到的换行、页数，和最后 PDF 里的完全一致。
 *
 * 表单本身不在这里定义：/api/bootstrap 把 schema.py 的字段表发过来，
 * buildForm() 照着长。加字段只改 schema.py，这个文件不用动。
 */

'use strict';

const PREVIEW_DELAY = 400;      // 打字停下 400ms 才渲染，别每敲一个字都渲
const SHEET_WIDTH = 818;        // 与 app.css 的 --sheet-w 一致

const state = {
  blocks: [],                   // 字段表
  content: {},                  // 当前表单内容，形状与 content.toml 一致
  contents: [],                 // 内容目录里可选的文件名
  themes: [],
  protected: [],
  outDir: '',
  dirty: false,                 // 有没有未保存的改动
  timer: null,
  inflight: null,               // 正在飞的预览请求，用来取消
};

const el = {
  form: document.getElementById('form'),
  jump: document.getElementById('jump'),
  sheet: document.getElementById('sheet'),
  paper: document.getElementById('paper'),
  name: document.getElementById('content-name'),
  list: document.getElementById('content-list'),
  theme: document.getElementById('theme-name'),
  pages: document.getElementById('stat-pages'),
  blanks: document.getElementById('stat-blanks'),
  file: document.getElementById('stat-file'),
  downloads: document.getElementById('downloads'),
  toast: document.getElementById('toast'),
  load: document.getElementById('btn-load'),
  save: document.getElementById('btn-save'),
  render: document.getElementById('btn-render'),
};

/* ---------- 小工具 ---------- */

function node(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}

let toastTimer = null;
function toast(message, kind = '', ms = 2600) {
  el.toast.textContent = message;
  el.toast.className = `toast show ${kind}`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.toast.className = 'toast'; }, ms);
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: options.body ? { 'Content-Type': 'application/json' } : undefined,
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(payload.error || `${response.status} ${response.statusText}`);
    error.status = response.status;
    throw error;
  }
  return payload;
}

/* ---------- 值的编辑形态 ----------
 * kind=list  一行里用 / 分隔（面包屑、关键词那种短词组）
 * kind=lines 一行一条（bullet 那种）
 * 这两种在 TOML 里都是数组，只是在输入框里的写法不同。
 */

function toInput(field, value) {
  if (field.kind === 'list') return (value || []).join(' / ');
  if (field.kind === 'lines') return (value || []).join('\n');
  return value == null ? '' : String(value);
}

function fromInput(field, raw) {
  if (field.kind === 'list') {
    return raw.split('/').map((x) => x.trim()).filter(Boolean);
  }
  if (field.kind === 'lines') {
    return raw.split('\n').map((x) => x.trim()).filter(Boolean);
  }
  return raw;
}

// 这几个空天生要写成几行字，给它们 textarea 而不是单行输入框。
const AREAS = new Set([
  'summary.text', 'skills.text', 'experiences.bullets', 'projects.description',
]);

function isArea(block, field) {
  return field.kind === 'lines' || AREAS.has(`${block.key}.${field.key}`);
}

function emptyValue(field) {
  if (field.kind === 'list' || field.kind === 'lines') {
    return field.default ? fromInput(field, field.default) : [];
  }
  return field.default || '';
}

function emptyRow(block) {
  const row = {};
  block.fields.forEach((field) => { row[field.key] = emptyValue(field); });
  return row;
}

function emptyContent() {
  const content = {};
  state.blocks.forEach((block) => {
    if (block.section_key) content[block.section_key] = { title: block.section_default };
    content[block.key] = block.repeat ? [emptyRow(block)] : emptyRow(block);
  });
  return content;
}

/* ---------- 长出表单 ---------- */

function hintText(field) {
  const bits = [];
  if (field.hint) bits.push(field.hint);
  if (field.kind === 'list') bits.push('用 / 分隔');
  if (field.kind === 'lines') bits.push('一行一条');
  if (field.example) bits.push(`例：${field.example}`);
  if (!field.required) bits.push('可留空');
  return bits.join(' · ');
}

/** 一个空。read/write 把它接到 state.content 上的具体位置。 */
function fieldView(block, field, read, write) {
  const wrap = node('div', 'field');
  const id = `f-${Math.random().toString(36).slice(2, 9)}`;

  const label = node('label', null, field.ask);
  label.htmlFor = id;
  if (field.required) label.append(node('span', 'req', '*'));
  wrap.append(label);

  const hint = hintText(field);
  if (hint) wrap.append(node('span', 'hint', hint));

  const input = isArea(block, field)
    ? node('textarea')
    : node('input');
  input.id = id;
  input.value = toInput(field, read());
  if (input.tagName === 'TEXTAREA') {
    input.rows = field.kind === 'lines' ? 4 : 2;
  } else {
    input.type = 'text';
    input.spellcheck = false;
  }
  if (field.required && !input.value.trim()) input.classList.add('blank');

  // 概况那一段长度最要命（超过四行会把后面的内容挤掉），给它一个字数计。
  const counter = block.key === 'summary' ? node('span', 'count') : null;
  const countUp = () => {
    if (counter) counter.textContent = `${input.value.trim().length} 字`;
  };
  countUp();

  input.addEventListener('input', () => {
    write(fromInput(field, input.value));
    input.classList.toggle('blank', field.required && !input.value.trim());
    countUp();
    touched();
  });

  wrap.append(input);
  if (counter) wrap.append(counter);
  return wrap;
}

/** 数组表里的一条：一张卡，带删除和上下移。 */
function cardView(block, index, rerender) {
  const rows = state.content[block.key];
  const card = node('div', 'card');

  const head = node('div', 'card-head');
  head.append(node('span', 'no', `${block.title} · 第 ${index + 1} 条`));

  const tools = node('div', 'tools');
  const move = (to) => {
    const [row] = rows.splice(index, 1);
    rows.splice(to, 0, row);
    touched();
    rerender();
  };

  const up = node('button', 'icon', '↑');
  up.type = 'button';
  up.title = '上移';
  up.disabled = index === 0;
  up.addEventListener('click', () => move(index - 1));

  const down = node('button', 'icon', '↓');
  down.type = 'button';
  down.title = '下移';
  down.disabled = index === rows.length - 1;
  down.addEventListener('click', () => move(index + 1));

  const drop = node('button', 'icon', '删除');
  drop.type = 'button';
  drop.disabled = rows.length <= block.min_items;
  drop.title = drop.disabled
    ? `至少要有 ${block.min_items} 条`
    : '删除这一条';
  drop.addEventListener('click', () => {
    rows.splice(index, 1);
    touched();
    rerender();
  });

  tools.append(up, down, drop);
  head.append(tools);
  card.append(head);

  block.fields.forEach((field) => {
    card.append(fieldView(
      block, field,
      () => rows[index][field.key],
      (value) => { rows[index][field.key] = value; },
    ));
  });
  return card;
}

function blockView(block) {
  const section = node('section', 'block');
  section.id = `block-${block.key}`;
  section.append(node('h2', null, block.title));
  if (block.intro) section.append(node('p', 'intro', block.intro));

  // 数组表整块会被重画（增删和上下移之后编号要跟着变）
  const body = node('div');
  const rerender = () => {
    body.textContent = '';
    paint();
  };

  function paint() {
    if (block.section_key) {
      body.append(fieldView(
        block,
        {
          key: 'title', ask: '这一栏在页面上叫什么', hint: '左侧竖脊上那几个字',
          example: block.section_default, kind: 'text', required: true, default: '',
        },
        () => (state.content[block.section_key] || {}).title,
        (value) => {
          state.content[block.section_key] = { title: value };
        },
      ));
    }

    if (!block.repeat) {
      block.fields.forEach((field) => {
        body.append(fieldView(
          block, field,
          () => state.content[block.key][field.key],
          (value) => { state.content[block.key][field.key] = value; },
        ));
      });
      return;
    }

    const rows = state.content[block.key];
    rows.forEach((_, index) => body.append(cardView(block, index, rerender)));

    const full = block.max_items && rows.length >= block.max_items;
    const add = node('button', 'add', `+ 再加一条${block.title}`);
    add.type = 'button';
    add.disabled = Boolean(full);
    add.addEventListener('click', () => {
      rows.push(emptyRow(block));
      touched();
      rerender();
    });
    body.append(add);
    if (full) body.append(node('p', 'limit', `最多 ${block.max_items} 条`));
  }

  paint();
  section.append(body);
  return section;
}

function buildForm() {
  el.form.textContent = '';
  el.jump.textContent = '';
  state.blocks.forEach((block) => {
    el.form.append(blockView(block));
    const link = node('a', null, block.title);
    link.href = `#block-${block.key}`;
    el.jump.append(link);
  });
}

/* ---------- 预览 ---------- */

function touched() {
  state.dirty = true;
  el.save.classList.add('dirty');
  schedule();
}

function schedule() {
  clearTimeout(state.timer);
  el.paper.classList.add('stale');
  state.timer = setTimeout(preview, PREVIEW_DELAY);
}

async function preview() {
  if (state.inflight) state.inflight.abort();   // 上一次还没回来就不要它了
  const controller = new AbortController();
  state.inflight = controller;

  try {
    const result = await api('/api/preview', {
      method: 'POST',
      signal: controller.signal,
      body: JSON.stringify({ content: state.content, theme: el.theme.value }),
    });
    // srcdoc 而不是 innerHTML：iframe 里是一份完整文档，也让 sandbox 隔离生效
    el.sheet.srcdoc = result.html;
    showPages(result.pages);
    showBlanks(result.blanks);
    el.paper.classList.remove('stale');
  } catch (error) {
    if (error.name === 'AbortError') return;
    toast(`预览失败：${error.message}`, 'bad');
  } finally {
    if (state.inflight === controller) state.inflight = null;
  }
}

function showPages(pages) {
  if (pages === 1) {
    el.pages.textContent = '页数 1 ✓';
    el.pages.className = 'stat good';
    return;
  }
  el.pages.textContent = `页数 ${pages} ✗ 砍内容，别缩字号`;
  el.pages.className = 'stat bad';
}

function showBlanks(blanks) {
  const count = (blanks || []).length;
  el.blanks.textContent = count ? `空白 ${count} 处` : '空白 0 ✓';
  el.blanks.className = count ? 'stat warn' : 'stat good';
  el.blanks.title = count ? blanks.join('\n') : '';
  el.render.disabled = count > 0;
  el.render.title = count ? '还有空没填，补齐后才能出 PDF' : '';
}

/** 把 A4 那张纸缩放到当前栏宽。 */
function fitPaper() {
  const room = el.paper.clientWidth - 32;       // 减掉 padding
  // 栏被折叠（窄屏把预览藏起来）时 clientWidth 是 0，不能让 scale 变成负数。
  const scale = Math.max(0.25, Math.min(1, room / SHEET_WIDTH));
  el.paper.style.setProperty('--scale', scale.toFixed(4));
}

/* ---------- 读 / 存 / 生成 ---------- */

/** 状态栏右边那个文件名，顺便说清楚为什么这一份不能存。 */
function readOnlyNote(result) {
  if (result.extends) {
    return `${result.name}（定制版，继承 ${result.extends}；只读，改它请编辑该文件）`;
  }
  if (!result.writable) {
    return `${result.name}（示例，只读；保存请换个名字）`;
  }
  return result.name;
}

async function load(name) {
  if (state.dirty && !confirm('当前改动还没保存，读取会丢掉它们。继续？')) return;
  try {
    const result = await api(`/api/content?name=${encodeURIComponent(name)}`);
    state.content = result.content;
    el.name.value = result.name;
    el.file.textContent = readOnlyNote(result);
    clean();
    buildForm();
    schedule();
  } catch (error) {
    toast(`读取失败：${error.message}`, 'bad');
  }
}

async function save() {
  const name = el.name.value.trim();
  if (!name) {
    toast('先给内容文件起个名字，比如 content.toml', 'bad');
    return;
  }
  try {
    const result = await api('/api/save', {
      method: 'POST',
      body: JSON.stringify({ name, content: state.content }),
    });
    clean();
    el.file.textContent = result.name;
    if (!state.contents.includes(result.name)) {
      state.contents.push(result.name);
      fillContentList();
    }
    const tail = result.backup ? `，旧文件备份为 ${result.backup}` : '';
    toast(`已写入 ${result.path}${tail}`, 'good');
    showBlanks(result.blanks);
  } catch (error) {
    toast(`保存失败：${error.message}`, 'bad', 5200);
  }
}

async function build() {
  el.render.disabled = true;
  try {
    const result = await api('/api/render', {
      method: 'POST',
      body: JSON.stringify({
        content: state.content,
        theme: el.theme.value,
      }),
    });
    showDownloads(result.files);
    toast(`已生成到 ${result.out_dir}`, 'good');
  } catch (error) {
    toast(error.message, 'bad', 6500);
  } finally {
    el.render.disabled = false;
  }
}

function showDownloads(files) {
  el.downloads.textContent = '';
  ['pdf', 'png', 'html'].forEach((kind) => {
    const name = files[kind];
    if (!name) return;
    const link = node('a', null, kind.toUpperCase());
    link.href = `/api/artifact?name=${encodeURIComponent(name)}`;
    link.title = name;
    el.downloads.append(link);
  });
}

function clean() {
  state.dirty = false;
  el.save.classList.remove('dirty');
}

/* ---------- 启动 ---------- */

function fillContentList() {
  el.list.textContent = '';
  state.contents.slice().sort().forEach((name) => {
    const option = node('option');
    option.value = name;
    if (state.protected.includes(name)) option.label = `${name}（示例，只读）`;
    el.list.append(option);
  });
}

async function boot() {
  let info;
  try {
    info = await api('/api/bootstrap');
  } catch (error) {
    toast(`启动失败：${error.message}`, 'bad', 8000);
    return;
  }

  state.blocks = info.blocks;
  state.contents = info.contents;
  state.protected = info.protected;
  state.themes = info.themes;
  state.outDir = info.out_dir;

  fillContentList();
  info.themes.forEach((name) => {
    const option = node('option', null, name);
    option.value = name;
    if (name === info.default_theme) option.selected = true;
    el.theme.append(option);
  });

  if (!info.png) {
    toast('没装 pdftoppm，PNG 预览图会跳过（PDF 照常生成）。', '', 4200);
  }

  if (info.default_content) {
    await load(info.default_content);
  } else {
    state.content = emptyContent();
    el.name.value = 'content.toml';
    buildForm();
    schedule();
  }
  fitPaper();
}

el.load.addEventListener('click', () => {
  const name = el.name.value.trim();
  if (name) load(name);
});
el.save.addEventListener('click', save);
el.render.addEventListener('click', build);
el.theme.addEventListener('change', schedule);
el.sheet.addEventListener('load', fitPaper);
window.addEventListener('resize', fitPaper);

// Ctrl-S / ⌘-S 存盘，和编辑器里的手感一致
window.addEventListener('keydown', (event) => {
  if ((event.ctrlKey || event.metaKey) && event.key === 's') {
    event.preventDefault();
    save();
  }
});

// 有未保存改动时关页面先问一句
window.addEventListener('beforeunload', (event) => {
  if (!state.dirty) return;
  event.preventDefault();
  event.returnValue = '';
});

boot();

