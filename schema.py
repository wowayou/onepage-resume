"""内容文件的字段表：这份简历一共有哪些"空"，只在这里定义一次。

四个地方都读它，所以加一个字段只用改这一处：

    fill.py            照着它一题一题地问
    fill.py --blank    照着它生成一份空白表单（喜欢在编辑器里填的人用）
    render.py          照着它检查还有哪些空没填，报到具体位置
    webui.py           把字段表发给浏览器，网页表单照着它长出来

分开写就迟早会出现"问卷问了、但渲染不认"或者"渲染要、但没人问"的字段。

字段的 kind 决定它在 TOML 里长什么样，也决定 fill.py 怎么问：

    text    一行字符串
    lines   字符串数组，一行一条（bullet 那种）
    list    字符串数组，一行里用「空格 / 空格」分隔（面包屑、关键词那种短词组）。
            只有两侧至少一边带空白的斜杠才算分隔符，所以网址能整条写进去
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass


INPUT_WHITESPACE = "\t\n\v\f\r\x1c\x1d\x1e\x1f \x85\xa0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000"
WHITESPACE_CLASS = r"[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]"
LIST_SEP = re.compile(rf"{WHITESPACE_CLASS}+/|/{WHITESPACE_CLASS}+")
DOCUMENT_METADATA = ("status", "updated", "preview_note", "edition")


def split_list(text: str) -> list[str]:
    """与浏览器共享分隔规则，裸斜杠保留在 URL、日期等条目中。"""
    return [part.strip(INPUT_WHITESPACE) for part in LIST_SEP.split(text)
            if part.strip(INPUT_WHITESPACE)]


def input_rules() -> dict[str, str]:
    return {"list_separator": LIST_SEP.pattern, "whitespace": WHITESPACE_CLASS}


@dataclass(frozen=True)
class Field:
    key: str
    ask: str                    # 题干：问用户的那句话
    hint: str = ""              # 一句话解释这个空是干什么的
    example: str = ""           # 示例答案。只作参考，不会被当成默认值填进去
    kind: str = "text"          # text | lines | list
    required: bool = True
    default: str = ""           # 预填值：回车直接采用


@dataclass(frozen=True)
class Block:
    key: str                    # 在 TOML 里的表名
    title: str                  # 人话名字，提示里用
    fields: tuple[Field, ...]
    intro: str = ""             # 进入这一块时先说一句
    repeat: bool = False        # True 表示 [[数组表]]，可以有多条
    min_items: int = 1
    max_items: int = 0          # 0 = 不限
    # 数组块在页面上有个栏目名（"工作经历"这四个字），它单独存在另一张表里
    section_key: str = ""
    section_default: str = ""
    # 数组块里"哪个字段能认出这一条"。定制版的 [keep] 表用它来挑条目和排顺序：
    #     [keep]
    #     skills = ["Technical SEO", "数据分析"]
    # 挑的是 label 等于这两个值的技能。选它作 identity 的标准是"人一眼能认出来
    # 且同一份简历里不会重复"——所以经历用公司名，技能用标签名。
    identity: str = ""


# 生成物文件名的最后兜底：--name 和 [document].output_basename 都没有时用它。
# render.resolve_basename() 是唯一的解析入口，这里同时是字段默认值的来源。
DEFAULT_BASENAME = "resume"


DOCUMENT = Block(
    key="document",
    title="文件信息",
    intro="先填几项和版面无关的：文件名、PDF 元数据。填错了也不会出现在纸上。",
    fields=(
        Field("output_basename", "生成的文件叫什么名字（不带 .pdf）",
              "HR 收到的附件就叫这个名字，写清楚点比 resume 好",
              "张三-SEO-简历", default=DEFAULT_BASENAME),
        Field("title", "PDF 的标题元数据",
              "在阅读器标题栏里显示，也会被一些 ATS 读走",
              "英文 SEO / 独立站运营 - 简历"),
        Field("subject", "一句话说明这份简历投什么岗位",
              "PDF 的 subject 元数据，纸面上看不到",
              "英文网站增长运营岗位简历"),
        Field("keywords", "关键词", "用 / 分隔，写岗位 JD 里出现的词",
              "SEO / GA4 / B2B / 独立站", kind="list"),
    ),
)

PROFILE = Block(
    key="profile",
    title="抬头",
    intro="页面最上面那一行：姓名、求职意向、身份事实。",
    fields=(
        Field("name", "你的姓名", "页面上字号最大的那几个字", "张三"),
        Field("intent", "求职意向", "和姓名同一行、右对齐的那句；三到五个词，别写成一句话",
              "英文 SEO · 独立站运营 · B2B 网站增长"),
        Field("facts", "身份事实", "用 / 分隔，和联系方式合并成一行。没有就留空",
              "北京 / 可远程 / 28 岁", kind="list", required=False),
    ),
)

CONTACTS = Block(
    key="contacts",
    title="联系方式",
    intro="一条一条填，填完问你要不要再加。手机和邮箱至少留一个能打通的。",
    repeat=True,
    min_items=1,
    identity="value",          # 联系方式没有更短的天然键，就用它本身
    fields=(
        Field("value", "联系方式的内容", "", "138-0000-0000"),
        Field("label", "前面的标签", "比如「手机」「邮箱」。链接类的（个人站、GitHub）留空更干净",
              "手机", required=False),
        Field("href", "点击后跳到哪", "只有网址和邮箱需要；手机号留空",
              "https://example.com", required=False),
    ),
)

SUMMARY = Block(
    key="summary",
    title="概况",
    intro="姓名下面那一段。三到四行，写你是谁、做过什么、想去哪——不要写成技能清单。",
    fields=(
        Field("text", "概况正文", "三到四行；超过四行会挤掉后面的内容",
              "两年英文网站内容与 Google SEO 经验，甲方内容生产、乙方 B2B 交付都做过。"),
    ),
)

SKILLS = Block(
    key="skills",
    title="核心能力",
    intro="左边一个短标签，右边一句话。四到六条最好看，超过八条读者就不看了。",
    repeat=True,
    min_items=1,
    section_key="skills_section",
    section_default="核心能力",
    identity="label",
    fields=(
        Field("label", "能力标签", "两到四个字，或一个英文词组", "Technical SEO"),
        Field("text", "这条能力具体是什么", "一到两行，写工具和动作，不要写「精通」",
              "抓取、索引与页面速度基础排查；Schema / JSON-LD 配置与验证"),
    ),
)

EXPERIENCES = Block(
    key="experiences",
    title="工作经历",
    intro="按时间倒序填，最近的一段放第一条。",
    repeat=True,
    min_items=1,
    section_key="experience_section",
    section_default="工作经历",
    identity="company",
    fields=(
        Field("company", "公司名", "", "Acme Digital"),
        Field("role", "你的职位", "", "SEO 助理 / B2B 外贸站交付"),
        Field("crumbs", "这段经历的元信息", "用 / 分隔：团队或业务 / 起止时间 / 时长或地点",
              "乙方 SEO 交付团队 / 2025.09 – 2026.05 / 8 个月", kind="list"),
        Field("bullets", "你做了什么（一行一条）",
              "两到三条。每条尽量写成「做了什么 → 用什么方法 → 得到什么」，"
              "空一行结束这一段",
              "输出 GSC / GA4 月报，从曝光、点击与 CTR 判断增长是否可持续。",
              kind="lines"),
    ),
)

PROJECTS = Block(
    key="projects",
    title="项目作品",
    intro="能被点开、被复核的东西最有说服力：线上站点、仓库、公开的分析报告。",
    repeat=True,
    min_items=1,
    section_key="projects_section",
    section_default="项目作品",
    identity="title",
    fields=(
        Field("title", "项目名", "", "个人双语博客"),
        Field("crumbs", "项目的元信息",
              "用「空格 / 空格」分隔：技术栈 / 链接 / 你的角色。"
              "网址里的斜杠不用管，github.com/账号/仓库 会整条留着",
              "example.com / Astro + Git + Cloudflare / 独立搭建并运营", kind="list"),
        Field("description", "这个项目你做了什么", "一到两行，写具体做法，不要写感想",
              "从旧共享二级域迁到自有域：逐路径 301、GSC 地址变更、上线校验与回滚方案。"),
    ),
)

EDUCATION = Block(
    key="education",
    title="教育背景",
    intro="页面最后一行，一行写完。",
    fields=(
        Field("title", "这一栏的栏目名", "", "教育背景", default="教育背景"),
        Field("items", "学校 / 专业 / 学历 / 起止年份 / 证书",
              "用 / 分隔，渲染时会用 · 连成一行",
              "示例大学 / 市场营销 / 本科 / 2015 – 2019 / CET-6", kind="list"),
    ),
)

BLOCKS: tuple[Block, ...] = (
    DOCUMENT, PROFILE, CONTACTS, SUMMARY, SKILLS, EXPERIENCES, PROJECTS, EDUCATION,
)


# ---------- 板块级编辑：body_order 与自定义板块 ----------
# 内建四块在磁盘上保持字节不变。板块的顺序、删除、以及全自定义的新板块，
# 靠两个新增的顶层键承载，老文件没有这两个键时行为完全不变：
#
#   body_order       正文板块的顺序。列表里没有的内建块 = 已删除（数据留档、
#                    不渲染、不查空）。自定义块在列表里写成 "custom:<key>"。
#   [[custom_sections]]  全自定义的新板块，字段定义随内容文件走（不进 describe()）。
#                    每条有 key/title/identity/fields/items；用通用版面渲染。
#
# body_order 只管辖"正文那几栏"（有竖脊栏目名的块）。抬头与脚注
# （document/profile/contacts/summary）始终渲染，不受它影响。
BODY_BLOCKS: tuple[str, ...] = ("skills", "experiences", "projects", "education")
BODY_ORDER_KEY = "body_order"
CUSTOM_SECTIONS_KEY = "custom_sections"
CUSTOM_PREFIX = "custom:"
FIELD_KINDS = ("text", "lines", "list")

# 允许的页数上限。这份工具的默认承诺仍是"一页"（DEFAULT_MAX_PAGES=1），
# 但用户可以按需放宽到 MAX_PAGES_LIMIT 页——有些岗位就是要两页写得下经历。
# max_pages 是根级标量键，没写这个键的老文件默认 1，落盘也不会凭空多出它。
MAX_PAGES_KEY = "max_pages"
DEFAULT_MAX_PAGES = 1
MAX_PAGES_LIMIT = 5


def effective_max_pages(content: dict) -> int:
    """这份内容允许几页。没写 max_pages（或写歪了）就回落到默认的 1 页。
    已通过 find_type_errors 的文件保证落在 1..MAX_PAGES_LIMIT。"""
    value = content.get(MAX_PAGES_KEY, DEFAULT_MAX_PAGES)
    if isinstance(value, bool) or not isinstance(value, int):
        return DEFAULT_MAX_PAGES
    if value < 1:
        return DEFAULT_MAX_PAGES
    return min(value, MAX_PAGES_LIMIT)
# 自定义板块的 key 与字段 key 都走这个：字母开头，字母数字下划线。
IDENTIFIER = re.compile(r"[A-Za-z][A-Za-z0-9_]*\Z")


def _raw_custom_sections(content: dict) -> list:
    """内容里声明的自定义板块原始列表（未校验；不是列表就当没有）。"""
    value = content.get(CUSTOM_SECTIONS_KEY)
    return value if isinstance(value, list) else []


def build_custom_block(section: dict) -> Block:
    """把一个 custom_sections 条目转成 Block，好让查空、继承、表单等
    照内建块的同一套机制消费它。假定结构已通过 find_type_errors 校验。

    自定义块一律是数组表（repeat=True），栏目名就是 section["title"]，
    不像内建块那样另存一张 *_section 表。"""
    fields = tuple(
        Field(
            key=item["key"],
            ask=item.get("ask") or item["key"],
            hint=item.get("hint", ""),
            example=item.get("example", ""),
            kind=item.get("kind", "text"),
            required=item.get("required", True),
            default=item.get("default", ""),
        )
        for item in section.get("fields", [])
        if isinstance(item, dict) and isinstance(item.get("key"), str)
    )
    return Block(
        key=CUSTOM_PREFIX + section["key"],
        title=section["title"],
        fields=fields,
        repeat=True,
        min_items=1,
        section_default=section["title"],
        identity=section.get("identity", ""),
    )


def custom_block_map(content: dict) -> dict[str, tuple[Block, dict]]:
    """"custom:key" → (Block, 原始 section 字典)。只收结构完好的条目。"""
    out: dict[str, tuple[Block, dict]] = {}
    for section in _raw_custom_sections(content):
        if (isinstance(section, dict)
                and isinstance(section.get("key"), str)
                and isinstance(section.get("title"), str)):
            out[CUSTOM_PREFIX + section["key"]] = (build_custom_block(section), section)
    return out


def effective_body_order(content: dict) -> list[str]:
    """有效的正文板块顺序，返回 token 列表（内建块用 key，自定义块用
    "custom:key"）。没写 body_order 时用内建默认顺序，再按声明顺序追加
    所有自定义块；写了就原样采用（已通过校验，token 都指向存在的块）。"""
    customs = [CUSTOM_PREFIX + section["key"]
               for section in _raw_custom_sections(content)
               if isinstance(section, dict) and isinstance(section.get("key"), str)]
    declared = content.get(BODY_ORDER_KEY)
    if not isinstance(declared, list):
        return list(BODY_BLOCKS) + customs
    return [token for token in declared if isinstance(token, str)]


def effective_body_blocks(content: dict) -> list[tuple[Block, object]]:
    """按 body_order 解析出要渲染/查空的正文板块，每项 (block, rows)。
    内建块 rows 取自 content[block.key]（education 非数组，rows 是那张表）；
    自定义块 rows 取自它自己的 items 列表。指不到的 token 跳过。"""
    builtins = {block.key: block for block in BLOCKS}
    customs = custom_block_map(content)
    out: list[tuple[Block, object]] = []
    for token in effective_body_order(content):
        if token in customs:
            block, section = customs[token]
            items = section.get("items")
            out.append((block, items if isinstance(items, list) else []))
        elif token in builtins and token in BODY_BLOCKS:
            block = builtins[token]
            out.append((block, content.get(block.key)))
    return out


# ---------- 字段表的 JSON 视图 ----------
# webui.py 把它发给浏览器，网页表单是照着它长出来的（题干、解释、例子、
# 是不是数组、能不能留空，全都来自这里）。所以"这份简历有哪些空"依然只在
# 本文件里定义一次：加一个字段，命令行问卷、空白表单、渲染检查、网页表单
# 四边一起跟上，不会出现"网页上能填但渲染不认"的字段。

def describe() -> list[dict]:
    """把 BLOCKS 摊成可 JSON 序列化的结构，字段顺序与页面顺序一致。"""
    return [
        {
            "key": block.key,
            "title": block.title,
            "intro": block.intro,
            "repeat": block.repeat,
            "min_items": block.min_items,
            "max_items": block.max_items,
            "section_key": block.section_key,
            "section_default": block.section_default,
            "identity": block.identity,
            # 正文块（有竖脊栏目名，能排序 / 删除）为 True；抬头四块为 False。
            # 前端照这个分栏，不再自己维护一份内建块名单（定义只在这里一处）。
            "body": block.key in BODY_BLOCKS,
            "fields": [
                {
                    "key": item.key,
                    "ask": item.ask,
                    "hint": item.hint,
                    "example": item.example,
                    "kind": item.kind,
                    "required": item.required,
                    "default": item.default,
                }
                for item in block.fields
            ],
        }
        for block in BLOCKS
    ]


# ---------- 空白检查 ----------
# render.py 用它。渲染出一份带着空标题、空 bullet 的 PDF 比直接报错更糟——
# 那种 PDF 看上去是"成功了"的，很容易就这么发出去了。

def _empty(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple)):
        # 空白表单里数组是 [""]——一个还没填的空位，不是"填了一条空的"。
        return all(_empty(item) for item in value)
    return False


def find_type_errors(content: object) -> list[str]:
    """检查结构而不要求填完，避免损坏的数据被转换或静默丢弃。"""
    if not isinstance(content, dict):
        return ["内容必须是一个对象（TOML 表）。"]
    errors: list[str] = []
    allowed = {block.key for block in BLOCKS}
    allowed.update(block.section_key for block in BLOCKS if block.section_key)
    allowed.update((BODY_ORDER_KEY, CUSTOM_SECTIONS_KEY, MAX_PAGES_KEY))
    for key in content.keys() - allowed:
        errors.append(f"未知内容块：{key}")

    def check_text(value: object, location: str) -> None:
        if not isinstance(value, str):
            errors.append(f"{location} 必须是字符串。")
        elif any(0xD800 <= ord(character) <= 0xDFFF for character in value):
            errors.append(f"{location} 含有无效 Unicode 字符。")

    def check_table(table: object, fields: tuple[Field, ...], location: str,
                    metadata: tuple[str, ...] = ()) -> None:
        if not isinstance(table, dict):
            errors.append(f"{location} 必须是表。")
            return
        keys = {field.key for field in fields} | set(metadata)
        for key in table.keys() - keys:
            errors.append(f"{location} 未知字段：{key}")
        for key in metadata:
            if key in table:
                check_text(table[key], f"{location} {key}")
        for field in fields:
            if field.key not in table:
                continue
            value = table[field.key]
            where = f"{location} {field.key}"
            if field.kind in ("list", "lines"):
                if not isinstance(value, list):
                    errors.append(f"{where} 必须是字符串数组。")
                else:
                    for index, entry in enumerate(value, 1):
                        check_text(entry, f"{where}[{index}]")
            else:
                check_text(value, where)

    for block in BLOCKS:
        if block.section_key and block.section_key in content:
            check_table(content[block.section_key], (Field("title", "栏目名"),),
                        f"[{block.section_key}]")
        if block.key not in content:
            continue
        value = content[block.key]
        if block.repeat:
            if not isinstance(value, list):
                errors.append(f"[[{block.key}]] 必须是数组表。")
                continue
            for index, row in enumerate(value, 1):
                check_table(row, block.fields, f"[[{block.key}]] 第 {index} 条")
        else:
            check_table(value, block.fields, f"[{block.key}]",
                        DOCUMENT_METADATA if block.key == "document" else ())

    _check_custom_sections(content, errors, check_table)
    _check_body_order(content, errors)
    _check_max_pages(content, errors)
    return errors


# custom_sections 条目自己那几个键（key/title/identity/fields/items）之外不许有别的。
CUSTOM_SECTION_KEYS = frozenset({"key", "title", "identity", "fields", "items"})
# 每个字段定义允许的键，与 Field 的构造参数对应。
CUSTOM_FIELD_KEYS = frozenset(
    {"key", "ask", "hint", "example", "kind", "required", "default"})


def _check_custom_sections(content: dict, errors: list[str],
                           check_table) -> None:
    """校验 [[custom_sections]] 的结构：板块 key/title/identity、字段定义、
    以及每条 items 是否合乎它自己声明的字段。结构由数据承载，所以校验也在
    这里做，不能像内建块那样交给静态 BLOCKS。"""
    value = content.get(CUSTOM_SECTIONS_KEY)
    if value is None:
        return
    if not isinstance(value, list):
        errors.append(f"[[{CUSTOM_SECTIONS_KEY}]] 必须是数组表。")
        return

    seen_keys: set[str] = set()
    for index, section in enumerate(value, 1):
        where = f"[[{CUSTOM_SECTIONS_KEY}]] 第 {index} 个"
        if not isinstance(section, dict):
            errors.append(f"{where} 必须是表。")
            continue
        for extra in section.keys() - CUSTOM_SECTION_KEYS:
            errors.append(f"{where} 未知字段：{extra}")

        key = section.get("key")
        if not isinstance(key, str) or not IDENTIFIER.match(key):
            errors.append(f"{where} 的 key 必须是字母开头的标识符（字母数字下划线）。")
        elif key in seen_keys:
            errors.append(f"{where} 的 key「{key}」与前面的自定义板块重复。")
        else:
            seen_keys.add(key)

        title = section.get("title")
        if not isinstance(title, str) or not title.strip():
            errors.append(f"{where} 的 title（栏目名）必须是非空字符串。")

        # 字段定义
        fields = section.get("fields")
        field_keys: list[str] = []
        parsed_fields: list[Field] = []
        if not isinstance(fields, list) or not fields:
            errors.append(f"{where} 至少要声明一个字段（fields）。")
        else:
            for field_index, field in enumerate(fields, 1):
                floc = f"{where} 第 {field_index} 个字段"
                if not isinstance(field, dict):
                    errors.append(f"{floc} 必须是表。")
                    continue
                for extra in field.keys() - CUSTOM_FIELD_KEYS:
                    errors.append(f"{floc} 未知字段：{extra}")
                fkey = field.get("key")
                if not isinstance(fkey, str) or not IDENTIFIER.match(fkey):
                    errors.append(f"{floc} 的 key 必须是字母开头的标识符。")
                elif fkey in field_keys:
                    errors.append(f"{floc} 的 key「{fkey}」在同一板块里重复。")
                else:
                    field_keys.append(fkey)
                kind = field.get("kind", "text")
                if kind not in FIELD_KINDS:
                    errors.append(
                        f"{floc} 的 kind 只能是 {'、'.join(FIELD_KINDS)}。")
                for text_key in ("ask", "hint", "example", "default"):
                    if text_key in field and not isinstance(field[text_key], str):
                        errors.append(f"{floc} 的 {text_key} 必须是字符串。")
                if "required" in field and not isinstance(field["required"], bool):
                    errors.append(f"{floc} 的 required 必须是 true 或 false。")
                if (isinstance(fkey, str) and IDENTIFIER.match(fkey)
                        and kind in FIELD_KINDS):
                    parsed_fields.append(Field(
                        key=fkey, ask="", kind=kind,
                        required=bool(field.get("required", True))))

        # identity 必须指向某个已声明的字段
        identity = section.get("identity")
        if not isinstance(identity, str) or not identity:
            errors.append(f"{where} 的 identity（认条目用的字段）必须填。")
        elif field_keys and identity not in field_keys:
            errors.append(
                f"{where} 的 identity「{identity}」不是它声明过的字段。")

        # items：每条按声明的字段校验（复用内建块那套 check_table）
        items = section.get("items")
        if items is not None:
            if not isinstance(items, list):
                errors.append(f"{where} 的 items 必须是数组表。")
            else:
                title_text = title if isinstance(title, str) else key
                for item_index, item in enumerate(items, 1):
                    check_table(item, tuple(parsed_fields),
                                f"{where}（{title_text}）第 {item_index} 条")


def _check_body_order(content: dict, errors: list[str]) -> None:
    """校验 body_order：必须是字符串列表，每个 token 指向一个存在的正文板块
    （内建块用 key，自定义块用 custom:key），不许重复。"""
    declared = content.get(BODY_ORDER_KEY)
    if declared is None:
        return
    if not isinstance(declared, list):
        errors.append(f"{BODY_ORDER_KEY} 必须是字符串数组。")
        return
    known = set(BODY_BLOCKS)
    for section in _raw_custom_sections(content):
        if isinstance(section, dict) and isinstance(section.get("key"), str):
            known.add(CUSTOM_PREFIX + section["key"])
    seen: set[str] = set()
    for token in declared:
        if not isinstance(token, str):
            errors.append(f"{BODY_ORDER_KEY} 里的每一项都必须是字符串。")
            continue
        if token in seen:
            errors.append(f"{BODY_ORDER_KEY} 里「{token}」出现了不止一次。")
            continue
        seen.add(token)
        if token not in known:
            errors.append(f"{BODY_ORDER_KEY} 里「{token}」指向了不存在的板块。")


def _check_max_pages(content: dict, errors: list[str]) -> None:
    """校验 max_pages：写了就必须是 1..MAX_PAGES_LIMIT 的整数。
    bool 是 int 的子类，得单独挡掉（true 不是 1 页）。"""
    if MAX_PAGES_KEY not in content:
        return
    value = content[MAX_PAGES_KEY]
    if isinstance(value, bool) or not isinstance(value, int):
        errors.append(f"{MAX_PAGES_KEY} 必须是整数。")
        return
    if not 1 <= value <= MAX_PAGES_LIMIT:
        errors.append(
            f"{MAX_PAGES_KEY} 必须在 1 到 {MAX_PAGES_LIMIT} 之间（现在是 {value}）。")


def validate_types(content: object) -> None:
    errors = find_type_errors(content)
    if errors:
        raise ValueError("内容格式有误：\n" + "\n".join(errors))


def find_blank_locations(content: dict) -> list[dict]:
    """返回结构化的空白位置列表，每项包含 block/index/field/item/section/message。"""
    errors = find_type_errors(content)
    if errors:
        # 类型错误也用同样的结构返回，但不含位置信息
        return [{"block": "", "index": None, "field": "", "item": None,
                 "section": False, "message": err} for err in errors]
    
    locations: list[dict] = []

    def check_fields(table: dict, block: Block, block_index: int | None) -> None:
        for item in block.fields:
            value = table.get(item.key)
            if _empty(value):
                if item.required:
                    if block_index is not None:
                        msg = f"[[{block.key}]] 第 {block_index + 1} 条的 {item.key} —— {item.ask}"
                    else:
                        msg = f"[{block.key}] {item.key} —— {item.ask}"
                    locations.append({
                        "block": block.key,
                        "index": block_index,
                        "field": item.key,
                        "item": None,
                        "section": False,
                        "message": msg,
                    })
                continue
            if isinstance(value, list):
                for item_index, entry in enumerate(value):
                    if _empty(entry):
                        if block_index is not None:
                            msg = f"[[{block.key}]] 第 {block_index + 1} 条的 {item.key}[{item_index + 1}] —— 有空白条目"
                        else:
                            msg = f"[{block.key}] {item.key}[{item_index + 1}] —— 有空白条目"
                        locations.append({
                            "block": block.key,
                            "index": block_index,
                            "field": item.key,
                            "item": item_index,
                            "section": False,
                            "message": msg,
                        })

    def check_block(block: Block, value: object) -> None:
        if block.section_key and _empty(
            (content.get(block.section_key) or {}).get("title")
        ):
            msg = f'[{block.section_key}] title —— {block.title}这一栏的栏目名'
            locations.append({
                "block": block.section_key,
                "index": None,
                "field": "title",
                "item": None,
                "section": True,
                "message": msg,
            })

        if not block.repeat:
            table = value
            if not isinstance(table, dict):
                msg = f"[{block.key}] 整块缺失 —— {block.title}"
                locations.append({
                    "block": block.key,
                    "index": None,
                    "field": "",
                    "item": None,
                    "section": False,
                    "message": msg,
                })
                return
            check_fields(table, block, None)
            return

        rows = value
        if not isinstance(rows, list) or len(rows) < block.min_items:
            msg = f"[[{block.key}]] 至少要有 {block.min_items} 条 —— {block.title}"
            locations.append({
                "block": block.key,
                "index": None,
                "field": "",
                "item": None,
                "section": False,
                "message": msg,
            })
            return
        if block.max_items and len(rows) > block.max_items:
            msg = f"[[{block.key}]] 最多 {block.max_items} 条 —— {block.title}"
            locations.append({
                "block": block.key,
                "index": None,
                "field": "",
                "item": None,
                "section": False,
                "message": msg,
            })
        for index, row in enumerate(rows):
            check_fields(row, block, index)

    # 抬头与脚注那几块（document/profile/contacts/summary）始终检查，
    # 不受 body_order 影响；正文块按 body_order 走——删掉的块不查，自定义块照查。
    for block in BLOCKS:
        if block.key in BODY_BLOCKS:
            continue
        check_block(block, content.get(block.key))
    for block, rows in effective_body_blocks(content):
        check_block(block, rows)

    return locations


def find_blanks(content: dict) -> list[str]:
    """返回还没填的空，每条是一句能直接照着去改的话。"""
    return [loc["message"] for loc in find_blank_locations(content)]


# ---------- 空白表单 ----------

def blank_form(sample: bool = False) -> str:
    """生成一份"每个空都在、但都还空着"的 TOML。

    sample=True 时把示例答案填进去，用来看版面；投递前必须自己重填一遍。
    """
    out: list[str] = [
        "# 一页简历的空白表单：把每个 = 右边的引号里填上你自己的内容。",
        "#",
        "# 生成：  python fill.py --blank",
        "# 渲染：  python render.py",
        "#",
        "# 规则：留空的必填项会在渲染时被逐条报出来，不会偷偷渲染成空白。",
        "# 数组表（[[skills]] 这种）想加一条就整段复制粘贴，想删一条就整段删掉。",
        "",
    ]

    def value_of(item: Field) -> str:
        if sample and item.example:
            return item.example
        return item.default

    def emit_fields(fields: tuple[Field, ...], indent: str = "") -> None:
        for item in fields:
            note = item.hint or ""
            if item.example and not sample:
                note = f"{note}（例：{item.example}）" if note else f"例：{item.example}"
            if not item.required:
                note = f"{note}｜可留空" if note else "可留空"
            if note:
                out.append(f"{indent}# {item.ask}：{note}")
            else:
                out.append(f"{indent}# {item.ask}")

            raw = value_of(item)
            if item.kind == "lines":
                items = [x for x in raw.split("\n") if x.strip()]
                if items:
                    out.append(f"{indent}{item.key} = [")
                    out.extend(f'{indent}  "{escape(x)}",' for x in items)
                    out.append(f"{indent}]")
                else:
                    out.append(f'{indent}{item.key} = [\n{indent}  "",\n{indent}]')
            elif item.kind == "list":
                items = split_list(raw)
                inner = ", ".join(f'"{escape(x)}"' for x in items) or '""'
                out.append(f"{indent}{item.key} = [{inner}]")
            else:
                out.append(f'{indent}{item.key} = "{escape(raw)}"')
            out.append("")

    for block in BLOCKS:
        out.append(f"# ===== {block.title} =====")
        if block.intro:
            out.append(f"# {block.intro}")
        out.append("")

        if block.section_key:
            out.append(f"[{block.section_key}]")
            out.append("# 页面左侧竖脊上的栏目名")
            out.append(f'title = "{escape(block.section_default)}"')
            out.append("")

        if block.repeat:
            out.append(f"# 想加一条就把下面这一整段复制一份。")
            out.append(f"[[{block.key}]]")
        else:
            out.append(f"[{block.key}]")
        emit_fields(block.fields)

    return "\n".join(out).rstrip() + "\n"


def escape(text: str) -> str:
    """转义 TOML 基本字符串，保留换行、控制字符与非 BMP 字符。"""
    return json.dumps(text, ensure_ascii=False)[1:-1].replace("\x7f", r"\u007f")
