/* 读、存：打开一份内容文件，把表单写回去。
 *
 * 网页和 `python fill.py` 认的是同一份 content.toml，所以这里不自己拼 TOML：
 * 表单 JSON 交给服务端，由它走 content_io.py 的原子保存与版本检查。
 * 读取时带着 revision，保存时原样送回——文件被别的窗口改过就会被拒绝，不会静默覆盖。
 */

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
  if (state.dirty) {
    const answer = await dialog({
      title: '当前改动还没保存',
      message: `读取 ${name} 会丢掉这些改动。`,
      buttons: [
        { label: '取消', kind: 'cancel' },
        { label: '放弃改动并读取', kind: 'primary' },
      ],
    });
    if (answer !== '放弃改动并读取') return;
  }
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
    banner(`读取失败：${error.message}`);
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
    banner(`保存失败：${error.message}`);
  } finally {
    state.saving = false;
    updateActions();
  }
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
