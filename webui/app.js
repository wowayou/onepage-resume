/* 主流程：状态、接口调用、启动、事件绑定。这个文件最后加载。
 *
 * 加载顺序（见 index.html）：ui → form → preview → export → files → app。
 * 前面几个文件只有函数声明和常量，不碰 DOM；一碰 DOM 就得等这里把 state / el
 * 建好，所以元素查找、事件绑定、boot() 全部留在这个文件里。
 */

'use strict';

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
  defaultContentName: '',        // 新建表单的默认文件名，来自 /api/bootstrap
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
  banners: document.getElementById('banners'),
  load: document.getElementById('btn-load'),
  save: document.getElementById('btn-save'),
  render: document.getElementById('btn-render'),
};

/* ---------- 接口 ---------- */

/** 统一的请求包装：一律带 JSON 头，失败时把服务端的错误码和附加字段一起抛出来。
 *
 * 服务端的错误体是 {"error": "给人看的话", "code": "machine_code", …}，
 * 除 error 外的字段（code、locations、pages、name…）挂在 error.detail 上，
 * 调用方想按错误码分支时用它，不必去解析文案。
 */
async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: options.body ? { 'Content-Type': 'application/json' } : undefined,
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(payload.error || `${response.status} ${response.statusText}`);
    error.status = response.status;
    error.code = payload.code || null;
    const { error: _message, ...rest } = payload;
    error.detail = rest;
    throw error;
  }
  return payload;
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
  state.defaultContentName = info.default_content_name;
  el.name.placeholder = state.defaultContentName;
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
    el.name.value = state.defaultContentName;
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
