/* 照着 schema.py 的字段表长出表单。
 *
 * 表单本身不在这里定义：/api/bootstrap 把字段表发过来，buildForm() 照着长。
 * 加一个字段只改 schema.py，这个文件不用动。
 *
 * 值的编辑形态有讲究（见下面「值的编辑形态」一段）：list 字段在输入框里用
 * 「空格 / 空格」分隔、lines 字段一行一条，两者在 TOML 里都是数组。分隔规则由
 * schema.py 发布（/api/bootstrap 的 input_rules），这里不另写一份——写歪了会
 * 出现"网页上看着对、存出来多两个 ›"这种纸面上才看得见的错。
 */

'use strict';

/* ---------- 值的编辑形态 ----------
 * kind=list  一行里用「空格 / 空格」分隔（面包屑、关键词那种短词组）。
 *            只有两侧至少一边带空白的斜杠才算分隔符，所以网址能整条写进去。
 * kind=lines 一行一条（bullet 那种）
 * 这两种在 TOML 里都是数组，只是在输入框里的写法不同。
 */

function toInput(field, value) {
  if (field.kind === 'list') return (value || []).join(' / ');
  if (field.kind === 'lines') return (value || []).join('\n');
  return value == null ? '' : String(value);
}

function fromInput(field, raw) {
  if (field.kind === 'list') {
    return raw.split(state.listSeparator).map(trimInput).filter(Boolean);
  }
  if (field.kind === 'lines') {
    return raw.split('\n').map(trimInput).filter(Boolean);
  }
  return raw;
}

function trimInput(value) {
  return value.replace(state.trimPattern, '');
}

// 这几个空天生要写成几行字，给它们 textarea 而不是单行输入框。
const AREAS = new Set([
  'summary.text', 'skills.text', 'experiences.bullets', 'projects.description',
]);

function isArea(block, field) {
  return field.kind === 'lines' || AREAS.has(`${block.key}.${field.key}`);
}

function emptyValue(field) {
  if (field.kind === 'list' || field.kind === 'lines') {
    return field.default ? fromInput(field, field.default) : [];
  }
  return field.default || '';
}

function emptyRow(block) {
  const row = {};
  block.fields.forEach((field) => { row[field.key] = emptyValue(field); });
  return row;
}

function emptyContent() {
  const content = {};
  state.blocks.forEach((block) => {
    if (block.section_key) content[block.section_key] = { title: block.section_default };
    content[block.key] = block.repeat ? [emptyRow(block)] : emptyRow(block);
  });
  return content;
}

/* ---------- 长出表单 ---------- */

function hintText(field) {
  const bits = [];
  if (field.hint) bits.push(field.hint);
  if (field.kind === 'list') bits.push('用 / 分隔');
  if (field.kind === 'lines') bits.push('一行一条');
  if (field.example) bits.push(`例：${field.example}`);
  if (!field.required) bits.push('可留空');
  return bits.join(' · ');
}

/** 一个空。read/write 把它接到 state.content 上的具体位置。 */
function fieldView(block, field, read, write) {
  const wrap = node('div', 'field');
  const id = `f-${Math.random().toString(36).slice(2, 9)}`;

  const label = node('label', null, field.ask);
  label.htmlFor = id;
  if (field.required) label.append(node('span', 'req', '*'));
  wrap.append(label);

  const hint = hintText(field);
  if (hint) wrap.append(node('span', 'hint', hint));

  const input = isArea(block, field)
    ? node('textarea')
    : node('input');
  input.id = id;
  input.value = toInput(field, read());
  if (input.tagName === 'TEXTAREA') {
    input.rows = field.kind === 'lines' ? 4 : 2;
  } else {
    input.type = 'text';
    input.spellcheck = false;
  }
  if (field.required && !input.value.trim()) input.classList.add('blank');

  // 概况那一段长度最要命（超过四行会把后面的内容挤掉），给它一个字数计。
  const counter = block.key === 'summary' ? node('span', 'count') : null;
  const countUp = () => {
    if (counter) counter.textContent = `${input.value.trim().length} 字`;
  };
  countUp();

  input.addEventListener('input', () => {
    write(fromInput(field, input.value));
    input.classList.toggle('blank', field.required && !input.value.trim());
    countUp();
    touched();
  });

  wrap.append(input);
  if (counter) wrap.append(counter);
  return wrap;
}

/** 数组表里的一条：一张卡，带删除和上下移。 */
function cardView(block, index, rerender) {
  const rows = state.content[block.key];
  const card = node('div', 'card');

  const head = node('div', 'card-head');
  head.append(node('span', 'no', `${block.title} · 第 ${index + 1} 条`));

  const tools = node('div', 'tools');
  const move = (to) => {
    const [row] = rows.splice(index, 1);
    rows.splice(to, 0, row);
    touched();
    rerender();
  };

  const up = node('button', 'icon', '↑');
  up.type = 'button';
  up.title = '上移';
  up.disabled = index === 0;
  up.addEventListener('click', () => move(index - 1));

  const down = node('button', 'icon', '↓');
  down.type = 'button';
  down.title = '下移';
  down.disabled = index === rows.length - 1;
  down.addEventListener('click', () => move(index + 1));

  const drop = node('button', 'icon', '删除');
  drop.type = 'button';
  drop.disabled = rows.length <= block.min_items;
  drop.title = drop.disabled
    ? `至少要有 ${block.min_items} 条`
    : '删除这一条';
  drop.addEventListener('click', () => {
    rows.splice(index, 1);
    touched();
    rerender();
  });

  tools.append(up, down, drop);
  head.append(tools);
  card.append(head);

  block.fields.forEach((field) => {
    card.append(fieldView(
      block, field,
      () => rows[index][field.key],
      (value) => { rows[index][field.key] = value; },
    ));
  });
  return card;
}

function blockView(block) {
  const section = node('section', 'block');
  section.id = `block-${block.key}`;
  section.append(node('h2', null, block.title));
  if (block.intro) section.append(node('p', 'intro', block.intro));

  // 数组表整块会被重画（增删和上下移之后编号要跟着变）
  const body = node('div');
  const rerender = () => {
    body.textContent = '';
    paint();
  };

  function paint() {
    if (block.section_key) {
      body.append(fieldView(
        block,
        {
          key: 'title', ask: '这一栏在页面上叫什么', hint: '左侧竖脊上那几个字',
          example: block.section_default, kind: 'text', required: true, default: '',
        },
        () => (state.content[block.section_key] || {}).title,
        (value) => {
          state.content[block.section_key] = { title: value };
        },
      ));
    }

    if (!block.repeat) {
      block.fields.forEach((field) => {
        body.append(fieldView(
          block, field,
          () => state.content[block.key][field.key],
          (value) => { state.content[block.key][field.key] = value; },
        ));
      });
      return;
    }

    const rows = state.content[block.key];
    rows.forEach((_, index) => body.append(cardView(block, index, rerender)));

    const full = block.max_items && rows.length >= block.max_items;
    const add = node('button', 'add', `+ 再加一条${block.title}`);
    add.type = 'button';
    add.disabled = Boolean(full);
    add.addEventListener('click', () => {
      rows.push(emptyRow(block));
      touched();
      rerender();
    });
    body.append(add);
    if (full) body.append(node('p', 'limit', `最多 ${block.max_items} 条`));
  }

  paint();
  section.append(body);
  return section;
}

function buildForm() {
  el.form.textContent = '';
  el.jump.textContent = '';
  state.blocks.forEach((block) => {
    el.form.append(blockView(block));
    const link = node('a', null, block.title);
    link.href = `#block-${block.key}`;
    el.jump.append(link);
  });
}
