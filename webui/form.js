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
  // 新建的空表单只含内建块，不写 body_order / custom_sections——
  // 这样它落盘后和改造前逐字节一致，老文件的语义不变。
  state.builtins.forEach((block) => {
    if (block.section_key) content[block.section_key] = { title: block.section_default };
    content[block.key] = block.repeat ? [emptyRow(block)] : emptyRow(block);
  });
  return content;
}

/* ---------- 板块模型：内建块是代码，自定义块是数据 ----------
 * state.builtins  来自 /api/bootstrap 的 describe()，永远只有内建那八块。
 * state.blocks    每次重画表单时合成：内建八块 + 从当前内容里的
 *                 custom_sections 现长出来的自定义块。字段表仍只在
 *                 schema.py 定义一次，自定义块的字段定义随内容文件走。
 */

const CUSTOM_PREFIX = 'custom:';
// 哪些内建块是正文块（有竖脊栏目名、能排序/删除），哪些是固定在最上面的
// 抬头块——都从 bootstrap 里每个块的 body 标志现算，schema.py 定义一次，
// 前端不再自己抄一份块名单。
function bodyBuiltins() {
  return state.builtins.filter((block) => block.body).map((block) => block.key);
}

function headerBuiltins() {
  return state.builtins.filter((block) => !block.body).map((block) => block.key);
}

/** 把一个 custom_sections 条目合成成和 describe() 同形状的 block。 */
function customBlock(section) {
  return {
    key: CUSTOM_PREFIX + section.key,
    title: section.title || section.key,
    intro: '',
    repeat: true,
    min_items: 1,
    max_items: 0,
    section_key: null,
    section_default: section.title || section.key,
    identity: section.identity || '',
    fields: Array.isArray(section.fields) ? section.fields : [],
    body: true,
    custom: true,
  };
}

/** 当前内容里声明的自定义板块（按声明顺序）。 */
function customSections() {
  const list = state.content.custom_sections;
  return Array.isArray(list) ? list.filter((s) => s && typeof s.key === 'string') : [];
}

/** 按 "custom:key" 找回原始 section 字典（可写，改它就改到了内容上）。 */
function customSection(blockKey) {
  const key = blockKey.slice(CUSTOM_PREFIX.length);
  return customSections().find((section) => section.key === key) || null;
}

/** 重建 state.blocks = 内建八块 + 现有自定义块。每次 buildForm 前调用。 */
function syncBlocks() {
  state.blocks = [...state.builtins, ...customSections().map(customBlock)];
}

/** 一个板块的数据行放在哪：内建块在自己的顶层 key，自定义块在
 *  custom_sections 里那条的 items（返回的是同一个数组引用，splice/push
 *  就地改它即可）。 */
function blockRows(block) {
  if (block.custom) {
    const section = customSection(block.key);
    if (section && !Array.isArray(section.items)) section.items = [];
    return section ? section.items : [];
  }
  return state.content[block.key];
}

/** 有效的正文板块顺序，镜像 schema.effective_body_order()。 */
function bodyOrder() {
  const customs = customSections().map((section) => CUSTOM_PREFIX + section.key);
  const declared = state.content.body_order;
  if (!Array.isArray(declared)) return [...bodyBuiltins(), ...customs];
  return declared.filter((token) => typeof token === 'string');
}

function isBodySection(block) {
  return Boolean(block.custom) || bodyBuiltins().includes(block.key);
}

/* ---------- 板块级增删改移 ----------
 * 一旦用户动了顺序/增删，就把有效顺序固化成显式的 body_order 存进内容，
 * 之后所有操作都改这个数组。没动过的文件不会凭空多出 body_order（保住
 * 老文件逐字节不变），因为这些函数只在用户真的点了按钮时才被调用。
 */

function materializeBodyOrder() {
  if (!Array.isArray(state.content.body_order)) {
    state.content.body_order = bodyOrder();
  }
  return state.content.body_order;
}

function moveSection(token, delta) {
  const order = materializeBodyOrder();
  const from = order.indexOf(token);
  const to = from + delta;
  if (from < 0 || to < 0 || to >= order.length) return;
  [order[from], order[to]] = [order[to], order[from]];
  touched();
  buildForm();
}

function deleteSection(block) {
  const order = materializeBodyOrder();
  const at = order.indexOf(block.key);
  if (at >= 0) order.splice(at, 1);
  if (block.custom) {
    // 自定义块删就真删：连同数据一起从内容里拿掉。
    const key = block.key.slice(CUSTOM_PREFIX.length);
    state.content.custom_sections = customSections().filter((s) => s.key !== key);
  }
  // 内建块只从 body_order 里拿掉，数据仍留在 state.content[key]，
  // 落盘后可再"恢复"加回来——移除是可逆的。
  touched();
  buildForm();
}

function restoreBuiltin(key) {
  const order = materializeBodyOrder();
  if (!order.includes(key)) order.push(key);
  touched();
  buildForm();
}

async function confirmDeleteSection(block) {
  if (block.custom) {
    const { label } = await dialog({
      title: `删除「${block.title}」板块`,
      message: '这个自定义板块连同它的全部内容都会删掉。保存后才真正写回文件。',
      buttons: [{ label: '取消', kind: 'cancel' }, { label: '删除', kind: 'primary' }],
    });
    if (label !== '删除') return;
  }
  deleteSection(block);
}

async function renameCustomSection(block) {
  const section = customSection(block.key);
  if (!section) return;
  const { label, value } = await dialog({
    title: '给这一栏改名',
    message: '这个名字会显示在简历左侧的竖脊上。',
    input: { value: section.title, placeholder: '比如：获奖情况' },
    buttons: [{ label: '取消', kind: 'cancel' }, { label: '改名', kind: 'primary' }],
  });
  if (label !== '改名') return;
  const name = trimInput(value || '');
  if (!name) return;
  section.title = name;
  touched();
  buildForm();
}

/** 生成一个还没被用过的 ASCII 板块 key（用户填的是中文标题，内部 key 自动排）。 */
function freshCustomKey() {
  const used = new Set(customSections().map((section) => section.key));
  let n = 1;
  while (used.has(`sec${n}`)) n += 1;
  return `sec${n}`;
}

const FIELD_KINDS = [
  { value: 'text', label: '单行文字' },
  { value: 'lines', label: '多行（每行一条）' },
  { value: 'list', label: '一行多项（用 / 分隔）' },
];

/** 新建自定义板块：一个小设计器，定标题和若干字段（名字+类型）。 */
async function createCustomSection() {
  const drafts = [{ ask: '', kind: 'text' }];   // 至少一个字段
  let list = null;

  const paintFields = () => {
    if (!list) return;
    list.textContent = '';
    drafts.forEach((draft, index) => {
      const row = node('div', 'field-row');

      const name = node('input');
      name.type = 'text';
      name.value = draft.ask;
      name.placeholder = index === 0 ? '字段名，如：奖项' : '字段名，如：时间';
      name.addEventListener('input', () => { draft.ask = name.value; });
      row.append(name);

      const kind = node('select');
      FIELD_KINDS.forEach((option) => {
        const item = node('option', null, option.label);
        item.value = option.value;
        if (option.value === draft.kind) item.selected = true;
        kind.append(item);
      });
      kind.value = draft.kind;
      kind.addEventListener('change', () => { draft.kind = kind.value; });
      row.append(kind);

      const drop = node('button', 'icon', '×');
      drop.type = 'button';
      drop.title = '删掉这个字段';
      drop.disabled = drafts.length <= 1;
      drop.addEventListener('click', () => { drafts.splice(index, 1); paintFields(); });
      row.append(drop);

      list.append(row);
    });
  };

  const { label, value } = await dialog({
    title: '新建自定义板块',
    message: '第一个字段会当作这一条的标题（也用来区分不同条目）。',
    input: { value: '', placeholder: '板块名，如：获奖情况' },
    buttons: [{ label: '取消', kind: 'cancel' }, { label: '创建', kind: 'primary' }],
    open: (box, controls) => {
      list = node('div', 'field-list');
      box.append(list);
      paintFields();
      const add = node('button', 'add', '+ 加一个字段');
      add.type = 'button';
      add.addEventListener('click', () => { drafts.push({ ask: '', kind: 'text' }); paintFields(); });
      box.append(add);
      controls.field.placeholder = '板块名，如：获奖情况';
    },
  });

  if (label !== '创建') return;
  const title = trimInput(value || '');
  const fields = drafts
    .map((draft) => ({ ask: trimInput(draft.ask), kind: draft.kind }))
    .filter((draft) => draft.ask);
  if (!title || !fields.length) {
    toast('板块名和至少一个字段名都要填。', 'bad');
    return;
  }

  const section = {
    key: freshCustomKey(),
    title,
    identity: 'f1',                       // 第一个字段当标识
    fields: fields.map((draft, index) => ({
      key: `f${index + 1}`,
      ask: draft.ask,
      hint: '',
      example: '',
      kind: draft.kind,
      required: index === 0,              // 标题字段必填，其余可留空
      default: '',
    })),
    items: [],
  };

  // 先固化当前顺序（此刻还不含新块），再挂上新块并把它的 token 追加一次，
  // 免得 materializeBodyOrder 的默认展开已经带上它、又被 push 重复一遍。
  const order = materializeBodyOrder();
  state.content.custom_sections = [...customSections(), section];
  order.push(CUSTOM_PREFIX + section.key);
  touched();
  buildForm();
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

/* 每个输入框按「区块 | 第几条 | 字段」登记一份，好让状态栏那份空白清单能点着
   跳过去。用一张表而不是给 DOM 加 data-* ：测试里的假 DOM 查不了复杂选择器，
   而这件事实在没什么好测 DOM 的。 */
const fieldIndex = new Map();

function fieldKey(block, index, field) {
  return `${block}|${index === null || index === undefined ? '' : index}|${field}`;
}

/** 按 schema.find_blank_locations() 给出的位置找回那个输入框。找不到就是 null。 */
function fieldElement(location) {
  const index = location.index === undefined ? null : location.index;
  return fieldIndex.get(fieldKey(location.block, index, location.field)) || null;
}

/**
 * 一个空。read/write 把它接到 state.content 上的具体位置。
 * where 是它在页面上的坐标 {block, index}，只用来登记跳转索引。
 */
function fieldView(block, field, read, write, where) {
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

  if (where) fieldIndex.set(fieldKey(where.block, where.index, field.key), input);

  wrap.append(input);
  if (counter) wrap.append(counter);
  return wrap;
}

/** 数组表里的一条：一张卡，带删除和上下移。 */
function cardView(block, index, rerender) {
  const rows = blockRows(block);
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
      { block: block.key, index },
    ));
  });
  return card;
}

/** 板块头上的工具条：上移 / 下移 / （自定义才有的）改名 / 移除。 */
function sectionToolbar(block) {
  const bar = node('div', 'section-tools');
  const order = bodyOrder();
  const at = order.indexOf(block.key);

  const up = node('button', 'icon', '↑');
  up.type = 'button';
  up.title = '上移';
  up.disabled = at <= 0;
  up.addEventListener('click', () => moveSection(block.key, -1));

  const down = node('button', 'icon', '↓');
  down.type = 'button';
  down.title = '下移';
  down.disabled = at < 0 || at >= order.length - 1;
  down.addEventListener('click', () => moveSection(block.key, 1));

  bar.append(up, down);

  if (block.custom) {
    const rename = node('button', 'icon', '改名');
    rename.type = 'button';
    rename.title = '改这一栏的名字';
    rename.addEventListener('click', () => renameCustomSection(block));
    bar.append(rename);
  }

  const drop = node('button', 'icon', block.custom ? '删除' : '移除');
  drop.type = 'button';
  drop.title = block.custom
    ? '删掉这个自定义板块（内容一起删）'
    : '从简历里移除（内容留档，可再加回来）';
  drop.addEventListener('click', () => confirmDeleteSection(block));
  bar.append(drop);

  return bar;
}

/** 表单末尾的"加板块"面板：恢复被移除的内建块，或新建自定义块。 */
function addSectionPanel() {
  const panel = node('section', 'block add-block');
  panel.append(node('h2', null, '加板块'));

  const order = bodyOrder();
  bodyBuiltins().filter((key) => !order.includes(key)).forEach((key) => {
    const block = state.builtins.find((item) => item.key === key);
    if (!block) return;
    const restore = node('button', 'add', `+ 恢复「${block.title}」`);
    restore.type = 'button';
    restore.addEventListener('click', () => restoreBuiltin(key));
    panel.append(restore);
  });

  const add = node('button', 'add', '+ 新建自定义板块');
  add.type = 'button';
  add.addEventListener('click', createCustomSection);
  panel.append(add);
  return panel;
}

function blockView(block) {
  const section = node('section', 'block');
  section.id = `block-${block.key}`;

  const head = node('div', 'block-head');
  head.append(node('h2', null, block.title));
  // 正文块（内建四块 + 自定义块）能排序/移除；抬头四块固定，不给工具条。
  if (isBodySection(block)) head.append(sectionToolbar(block));
  section.append(head);

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
        // 栏目标题在 schema 里属于另一张表（section_key），登记时用它，
        // 空白清单报的也是那个名字。
        { block: block.section_key, index: null },
      ));
    }

    if (!block.repeat) {
      block.fields.forEach((field) => {
        body.append(fieldView(
          block, field,
          () => state.content[block.key][field.key],
          (value) => { state.content[block.key][field.key] = value; },
          { block: block.key, index: null },
        ));
      });
      return;
    }

    const rows = blockRows(block);
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
  syncBlocks();
  el.form.textContent = '';
  el.jump.textContent = '';
  fieldIndex.clear();

  const byKey = new Map(state.blocks.map((block) => [block.key, block]));
  // 抬头四块永远在最上面，顺序固定；正文块按 body_order 排，删掉的不画。
  const shown = [
    ...headerBuiltins().map((key) => byKey.get(key)).filter(Boolean),
    ...bodyOrder().map((token) => byKey.get(token)).filter(Boolean),
  ];
  shown.forEach((block) => {
    el.form.append(blockView(block));
    const link = node('a', null, block.title);
    link.href = `#block-${block.key}`;
    el.jump.append(link);
  });

  el.form.append(addSectionPanel());
}
