/* 生成与导出：出 PDF / PNG / HTML，以及生成之后那几步。
 *
 * 生成物有哪些、叫什么名字由服务端 render.write_outputs() 说了算，这里只负责
 * 在生成之前把"会写到哪、撞名了怎么办"问清楚，在生成之后把文件交到用户手里。
 *
 * 两条边界：
 *   · "查看"只给能在浏览器沙箱里自己打开的（PDF、PNG）。HTML 永远只给下载——
 *     内联打开等于让生成的页面脚本跑在本服务的源下。
 *   · 服务跑在 WSL、浏览器在 Windows，所以"存到哪"的系统对话框只能由浏览器出
 *     （File System Access API）。服务端出不了 Windows 的保存对话框。
 */

'use strict';

// 能内联查看的类型：新标签页里交给浏览器自带的 PDF 阅读器 / 图片查看器。
const INLINE_KINDS = new Set(['pdf', 'png']);

const SUFFIX_TYPES = {
  '.pdf': 'application/pdf',
  '.png': 'image/png',
  '.html': 'text/html',
};

const SUFFIX_LABELS = {
  '.pdf': 'PDF 文档',
  '.png': 'PNG 图片',
  '.html': 'HTML 文件',
};

function canPickFiles() {
  return typeof window.showSaveFilePicker === 'function';
}

function artifactUrl(name, inline) {
  const suffix = inline ? '&inline=1' : '';
  return `/api/artifact?name=${encodeURIComponent(name)}${suffix}`;
}

/* ---------- 生成前的对话框 ---------- */

async function showBuildDialog() {
  if (!state.ready || state.building) return;
  if (!state.previewReady || state.blanks.length || state.pages !== 1) {
    banner('先把内容改到一页、而且没有空白，再生成 PDF。');
    return;
  }

  let latest = null;
  let policy = 'rename';        // 撞名时选哪个：默认改成新名字，不覆盖别人的东西
  let token = 0;                // 丢弃过期的 /api/stat 响应
  let pickInput = null;
  let conflictBox = null;

  const renderChoices = (info) => {
    conflictBox.textContent = '';
    [
      { value: 'rename', text: `自动改名为 ${info.suggested}.pdf` },
      { value: 'overwrite', text: `覆盖已有的 ${info.conflict}` },
    ].forEach((option) => {
      const item = node('label', 'dialog-choice-item');
      const radio = node('input');
      radio.type = 'radio';
      radio.name = 'if-exists';
      radio.value = option.value;
      radio.checked = option.value === policy;
      radio.addEventListener('change', () => { policy = option.value; });
      item.append(radio, node('span', null, option.text));
      conflictBox.append(item);
    });
  };

  const check = async (raw, controls) => {
    const mine = ++token;
    let info;
    try {
      info = await api(`/api/stat?kind=artifact&name=${encodeURIComponent(raw)}`);
    } catch (error) {
      if (mine !== token) return;
      latest = null;
      controls.setMessage(`这个名字用不了：${error.message}`);
      controls.setPrimary({ label: '生成', disabled: true });
      return;
    }
    if (mine !== token) return;
    latest = info;
    const willWrite = `将生成到 ${state.outDir}\n${info.name}.pdf / .png / .html`;
    if (!info.exists) {
      conflictBox.hidden = true;
      controls.setMessage(willWrite);
      controls.setPrimary({ label: '生成', disabled: false });
      return;
    }
    renderChoices(info);
    conflictBox.hidden = false;
    controls.setMessage(`${willWrite}\n不过已经有 ${info.conflict} 了，选一下怎么办：`);
  };

  const { label } = await dialog({
    title: '生成 PDF',
    message: '正在确认文件名…',
    input: {
      value: state.content.document.output_basename || '',
      placeholder: 'resume',
    },
    buttons: [
      { label: '取消', kind: 'cancel' },
      { label: '生成', kind: 'primary' },
    ],
    open: (box, controls) => {
      box.append(node('p', 'dialog-note', `版式：${el.theme.value}`));
      conflictBox = node('div', 'dialog-choice');
      conflictBox.hidden = true;
      box.append(conflictBox);
      if (canPickFiles()) {
        const item = node('label', 'dialog-check');
        pickInput = node('input');
        pickInput.type = 'checkbox';
        pickInput.checked = true;
        item.append(pickInput, node('span', null, '生成后让我选择保存位置'));
        box.append(item);
      } else {
        box.append(node('p', 'dialog-note muted',
                        '这个浏览器不支持选择保存位置，将按浏览器自己的下载设置保存。'));
      }
      check(controls.field ? controls.field.value : '', controls);
    },
    onInput: (value, controls) => {
      clearTimeout(state.statTimer);
      state.statTimer = setTimeout(() => check(value, controls), 300);
    },
  });

  if (label !== '生成' || !latest) return;
  // 没有撞名时仍然把 fail 传下去：万一这几秒里别人也生成了同名文件，
  // 宁可被拒一次，也别无声把人家的覆盖掉。
  await runBuild(latest.name, latest.exists ? policy : 'fail',
                 pickInput ? pickInput.checked : false);
}

/* ---------- 生成 ---------- */

async function runBuild(basename, ifExists, pickAfter) {
  const version = state.previewVersion;
  state.building = true;
  updateActions();
  try {
    const result = await api('/api/render', {
      method: 'POST',
      body: JSON.stringify({
        content: state.content,
        theme: el.theme.value,
        basename,
        if_exists: ifExists,
      }),
    });
    showResults(result);
    toast(`已生成到 ${result.out_dir}`, 'good');
    if (version !== state.previewVersion) {
      banner('生成期间内容又变了：上面这几个文件是改动之前那一版，要出当前这版请再生成一次。');
    }
    if (pickAfter && result.files.pdf) await saveArtifactTo(result.files.pdf);
  } catch (error) {
    handleBuildError(error);
  } finally {
    state.building = false;
    updateActions();
  }
}

function handleBuildError(error) {
  if (error.code === 'blanks') {
    // 空白清单直接在状态栏摊开，点一条就跳过去
    if (error.detail.blanks) showBlanks(error.detail.blanks, error.detail.locations);
    if (!state.blanksOpen) toggleBlankList();
    banner(error.message);
    return;
  }
  if (error.code === 'exists') {
    banner(`${error.message}再点一次「生成 PDF…」，会问你是改名还是覆盖。`, 'bad',
           [{ label: '重新生成', onClick: () => showBuildDialog() }]);
    return;
  }
  // 超页（overflow）等：服务端的文案已经说清了页数和该怎么办
  banner(error.message);
}

/* ---------- 生成之后 ---------- */

function showResults(result) {
  state.lastBuild = result;
  el.results.textContent = '';
  el.results.hidden = false;

  ['pdf', 'png', 'html'].forEach((kind) => {
    const name = result.files[kind];
    if (!name) return;
    const row = node('div', 'result-row');
    row.append(node('span', 'result-kind', kind.toUpperCase()));
    row.append(node('span', 'result-name', name));

    const actions = node('div', 'result-actions');
    if (INLINE_KINDS.has(kind)) {
      const view = node('a', 'ghost', '查看');
      view.href = artifactUrl(name, true);
      view.target = '_blank';
      view.rel = 'noopener';
      view.title = `在浏览器里打开 ${name}`;
      actions.append(view);
    }
    const download = node('a', 'ghost', '下载');
    download.href = artifactUrl(name, false);
    download.title = `下载 ${name}`;
    actions.append(download);

    const saveTo = node('button', 'ghost', '另存到…');
    saveTo.type = 'button';
    if (canPickFiles()) {
      saveTo.addEventListener('click', () => saveArtifactTo(name));
    } else {
      saveTo.disabled = true;
      saveTo.title = '这个浏览器不支持选择保存位置，用「下载」吧';
    }
    actions.append(saveTo);

    const reveal = node('button', 'ghost', '在文件夹中显示');
    reveal.type = 'button';
    reveal.addEventListener('click', () => revealArtifact(name));
    actions.append(reveal);

    row.append(actions);
    el.results.append(row);
  });

  if (!result.files.png) {
    el.results.append(node('p', 'result-note',
                           '没有 PNG：这台机器缺 pdftoppm，装 poppler-utils 就有了（PDF 照常可用）。'));
  }
}

/** 让浏览器弹出系统保存对话框，把服务端那份文件写到用户选的地方。 */
async function saveArtifactTo(name) {
  if (!canPickFiles()) return;
  const suffix = name.slice(name.lastIndexOf('.'));
  let handle;
  try {
    handle = await window.showSaveFilePicker({
      suggestedName: name,
      types: [{
        description: SUFFIX_LABELS[suffix] || '文件',
        accept: { [SUFFIX_TYPES[suffix] || 'application/octet-stream']: [suffix] },
      }],
    });
  } catch (error) {
    if (error.name === 'AbortError') return;      // 用户自己点了取消，不是错
    // 浏览器只肯在"用户刚点过"的几秒内弹这个对话框，而生成要渲一遍 PDF。
    // 渲染慢一点就赶上过期了——这不是错，指个路就行。
    // Chrome 按规范抛 SecurityError，别的实现可能抛 NotAllowedError，两个都接。
    if (error.name === 'SecurityError' || error.name === 'NotAllowedError') {
      banner('文件已经生成好了，但浏览器要你亲手点一下「另存到…」才会弹保存对话框。');
      return;
    }
    banner(`打不开保存对话框：${error.message}`);
    return;
  }
  try {
    const response = await fetch(artifactUrl(name, false));
    if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
    const writable = await handle.createWritable();
    await writable.write(await response.blob());
    await writable.close();
    toast(`已保存到 ${handle.name}`, 'good');
  } catch (error) {
    banner(`保存失败：${error.message}`);
  }
}

/** 在文件管理器里选中这个文件。服务端出不了对话框，只能开一个窗口。 */
async function revealArtifact(name) {
  try {
    await api('/api/reveal', { method: 'POST', body: JSON.stringify({ name }) });
  } catch (error) {
    if (error.code === 'unsupported') {
      const path = error.detail.path || '';
      const answer = await dialog({
        title: '打不开文件管理器',
        message: `${error.message}\n可以复制路径，自己找过去。`,
        buttons: [
          { label: '知道了', kind: 'cancel' },
          { label: '复制路径', kind: 'primary' },
        ],
      });
      if (answer.label === '复制路径') {
        try {
          await window.navigator.clipboard.writeText(path);
          toast('路径已复制', 'good');
        } catch (copyError) {
          banner(`复制不了，路径是：${path}`);
        }
      }
      return;
    }
    banner(error.message);
  }
}
