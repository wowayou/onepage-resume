/* 填空表单的前端。
 *
 * 一条主线：表单里的每一次输入都写进 state.content，防抖 400ms 之后 POST 给
 * /api/preview，优先显示同一排版引擎生成的 PDF 页面图；缺少 pdftoppm 时
 * 明确标注为 HTML 近似预览，页数仍由 PDF 排版引擎计算。
 *
 * 表单本身不在这里定义：/api/bootstrap 把 schema.py 的字段表发过来，
 * buildForm() 照着长。加字段只改 schema.py，这个文件不用动。
 */

'use strict';

const PREVIEW_DELAY = 400;      // 打字停下 400ms 才渲染，别每敲一个字都渲

const state = {
  blocks: [],                   // 字段表
  content: {},                  // 当前表单内容，形状与 content.toml 一致
  contents: [],                 // 内容目录里可选的文件名
  themes: [],
  protected: [],
  outDir: '',
  dirty: false,                 // 有没有未保存的改动
  timer: null,
  inflight: false,
  ready: false,
  loading: false,
  saving: false,
  building: false,
  contentVersion: 0,
  previewVersion: 0,
  previewReady: false,
  previewWidth: 794,
  pages: null,
  blanks: [],
  fileName: null,
  fileRevision: null,
  listSeparator: null,
  trimPattern: null,
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
  mode: document.getElementById('stat-mode'),
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
 * kind=list  一行里用「空格 / 空格」分隔（面包屑、关键词那种短词组）。
 *            只有两侧至少一边带空白的斜杠才算分隔符，所以网址能整条写进去。
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
    return raw.split(state.listSeparator).map(trimInput).filter(Boolean);
  }
  if (field.kind === 'lines') {
    return raw.split('\n').map(trimInput).filter(Boolean);
  }
  return raw;
}

function trimInput(value) {
  return value.replace(state.trimPattern, '');
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
  state.contentVersion += 1;
  state.dirty = true;
  el.save.classList.add('dirty');
  schedule();
}

function schedule() {
  clearTimeout(state.timer);
  state.previewVersion += 1;
  state.previewReady = false;
  el.paper.classList.add('stale');
  el.pages.textContent = '页数 — 校验中';
  el.pages.className = 'stat';
  el.blanks.textContent = '空白 —';
  el.blanks.className = 'stat';
  el.downloads.textContent = '';
  updateActions();
  state.timer = setTimeout(preview, PREVIEW_DELAY);
}

async function preview() {
  if (!state.ready || state.loading || state.inflight) return;
  const version = state.previewVersion;
  state.inflight = true;

  try {
    const result = await api('/api/preview', {
      method: 'POST',
      body: JSON.stringify({ content: state.content, theme: el.theme.value }),
    });
    if (version !== state.previewVersion) return;
    // srcdoc 而不是 innerHTML：iframe 里是一份完整文档，也让 sandbox 隔离生效
    el.sheet.srcdoc = result.preview_html || result.html;
    state.previewWidth = result.width;
    el.paper.style.setProperty('--sheet-w', `${result.width}px`);
    el.paper.style.setProperty('--sheet-h', `${result.height}px`);
    el.mode.textContent = result.preview_mode === 'pdf' ? 'PDF 实渲' : 'HTML 近似';
    el.mode.title = result.preview_mode === 'pdf'
      ? `显示前 ${result.shown_pages} 页，与 PDF 使用同一排版`
      : '未安装 pdftoppm，换行仅供参考；页数仍以 PDF 排版为准';
    state.previewReady = true;
    showPages(result.pages);
    showBlanks(result.blanks);
    el.paper.classList.remove('stale');
    fitPaper();
  } catch (error) {
    if (version !== state.previewVersion) return;
    el.pages.textContent = '预览失败';
    el.pages.className = 'stat bad';
    toast(`预览失败：${error.message}`, 'bad');
  } finally {
    state.inflight = false;
    updateActions();
    if (version !== state.previewVersion) {
      clearTimeout(state.timer);
      state.timer = setTimeout(preview, PREVIEW_DELAY);
    }
  }
}

function showPages(pages) {
  state.pages = pages;
  if (pages === 1) {
    el.pages.textContent = '页数 1 ✓';
    el.pages.className = 'stat good';
    return;
  }
  el.pages.textContent = `页数 ${pages} ✗ 砍内容，别缩字号`;
  el.pages.className = 'stat bad';
}

function showBlanks(blanks) {
  state.blanks = blanks || [];
  const count = (blanks || []).length;
  el.blanks.textContent = count ? `空白 ${count} 处` : '空白 0 ✓';
  el.blanks.className = count ? 'stat warn' : 'stat good';
  el.blanks.title = count ? blanks.join('\n') : '';
  updateActions();
}

function updateActions() {
  el.load.disabled = state.loading || state.saving;
  el.save.disabled = !state.ready || state.loading || state.saving;
  const reason = !state.ready || state.loading ? '先读取一份内容'
    : state.building ? '正在生成 PDF'
      : !state.previewReady ? '等待当前内容预览校验'
        : state.blanks.length ? '还有空没填，补齐后才能出 PDF'
          : state.pages !== 1 ? '内容超过一页，请先精简' : '';
  el.render.disabled = Boolean(reason);
  el.render.title = reason;
}

/** 把 A4 那张纸缩放到当前栏宽。 */
function fitPaper() {
  const room = el.paper.clientWidth - 32;       // 减掉 padding
  // 栏被折叠（窄屏把预览藏起来）时 clientWidth 是 0，不能让 scale 变成负数。
  const scale = Math.max(0.1, Math.min(1, room / state.previewWidth));
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
  if (state.loading || state.saving) return;
  if (state.dirty && !confirm('当前改动还没保存，读取会丢掉它们。继续？')) return;
  const version = state.contentVersion;
  state.loading = true;
  updateActions();
  try {
    const result = await api(`/api/content?name=${encodeURIComponent(name)}`);
    if (version !== state.contentVersion) {
      toast('读取期间又有修改，已保留当前表单；需要切换时请重新读取。', 'bad');
      return;
    }
    state.content = result.content;
    state.ready = true;
    state.contentVersion += 1;
    state.fileName = result.name;
    state.fileRevision = result.revision;
    el.name.value = result.name;
    el.file.textContent = readOnlyNote(result);
    clean();
    buildForm();
    schedule();
  } catch (error) {
    toast(`读取失败：${error.message}`, 'bad');
  } finally {
    state.loading = false;
    updateActions();
    if (state.ready && !state.previewReady) {
      clearTimeout(state.timer);
      state.timer = setTimeout(preview, PREVIEW_DELAY);
    }
  }
}

async function save() {
  if (!state.ready || state.loading || state.saving) return;
  const name = el.name.value.trim();
  if (!name) {
    toast('先给内容文件起个名字，比如 content.toml', 'bad');
    return;
  }
  const version = state.contentVersion;
  state.saving = true;
  updateActions();
  try {
    const result = await api('/api/save', {
      method: 'POST',
      body: JSON.stringify({
        name, content: state.content,
        revision: name === state.fileName ? state.fileRevision : null,
      }),
    });
    state.fileName = result.name;
    state.fileRevision = result.revision;
    if (version === state.contentVersion) clean();
    el.file.textContent = result.name;
    if (!state.contents.includes(result.name)) {
      state.contents.push(result.name);
      fillContentList();
    }
    const tail = result.backup ? `，旧文件备份为 ${result.backup}` : '';
    toast(`已写入 ${result.path}${tail}`, 'good');
    if (version === state.contentVersion) showBlanks(result.blanks);
  } catch (error) {
    toast(`保存失败：${error.message}`, 'bad', 5200);
  } finally {
    state.saving = false;
    updateActions();
  }
}

async function build() {
  if (el.render.disabled) return;
  const version = state.previewVersion;
  state.building = true;
  updateActions();
  try {
    const result = await api('/api/render', {
      method: 'POST',
      body: JSON.stringify({
        content: state.content,
        theme: el.theme.value,
      }),
    });
    if (version === state.previewVersion) {
      showDownloads(result.files);
      toast(`已生成到 ${result.out_dir}`, 'good');
    } else {
      toast('生成期间内容已变化，旧版本已生成；请为当前内容重新生成 PDF。');
    }
  } catch (error) {
    toast(error.message, 'bad', 6500);
  } finally {
    state.building = false;
    updateActions();
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
  state.listSeparator = new RegExp(info.input_rules.list_separator, 'u');
  state.trimPattern = new RegExp(`^${info.input_rules.whitespace}+|${info.input_rules.whitespace}+$`, 'gu');
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
    toast('没装 pdftoppm，使用 HTML 近似预览；PDF 照常生成。', '', 4200);
  }

  if (info.default_content) {
    await load(info.default_content);
  } else {
    state.content = emptyContent();
    state.ready = true;
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

updateActions();
boot();
