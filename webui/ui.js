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

/**
 * 模态对话框：原生 <dialog>，ESC 等于点那个 kind === 'cancel' 的按钮。
 *
 * 返回 Promise，resolve 成 { label, value }：
 *   label  被按下那个按钮当时的文字（ESC 时是取消按钮的）
 *   value  有输入框时是框里此刻的文字，没有就是 null
 *
 * @param {object}   options
 * @param {string}   options.title
 * @param {string}   [options.message]  一段纯文本说明
 * @param {object}   [options.input]    { value, placeholder } 给一个输入框
 * @param {Array}    options.buttons    [{ label, kind }]，kind: 'cancel' | 'primary'
 * @param {function} [options.open]     (box, controls) 往对话框里放别的东西
 * @param {function} [options.onInput]  (value, controls) 每次输入后调用
 *
 * controls 给 open / onInput 用：
 *   close(label)                当作按下了某个按钮：关掉并 resolve
 *   setMessage(text)            换掉那段说明
 *   setPrimary({label, disabled})  改主按钮的文字 / 禁用态
 *
 * 按钮先造好、最后才挂进对话框，这样 open() 放进去的内容自然排在按钮上方，
 * 而 controls.setPrimary() 在那之前就能用。
 */
function dialog({ title, message, input, buttons, open, onInput }) {
  return new Promise((resolve) => {
    const box = node('dialog', 'dialog');
    if (title) box.append(node('h2', 'dialog-title', title));

    const messageElement = message ? node('p', 'dialog-message', message) : null;
    if (messageElement) box.append(messageElement);

    let field = null;
    if (input) {
      field = node('input', 'dialog-input');
      field.type = 'text';
      field.value = input.value || '';
      field.placeholder = input.placeholder || '';
      field.spellcheck = false;
      field.autocomplete = 'off';
      box.append(field);
    }

    const row = node('div', 'dialog-actions');
    let primary = null;
    let settled = false;
    const finish = (label) => {
      if (settled) return;               // ESC 与按钮点击可能都到，只认第一次
      settled = true;
      const value = field ? field.value : null;
      box.close();
      box.remove();
      resolve({ label, value });
    };

    let cancelLabel = null;
    buttons.forEach((button) => {
      if (button.kind === 'cancel') cancelLabel = button.label;
      const item = node('button', button.kind === 'primary' ? 'primary' : null,
                        button.label);
      item.type = 'button';
      // 用点击那一刻的文字，而不是创建时的：主按钮的文字会随输入变（保存 / 覆盖）
      item.addEventListener('click', () => finish(item.textContent));
      if (button.kind === 'primary') primary = item;
      row.append(item);
    });

    const controls = {
      close: finish,
      setMessage(text) {
        if (messageElement) messageElement.textContent = text;
      },
      setPrimary({ label, disabled = false } = {}) {
        if (!primary) return;
        if (label) primary.textContent = label;
        primary.disabled = disabled;
      },
    };

    if (open) open(box, controls);        // 自定义内容排在按钮上方
    box.append(row);
    if (field && onInput) field.addEventListener('input', () => onInput(field.value, controls));

    // ESC 或点背景关闭：算作点了那个 kind === 'cancel' 的按钮。
    box.addEventListener('cancel', (event) => {
      event.preventDefault();
      finish(cancelLabel);
    });

    document.body.append(box);
    box.showModal();
    if (field) field.focus();
  });
}

/** 把时间戳说成"3 分钟前"这种，历史版本列表用。 */
function relativeTime(seconds) {
  const gap = Math.max(0, Math.round(Date.now() / 1000 - seconds));
  if (gap < 60) return '刚刚';
  if (gap < 3600) return `${Math.floor(gap / 60)} 分钟前`;
  if (gap < 86400) return `${Math.floor(gap / 3600)} 小时前`;
  return `${Math.floor(gap / 86400)} 天前`;
}

/* ---------- 横幅 ---------- */

/** 持久横幅：留给"必须被看到、且要先处理再继续"的错误。
 *
 * actions 是 [{ label, onClick }]，用来就地给出下一步
 * （"被别的窗口改过"时那两个按钮）。返回元素本身，用户可以自己关掉。 */
function banner(message, kind = 'bad', actions = []) {
  const bar = node('div', `banner ${kind}`);
  bar.append(node('span', 'banner-text', message));
  if (actions.length) {
    const row = node('div', 'banner-actions');
    actions.forEach((action) => {
      const item = node('button', 'ghost', action.label);
      item.type = 'button';
      item.addEventListener('click', () => {
        bar.remove();
        action.onClick();
      });
      row.append(item);
    });
    bar.append(row);
  }
  const close = node('button', 'banner-close', '关闭');
  close.type = 'button';
  close.addEventListener('click', () => bar.remove());
  bar.append(close);
  el.banners.append(bar);
  return bar;
}
