/* 预览：防抖、请求、页数与空白显示、纸张缩放。
 *
 * 预览走 render.py 真渲（/api/preview 返回 WeasyPrint 排出来的页面图），不是前端
 * 另写一套近似排版——所以屏幕上的换行和页数与 PDF 一致，这一条是刻意的。
 *
 * 每个窗口最多一个在途请求：预览版本号对不上就丢弃旧响应，绝不拿旧结果去校验新内容。
 */

'use strict';

const PREVIEW_DELAY = 400;      // 打字停下 400ms 才渲染，别每敲一个字都渲

function touched() {
  state.contentVersion += 1;
  state.dirty = true;
  el.save.classList.add('dirty');
  updateBadge();                 // 徽标立刻从"已保存"变成"未保存"
  scheduleDraft();               // 停手一秒后把草稿写进 localStorage
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
  // 内容一变，上一次的生成结果就对不上了，先收起来
  el.results.textContent = '';
  el.results.hidden = true;
  state.lastBuild = null;
  closeBlankList();
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
    showBlanks(result.blanks, result.locations);
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

function showBlanks(blanks, locations) {
  state.blanks = blanks || [];
  if (locations) state.blankLocations = locations;
  const count = state.blanks.length;
  el.blanks.textContent = count ? `空白 ${count} 处` : '空白 0 ✓';
  el.blanks.className = count ? 'stat warn' : 'stat good';
  el.blanks.title = count ? state.blanks.join('\n') : '';
  if (!count) closeBlankList();
  else if (state.blanksOpen) renderBlankList();
  updateActions();
}

/* ---------- 空白清单 ---------- */
/* 状态栏那句"空白 N 处"是可以点的：点开列出每一处，点一条就跳到那个输入框。
   只报个数字的话，用户还得自己一行行找。 */

function renderBlankList() {
  el.blankList.textContent = '';
  state.blankLocations.forEach((location) => {
    const item = node('button', 'blank-item', location.message);
    item.type = 'button';
    item.addEventListener('click', () => jumpToBlank(location));
    el.blankList.append(item);
  });
  el.blankList.hidden = false;
}

function closeBlankList() {
  state.blanksOpen = false;
  el.blankList.hidden = true;
  el.blankList.textContent = '';
  el.blanks.setAttribute('aria-expanded', 'false');
}

function toggleBlankList() {
  if (state.blanksOpen) {
    closeBlankList();
    return;
  }
  if (!state.blankLocations.length) return;
  state.blanksOpen = true;
  el.blanks.setAttribute('aria-expanded', 'true');
  renderBlankList();
}

function jumpToBlank(location) {
  const field = fieldElement(location);
  if (!field) {
    toast('这一处空在当前表单里找不到对应的输入框。', 'bad');
    return;
  }
  field.scrollIntoView({ block: 'center' });
  field.focus({ preventScroll: true });
  field.classList.add('flash');
  setTimeout(() => field.classList.remove('flash'), 1500);
}

function updateActions() {
  const busy = state.loading || state.saving;
  el.new.disabled = busy;
  el.save.disabled = !state.ready || busy;
  el.saveAs.disabled = !state.ready || busy;
  el.history.disabled = !state.ready || busy || !state.fileName;
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
