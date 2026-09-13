/* 工具函数：DOM 节点创建、API 调用、空数据构造。 */

'use strict';

/** 简写 createElement + className + textContent。 */
function node(tag, cls, text) {
  const el = document.createElement(tag);
  if (cls) el.className = cls;
  if (text !== undefined) el.textContent = text;
  return el;
}

/** 统一的 API 请求包装，把错误从响应里扔出来。 */
async function api(url, options = {}) {
  const response = await fetch(url, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error);
  return data;
}

/** 给一个 repeat block 造一条空行。 */
function emptyRow(block) {
  const row = {};
  block.fields.forEach((field) => {
    row[field.key] = field.default !== undefined ? field.default : '';
  });
  return row;
}

/** 初始化时的空文档。 */
function emptyContent() {
  const content = {};
  state.blocks.forEach((block) => {
    if (block.repeat) {
      const rows = [];
      for (let i = 0; i < (block.min_items || 0); i += 1) rows.push(emptyRow(block));
      content[block.key] = rows;
    } else {
      const row = {};
      block.fields.forEach((field) => {
        row[field.key] = field.default !== undefined ? field.default : '';
      });
      content[block.key] = row;
    }
    if (block.section_key) {
      content[block.section_key] = { title: block.section_default || '' };
    }
  });
  return content;
}

/** 短暂提示，不阻塞用户。类型：'' | 'good' | 'bad'。 */
function toast(message, kind = '', ms = 2600) {
  console.log(`[toast ${kind}] ${message}`);
  // 实际 UI 由 ui.js 提供，这里只是日志占位
  // 后续 app.js 里会真正接入
}
