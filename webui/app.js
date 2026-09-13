/* 主流程：状态、启动、事件绑定。 */

'use strict';

const el = {
  form: document.getElementById('form'),
  jump: document.getElementById('jump'),
  load: document.getElementById('btn-load'),
  save: document.getElementById('btn-save'),
  render: document.getElementById('btn-render'),
  name: document.getElementById('content-name'),
  file: document.getElementById('stat-file'),
  list: document.getElementById('content-list'),
  theme: document.getElementById('theme-name'),
  paper: document.getElementById('paper'),
  sheet: document.getElementById('sheet'),
  mode: document.getElementById('stat-mode'),
  pages: document.getElementById('stat-pages'),
  blanks: document.getElementById('stat-blanks'),
  downloads: document.getElementById('downloads'),
};

const state = {
  ready: false,               // 是否已读到 bootstrap
  loading: false,             // 正在读取内容文件
  saving: false,              // 正在保存
  building: false,            // 正在生成 PDF
  dirty: false,               // 是否有未保存改动
  inflight: false,            // 预览请求在途中
  previewReady: false,        // 当前预览是否可用
  contentVersion: 0,          // 内容版本号，读/存时用来检测冲突
  previewVersion: 0,          // 预览版本号，用来丢弃过期的预览结果
  timer: null,                // schedule() 的定时器
  content: {},                // 当前表单数据
  fileName: '',               // 当前打开的文件名
  fileRevision: null,         // 文件修改时间戳，用于冲突检测
  blocks: [],                 // schema 定义的区块列表
  contents: [],               // 可用的内容文件列表
  protected: [],              // 只读的示例文件列表
  themes: [],                 // 可用主题列表
  listSeparator: null,        // list 字段的分隔符正则
  trimPattern: null,          // 空白修剪正则
  defaultContentName: '',     // 默认内容文件名
  outDir: '',                 // 输出目录路径
  pages: 0,                   // 当前页数
  blanks: [],                 // 空白字段列表
  previewWidth: 595,          // A4 宽度（像素）
};

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
