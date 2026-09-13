/* 读、存、生成：与后端的 I/O 交互。 */

'use strict';

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
    toast(`先给内容文件起个名字，比如 ${state.defaultContentName}`, 'bad');
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

// 能内联查看的类型：新标签页里交给浏览器自带的 PDF 阅读器 / 图片查看器。
// HTML 不给「查看」——内联打开等于让生成的页面脚本跑在本服务的源下。
const INLINE_KINDS = new Set(['pdf', 'png']);

function artifactUrl(name, inline) {
  const suffix = inline ? '&inline=1' : '';
  return `/api/artifact?name=${encodeURIComponent(name)}${suffix}`;
}

function showDownloads(files) {
  el.downloads.textContent = '';
  ['pdf', 'png', 'html'].forEach((kind) => {
    const name = files[kind];
    if (!name) return;
    if (INLINE_KINDS.has(kind)) {
      const view = node('a', null, `${kind.toUpperCase()} 查看`);
      view.href = artifactUrl(name, true);
      view.target = '_blank';
      view.rel = 'noopener';
      view.title = `在浏览器里打开 ${name}`;
      el.downloads.append(view);
    }
    const link = node('a', null, `${kind.toUpperCase()} 下载`);
    link.href = artifactUrl(name, false);
    link.title = `下载 ${name}`;
    el.downloads.append(link);
  });
}

function clean() {
  state.dirty = false;
  el.save.classList.remove('dirty');
}

function fillContentList() {
  el.list.textContent = '';
  state.contents.slice().sort().forEach((name) => {
    const option = node('option');
    option.value = name;
    if (state.protected.includes(name)) option.label = `${name}（示例，只读）`;
    el.list.append(option);
  });
}
