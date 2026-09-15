/* 主流程：状态、接口调用、启动、事件绑定。这个文件最后加载。
 *
 * 加载顺序（见 index.html）：ui → form → preview → export → files → app。
 * 前面几个文件只有函数声明和常量，不碰 DOM；一碰 DOM 就得等这里把 state / el
 * 建好，所以元素查找、事件绑定、boot() 全部留在这个文件里。
 */

'use strict';

const el = {
  form: document.getElementById('form'),
  jump: document.getElementById('jump'),
  sheet: document.getElementById('sheet'),
  paper: document.getElementById('paper'),
  picker: document.getElementById('file-picker'),
  theme: document.getElementById('theme-name'),
  pages: document.getElementById('stat-pages'),
  blanks: document.getElementById('stat-blanks'),
  blankList: document.getElementById('blank-list'),
  file: document.getElementById('stat-file'),
  badge: document.getElementById('stat-badge'),
  mode: document.getElementById('stat-mode'),
  results: document.getElementById('results'),
  toast: document.getElementById('toast'),
  banners: document.getElementById('banners'),
  new: document.getElementById('btn-new'),
  save: document.getElementById('btn-save'),
  saveAs: document.getElementById('btn-save-as'),
  history: document.getElementById('btn-history'),
  render: document.getElementById('btn-render'),
  help: document.getElementById('btn-help'),
};

const state = {
  blocks: [],                   // 字段表
  content: {},                  // 当前表单内容，形状与 content.toml 一致
  files: [],                    // 内容目录里的文件 [{name, writable, reason, extends}]
  themes: [],
  outDir: '',
  contentDir: '',
  dirty: false,                 // 有没有未保存的改动
  timer: null,                  // 预览防抖
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
  blanks: [],                   // 空白的文字说明
  blankLocations: [],           // 同一批空的结构化位置，点着能跳过去
  blanksOpen: false,
  fileName: null,
  fileRevision: null,
  fileInfo: { name: null, writable: true, reason: '', extends: null },
  savedAt: null,                // 上次保存成功的时间戳
  lastBuild: null,              // 最近一次生成的结果，结果区读它
  draftTimer: null,
  statTimer: null,
  listSeparator: null,
  trimPattern: null,
  defaultContentName: '',        // 新建表单的默认文件名，来自 /api/bootstrap
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
    banner(`启动失败：${error.message}`);
    return;
  }

  state.blocks = info.blocks;
  state.listSeparator = new RegExp(info.input_rules.list_separator, 'u');
  state.trimPattern = new RegExp(`^${info.input_rules.whitespace}+|${info.input_rules.whitespace}+$`, 'gu');
  state.defaultContentName = info.default_content_name;
  state.files = info.files;
  state.themes = info.themes;
  state.outDir = info.out_dir;
  state.contentDir = info.content_dir;

  fillFilePicker();
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
    await openFile(info.default_content);
  } else {
    await newFile();              // 内容目录里还什么都没有：从空表单开始
  }
  fitPaper();
}

/* ---------- 帮助 ---------- */

function showHelp() {
  dialog({
    title: '这个界面怎么用',
    message: [
      '1. 顶上「文件」里挑一份，或者点「新建」；左边填，右边实时看 A4。',
      '2. 打字停下就自动重排。页数不是 1、或者还有空白，状态栏会立刻变色。',
      '3. Ctrl-S 保存。第一次要起个名字，以后就是写回同一份。',
      '4. 每次覆盖之前，上一版都会留在内容目录的 .history/ 里，随时读得回来。',
      '5. 点「生成 PDF」出附件；投递前先看 PNG，确认无误再发 PDF。',
      '',
      `内容目录：${state.contentDir}`,
      `生成物：　${state.outDir}`,
    ].join('\n'),
    buttons: [{ label: '知道了', kind: 'primary' }],
  });
}

el.picker.addEventListener('change', () => {
  const name = el.picker.value;
  if (name) openFile(name);
});
el.new.addEventListener('click', newFile);
el.save.addEventListener('click', saveFile);
el.saveAs.addEventListener('click', saveAsFile);
el.history.addEventListener('click', showHistory);
el.render.addEventListener('click', showBuildDialog);
el.theme.addEventListener('change', schedule);
el.sheet.addEventListener('load', fitPaper);
el.help.addEventListener('click', showHelp);
el.blanks.addEventListener('click', toggleBlankList);
window.addEventListener('resize', fitPaper);

// Ctrl-S / ⌘-S 存盘，和编辑器里的手感一致
window.addEventListener('keydown', (event) => {
  if ((event.ctrlKey || event.metaKey) && event.key === 's') {
    event.preventDefault();
    saveFile();
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
