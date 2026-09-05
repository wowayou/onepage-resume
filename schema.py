"""内容文件的字段表：这份简历一共有哪些"空"，只在这里定义一次。

三个地方都读它，所以加一个字段只用改这一处：

    fill.py            照着它一题一题地问
    fill.py --blank    照着它生成一份空白表单（喜欢在编辑器里填的人用）
    render.py          照着它检查还有哪些空没填，报到具体位置

分开写就迟早会出现"问卷问了、但渲染不认"或者"渲染要、但没人问"的字段。

字段的 kind 决定它在 TOML 里长什么样，也决定 fill.py 怎么问：

    text    一行字符串
    lines   字符串数组，一行一条（bullet 那种）
    list    字符串数组，一行里用 / 分隔（面包屑、关键词那种短词组）
"""

from __future__ import annotations

from dataclasses import dataclass


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


DOCUMENT = Block(
    key="document",
    title="文件信息",
    intro="先填几项和版面无关的：文件名、PDF 元数据。填错了也不会出现在纸上。",
    fields=(
        Field("output_basename", "生成的文件叫什么名字（不带 .pdf）",
              "HR 收到的附件就叫这个名字，写清楚点比 resume 好",
              "张三-SEO-简历", default="resume"),
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
    fields=(
        Field("title", "项目名", "", "个人双语博客"),
        Field("crumbs", "项目的元信息", "用 / 分隔：技术栈 / 链接 / 你的角色",
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


def find_blanks(content: dict) -> list[str]:
    """返回还没填的空，每条是一句能直接照着去改的话。"""
    blanks: list[str] = []

    for block in BLOCKS:
        if block.section_key and _empty(
            (content.get(block.section_key) or {}).get("title")
        ):
            blanks.append(f'[{block.section_key}] title —— {block.title}这一栏的栏目名')

        if not block.repeat:
            table = content.get(block.key)
            if not isinstance(table, dict):
                blanks.append(f"[{block.key}] 整块缺失 —— {block.title}")
                continue
            for item in block.fields:
                if item.required and _empty(table.get(item.key)):
                    blanks.append(f"[{block.key}] {item.key} —— {item.ask}")
            continue

        rows = content.get(block.key)
        if not isinstance(rows, list) or len(rows) < block.min_items:
            blanks.append(
                f"[[{block.key}]] 至少要有 {block.min_items} 条 —— {block.title}"
            )
            continue
        for index, row in enumerate(rows, start=1):
            for item in block.fields:
                if item.required and _empty((row or {}).get(item.key)):
                    blanks.append(
                        f"[[{block.key}]] 第 {index} 条的 {item.key} —— {item.ask}"
                    )

    return blanks


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
                items = [x.strip() for x in raw.split("/") if x.strip()]
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
    """TOML 基本字符串里只需要转义反斜杠和双引号。"""
    return text.replace("\\", "\\\\").replace('"', '\\"')
