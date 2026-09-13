/* UI 原语：对话框、提示条、横幅。
 *
 * 这三样是前端里最容易滥用的，所以抽成单独的文件，API 定了就别轻易改：
 * - dialog()  模态对话框，阻塞式交互
 * - toast()   短暂提示，不需要用户操作
 * - banner()  持久横幅，可被关闭
 */

'use strict';

/* ---------- 对话框 ---------- */

let dialogStack = [];
let dialogBackdrop = null;

/**
 * 显示一个模态对话框。
 * @param {object} options
 * @param {string} options.title - 标题
 * @param {string} options.message - 内容（纯文本）
 * @param {Array<{label: string, kind?: string, action: function}>} options.buttons - 按钮列表
 * @returns {HTMLElement} 对话框元素
 */
function dialog({ title, message, buttons }) {
  if (!dialogBackdrop) {
    dialogBackdrop = document.createElement('div');
    dialogBackdrop.className = 'dialog-backdrop';
    document.body.appendChild(dialogBackdrop);
  }

  const box = document.createElement('div');
  box.className = 'dialog';
  box.setAttribute('role', 'dialog');
  box.setAttribute('aria-modal', 'true');

  const header = document.createElement('div');
  header.className = 'dialog-header';
  const h2 = document.createElement('h2');
  h2.textContent = title;
  header.appendChild(h2);

  const body = document.createElement('div');
  body.className = 'dialog-body';
  body.textContent = message;

  const footer = document.createElement('div');
  footer.className = 'dialog-footer';

  buttons.forEach((btn) => {
    const button = document.createElement('button');
    button.textContent = btn.label;
    button.className = btn.kind || 'ghost';
    button.addEventListener('click', () => {
      closeDialog(box);
      if (btn.action) btn.action();
    });
    footer.appendChild(button);
  });

  box.appendChild(header);
  box.appendChild(body);
  box.appendChild(footer);

  dialogBackdrop.appendChild(box);
  dialogBackdrop.classList.add('show');
  dialogStack.push(box);

  // 焦点放在第一个按钮上
  const firstButton = footer.querySelector('button');
  if (firstButton) firstButton.focus();

  return box;
}

function closeDialog(box) {
  const index = dialogStack.indexOf(box);
  if (index !== -1) dialogStack.splice(index, 1);
  box.remove();
  if (dialogStack.length === 0 && dialogBackdrop) {
    dialogBackdrop.classList.remove('show');
  }
}

/* ---------- 提示条 ---------- */

let toastElement = null;
let toastTimer = null;

/**
 * 显示短暂提示。
 * @param {string} message - 提示内容
 * @param {string} kind - 类型：'', 'success', 'error'
 * @param {number} ms - 显示时长（毫秒）
 */
function toast(message, kind = '', ms = 2600) {
  if (!toastElement) {
    toastElement = document.getElementById('toast');
    if (!toastElement) {
      toastElement = document.createElement('div');
      toastElement.id = 'toast';
      toastElement.className = 'toast';
      toastElement.setAttribute('role', 'status');
      toastElement.setAttribute('aria-live', 'polite');
      document.body.appendChild(toastElement);
    }
  }

  toastElement.textContent = message;
  toastElement.className = `toast show ${kind}`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    toastElement.className = 'toast';
  }, ms);
}

/* ---------- 横幅 ---------- */

/**
 * 显示持久横幅。
 * @param {object} options
 * @param {string} options.message - 内容
 * @param {string} options.kind - 类型：'info', 'warning', 'error'
 * @param {HTMLElement} options.parent - 父容器
 * @returns {HTMLElement} 横幅元素
 */
function banner({ message, kind = 'info', parent = document.body }) {
  const bar = document.createElement('div');
  bar.className = `banner banner-${kind}`;
  bar.setAttribute('role', 'alert');

  const text = document.createElement('span');
  text.textContent = message;
  bar.appendChild(text);

  const closeBtn = document.createElement('button');
  closeBtn.className = 'banner-close';
  closeBtn.textContent = '✕';
  closeBtn.setAttribute('aria-label', '关闭');
  closeBtn.addEventListener('click', () => bar.remove());
  bar.appendChild(closeBtn);

  parent.appendChild(bar);
  return bar;
}
