"""CLI 与浏览器共用的内容读取、继承和原子保存；不依赖排版引擎。"""

from __future__ import annotations

import hashlib
import os
import re
import sys
import tempfile
import tomllib
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import schema


class ConflictError(ValueError):
    """目标文件已改变，必须重新读取后再保存。"""


class ExistsError(ConflictError):
    """目标已存在，而调用方以为在新建（另存为撞名）。"""


class ModifiedError(ConflictError):
    """文件在读取之后被改过（别人改了同一个文件）。"""


class VariantError(ValueError):
    """定制版（写了 extends）不能被整份重写。

    单独一个类型是为了让网页能把它映射成 403 并说清原因，而不是笼统的 400——
    用户看到"不能整份重写、请直接编辑"才知道下一步该干什么。
    """


class InvalidNameError(ValueError):
    """文件名不合法：带路径分隔符、是 Windows 保留名、过长等。"""


# 内容文件与版式文件的文件名规则。CLI 的继承闸门与网页的文件闸门共用这一份，
# 只改一处就能同时放开或收紧两边。
CONTENT_GLOB = "content*.toml"
THEME_GLOB = "theme*.toml"

# 默认的内容文件名。fill.py 的输出默认值、网页新建表单的默认名、render.py 的查找
# 顺序都引用它，改一处就够。
DEFAULT_CONTENT_NAME = "content.toml"

# 覆盖前留的那一份去哪。目录名前面有个点，和 .gitignore 里那条一起挡住误提交。
HISTORY_DIR = ".history"
HISTORY_KEEP = 30

# 快照文件名：UTC 时间戳 + 旧内容的版本号前 8 位。这个正则同时是读取时的闸门——
# 它不含斜杠，也不含除结尾 .toml 之外的点，所以拼不出目录穿越。
SNAPSHOT_NAME = re.compile(r"^\d{8}T\d{6}Z-[0-9a-f]{8}\.toml$")


@dataclass(frozen=True)
class SaveResult:
    """一次保存的结果。unchanged 表示内容与磁盘上一模一样，什么都没写。"""
    path: Path
    revision: str
    snapshot: Path | None
    unchanged: bool


def revision(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def parse_content(raw: bytes, source: str = "内容") -> dict:
    """把内容字节解成表。坏 TOML 明确报错，不静默当成空表。

    这里只解析、不校验字段表：继承链上每一层都可能是"只写了要改的那几项"的
    半份文件（还有 extends / keep 这种不属于字段表的键），校验得等合并之后。
    """
    try:
        return tomllib.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeError) as error:
        raise ValueError(f"{source} 不是合法的 UTF-8 TOML：{error}") from error


def read_snapshot(path: Path) -> tuple[dict, str]:
    raw = path.read_bytes()
    return parse_content(raw, path.name), revision(raw)


def load_toml(path: Path) -> dict:
    return read_snapshot(path)[0]


def plain_name(name: str) -> str:
    if (not isinstance(name, str) or not name or name != name.strip()
            or name.startswith(".") or name.endswith(".")
            or re.search(r'[\\/<>:"|?*\x00-\x1f\x7f]', name)):
        raise InvalidNameError(f"文件名不合法：{name!r}")
    if len(name.encode("utf-8")) > 240:
        raise InvalidNameError("文件名过长，请缩短到 240 个 UTF-8 字节以内。")
    stem = name.split(".", 1)[0].upper()
    if stem in {"CON", "PRN", "AUX", "NUL"} or re.fullmatch(r"(?:COM|LPT)[1-9]", stem):
        raise InvalidNameError(f"文件名是 Windows 保留名称：{name!r}")
    return name


def safe_name(name: str, pattern: str, base: Path) -> Path:
    plain_name(name)
    if not Path(name).match(pattern):
        raise InvalidNameError(f"只接受匹配 {pattern} 的文件：{name!r}")
    base = base.resolve()
    path = base / name
    if path.is_symlink() or path.resolve().parent != base:
        raise InvalidNameError(f"路径越界或是符号链接：{name!r}")
    return path


def _load(path: Path, kind: str, seen: tuple[Path, ...],
          allowed_dir: Path | None) -> dict:
    pattern = CONTENT_GLOB if kind == "内容文件" else THEME_GLOB
    path = path.expanduser().resolve()
    if allowed_dir is not None:
        if path.parent != allowed_dir.resolve():
            raise ValueError(f"{kind}继承路径越界：{path.name}")
        safe_name(path.name, pattern, allowed_dir)
    if path in seen:
        chain = " → ".join(item.name for item in (*seen, path))
        raise ValueError(f"{kind}继承成环了：{chain}")
    if len(seen) >= 32:
        raise ValueError(f"{kind}继承层数超过 32 层。")
    if not path.is_file():
        raise ValueError(f"{kind}不存在：{path.name}")

    data = load_toml(path)
    has_parent = "extends" in data
    parent_name = data.pop("extends", None)
    keep = data.pop("keep", None) if kind == "内容文件" else None
    if has_parent and (not isinstance(parent_name, str) or not parent_name.strip()):
        raise ValueError(f"{path.name} 的 extends 必须是非空文件名字符串。")
    if keep is not None and not isinstance(keep, dict):
        raise ValueError(f"{path.name} 的 [keep] 必须是表。")
    if kind == "内容文件":
        schema.validate_types(data)
    if not has_parent:
        if keep is not None:
            raise ValueError(f"{path.name} 写了 [keep] 但没有 extends。")
        return data

    if allowed_dir is not None:
        parent_path = safe_name(parent_name, pattern, allowed_dir)
    else:
        parent_path = path.parent / parent_name
    merged = _load(parent_path, kind, (*seen, path), allowed_dir)
    if keep is not None:
        merged = apply_keep(merged, keep, path)
    for key, value in data.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = {**merged[key], **value}
        else:
            merged[key] = value
    return merged


def load_content(path: Path, seen: tuple[Path, ...] = (), *,
                 allowed_dir: Path | None = None) -> dict:
    return _load(path, "内容文件", seen, allowed_dir)


def load_theme(path: Path, seen: tuple[Path, ...] = (), *,
               allowed_dir: Path | None = None) -> dict:
    return _load(path, "版式", seen, allowed_dir)


def apply_keep(content: dict, keep: dict, source: Path) -> dict:
    blocks = {block.key: block for block in schema.BLOCKS if block.repeat}
    result = dict(content)
    for block_key, wanted in keep.items():
        block = blocks.get(block_key)
        if block is None:
            raise ValueError(f"{source.name} 的 [keep] 不支持 {block_key}；"
                             f"可选：{' / '.join(sorted(blocks))}")
        if not isinstance(wanted, list) or not all(isinstance(name, str) for name in wanted):
            raise ValueError(f"{source.name} 的 [keep] {block_key} 必须是字符串数组。")
        if len(wanted) != len(set(wanted)):
            raise ValueError(f"{source.name} 的 [keep] {block_key} 有重复条目。")
        index: dict[str, dict] = {}
        for row in content.get(block_key, []):
            name = row.get(block.identity, "")
            if not name.strip() or name in index:
                raise ValueError(f"{source.name} 的基底 {block_key}.{block.identity} "
                                 "为空或重复，无法唯一挑选。")
            index[name] = row
        missing = [name for name in wanted if name not in index]
        if missing:
            raise ValueError(f"{source.name} 的 [keep] {block_key} 里写了 "
                             f"{' / '.join(missing)}，但基底没有这一条。\n"
                             f"可选：{' / '.join(index) or '（空）'}")
        result[block_key] = [index[name] for name in wanted]
    return result


def history_dir(path: Path) -> Path:
    """某个内容文件自己的历史目录。按文件分开放，同名时间戳才不会互相顶掉。"""
    return path.parent / HISTORY_DIR / path.name


def snapshot_files(path: Path) -> list[Path]:
    """这个文件已有的快照，按名字（也就是按时间）从旧到新。"""
    try:
        entries = list(history_dir(path).iterdir())
    except OSError:
        return []
    return sorted(
        (item for item in entries if item.is_file() and SNAPSHOT_NAME.match(item.name)),
        key=lambda item: item.name,
    )


def list_history(path: Path) -> list[dict]:
    """给网页的历史版本列表用。新的排在前面。"""
    out = []
    for snapshot in snapshot_files(path):
        try:
            stat = snapshot.stat()
        except OSError:
            continue
        out.append({"id": snapshot.name, "size": stat.st_size, "time": stat.st_mtime})
    return list(reversed(out))


def read_history(path: Path, snapshot_id: str) -> bytes:
    """读一份快照。id 必须是快照名的形状，也只能落在该文件自己的历史目录里。"""
    if not isinstance(snapshot_id, str) or not SNAPSHOT_NAME.match(snapshot_id):
        raise InvalidNameError(f"快照编号不合法：{snapshot_id!r}")
    target = history_dir(path) / snapshot_id
    if not target.is_file():
        raise FileNotFoundError(f"没有这份历史版本：{snapshot_id}")
    return target.read_bytes()


def _write_snapshot(path: Path, previous: bytes, moment: datetime) -> Path:
    directory = history_dir(path)
    # .history 被人换成符号链接的话，快照就会写到链接指向的地方去。同样的道理，
    # 主文件那边也有这一道（atomic_write）。宁可这次保存失败。
    if directory.is_symlink():
        raise ValueError(f"拒绝写入符号链接：{directory.name}")
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    # mkdir 的 mode 会被 umask 削掉，而且 parents=True 建出来的中间目录根本不吃它，
    # 所以从 .history 到自己这一层都显式钉一遍：和主文件一样只给当前用户。
    os.chmod(directory.parent, 0o700)
    os.chmod(directory, 0o700)
    target = directory / f"{moment.strftime('%Y%m%dT%H%M%SZ')}-{revision(previous)[:8]}.toml"
    if not target.exists():         # 同一秒里存两次相同的内容，不必写两遍
        atomic_write(target, previous)
    return target


def prune_history(path: Path, keep: int = HISTORY_KEEP) -> list[Path]:
    """只留最近 keep 份。删不掉就警告——该删的是旧快照，不该拖累这一次保存。"""
    snapshots = snapshot_files(path)
    removed = []
    for stale in snapshots[:max(0, len(snapshots) - keep)]:
        try:
            stale.unlink()
            removed.append(stale)
        except OSError as error:
            print(f"警告：删不掉旧快照 {stale.name}：{error}", file=sys.stderr)
    return removed


def normalize_content_name(raw: str) -> str:
    """把用户随手写的一个名字收成规范的内容文件名。

        acme            -> content.acme.toml
        acme.toml       -> content.acme.toml
        content.acme    -> content.acme.toml
        content         -> content.toml

    收完仍要过 plain_name 与 content*.toml 两道闸门，所以路径分隔符、Windows 保留
    名、过长的名字照样被挡在外面。网页不自己算这个名字，一律问服务端。
    """
    if not isinstance(raw, str):
        raise InvalidNameError(f"文件名不合法：{raw!r}")
    name = unicodedata.normalize("NFC", raw).strip()
    if not name:
        raise InvalidNameError("文件名不能为空。")
    if name.lower().endswith(".toml"):
        name = name[: -len(".toml")]
    lowered = name.casefold()
    if lowered == "content":
        return DEFAULT_CONTENT_NAME
    if lowered.startswith("content."):
        # 前缀不分大小写，"Content.Acme" 与 "content.acme" 收成同一个名字；
        # 后面的部分保留原样，别把用户想要的写法改掉。
        name = name[len("content."):]
    if not name or not name.strip("."):
        # ".." 会变成 content....toml：虽然能过闸门，但显然是手滑，别照样收下
        raise InvalidNameError(f"文件名不合法：{raw!r}")
    result = plain_name(f"content.{name}.toml")
    if not Path(result).match(CONTENT_GLOB):
        raise InvalidNameError(f"文件名不合法：{raw!r}")
    return result


def content_exists(base: Path, name: str) -> Path | None:
    """按大小写不敏感找同名文件。

    Windows / macOS 的文件系统不分大小写，在那边 content.Acme.toml 与
    content.acme.toml 是同一个文件。判断"已存在"时必须跟它们一致，
    否则在 Windows 上会把覆盖当成新建。
    """
    wanted = name.casefold()
    for candidate in sorted(base.glob(CONTENT_GLOB)):
        if candidate.name.casefold() != wanted or not candidate.is_file():
            continue
        try:
            safe_name(candidate.name, CONTENT_GLOB, base)
        except ValueError:
            continue        # 符号链接之类，不当作"已存在"
        return candidate
    return None


def _parse(previous: bytes | None) -> dict | None:
    """把已有内容解出来；读不动（坏 TOML）就当没有，交给调用方按版本判断处理。"""
    if previous is None:
        return None
    try:
        return tomllib.loads(previous.decode("utf-8"))
    except (ValueError, UnicodeError):
        return None


def atomic_write(path: Path, raw: bytes) -> None:
    """同目录暂存后替换，写入失败不会留下半份文件，也不会跟随目标符号链接。"""
    if path.is_symlink():
        raise ValueError(f"拒绝写入符号链接：{path.name}")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    staged = Path(temporary)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        staged.replace(path)
    finally:
        staged.unlink(missing_ok=True)


def save_content(path: Path, text: str, expected_revision: str | None, *,
                 mode: str | None = None,
                 moment: datetime | None = None) -> SaveResult:
    """校验、留快照，再原子替换内容文件。调用方串行化同一目录的保存。

    mode 三种：
        create     目标必须还不存在（"另存为"到一个新名字）
        update     目标必须存在，且版本与读取时一致（"保存"）
        overwrite  不看版本，直接覆盖（用户在对话框里确认过"覆盖"）
                   即便如此，定制版仍然拒绝
    mode=None 时按 expected_revision 推断，老调用方的行为因此不变。

    覆盖前先把旧内容写进 .history/。返回值里带着快照路径和"内容没变、没写盘"
    的标记，好让调用方把话说准。
    """
    raw = text.encode("utf-8")
    schema.validate_types(tomllib.loads(text))
    if path.is_symlink():
        raise InvalidNameError(f"拒绝写入符号链接：{path.name}")
    if mode is None:
        mode = "update" if expected_revision is not None else "create"
    if mode not in ("create", "update", "overwrite"):
        raise ValueError(f"未知的保存方式：{mode!r}")

    previous = path.read_bytes() if path.exists() else None
    existing = _parse(previous)

    # 定制版永远不许整份重写。这比"文件已存在"更具体，所以先判它——
    # 否则用户看到的会是"已存在，换个名字"，而他真正该做的是直接编辑那个文件。
    if existing is not None and ("extends" in existing or "keep" in existing):
        inherited = existing.get("extends")
        detail = f"继承 {inherited}" if inherited else "写了 [keep]"
        raise VariantError(
            f"{path.name} 是定制版（{detail}），不能整份重写；请直接编辑该文件。")

    current_revision = revision(previous) if previous is not None else None
    if mode == "create":
        if previous is not None:
            raise ExistsError(f"{path.name} 已存在，换个名字或选择覆盖。")
    elif mode == "update":
        if previous is None:
            raise ModifiedError(
                f"{path.name} 不在了（可能被删掉或改了名），请重新读取后再保存。")
        if current_revision != expected_revision:
            raise ModifiedError(
                f"{path.name} 在你读取之后被改过（可能是另一个窗口或编辑器），"
                f"请重新读取后再保存。"
            )
    # overwrite：不看版本，直接往下走

    if previous is not None and previous == raw:
        return SaveResult(path, current_revision, None, True)   # 内容没变，不写盘

    snapshot = None
    if previous is not None:
        if existing is not None:
            schema.validate_types(existing)
        try:
            snapshot = _write_snapshot(path, previous, moment or datetime.now(timezone.utc))
        except (OSError, ValueError) as error:
            # 快照写不进去就别动主文件：宁可这次保存失败，也不能让上一版没处找。
            raise ValueError(
                f"写不了历史快照（{history_dir(path)}）：{error}。内容文件没有改动。"
            ) from error
        prune_history(path)

    atomic_write(path, raw)
    return SaveResult(path, revision(raw), snapshot, False)
