/* 读、存、另存为、新建、历史版本，以及"没保存的改动"那份草稿。
 *
 * 网页和 `python fill.py` 认的是同一份 content.toml，所以这里不自己拼 TOML：
 * 表单 JSON 交给服务端，由它走 content_io.py 的原子保存、版本检查和历史快照。
 *
 * 三条规矩：
 * 1. 覆盖前必留快照——这件事由服务端保证，这里只负责把结果说出来。
 * 2. 只读的文件（示例 / 定制版）不硬拼，直接引导到"另存为"。
 * 3. 文件被别的窗口改过时，只给"重新读取"和"另存为"两条路，不提供强制覆盖：
 *    强行盖掉别人的改动是这里最不该有的一个按钮。
 */

'use strict';

const DRAFT_PREFIX = 'onepage-resume:draft:';
const DRAFT_DELAY = 1000;        // 停手 1 秒才写草稿，别每敲一个字都动 localStorage

/* ---------- 状态徽标 ---------- */

function setBadge(text, kind = '') {
  el.badge.textContent = text;
  el.badge.className = `badge ${kind}`;
  el.badge.title = text;
}

function clock(milliseconds) {
  const moment = new Date(milliseconds);
  const pad = (value) => String(value).padStart(2, '0');
  return `${pad(moment.getHours())}:${pad(moment.getMinutes())}`;
}

/** 状态栏右边那个徽标：未命名 / 未保存 / 已保存 HH:MM / 只读：原因。 */
function updateBadge() {
  el.file.textContent = state.fileName || (state.ready ? '（未命名）' : '');
  if (!state.ready) {
    setBadge('');
    return;
  }
  const info = state.fileInfo;
  if (info && !info.writable) {
    setBadge(`只读：${info.reason}`, 'ro');
    return;
  }
  if (!state.fileName) {
    setBadge('未命名', 'warn');
    return;
  }
  if (state.dirty) {
    setBadge('未保存', 'warn');
    return;
  }
  setBadge(state.savedAt ? `已保存 ${clock(state.savedAt)}` : '');
}

/* ---------- 文件下拉 ---------- */

function fillFilePicker() {
  el.picker.textContent = '';
  const placeholder = node('option');
  placeholder.value = '';
  placeholder.textContent = state.files.length ? '选择一份…' : '（内容目录里还没有内容文件）';
  el.picker.append(placeholder);
  state.files.forEach((info) => {
    const option = node('option');
    option.value = info.name;
    // 只读的那几份照样能打开看版面，只是存不回去
    option.textContent = info.writable ? info.name : `${info.name}（只读）`;
    el.picker.append(option);
  });
  syncFilePicker();
}

function syncFilePicker() {
  el.picker.value = state.fileName || '';
}

async function refreshFiles() {
  const info = await api('/api/bootstrap');
  state.files = info.files;
  fillFilePicker();
}

/* ---------- 没保存的改动 ---------- */

function draftKey() {
  return DRAFT_PREFIX + (state.fileName || 'untitled');
}

function writeDraft() {
  try {
    window.localStorage.setItem(draftKey(), JSON.stringify({
      content: state.content,
      theme: el.theme.value,
      savedRevision: state.fileRevision,
      time: Date.now(),
    }));
  } catch (error) {
    // localStorage 被禁用 / 写满：当成没有草稿功能，别拿这个打扰用户
  }
}

function readDraft() {
  try {
    const raw = window.localStorage.getItem(draftKey());
    return raw ? JSON.parse(raw) : null;
  } catch (error) {
    return null;
  }
}

function clearDraft() {
  try {
    window.localStorage.removeItem(draftKey());
  } catch (error) {
    // 同上：清不掉就算了
  }
}

function scheduleDraft() {
  clearTimeout(state.draftTimer);
  state.draftTimer = setTimeout(writeDraft, DRAFT_DELAY);
}

/** 打开一份文件之后，看看有没有上次没存下的改动。
 *  文件在那之后被改过的话照问，但把话说清楚——别让人以为自己改的是当前这一版。 */
async function maybeRestoreDraft(result) {
  const draft = readDraft();
  if (!draft || !draft.content) return false;
  const same = draft.savedRevision && draft.savedRevision === result.revision;
  const { label } = await dialog({
    title: '有一份没保存的改动',
    message: same
      ? `${result.name} 里还留着你上次没保存的改动。要接着改吗？`
      : `${result.name} 自那以后已经被改过（可能是别的窗口或编辑器）。`
        + '那份没保存的改动还要接着改吗？',
    buttons: [{ label: '丢弃', kind: 'cancel' }, { label: '恢复', kind: 'primary' }],
  });
  if (label !== '恢复') {
    clearDraft();
    return false;
  }
  state.content = draft.content;
  state.dirty = true;
  el.save.classList.add('dirty');
  updateBadge();
  return true;
}

/* ---------- 打开 / 新建 ---------- */

/** 有未保存改动时先问一句。返回 true 表示可以继续。 */
async function confirmDiscard(what) {
  if (!state.dirty) return true;
  const { label } = await dialog({
    title: '当前改动还没保存',
    message: `打开${what}会丢掉这些改动。`,
    buttons: [
      { label: '取消', kind: 'cancel' },
      { label: '放弃改动' },
      { label: '保存后切换', kind: 'primary' },
    ],
  });
  if (label === '取消' || label === null) return false;
  if (label === '保存后切换') {
    await saveFile();
    return !state.dirty;          // 没存成（比如撞上了冲突）就先别切
  }
  clearDraft();
  return true;
}

function applyLoaded(result) {
  state.content = result.content;
  state.ready = true;
  state.contentVersion += 1;
  state.fileName = result.name;
  state.fileRevision = result.revision;
  state.fileInfo = {
    name: result.name,
    writable: result.writable,
    reason: result.reason || '',
    extends: result.extends || null,
  };
  state.savedAt = null;
  state.dirty = false;
  el.save.classList.remove('dirty');
  syncFilePicker();
  updateBadge();
}

async function openFile(name, { force = false } = {}) {
  if (state.loading || state.saving) return;
  if (!force && !(await confirmDiscard(`「${name}」`))) {
    syncFilePicker();
    return;
  }
  const version = state.contentVersion;
  state.loading = true;
  updateActions();
  try {
    const result = await api(`/api/content?name=${encodeURIComponent(name)}`);
    if (version !== state.contentVersion) {
      banner('读取期间表单又有修改，已保留当前内容；要切换请再选一次。');
      syncFilePicker();
      return;
    }
    applyLoaded(result);
    buildForm();
    if (await maybeRestoreDraft(result)) buildForm();
    schedule();
  } catch (error) {
    banner(`打开失败：${error.message}`);
    syncFilePicker();          // 选回原来那一份，别停在一个打不开的名字上
  } finally {
    state.loading = false;
    updateActions();
    if (state.ready && !state.previewReady) {
      clearTimeout(state.timer);
      state.timer = setTimeout(preview, PREVIEW_DELAY);
    }
  }
}

async function newFile() {
  if (state.loading || state.saving) return;
  if (!(await confirmDiscard('一份新的空白简历'))) {
    syncFilePicker();
    return;
  }
  state.content = emptyContent();
  state.ready = true;
  state.contentVersion += 1;
  state.fileName = null;
  state.fileRevision = null;
  state.fileInfo = { name: null, writable: true, reason: '', extends: null };
  state.savedAt = null;
  state.dirty = false;
  el.save.classList.remove('dirty');
  syncFilePicker();
  updateBadge();
  buildForm();
  schedule();
}

/* ---------- 保存 ---------- */

/** 保存完（或另存为完）之后，把返回值落到状态上。 */
function applySaved(result, version) {
  state.fileName = result.name;
  state.fileRevision = result.revision;
  state.savedAt = Date.now();
  state.fileInfo = { name: result.name, writable: true, reason: '', extends: null };
  if (version === state.contentVersion) {
    state.dirty = false;
    el.save.classList.remove('dirty');
  }
  clearDraft();
  if (!state.files.some((item) => item.name === result.name)) {
    state.files.push({ name: result.name, writable: true, reason: '', extends: null });
    state.files.sort((left, right) => left.name.localeCompare(right.name));
    fillFilePicker();
  } else {
    syncFilePicker();
  }
  updateBadge();
  if (result.unchanged) {
    toast('内容没变，没有写盘。');
  } else {
    const tail = result.snapshot ? '，上一版已存进 .history/' : '';
    toast(`已保存 ${clock(state.savedAt)}${tail}`, 'good');
  }
  if (version === state.contentVersion) showBlanks(result.blanks);
}

/** 保存失败时的下一步。被改过只给两条路，绝不给"强制覆盖"。 */
function handleSaveError(error) {
  if (error.code === 'modified') {
    banner(`保存失败：${error.message}`, 'bad', [
      { label: '重新读取（丢掉我的改动）',
        onClick: () => openFile(state.fileName, { force: true }) },
      { label: '另存为…', onClick: () => saveAsFile() },
    ]);
    return;
  }
  if (error.code === 'variant' || error.code === 'protected') {
    // 服务端这两句本身就是完整的建议（"请直接编辑该文件"），别再拖一条尾巴
    banner(error.message, 'bad', [{ label: '另存为…', onClick: () => saveAsFile() }]);
    return;
  }
  banner(`保存失败：${error.message}`);
}

async function saveFile() {
  if (!state.ready || state.loading || state.saving) return;
  if (!state.fileName) {
    await saveAsFile();           // 还没起名字：保存就是另存为
    return;
  }
  if (state.fileInfo && !state.fileInfo.writable) {
    banner(`${state.fileName} 是只读的（${state.fileInfo.reason}），写不回去。`
           + '用「另存为…」存成你自己的一份。', 'bad',
           [{ label: '另存为…', onClick: () => saveAsFile() }]);
    return;
  }
  const version = state.contentVersion;
  state.saving = true;
  updateActions();
  try {
    const result = await api('/api/save', {
      method: 'POST',
      body: JSON.stringify({
        name: state.fileName,
        content: state.content,
        revision: state.fileRevision,
        mode: 'update',
      }),
    });
    applySaved(result, version);
  } catch (error) {
    handleSaveError(error);
  } finally {
    state.saving = false;
    updateActions();
  }
}

/** 另存为：一边打字一边问服务端"这个名字收成什么、在不在、能不能写"。 */
async function saveAsFile() {
  if (!state.ready || state.saving) return;

  let latest = null;              // 最近一次 /api/stat 的结果
  let token = 0;                  // 丢弃过期的响应：打字快时它们会乱序回来

  const check = async (raw, controls) => {
    if (!raw.trim()) {
      latest = null;
      controls.setMessage('起个名字。写「acme」就会存成 content.acme.toml。');
      controls.setPrimary({ label: '保存', disabled: true });
      return;
    }
    const mine = ++token;
    let info;
    try {
      info = await api(`/api/stat?kind=content&name=${encodeURIComponent(raw)}`);
    } catch (error) {
      if (mine !== token) return;
      latest = null;
      controls.setMessage(`这个名字用不了：${error.message}`);
      controls.setPrimary({ label: '保存', disabled: true });
      return;
    }
    if (mine !== token) return;
    latest = info;
    if (!info.writable) {
      controls.setMessage(`将写入 ${info.name}\n但这一份是只读的（${info.reason}），`
                          + '不能覆盖。换个名字。');
      controls.setPrimary({ label: '保存', disabled: true });
      return;
    }
    controls.setMessage(info.exists
      ? `将写入 ${info.name}\n它已经存在，保存会覆盖它（覆盖前自动留一份历史版本）。`
      : `将写入 ${info.name}（新文件）`);
    controls.setPrimary({ label: info.exists ? '覆盖' : '保存', disabled: false });
  };

  const { label } = await dialog({
    title: '另存为',
    message: '正在确认文件名…',
    input: { value: state.fileName || '', placeholder: state.defaultContentName },
    buttons: [
      { label: '取消', kind: 'cancel' },
      { label: '保存', kind: 'primary' },
    ],
    open: (box, controls) => { check(state.fileName || '', controls); },
    onInput: (value, controls) => {
      clearTimeout(state.statTimer);
      state.statTimer = setTimeout(() => check(value, controls), 300);
    },
  });

  if (label === '取消' || label === null || !latest || !latest.writable) return;

  const version = state.contentVersion;
  state.saving = true;
  updateActions();
  try {
    const result = await api('/api/save', {
      method: 'POST',
      body: JSON.stringify({
        name: latest.name,
        content: state.content,
        revision: null,
        mode: latest.exists ? 'overwrite' : 'create',
      }),
    });
    applySaved(result, version);
  } catch (error) {
    handleSaveError(error);
  } finally {
    state.saving = false;
    updateActions();
  }
}

/* ---------- 历史版本 ---------- */

async function showHistory() {
  if (!state.fileName) {
    banner('先打开一份内容文件，再看它的历史版本。');
    return;
  }
  let versions;
  try {
    const result = await api(`/api/history?name=${encodeURIComponent(state.fileName)}`);
    versions = result.versions;
  } catch (error) {
    banner(`看不了历史版本：${error.message}`);
    return;
  }
  if (!versions.length) {
    await dialog({
      title: `${state.fileName} 的历史版本`,
      message: '还没有历史版本。每次覆盖之前，上一版都会自动留在这里。',
      buttons: [{ label: '知道了', kind: 'primary' }],
    });
    return;
  }

  const { label } = await dialog({
    title: `${state.fileName} 的历史版本`,
    message: '读入某一版只会替换当前表单，点保存才写回文件。',
    buttons: [{ label: '关闭', kind: 'cancel' }],
    open: (box, controls) => {
      const list = node('div', 'history-list');
      versions.forEach((version) => {
        const row = node('div', 'history-row');
        const when = new Date(version.time * 1000);
        row.append(node('span', 'history-time',
                        `${when.toLocaleString()} · ${relativeTime(version.time)}`));
        row.append(node('span', 'history-size',
                        `${Math.max(1, Math.round(version.size / 1024))} KB`));
        const take = node('button', 'ghost', '读入表单');
        take.type = 'button';
        take.addEventListener('click', () => controls.close(version.id));
        row.append(take);
        list.append(row);
      });
      box.append(list);
    },
  });

  if (!label || label === '关闭') return;
  try {
    const old = await api(`/api/history/read?name=${encodeURIComponent(state.fileName)}`
                          + `&id=${encodeURIComponent(label)}`);
    state.content = old.content;
    state.contentVersion += 1;
    state.dirty = true;
    el.save.classList.add('dirty');
    buildForm();
    schedule();
    updateBadge();
    banner(`已读入 ${state.fileName} 的一个历史版本。点保存就会用它覆盖当前文件`
           + '（现在的这一版同样会先被留进历史）。');
  } catch (error) {
    banner(`读入历史版本失败：${error.message}`);
  }
}
