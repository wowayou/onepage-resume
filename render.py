"""把一份 TOML 内容文件 + theme.toml + resume.css 渲染成一页 HTML、PDF 和 PNG。

排版由 WeasyPrint 用真正的 CSS 盒模型完成，间距由引擎计算，不再手工算坐标。
日常维护只需要改内容文件；调版式改 theme.toml 或 resume.css；这个文件不用动。

内容文件怎么来：跑 `python fill.py` 一题一题填，或 `python fill.py --blank`
生成空白表单自己填。字段表在 schema.py，填和渲染读的是同一份定义。

用法：
    python render.py                          # 用默认查找到的内容文件
    python render.py --theme theme.en.toml    # 英文版式（竖脊更宽、行距更紧）
    python render.py --content ~/private/me.toml --out-dir ~/private/build
"""

from __future__ import annotations

import argparse
import html
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

from weasyprint import HTML

import schema

HERE = Path(__file__).resolve().parent

# 内容文件的查找顺序。前两个在 .gitignore 里，是"你自己的那一份"；
# content.example.toml 是仓库里跟踪的虚构示例，只用来证明工具能跑。
# 真实姓名、手机、邮箱、微信、学校永远不要写进 content.example.toml。
CONTENT_CANDIDATES = ("content.local.toml", "content.toml", "content.example.toml")
EXAMPLE_CONTENT = "content.example.toml"

DEFAULT_THEME = HERE / "theme.toml"
DEFAULT_CSS = HERE / "resume.css"
DEFAULT_OUT_DIR = HERE / "build"

PAPER_SIZES = {"A4": ("210mm", "297mm"), "Letter": ("8.5in", "11in")}

# 判断一个字体家族名是不是中文字体。够用就行——只是为了在字体栈里挑出
# 该由谁承担中文字形，不是要做字体分类。
CJK_MARKERS = ("CJK", "Han", "YaHei", "SimSun", "SimHei", "PingFang", "Heiti", "Song", "Ming")

WINDOWS_FONT_KEY = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts"


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def load_toml(path: Path) -> dict:
    with path.open("rb") as stream:
        return tomllib.load(stream)


def load_theme(path: Path, seen: tuple[Path, ...] = ()) -> dict:
    """读一个主题文件。它可以用 extends = "theme.toml" 继承另一个，只写要改的令牌。

    这样做语言变体（中文窄竖脊 / 英文宽竖脊）不用把整份令牌抄一遍——抄一遍的
    代价是以后改颜色要记得改两处，而人是会忘的。
    """
    if path in seen:
        chain = " → ".join(p.name for p in (*seen, path))
        raise SystemExit(f"错误：主题继承成环了：{chain}")

    theme = load_toml(path)
    parent_name = theme.pop("extends", None)
    if not parent_name:
        return theme

    parent_path = (path.parent / parent_name).resolve()
    if not parent_path.exists():
        raise SystemExit(f"错误：{path.name} 继承的 {parent_name} 不存在。")

    merged = load_theme(parent_path, (*seen, path))
    for group, values in theme.items():
        if isinstance(values, dict) and isinstance(merged.get(group), dict):
            merged[group] = {**merged[group], **values}
        else:
            merged[group] = values
    return merged


def load_content(path: Path, seen: tuple[Path, ...] = ()) -> dict:
    """读一份内容文件。它可以用 extends = "content.toml" 继承另一份，只写要改的地方。

    为什么要有这个：按岗位做定制版时，整份抄一遍的代价是以后改手机号要记得改五处，
    而人是会忘的——和 theme.en.toml 继承 theme.toml 是同一个理由。

    合并规则，三条：

    1. **普通表深合并**：定制版写了的键覆盖基底，没写的继承。
       所以只想换求职意向和概况，就只写那两处。
    2. **数组表整块替换**：定制版写了 [[skills]]，就用定制版的那几条；没写就全继承。
       半自动的"按下标改第 2 条"看着聪明，但基底加了一条之后下标就全错位了。
    3. **[keep] 表按天然键挑选并排序**：想要的只是"从基底那 6 条技能里留 4 条、
       换个顺序"，写数组太啰嗦。就写：

           [keep]
           skills = ["Technical SEO", "数据分析", "英文内容", "SEO 执行"]

       挑的是 label 等于这些值的技能（每个数组块用哪个字段作键，见 schema.py 的
       identity）。名字拼错会当场报错，不会静默丢掉一整条经历——那种错误在
       PDF 上看不出来，投出去才发现少了一段。

    [keep] 只是筛选指令，不是内容，合并完就从结果里摘掉。
    """
    if path in seen:
        chain = " → ".join(p.name for p in (*seen, path))
        raise SystemExit(f"错误：内容文件继承成环了：{chain}")

    content = load_toml(path)
    parent_name = content.pop("extends", None)
    keep = content.pop("keep", None)

    if not parent_name:
        if keep:
            raise SystemExit(
                f"错误：{path.name} 写了 [keep] 但没有 extends。"
                "[keep] 是从被继承的那份里挑条目用的。"
            )
        return content

    parent_path = (path.parent / parent_name).resolve()
    if not parent_path.exists():
        raise SystemExit(f"错误：{path.name} 继承的 {parent_name} 不存在。")

    merged = load_content(parent_path, (*seen, path))
    if keep:
        merged = apply_keep(merged, keep, path)

    for key, value in content.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = {**merged[key], **value}
        else:
            merged[key] = value        # 含数组表：整块替换
    return merged


def apply_keep(content: dict, keep: dict, source: Path) -> dict:
    """按 [keep] 里给的天然键，从数组块里挑出要留的条目，顺序也按给的来。"""
    blocks = {b.key: b for b in schema.BLOCKS if b.repeat and b.identity}

    for block_key, wanted in keep.items():
        block = blocks.get(block_key)
        if block is None:
            allowed = " / ".join(sorted(blocks))
            raise SystemExit(
                f"错误：{source.name} 的 [keep] 里有 {block_key}，"
                f"但只有这些数组块支持挑选：{allowed}。"
            )
        if not isinstance(wanted, list):
            raise SystemExit(
                f"错误：{source.name} 的 [keep] {block_key} 要写成数组。"
            )

        rows = content.get(block_key) or []
        index = {str(row.get(block.identity, "")): row for row in rows}
        picked = []
        for name in wanted:
            row = index.get(str(name))
            if row is None:
                have = " / ".join(index) or "（空）"
                raise SystemExit(
                    f"错误：{source.name} 的 [keep] {block_key} 里写了 {name!r}，"
                    f"但被继承的那份里没有这一条。\n"
                    f"    它的 {block.identity} 可选：{have}"
                )
            picked.append(row)
        content[block_key] = picked

    return content


def validate_content(content: dict, source: Path) -> None:
    """字段表在 schema.py 里，这里只负责把没填的空报到具体位置。

    宁可在这里停下，也不要渲染出一份带着空标题、空 bullet 的 PDF——
    那种 PDF 看上去是"成功了"的，很容易就这么发出去。
    """
    blanks = schema.find_blanks(content)
    if not blanks:
        return
    listing = "\n".join(f"  {line}" for line in blanks)
    raise SystemExit(
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


def installed_font_names() -> list[str] | None:
    """系统里已安装的字体名。查不到就返回 None——宁可跳过检查，也不误报。"""
    if shutil.which("fc-list"):  # Linux、macOS、MSYS2
        result = subprocess.run(
            ["fc-list", ":", "family"], capture_output=True, text=True, check=False
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
    installed = installed_font_names()
    if installed is None:
        print("提示：查不到系统字体清单，跳过字体检查。若 PDF 里中文是方块，装 Noto Sans CJK SC。")
        return

    def available(family: str) -> bool:
        return any(family.lower() in name.lower() for name in installed)

    for role, stack in (("正文", theme["fonts"]["sans"]), ("标题", theme["fonts"]["serif"])):
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
        for key, value in theme[group].items():
            variables[key] = str(value)

    page = theme["page"]
    width, height = PAPER_SIZES.get(page["size"], PAPER_SIZES["A4"])
    variables["sheet-width"] = width
    variables["sheet-height"] = height

    declarations = "\n".join(f"  --{key}: {value};" for key, value in variables.items())
    margin = f'{page["margin-top"]} {page["margin-side"]} {page["margin-bottom"]}'
    return (
        f":root {{\n{declarations}\n}}\n\n"
        f"@page {{ size: {page['size']}; margin: {margin}; }}\n"
    )


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
            if item.get("href"):
                text = f'<a href="{esc(item["href"])}">{text}</a>'
            parts.append(text)
        return " · ".join(parts)

    @staticmethod
    def crumbs(items: list[str]) -> str:
        """面包屑：用 › 表示层级，分隔符由 CSS 生成，不写进内容。"""
        return "".join(f'<span class="crumb">{esc(item)}</span>' for item in items)

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

    def render_html(self) -> str:
        content = self.content
        document = content["document"]
        profile = content["profile"]

        rows = "".join([
            self.row(content["skills_section"]["title"], self.skills_block()),
            self.row(content["experience_section"]["title"], self.experience_block()),
            self.row(content["projects_section"]["title"], self.projects_block()),
            self.row(content["education"]["title"], self.education_block()),
        ])

        return f"""<!doctype html>
<html lang="zh-CN">
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
  <header class="masthead">
    <div class="masthead-line">
      <h1>{esc(profile["name"])}</h1>
      <p class="intent">{esc(profile["intent"])}</p>
    </div>
    <div class="masthead-rule"></div>
    <p class="identity">{self.identity_line()}</p>
    <p class="snippet">{esc(content["summary"]["text"])}</p>
  </header>
{rows}
  {self.footer_block()}
</main>
</body>
</html>
"""


def render_pdf(markup: str, pdf_path: Path) -> None:
    document = HTML(string=markup, base_url=str(HERE)).render()
    pages = len(document.pages)
    if pages != 1:
        raise RuntimeError(
            f"渲染出了 {pages} 页，这份简历必须是一页。"
            "请精简 content.toml，不要靠缩小字号硬塞。"
        )
    document.write_pdf(pdf_path)


def render_png(pdf_path: Path, png_path: Path) -> bool:
    if not shutil.which("pdftoppm"):
        return False
    subprocess.run(
        ["pdftoppm", "-png", "-r", "150", "-singlefile",
         str(pdf_path), str(png_path.with_suffix(""))],
        check=True,
    )
    return True


def build_stylesheet(theme: dict, css_path: Path) -> str:
    """theme.toml 摊平出来的 CSS 变量 + 版式 CSS，拼成一份完整样式表。"""
    return build_root_css(theme) + "\n" + css_path.read_text(encoding="utf-8")


def write_outputs(content: dict, theme: dict, stylesheet: str,
                  out_dir: Path, basename: str) -> dict[str, Path | None]:
    """写出 HTML / PDF / PNG，返回各自路径；缺 pdftoppm 时 PNG 是 None。

    "生成物有哪些、叫什么名字"只在这里说一次——命令行和 webui.py 都走这个函数。
    分开写迟早会出现"网页上下载到的和命令行生成的不是同一份东西"。
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    html_path = out_dir / f"{basename}.html"
    pdf_path = out_dir / f"{basename}.pdf"
    png_path = out_dir / f"{basename}.png"

    markup = ResumeBuilder(content, theme, stylesheet).render_html()
    html_path.write_text(markup, encoding="utf-8")
    render_pdf(markup, pdf_path)          # 超过一页就在这里报错，不会偷偷出第二页
    return {
        "html": html_path,
        "pdf": pdf_path,
        "png": png_path if render_png(pdf_path, png_path) else None,
    }


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
    parser.add_argument("--theme", metavar="PATH", default=str(DEFAULT_THEME),
                        help="设计令牌 TOML，默认 theme.toml。")
    parser.add_argument("--css", metavar="PATH", default=str(DEFAULT_CSS),
                        help="版式 CSS，默认 resume.css。")
    parser.add_argument("--out-dir", metavar="DIR", default=str(DEFAULT_OUT_DIR),
                        help="生成物目录，默认 build/（已在 .gitignore 里）。")
    parser.add_argument("--name", metavar="BASENAME",
                        help="生成物的文件名主干，默认取 [document] output_basename，"
                             "再默认 resume。")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)

    content_path = resolve_content(args.content)
    theme_path = Path(args.theme).expanduser().resolve()
    css_path = Path(args.css).expanduser().resolve()
    out_dir = Path(args.out_dir).expanduser().resolve()

    content = load_content(content_path)
    theme = load_theme(theme_path)
    validate_content(content, content_path)
    check_fonts(theme)

    basename = args.name or content["document"].get("output_basename") or "resume"
    stylesheet = build_stylesheet(theme, css_path)
    outputs = write_outputs(content, theme, stylesheet, out_dir, basename)

    if content_path.name == EXAMPLE_CONTENT:
        print(f"内容: {content_path}（虚构示例；你自己的那份请写进 content.toml"
              " 或用 --content 指定）", file=sys.stderr)
    else:
        print(f"内容: {content_path}")
    print(f"HTML: {outputs['html']}")
    print(f"PDF:  {outputs['pdf']}")
    print(f"PNG:  {outputs['png']}" if outputs["png"]
          else "PNG:  跳过（没有 pdftoppm，装 poppler-utils 就有了）")


if __name__ == "__main__":
    main()
