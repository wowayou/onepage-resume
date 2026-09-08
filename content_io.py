"""CLI 与浏览器共用的内容读取、继承和原子保存；不依赖排版引擎。"""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
import tomllib
from pathlib import Path

import schema


class ConflictError(ValueError):
    """目标文件已改变，必须重新读取后再保存。"""


def revision(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def read_snapshot(path: Path) -> tuple[dict, str]:
    raw = path.read_bytes()
    try:
        content = tomllib.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeError) as error:
        raise ValueError(f"{path.name} 不是合法的 UTF-8 TOML：{error}") from error
    return content, revision(raw)


def load_toml(path: Path) -> dict:
    return read_snapshot(path)[0]


def plain_name(name: str) -> str:
    if (not isinstance(name, str) or not name or name != name.strip()
            or name.startswith(".") or name.endswith(".")
            or re.search(r'[\\/<>:"|?*\x00-\x1f\x7f]', name)):
        raise ValueError(f"文件名不合法：{name!r}")
    if len(name.encode("utf-8")) > 240:
        raise ValueError("文件名过长，请缩短到 240 个 UTF-8 字节以内。")
    stem = name.split(".", 1)[0].upper()
    if stem in {"CON", "PRN", "AUX", "NUL"} or re.fullmatch(r"(?:COM|LPT)[1-9]", stem):
        raise ValueError(f"文件名是 Windows 保留名称：{name!r}")
    return name


def safe_name(name: str, pattern: str, base: Path) -> Path:
    plain_name(name)
    if not Path(name).match(pattern):
        raise ValueError(f"只接受匹配 {pattern} 的文件：{name!r}")
    base = base.resolve()
    path = base / name
    if path.is_symlink() or path.resolve().parent != base:
        raise ValueError(f"路径越界或是符号链接：{name!r}")
    return path


def _load(path: Path, kind: str, seen: tuple[Path, ...],
          allowed_dir: Path | None) -> dict:
    path = path.expanduser().resolve()
    if allowed_dir is not None:
        if path.parent != allowed_dir.resolve():
            raise ValueError(f"{kind}继承路径越界：{path.name}")
        safe_name(path.name, "content*.toml" if kind == "内容文件" else "theme*.toml",
                  allowed_dir)
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
        parent_path = safe_name(parent_name,
                                "content*.toml" if kind == "内容文件" else "theme*.toml",
                                allowed_dir)
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
    return _load(path, "主题", seen, allowed_dir)


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


def save_content(path: Path, text: str, expected_revision: str | None) -> tuple[Path | None, str]:
    """校验读写版本并备份，再原子替换内容文件。调用方串行化同一目录的保存。"""
    raw = text.encode("utf-8")
    schema.validate_types(tomllib.loads(text))
    if path.is_symlink():
        raise ValueError(f"拒绝写入符号链接：{path.name}")
    previous = path.read_bytes() if path.exists() else None
    current_revision = revision(previous) if previous is not None else None
    if current_revision != expected_revision:
        raise ConflictError(f"{path.name} 已存在或已被其他窗口修改，请重新读取后再保存。")
    backup = None
    if previous is not None:
        existing = tomllib.loads(previous.decode("utf-8"))
        if "extends" in existing or "keep" in existing:
            raise ValueError(f"{path.name} 是定制版，不能整份重写；请直接编辑该文件。")
        schema.validate_types(existing)
        backup = path.with_suffix(path.suffix + ".bak")
        atomic_write(backup, previous)
    atomic_write(path, raw)
    return backup, revision(raw)
