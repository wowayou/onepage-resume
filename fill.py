"""填空式的简历内容生成器：一题一题问，最后写出一份可以直接渲染的 content.toml。

    python fill.py                  # 交互填空，写到 content.toml
    python fill.py --out me.toml    # 写到别处（放仓库外最稳）
    python fill.py --blank          # 不问了，直接生成一份空白表单，自己在编辑器里填
    python fill.py --check          # 只检查：还有哪些空没填

内容长什么样由 schema.py 定义，这个文件只管"怎么问"和"怎么写出去"。

两条设计约束：
1. **不覆盖已有答案**。目标文件已经存在时，先把它读进来当默认值，每一题都显示
   当前值，回车就是保留。所以这个程序既是"第一次填"，也是"改一处"。
2. **不替用户编内容**。示例只作参考展示，永远不会被当成答案写进文件——
   一份带着示例文字的简历投出去，比没投更糟。
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

import schema
import content_io
from schema import BLOCKS, Block, Field, escape, split_list

HERE = Path(__file__).resolve().parent
DEFAULT_OUT = HERE / "content.toml"

COLOR = sys.stdout.isatty()


def paint(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m" if COLOR else text


def bold(text: str) -> str:
    return paint(text, "1")


def dim(text: str) -> str:
    return paint(text, "2")


def green(text: str) -> str:
    return paint(text, "32")


def red(text: str) -> str:
    return paint(text, "31")


class Abort(Exception):
    """用户按了 Ctrl-C / Ctrl-D。当场停下，不写半份文件。"""


def prompt(label: str = "> ") -> str:
    try:
        return input(label)
    except (KeyboardInterrupt, EOFError):
        raise Abort from None


def confirm(question: str, default: bool = False) -> bool:
    tail = "[Y/n]" if default else "[y/N]"
    while True:
        answer = prompt(f"{question} {dim(tail)} ").strip().lower()
        if not answer:
            return default
        if answer in ("y", "yes", "是"):
            return True
        if answer in ("n", "no", "否"):
            return False


# ---------- 问一个字段 ----------

def show_question(item: Field, current: object) -> None:
    print()
    print(bold(f"  {item.ask}"))
    if item.hint:
        print(dim(f"    {item.hint}"))
    if item.example:
        print(dim(f"    例：{item.example}"))
    if not item.required and current in (None, "", []):
        print(dim("    不需要就直接回车跳过"))
    if current not in (None, "", []):
        shown = " / ".join(current) if isinstance(current, list) else str(current)
        print(dim(f"    当前：{shown}（回车保留）"))


def ask_text(item: Field, current: str) -> str:
    fallback = current or item.default
    while True:
        show_question(item, current)
        if not current and item.default:
            print(dim(f"    默认：{item.default}（回车采用）"))
        answer = prompt().strip()
        if answer:
            return answer
        if fallback:
            return fallback
        if not item.required:
            return ""
        print(red("    这一项是必填的，渲染时会被拦下来。"))


def ask_list(item: Field, current: list[str]) -> list[str]:
    while True:
        show_question(item, current)
        answer = prompt().strip()
        if answer:
            values = split_list(answer)
            if values or not item.required:
                return values
            print(red("    至少填写一个非空条目。"))
            continue
        if current:
            return list(current)
        if item.default:
            return split_list(item.default)
        if not item.required:
            return []
        print(red("    这一项是必填的，用 / 分隔着写几个词。"))


def ask_lines(item: Field, current: list[str]) -> list[str]:
    while True:
        show_question(item, current)
        print(dim("    一行一条，写完空一行结束"))
        lines: list[str] = []
        while True:
            line = prompt("  - ").strip()
            if not line:
                break
            lines.append(line)
        if lines:
            return lines
        if current:
            return list(current)
        if not item.required:
            return []
        print(red("    至少写一条。"))


def ask_field(item: Field, current: object) -> object:
    if item.kind == "list":
        return ask_list(item, list(current or []))
    if item.kind == "lines":
        return ask_lines(item, list(current or []))
    return ask_text(item, str(current or ""))


# ---------- 问一整块 ----------

def ask_entry(block: Block, existing: dict) -> dict:
    entry: dict = {}
    for item in block.fields:
        value = ask_field(item, existing.get(item.key))
        if value or item.required:
            entry[item.key] = value
    return entry


def summarize(block: Block, entry: dict) -> str:
    """一条填完后回显一句，让人确认自己填到了正确的位置。"""
    head = block.fields[0].key
    return str(entry.get(head, "")) or "（空）"


def ask_block(block: Block, existing: dict, step: str) -> dict:
    print()
    print(green(f"{step} {block.title}"))
    if block.intro:
        print(dim(f"  {block.intro}"))

    collected: dict = {}

    if block.section_key:
        current = (existing.get(block.section_key) or {}).get("title", "")
        title = ask_text(
            Field("title", f"「{block.title}」这一栏在页面上叫什么",
                  "左侧竖脊上那几个字", block.section_default,
                  default=block.section_default),
            current,
        )
        collected[block.section_key] = {"title": title}

    if not block.repeat:
        collected[block.key] = ask_entry(block, existing.get(block.key) or {})
        return collected

    old_rows = list(existing.get(block.key) or [])
    rows: list[dict] = []
    index = 0
    while True:
        old = old_rows[index] if index < len(old_rows) else {}
        print(dim(f"\n  ── {block.title} 第 {index + 1} 条 ──"))
        rows.append(ask_entry(block, old))
        print(dim(f"  ✓ 已记下：{summarize(block, rows[-1])}"))
        index += 1

        if block.max_items and index >= block.max_items:
            break
        if index < block.min_items:
            continue
        more = index < len(old_rows)  # 原来还有更多条，默认继续，免得手滑丢内容
        if not confirm(f"  再加一条{block.title}？", default=more):
            break

    collected[block.key] = rows
    return collected


def collect(existing: dict) -> dict:
    content: dict = {}
    total = len(BLOCKS)
    for number, block in enumerate(BLOCKS, start=1):
        content.update(ask_block(block, existing, f"[{number}/{total}]"))
    if "status" in existing.get("document", {}):
        content["document"]["status"] = existing["document"]["status"]
    return content


# ---------- 写出去 ----------

def render_value(value: object) -> str:
    if isinstance(value, list):
        if not value:
            return "[]"
        if all(len(str(v)) < 40 for v in value):
            inner = ", ".join(f'"{escape(str(v))}"' for v in value)
            return f"[{inner}]"
        body = "".join(f'  "{escape(str(v))}",\n' for v in value)
        return f"[\n{body}]"
    return f'"{escape(str(value))}"'


def dump_toml(content: dict) -> str:
    """按 schema 的顺序写出去，不用第三方库——这样生成的文件里注释是我们说了算的。"""
    schema.validate_types(content)
    out: list[str] = [
        "# 这份是你自己的简历内容，由 fill.py 生成。",
        "# 它被 .gitignore 挡住，不会进 Git。改完直接 make render。",
        "#",
        "# 想改某一处：直接编辑这个文件，或者再跑一次 python fill.py，",
        "# 每一题都会显示当前值，回车保留、输入覆盖。",
        "",
        "[document]",
        f'status = "{escape(str(content["document"].get("status", "real")))}"',
        f'updated = "{date.today().isoformat()}"',
    ]

    document = content["document"]
    for item in schema.DOCUMENT.fields:
        default = [] if item.kind in ("list", "lines") else ""
        out.append(f"{item.key} = {render_value(document.get(item.key, default))}")
    out += [
        "# 页脚。要投出去的那一份留空，页脚整条消失——",
        "# 带着「示例内容」字样投出去等于告诉对方这是没填完的模板。",
        'preview_note = ""',
        'edition = ""',
        "",
    ]

    for block in BLOCKS:
        if block.key == "document":
            continue

        if block.section_key:
            out.append(f"[{block.section_key}]")
            title = (content.get(block.section_key) or {}).get("title", block.section_default)
            out.append(f"title = {render_value(title)}")
            out.append("")

        if block.repeat:
            for entry in content.get(block.key, []):
                out.append(f"[[{block.key}]]")
                for item in block.fields:
                    if item.key in entry and (entry[item.key] or item.required):
                        out.append(f"{item.key} = {render_value(entry[item.key])}")
                out.append("")
        else:
            table = content.get(block.key, {})
            out.append(f"[{block.key}]")
            for item in block.fields:
                if item.key in table and (table[item.key] or item.required):
                    out.append(f"{item.key} = {render_value(table[item.key])}")
            out.append("")

    return "\n".join(out).rstrip() + "\n"


def read_existing(path: Path) -> dict:
    if not path.exists():
        return {}
    return content_io.load_toml(path)


def refuse_derived(path: Path, existing: dict) -> None:
    """定制版（写了 extends 的那种）不给交互填。

    这个程序是"读进来、问一遍、整份写回去"。整份写回去会把 extends 和 [keep] 一起
    抹掉，定制版就退化成一份和基底一模一样的全量拷贝——而且不报错，下次改基底时
    才发现这一份没跟着变。宁可在这里停下。
    """
    if "extends" not in existing:
        return
    raise SystemExit(
        f"{path.name} 是定制版（extends = \"{existing['extends']}\"）。\n"
        "交互填空会把整份重写，extends 和 [keep] 会被抹掉，它就变成一份全量拷贝了。\n\n"
        f"定制版通常只有十几行，直接编辑：$EDITOR {path.name}\n"
        f"想看它合并后还缺什么：python fill.py --check --out {path.name}"
    )


def write_out(path: Path, text: str, expected_revision: str | None = None) -> None:
    backup, _ = content_io.save_content(path, text, expected_revision)
    if backup:
        print(dim(f"旧文件已备份到 {backup.name}"))


def report_blanks(content: dict) -> int:
    blanks = schema.find_blanks(content)
    if not blanks:
        print(green("✓ 没有空着的必填项"))
        return 0
    print(red(f"✗ 还有 {len(blanks)} 处空白没填："))
    for line in blanks:
        print(f"  {line}")
    return 1


# ---------- 命令行 ----------

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="填空式地生成一页简历的内容文件。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="填完跑 python render.py 出 PDF。",
    )
    parser.add_argument("--out", metavar="PATH", default=str(DEFAULT_OUT),
                        help="写到哪，默认 content.toml（已在 .gitignore 里）。"
                             "写成 - 就打到标准输出，方便接管道。")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--blank", action="store_true",
                        help="不提问，直接输出一份空白表单，自己在编辑器里填。")
    parser.add_argument("--sample", action="store_true",
                        help="配合 --blank：把示例答案填进去，用来先看版面。")
    mode.add_argument("--check", action="store_true",
                        help="只检查 --out 指的那个文件还有哪些空没填。")
    args = parser.parse_args(argv)
    if args.sample and not args.blank:
        parser.error("--sample 必须与 --blank 一起使用。")
    if args.out == "-" and not args.blank:
        parser.error("--out - 只适用于 --blank，交互提示不能混入 TOML 标准输出。")
    return args


def run(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    out_path = Path(args.out).expanduser().resolve()

    if args.blank:
        text = schema.blank_form(sample=args.sample)
        if args.out == "-":          # 想接管道就写 --out -
            sys.stdout.write(text)
            return 0
        # 先自己挡一道：走 write_out 的版本检查虽然也拒绝覆盖，但报出来的是
        # "请重新读取后再保存"——空白表单没有东西可读，那句话在这里是误导。
        if out_path.exists():
            print(red(f"{out_path} 已存在。--blank 只用来新建空白表单，不会覆盖已有内容。"))
            print(dim("换个 --out 名字，或直接编辑现有文件。"))
            return 1
        write_out(out_path, text)
        print(green(f"空白表单已写到 {out_path}"))
        print(dim("在编辑器里把每个空填上，然后跑：python render.py"))
        return 0

    if args.check:
        if not out_path.exists():
            print(red(f"{out_path} 不存在。先跑 python fill.py 填一份。"))
            return 1
        # 定制版要检查的是"合并之后"还缺什么：它自己那十几行当然到处都是空的，
        # 那些空是由被继承的那份填上的。
        #
        return report_blanks(content_io.load_content(out_path))

    # 先看这一份是不是定制版，再看有没有终端：定制版不能整份重写这件事，
    # 跟当前有没有终端无关，报错该说真正的原因。
    existing, revision = content_io.read_snapshot(out_path) if out_path.exists() else ({}, None)
    refuse_derived(out_path, existing)
    schema.validate_types(existing)

    if not sys.stdin.isatty():
        print(red("交互填空需要终端。非交互场景请用 --blank 生成表单再编辑。"))
        return 1

    print(bold("一页简历 · 填空"))
    print(dim("  每题回车 = 跳过或保留当前值；Ctrl-C 随时退出，不会写半份文件。"))
    if existing:
        print(dim(f"  已读到 {out_path.name}，下面每题都会显示当前值。"))

    try:
        content = collect(existing)
    except Abort:
        print("\n" + dim("已退出，没有改动任何文件。"))
        return 130

    write_out(out_path, dump_toml(content), revision)
    print()
    print(green(f"✓ 内容已写到 {out_path}"))
    if report_blanks(content):
        print(dim("  再跑一次 python fill.py 可以把空补上。"))
    print(dim("  下一步：python render.py（或 make render）"))
    return 0


def main(argv: list[str] | None = None) -> int:
    try:
        return run(argv)
    except (ValueError, OSError) as error:
        print(red(f"错误：{error}"), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
