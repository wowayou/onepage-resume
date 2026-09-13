/* 表单渲染：字段、卡片、区块。 */

'use strict';

/** 给某一个字段渲染 <label> + input/textarea。 */
function fieldView(block, field, read, write) {
  const label = node('label');
  label.htmlFor = `${block.key}-${field.key}`;
  label.textContent = field.ask;

  const wrap = node('div', 'field');
  wrap.append(label);

  const value = read();
  let input;
  let counter = null;

  if (field.kind === 'text') {
    input = node('input');
    input.type = 'text';
    input.value = value || '';
    input.placeholder = field.example || field.hint || '';
    if (field.max_length) input.maxLength = field.max_length;
  } else if (field.kind === 'lines') {
    input = node('textarea');
    input.value = value || '';
    input.placeholder = field.example || field.hint || '';
    input.rows = 3;
    if (field.max_length) {
      input.maxLength = field.max_length;
      counter = node('span', 'counter', `0 / ${field.max_length}`);
      const tick = () => {
        counter.textContent = `${input.value.length} / ${field.max_length}`;
      };
      input.addEventListener('input', tick);
      tick();
    }
  } else if (field.kind === 'list') {
    input = node('textarea');
    const lines = Array.isArray(value) ? value : [];
    input.value = lines.join('\n');
    input.placeholder = field.example || field.hint || '';
    input.rows = Math.max(3, lines.length + 1);
  } else {
    // 未知 kind，降级为单行输入
    input = node('input');
    input.type = 'text';
    input.value = value || '';
  }

  input.id = `${block.key}-${field.key}`;
  input.required = Boolean(field.required);
  if (field.hint && field.kind !== 'longtext') input.title = field.hint;

  input.addEventListener('input', () => {
    let val = input.value;
    if (field.kind === 'list') {
      val = val.split('\n').map((line) => line.trim()).filter((line) => line);
    }
    write(val);
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
