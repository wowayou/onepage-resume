"""把一份 TOML 内容文件 + theme.toml + resume.css 渲染成一页 HTML、PDF 和 PNG。

排版由 WeasyPrint 用真正的 CSS 盒模型完成，间距由引擎计算，不再手工算坐标。
日常维护只需要改内容文件；调版式改 theme.toml 或 resume.css；这个文件不用动。

内容文件怎么来：跑 `python fill.py` 一题一题填，或 `python fill.py --blank`
生成空白表单自己填。字段表在 schema.py，填和渲染读的是同一份定义。

用法：
    python render.py                          # 用默认查找到的内容文件
    python render.py --theme theme.en.toml    # 英文版式（竖脊更宽、行距更紧）
    python render.py --content ~/private/me.toml --out-dir ~/private/build

版式的选择顺序：--theme > 内容文件里的 theme = "…" > theme.toml。
英文简历在内容文件里写一次 theme = "theme.en.toml"，以后就不用每次记得带参数。
"""

from __future__ import annotations

import argparse
import html
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
from pathlib import Path

from weasyprint import HTML
from weasyprint.formatting_structure import boxes

import schema
from content_io import DEFAULT_CONTENT_NAME, load_content, plain_name, safe_name
from content_io import load_theme as _load_theme

HERE = Path(__file__).resolve().parent

# 内容文件的查找顺序。前两个在 .gitignore 里，是"你自己的那一份"；
# content.example.toml 是仓库里跟踪的虚构示例，只用来证明工具能跑。
# 真实姓名、手机、邮箱、微信、学校永远不要写进 content.example.toml。
EXAMPLE_CONTENT = "content.example.toml"
CONTENT_CANDIDATES = ("content.local.toml", DEFAULT_CONTENT_NAME, EXAMPLE_CONTENT)

DEFAULT_THEME = HERE / schema.DEFAULT_THEME
DEFAULT_CSS = HERE / "resume.css"
DEFAULT_OUT_DIR = HERE / "build"

PAPER_SIZES = {"A4": ("210mm", "297mm"), "Letter": ("8.5in", "11in")}

# 一次生成会写出的三种文件。它们共用同一个主干名，改名时也必须一起动——
# 只避开 .pdf 的话会得到"新 PDF 配旧 PNG"，这种更难发现。
OUTPUT_KINDS = ("html", "pdf", "png")

# 自动改名时最多试到第几号。到不了就报错让人去清理，别无声地转下去。
RENAME_LIMIT = 1000

# 判断一个字体家族名是不是中文字体。够用就行——只是为了在字体栈里挑出
# 该由谁承担中文字形，不是要做字体分类。
CJK_MARKERS = ("CJK", "Han", "YaHei", "SimSun", "SimHei", "PingFang", "Heiti", "Song", "Ming")

WINDOWS_FONT_KEY = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts"

# 版式没写 lang 时的页面语言。写进 <html lang> 和 PDF 的 /Lang，
# 读屏软件和文字提取都按它来，英文简历标成中文会被按中文读。
DEFAULT_LANG = "zh-CN"
LANG_TAG = re.compile(r"[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*\Z")

# 版面溢出检查的容差。WeasyPrint 的长度单位是 CSS px（1pt = 4/3 px）。
# 栏目名用负 margin 抵掉末字字距，文字框会比栏宽多出零点几 pt，那不是溢出；
# 再大就是字真的挤出了自己那一栏（压到竖脊、伸出页边）。
PX_PER_PT = 4 / 3
OVERFLOW_TOLERANCE = 1 * PX_PER_PT
OVERFLOW_REPORT_LIMIT = 20


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def validate_content(content: dict, source: Path) -> None:
    """字段表在 schema.py 里，这里只负责把没填的空报到具体位置。

    宁可在这里停下，也不要渲染出一份带着空标题、空 bullet 的 PDF——
    那种 PDF 看上去是"成功了"的，很容易就这么发出去。
    """
    schema.validate_types(content)
    blanks = schema.find_blanks(content)
    if not blanks:
        return
    listing = "\n".join(f"  {line}" for line in blanks)
    raise ValueError(
        f"错误：{source.name} 还有 {len(blanks)} 处空白没填：\n{listing}\n\n"
        f"补齐：python fill.py --out {source}\n"
        f"或者直接编辑 {source.name}。"
    )


def stack_families(stack: str) -> list[str]:
    """把 CSS 字体栈拆成家族名，去掉引号和 sans-serif / serif 这类通用关键字。"""
    families = []
    for item in stack.split(","):
        name = item.strip().strip("'\"")
        if name and name not in ("sans-serif", "serif", "monospace", "cursive", "fantasy"):
            families.append(name)
    return families


def _font_stacks(theme: dict) -> dict:
    fonts = theme.get("fonts")
    if not isinstance(fonts, dict):
        raise ValueError("版式缺少有效的 [fonts] 表。")
    for role in ("sans", "serif"):
        if not isinstance(fonts.get(role), str) or not fonts[role].strip():
            raise ValueError(f"版式 [fonts].{role} 必须是非空的字体栈字符串。")
    return fonts


def load_theme(path: Path, seen: tuple[Path, ...] = (), *,
               allowed_dir: Path | None = None) -> dict:
    """继承合并后校验，半份子版式仍可继承完整配置；错误定位到加载的文件。"""
    theme = _load_theme(path, seen, allowed_dir=allowed_dir)
    try:
        _font_stacks(theme)
        build_root_css(theme)
        theme_lang(theme)
    except ValueError as error:
        raise ValueError(f"{path.name}：{error}") from error
    return theme


def installed_font_names() -> list[str] | None:
    """系统里已安装的字体名。查不到就返回 None——宁可跳过检查，也不误报。"""
    if shutil.which("fc-list"):  # Linux、macOS、MSYS2
        result = subprocess.run(
            ["fc-list", ":", "family"], capture_output=True, text=True, check=False,
            timeout=5,
        )
        if result.returncode == 0:
            return [
                name.strip()
                for line in result.stdout.splitlines()
                for name in line.split(",")
                if name.strip()
            ]

    try:  # 原生 Windows 没有 fc-list，字体清单在注册表里
        import winreg
    except ImportError:
        return None

    names: list[str] = []
    for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        try:
            with winreg.OpenKey(root, WINDOWS_FONT_KEY) as key:
                total = winreg.QueryInfoKey(key)[1]
                names += [winreg.EnumValue(key, i)[0] for i in range(total)]
        except OSError:
            continue  # 该 hive 下没有这个键，换下一个
    return names or None


def check_fonts(theme: dict) -> None:
    """字体缺失是最容易被忽略的失败模式：WeasyPrint 会静默回落，PDF 生成成功但中文
    是方块，或者字重、字宽和验证过的版本对不上。所以生成前先把话说在前面。

    注册表里的名字是显示名（例如 “Microsoft YaHei & Microsoft YaHei UI”），
    所以用包含匹配而不是相等匹配。
    """
    fonts = _font_stacks(theme)
    installed = installed_font_names()
    if installed is None:
        print("提示：查不到系统字体清单，跳过字体检查。若 PDF 里中文是方块，装 Noto Sans CJK SC。")
        return

    def available(family: str) -> bool:
        return any(family.lower() in name.lower() for name in installed)

    for role, stack in (("正文", fonts["sans"]), ("标题", fonts["serif"])):
        cjk = [f for f in stack_families(stack) if any(m in f for m in CJK_MARKERS)]
        found = [f for f in cjk if available(f)]
        if not found:
            print(f"警告：{role}字体栈里没有一款中文字体可用（{' / '.join(cjk)}），中文会显示为方块。")
        elif cjk and found[0] != cjk[0]:
            print(f"提示：{role}中文回落到 {found[0]}（首选 {cjk[0]} 未安装），排版与已验证版本会有差异。")


def build_root_css(theme: dict) -> str:
    """把 theme.toml 的每一项摊平成 CSS 变量，再补上 @page 和屏幕预览用的纸张尺寸。"""
    variables: dict[str, str] = {}
    for group in ("fonts", "colors", "layout", "type", "rules"):
        if not isinstance(theme.get(group), dict):
            raise ValueError(f"版式缺少 [{group}] 表。")
        for key, value in theme[group].items():
            variables[key] = str(value)

    page = theme.get("page")
    if (not isinstance(page, dict) or not isinstance(page.get("size"), str)
            or page["size"] not in PAPER_SIZES):
        raise ValueError("版式 [page] size 只支持 A4 或 Letter。")
    for key in ("margin-top", "margin-side", "margin-bottom"):
        if not isinstance(page.get(key), str) or not page[key].strip():
            raise ValueError(f"版式 [page] 缺少有效的 {key}。")
        variables[key] = page[key]
    width, height = PAPER_SIZES[page["size"]]
    variables["sheet-width"] = width
    variables["sheet-height"] = height

    declarations = "\n".join(f"  --{key}: {value};" for key, value in variables.items())
    margin = f'{page["margin-top"]} {page["margin-side"]} {page["margin-bottom"]}'
    return (
        f":root {{\n{declarations}\n}}\n\n"
        f"@page {{ size: {page['size']}; margin: {margin}; }}\n"
    )


def theme_lang(theme: dict) -> str:
    """版式声明的页面语言。不像语言标签的直接报错——它要原样写进 HTML。"""
    value = theme.get("lang", DEFAULT_LANG)
    if not isinstance(value, str) or not LANG_TAG.match(value):
        raise ValueError(f"版式 lang 必须是 zh-CN、en 这样的语言标签（现在是 {value!r}）。")
    return value


# 面包屑里裸写的网址：github.com/账号/仓库、example.org/a/b/。要求首段带点、
# 点后是 2 个以上纯字母（挡掉 "2026.05"），整条不含空白（挡掉 "Astro + Git"）。
BARE_URL = re.compile(r"^[\w.-]+\.[A-Za-z]{2,}(?:/\S*)?$")


def bare_url_href(value: str) -> str:
    """面包屑里的裸网址补上 https:// 再交给 safe_href；不像网址的原样返回空串。"""
    text = value.strip()
    if not text or not BARE_URL.match(text):
        return ""
    return safe_href(f"https://{text}")


def safe_href(value: str) -> str:
    value = value.strip()
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        return ""
    try:
        parsed = urllib.parse.urlsplit(value)
    except ValueError:
        return ""
    if parsed.scheme in ("http", "https") and parsed.hostname:
        return value
    if parsed.scheme in ("mailto", "tel") and parsed.path:
        return value
    return ""


class ResumeBuilder:
    def __init__(self, content: dict, theme: dict, stylesheet: str):
        self.content = content
        self.theme = theme
        self.stylesheet = stylesheet

    # ---------- 片段 ----------

    def identity_line(self) -> str:
        """身份事实和联系方式合并成一行，用 · 分隔（并列关系，区别于经历行的 ›）。

        facts 是选填的；标签和内容之间的那个空格由这里补，不指望内容文件里
        写成 "手机 "——TOML 里行尾的空格看不见，也很容易被编辑器吃掉。
        """
        facts = self.content["profile"].get("facts") or []
        parts = [esc(fact) for fact in facts if str(fact).strip()]
        for item in self.content["contacts"]:
            label = str(item.get("label", "")).strip()
            text = f'{esc(label)} {esc(item["value"])}' if label else esc(item["value"])
            href = safe_href(item.get("href", ""))
            if href:
                text = f'<a href="{esc(href)}">{text}</a>'
            parts.append(text)
        return " · ".join(parts)

    @staticmethod
    def crumbs(items: list[str]) -> str:
        """面包屑：用 › 表示层级，分隔符由 CSS 生成，不写进内容。

        裸写的网址渲染成可点链接——作品链接点不开，PDF 投出去就等于没写。
        """
        parts = []
        for item in items:
            text = esc(item)
            href = bare_url_href(item)
            if href:
                text = f'<a href="{esc(href)}">{text}</a>'
            parts.append(f'<span class="crumb">{text}</span>')
        return "".join(parts)

    def row(self, title: str, body: str) -> str:
        return (
            f'<section class="row">'
            f'<div class="rail"><span>{esc(title)}</span></div>'
            f'<div class="col">{body}</div>'
            f"</section>"
        )

    def skills_block(self) -> str:
        pairs = "".join(
            f'<dt>{esc(item["label"])}</dt><dd>{esc(item["text"])}</dd>'
            for item in self.content["skills"]
        )
        return f'<dl class="skills">{pairs}</dl>'

    def experience_block(self) -> str:
        entries = []
        for item in self.content["experiences"]:
            bullets = "".join(f"<li>{esc(text)}</li>" for text in item["bullets"])
            entries.append(
                f'<article class="entry">'
                f'<h3 class="entry-title">{esc(item["company"])}'
                f'<span class="sep">·</span>'
                f'<span class="role">{esc(item["role"])}</span></h3>'
                f'<p class="entry-meta">{self.crumbs(item["crumbs"])}</p>'
                f"<ul>{bullets}</ul>"
                f"</article>"
            )
        return "".join(entries)

    def projects_block(self) -> str:
        entries = []
        for item in self.content["projects"]:
            entries.append(
                f'<article class="entry">'
                f'<h3 class="entry-title">{esc(item["title"])}</h3>'
                f'<p class="entry-meta">{self.crumbs(item["crumbs"])}</p>'
                f'<p class="entry-body">{esc(item["description"])}</p>'
                f"</article>"
            )
        return "".join(entries)

    def education_block(self) -> str:
        items = " · ".join(esc(item) for item in self.content["education"]["items"])
        return f'<p class="education">{items}</p>'

    def custom_block(self, block, rows: list) -> str:
        """自定义板块的通用版面：每条一个 .entry，字段按声明顺序渲染。
        没有内建块那种手调版面，复用经历/项目的 .entry 语言——第一个 text
        字段当标题，list 当面包屑，lines 当 bullet，其余 text 当正文段落。
        用户接受"可能不好看"，换来的是全自定义字段。"""
        entries = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            parts = []
            title_done = False
            for field in block.fields:
                value = row.get(field.key)
                if field.kind == "list":
                    items = [v for v in (value or []) if str(v).strip()]
                    if items:
                        parts.append(
                            f'<p class="entry-meta">{self.crumbs(items)}</p>')
                elif field.kind == "lines":
                    bullets = "".join(
                        f"<li>{esc(v)}</li>" for v in (value or []) if str(v).strip())
                    if bullets:
                        parts.append(f"<ul>{bullets}</ul>")
                else:
                    text = str(value or "").strip()
                    if not text:
                        continue
                    if not title_done:
                        parts.insert(0, f'<h3 class="entry-title">{esc(text)}</h3>')
                        title_done = True
                    else:
                        parts.append(f'<p class="entry-body">{esc(text)}</p>')
            if parts:
                entries.append(f'<article class="entry">{"".join(parts)}</article>')
        return "".join(entries)

    def footer_block(self) -> str:
        """脚注只用来标记这份还是占位版。把 document.preview_note 和 edition 清空，
        脚注整条消失——真正要投出去的那一份不应该带任何生成说明。"""
        document = self.content["document"]
        spans = [
            f"<span>{esc(document[key])}</span>"
            for key in ("preview_note", "edition")
            if document.get(key)
        ]
        if not spans:
            return ""
        return f'<footer class="sheet-footer">{"".join(spans)}</footer>'

    # ---------- 整页 ----------

    def body_rows(self) -> list[str]:
        """按 body_order 拼出正文那几栏。内建四块走各自的手调版面，
        自定义块走通用版面。栏目名来源各不相同：skills/experiences/projects
        在各自的 *_section 表，education 在自己表里的 title，自定义块用
        section["title"]（schema 把它放进了 block.section_default）。

        没写 body_order 的老文件，effective_body_blocks 返回四内建块的原
        顺序，拼出来的行与改造前逐字节相同。"""
        content = self.content
        builtin = {
            "skills": lambda: self.row(
                content["skills_section"]["title"], self.skills_block()),
            "experiences": lambda: self.row(
                content["experience_section"]["title"], self.experience_block()),
            "projects": lambda: self.row(
                content["projects_section"]["title"], self.projects_block()),
            "education": lambda: self.row(
                content["education"]["title"], self.education_block()),
        }
        rows = []
        for block, data in schema.effective_body_blocks(content):
            if block.key in builtin:
                rows.append(builtin[block.key]())
            else:
                body = self.custom_block(block, data if isinstance(data, list) else [])
                rows.append(self.row(block.section_default, body))
        return rows

    def render_html(self) -> str:
        content = self.content
        document = content["document"]
        profile = content["profile"]

        rows = "".join(self.body_rows())

        return f"""<!doctype html>
<html lang="{esc(theme_lang(self.theme))}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(document["title"])}</title>
<meta name="description" content="{esc(document["subject"])}">
<meta name="keywords" content="{esc(", ".join(document["keywords"]))}">
<meta name="author" content="{esc(profile["name"])}">
<style>
{self.stylesheet}
</style>
</head>
<body>
<main class="sheet">
  <section class="row masthead-row">
    <div class="rail"></div>
    <div class="col">
      <header class="masthead">
        <div class="masthead-line">
          <h1>{esc(profile["name"])}</h1>
          <p class="intent">{esc(profile["intent"])}</p>
        </div>
        <div class="masthead-rule"></div>
        <p class="identity">{self.identity_line()}</p>
        <p class="snippet">{esc(content["summary"]["text"])}</p>
      </header>
    </div>
  </section>
{rows}
  {self.footer_block()}
</main>
</body>
</html>
"""


class PageOverflow(RuntimeError):
    """内容超出了允许的页数。带上实际页数和上限，好让调用方原样报给用户。

    仍然继承 RuntimeError：命令行和既有测试都按 RuntimeError 接它。
    """

    def __init__(self, pages: int, limit: int = 1):
        super().__init__(
            f"渲染出了 {pages} 页，超过了设定的 {limit} 页上限。"
            "请精简内容，或把页数上限调大，不要靠缩小字号硬塞。"
        )
        self.pages = pages
        self.limit = limit


class LayoutOverflow(RuntimeError):
    """有字挤出了自己那一栏。页数和空白都对，PDF 也照样生成得出来，
    但栏目名压在正文上、网址伸出页边——这种 PDF 最容易被当成"成功了"发出去。"""

    def __init__(self, problems: list[str]):
        super().__init__(
            f"版面有 {len(problems)} 处文字挤出了自己那一栏：\n"
            + "\n".join(f"  {line}" for line in problems)
        )
        self.problems = problems


def _is_rail(box) -> bool:
    """这个盒子是不是竖脊左栏。元素是 ElementTree 节点，没有父指针，
    所以"在不在左栏里"由 walk 往下传，不往上找。"""
    element = getattr(box, "element", None)
    return element is not None and "rail" in (element.get("class") or "").split()


def find_overflows(document) -> list[str]:
    """逐个文字框比对两条边界，越界超过容差的报出来：

    - 它所在块的内容区：栏目名放不进左栏、压到竖脊上；
    - 页面的内容区：断不开的长词会把整列撑宽（grid 的 1fr 按最长的词定下限），
      这时所在块跟着变宽，只看块就看不出来，得看字有没有伸出页边。

    只看文字、不看线：主线往左伸到竖脊、栏目名的记号压在竖脊上都是设计，
    它们不是文字框。返回给人看的说明，空列表 = 版面干净。
    """
    problems: list[str] = []
    seen: set[str] = set()
    pushed: list[tuple[float, str]] = []     # 伸出版心的行：(越界量, 文字)

    def report_rail(text: str, over: float) -> None:
        if text in seen:
            return
        seen.add(text)
        problems.append(
            f"栏目名「{text}」比左栏宽 {over / PX_PER_PT:.0f}pt，压到了竖脊。"
            "英文内容请把版式换成 theme.en.toml，或把栏目名改短。")

    def walk(box, left: float, right: float, page: tuple[float, float],
             rail: bool) -> None:
        if isinstance(box, boxes.BlockContainerBox):
            left = box.content_box_x()
            right = left + box.width
            rail = rail or _is_rail(box)
        if isinstance(box, boxes.TextBox):
            text = box.text.strip()
            start, end = box.position_x, box.position_x + box.width
            over = max(left - start, end - right, page[0] - start, end - page[1])
            if text and over > OVERFLOW_TOLERANCE:
                if rail:
                    report_rail(text, over)
                else:
                    pushed.append((over, text))
            return
        for child in getattr(box, "children", None) or ():
            walk(child, left, right, page, rail)

    for page in document.pages:
        root = page._page_box
        area = (root.content_box_x(), root.content_box_x() + root.width)
        walk(root, area[0], area[1], area, False)

    # 一个断不开的长词会把整栏撑宽，同栏的正常句子跟着换行到新栏宽、一起伸出去。
    # 栏宽就是按最长的那个词定的，所以伸得最远的那行就是祸首；只点它的名。
    if pushed:
        over, text = max(pushed)
        shown = text if len(text) <= 40 else text[:40] + "…"
        others = len({line for _, line in pushed} - {text})
        tail = f"，另有 {others} 行跟着被挤出去" if others else ""
        problems.append(
            f"「{shown}」断不开，把所在栏撑出版心 {over / PX_PER_PT:.0f}pt{tail}。"
            "给这个长词或网址加个空格，或改短。")
    return problems[:OVERFLOW_REPORT_LIMIT]


def render_pdf_bytes(markup: str, max_pages: int = 1) -> bytes:
    """渲染成 PDF 字节，一个文件都不写。

    网页端"只存到我选的位置"走这条：那份 PDF 的落点由浏览器的保存对话框决定，
    中途不该在磁盘上先留一份副本。页数上限和版面溢出照查——那是这个工具的
    硬承诺，哪条路都不许绕过去。
    """
    document = HTML(string=markup, base_url=str(HERE)).render()
    pages = len(document.pages)
    if pages > max_pages:
        raise PageOverflow(pages, max_pages)
    problems = find_overflows(document)
    if problems:
        raise LayoutOverflow(problems)
    return document.write_pdf()


def render_pdf(markup: str, pdf_path: Path, max_pages: int = 1) -> None:
    pdf_path.write_bytes(render_pdf_bytes(markup, max_pages))


def render_png(pdf_path: Path, png_path: Path) -> bool:
    if not shutil.which("pdftoppm"):
        return False
    subprocess.run(
        ["pdftoppm", "-png", "-r", "150", "-singlefile",
         str(pdf_path), str(png_path.with_suffix(""))],
        check=True, timeout=60,
    )
    return True


class OutputExistsError(RuntimeError):
    """同名生成物已经存在，而调用方要求"存在就报错"。

    带着 suggested（自动改名会得到的名字），好让网页的对话框直接把两个选项摆出来。
    """

    def __init__(self, name: str, suggested: str):
        super().__init__(f"{name} 已存在。")
        self.name = name
        self.suggested = suggested


def output_paths(out_dir: Path, basename: str) -> dict[str, Path]:
    return {kind: out_dir / f"{basename}.{kind}" for kind in OUTPUT_KINDS}


def existing_outputs(out_dir: Path, basename: str) -> list[Path]:
    """这个主干上已经躺着哪些生成物。目录不存在就当没有。"""
    try:
        return [path for path in output_paths(out_dir, basename).values() if path.is_file()]
    except OSError:
        return []


def next_free_basename(out_dir: Path, basename: str) -> str:
    """找一个三种后缀都还空着的主干：<名>-2 / -3 / …"""
    for index in range(2, RENAME_LIMIT):
        candidate = f"{basename}-{index}"
        if not existing_outputs(out_dir, candidate):
            return candidate
    raise ValueError(f"生成物目录里 {basename}-* 太多了，先清理一下再生成。")


def build_stylesheet(theme: dict, css_path: Path) -> str:
    """theme.toml 摊平出来的 CSS 变量 + 版式 CSS，拼成一份完整样式表。"""
    return build_root_css(theme) + "\n" + css_path.read_text(encoding="utf-8")


def resolve_basename(explicit: str | None, content: dict) -> str:
    """生成物文件名主干：显式指定 > [document].output_basename > 字段默认值。"""
    return (explicit or content["document"].get("output_basename")
            or schema.DEFAULT_BASENAME)


def write_outputs(content: dict, theme: dict, stylesheet: str,
                  out_dir: Path, basename: str,
                  if_exists: str = "overwrite") -> dict[str, Path | None]:
    """写出 HTML / PDF / PNG，返回各自路径；缺 pdftoppm 时 PNG 是 None。

    if_exists 三种：
        overwrite  同名就覆盖（命令行默认，等于从前的行为）
        rename     同名就换成 <名>-2 / -3 …（三种后缀一起避开）
        fail       同名就报错，让调用方去问用户

    "生成物有哪些、叫什么名字"只在这里说一次——命令行和 webui.py 都走这个函数。
    分开写迟早会出现"网页上下载到的和命令行生成的不是同一份东西"。
    """
    if if_exists not in ("overwrite", "rename", "fail"):
        raise ValueError(f"未知的重名处理方式：{if_exists!r}")
    basename = plain_name(basename)
    schema.validate_types(content)
    out_dir.mkdir(parents=True, exist_ok=True)

    if if_exists != "overwrite" and existing_outputs(out_dir, basename):
        if if_exists == "fail":
            raise OutputExistsError(
                f"{basename}.pdf",
                f"{next_free_basename(out_dir, basename)}.pdf",
            )
        basename = next_free_basename(out_dir, basename)

    paths = output_paths(out_dir, basename)
    for path in paths.values():
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise ValueError(f"生成物目标不是普通文件：{path.name}")
    markup = ResumeBuilder(content, theme, stylesheet).render_html()
    with tempfile.TemporaryDirectory(prefix=".resume-", dir=out_dir) as temporary:
        staged = {kind: Path(temporary) / path.name for kind, path in paths.items()}
        render_pdf(markup, staged["pdf"], schema.effective_max_pages(content))
        staged["html"].write_text(markup, encoding="utf-8")
        has_png = render_png(staged["pdf"], staged["png"])
        for kind in ("html", "pdf", "png"):
            if kind != "png" or has_png:
                staged[kind].replace(paths[kind])
    return {**paths, "png": paths["png"] if has_png else None}


def resolve_content(explicit: str | None) -> Path:
    """--content 指定就用它；否则按 CONTENT_CANDIDATES 的顺序在脚本目录里找。"""
    if explicit:
        path = Path(explicit).expanduser().resolve()
        if not path.exists():
            raise SystemExit(f"错误：内容文件不存在：{path}")
        return path
    for name in CONTENT_CANDIDATES:
        candidate = HERE / name
        if candidate.exists():
            return candidate
    raise SystemExit(
        "错误：没有找到内容文件。两条路：\n"
        "    python fill.py           一题一题地填，填完自动写 content.toml\n"
        "    python fill.py --blank   生成一份空白表单，自己在编辑器里填"
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="把 TOML 内容渲染成一页简历（HTML / PDF / PNG）。",
    )
    parser.add_argument(
        "--content", metavar="PATH",
        help=f"内容 TOML 的路径。省略时按顺序查找 {' → '.join(CONTENT_CANDIDATES)}。"
             "真实简历建议放在本仓库之外，用这个参数指过来。",
    )
    parser.add_argument("--theme", metavar="PATH",
                        help="设计令牌 TOML。省略时用内容文件里的 theme，再默认 theme.toml。")
    parser.add_argument("--css", metavar="PATH", default=str(DEFAULT_CSS),
                        help="版式 CSS，默认 resume.css。")
    parser.add_argument("--out-dir", metavar="DIR", default=str(DEFAULT_OUT_DIR),
                        help="生成物目录，默认 build/（已在 .gitignore 里）。")
    parser.add_argument("--name", metavar="BASENAME",
                        help="生成物的文件名主干，默认取 [document] output_basename，"
                             "再默认 resume。")
    parser.add_argument("--if-exists", choices=("overwrite", "rename", "fail"),
                        default="overwrite",
                        help="生成物同名时怎么办，默认 overwrite（直接覆盖）。"
                             "rename 会自动改成 <名>-2；fail 直接报错，不改任何文件。")
    return parser.parse_args(argv)


def resolve_theme(explicit: str | None, content: dict) -> Path:
    """--theme 指定就用它（任意路径，和从前一样）；否则用内容文件里写的版式名，
    在本仓库目录里找——内容文件只能点名仓库里的 theme*.toml，不能指到别处。"""
    if explicit:
        return Path(explicit).expanduser().resolve()
    return safe_name(schema.effective_theme(content), "theme*.toml", HERE)


def run(argv: list[str] | None = None) -> None:
    args = parse_args(argv)

    content_path = resolve_content(args.content)
    css_path = Path(args.css).expanduser().resolve()
    out_dir = Path(args.out_dir).expanduser().resolve()

    content = load_content(content_path)
    validate_content(content, content_path)
    theme_path = resolve_theme(args.theme, content)
    theme = load_theme(theme_path)
    basename = resolve_basename(args.name, content)
    stylesheet = build_stylesheet(theme, css_path)
    check_fonts(theme)
    outputs = write_outputs(content, theme, stylesheet, out_dir, basename,
                            if_exists=args.if_exists)

    if content_path.name == EXAMPLE_CONTENT:
        print(f"内容: {content_path}（虚构示例；你自己的那份请写进 content.toml"
              " 或用 --content 指定）", file=sys.stderr)
    else:
        print(f"内容: {content_path}")
    print(f"版式: {theme_path.name}")
    print(f"HTML: {outputs['html']}")
    print(f"PDF:  {outputs['pdf']}")
    print(f"PNG:  {outputs['png']}" if outputs["png"]
          else "PNG:  跳过（没有 pdftoppm，装 poppler-utils 就有了）")


def main(argv: list[str] | None = None) -> None:
    try:
        run(argv)
    except OutputExistsError as error:
        raise SystemExit(
            f"错误：{error}\n"
            f"    想自动改名：--if-exists rename（这一次会写成 {error.suggested}）\n"
            f"    想覆盖它：  --if-exists overwrite（默认行为）"
        ) from error
    except (ValueError, OSError, RuntimeError, subprocess.SubprocessError) as error:
        raise SystemExit(f"错误：{error}") from error


if __name__ == "__main__":
    main()
