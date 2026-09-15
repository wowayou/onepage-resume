/* UI 原语：DOM 节点简写、提示条、模态对话框、横幅。
 *
 * 这里只放"界面零件"，不放业务：谁要弹窗、谁要提示，由 files.js / export.js 决定。
 * 改动集中在两处要求：
 *   · 对话框用原生 <dialog> + showModal()，ESC 等价于点取消，不再用 confirm()。
 *   · 提示条与横幅分开：toast 是短暂的、不需要回应的；banner 是持久的、可关闭的。
 */

'use strict';

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

/* ---------- 对话框 ---------- */

/** 模态对话框。返回 Promise，resolve 成被按下那个按钮的 label；按 ESC 得到 null。
 *
 * 用法：
 *     const answer = await dialog({
 *       title: '这一栏还没填完',
 *       message: '……',
 *       buttons: [
 *         { label: '取消', kind: 'cancel' },
 *         { label: '继续', kind: 'primary' },
 *       ],
 *     });
 *     if (answer === '继续') { … }
 */
function dialog({ title, message, buttons }) {
  return new Promise((resolve) => {
    const box = node('dialog', 'dialog');
    if (title) box.append(node('h2', 'dialog-title', title));
    if (message) box.append(node('p', 'dialog-message', message));

    const row = node('div', 'dialog-actions');
    box.append(row);

    let settled = false;
    const finish = (label) => {
      if (settled) return;              // ESC 与按钮点击可能都到，只认第一次
      settled = true;
      box.close();
      box.remove();
      resolve(label);
    };

    let cancelLabel = null;
    buttons.forEach((button) => {
      if (button.kind === 'cancel') cancelLabel = button.label;
      const item = node('button', button.kind === 'primary' ? 'primary' : null,
                        button.label);
      item.type = 'button';
      item.addEventListener('click', () => finish(button.label));
      row.append(item);
    });

    // ESC 或点背景关闭：算作点了那个 kind === 'cancel' 的按钮。
    box.addEventListener('cancel', (event) => {
      event.preventDefault();
      finish(cancelLabel);
    });

    document.body.append(box);
    box.showModal();
  });
}

/* ---------- 横幅 ---------- */

/** 持久横幅：留给"必须被看到、且要先处理再继续"的错误。返回元素本身，
 *  调用方不需要它时可以直接忽略；用户可以自己关掉。 */
function banner(message, kind = 'bad') {
  const bar = node('div', `banner ${kind}`);
  bar.append(node('span', 'banner-text', message));
  const close = node('button', 'banner-close', '关闭');
  close.type = 'button';
  close.addEventListener('click', () => bar.remove());
  bar.append(close);
  el.banners.append(bar);
  return bar;
}
