"""浏览器里的填空表单：左边填字，右边看着 A4 纸实时变。

    python webui.py                     # 打开 http://127.0.0.1:8765
    python webui.py --port 9000
    python webui.py --content-dir ~/.private/resume    # 真实内容放仓库外

它和 fill.py 是同一件事的两种界面，共用同一套底座：

    schema.py   字段表。网页表单是照着它长出来的，不在这里重复定义字段
    fill.py     dump_toml()，写出去的 TOML 与命令行填的一模一样
    render.py   排版与生成物。预览、出 PDF 都走它，不另写一套

所以两种界面可以来回换：命令行填一半，网页里接着改，再回命令行都认。

── 这个服务的安全边界（先读这段）──────────────────────────────

1. **默认只听 127.0.0.1**，同一台机器之外连不进来。
2. **没有登录、没有口令**——门禁就是第 1 条。所以 `--host 0.0.0.0` 等于把你的
   姓名手机邮箱敞开给整个局域网，程序会为此打印一条显眼的警告。除非你清楚
   自己在做什么（比如只在受控内网里、或者外面还套了一层反向代理和认证），
   否则别加这个参数。
3. **能读写的文件被夹死在两处**：内容目录下匹配 `content*.toml` 的文件，
   以及生成物目录下的 .pdf / .html / .png。路径里带 `..` 或分隔符一律拒绝。
   `content*.toml` 正是 .gitignore 挡住的那一批，网页能碰的文件天然不进 Git。
4. **拒绝写 content.example.toml**——那是仓库里跟踪的虚构示例，真实内容写进去
   就等着被提交了。
5. **校验 Host 头**，防的是 DNS 重绑定：别的网站把域名解析到 127.0.0.1，
   借你的浏览器来调这个接口读你的简历。
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import tomllib
import urllib.parse
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import fill
import render
import schema

HERE = Path(__file__).resolve().parent
WEB_DIR = HERE / "webui"

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765

# 网页能读写的内容文件：与 .gitignore 的 content*.toml 同一批。
CONTENT_GLOB = "content*.toml"
THEME_GLOB = "theme*.toml"
# 仓库里跟踪的虚构示例：可以读进来看版面，不许写回去。
PROTECTED_CONTENT = {render.EXAMPLE_CONTENT}

STATIC_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
}
ARTIFACT_TYPES = {
    ".pdf": "application/pdf",
    ".html": "text/html; charset=utf-8",
    ".png": "image/png",
}

MAX_BODY = 1 << 20          # 1 MiB。一页简历的 JSON 离这个上限很远
PREVIEW_LOCK = threading.Lock()   # WeasyPrint 不保证线程安全，渲染串起来做


# ---------- 表单 JSON ←→ 内容文件 ----------

def _value(field: schema.Field, raw: object) -> object:
    """把表单交上来的一个值收成字段表要求的形状。"""
    if field.kind in ("list", "lines"):
        if isinstance(raw, list):
            return [str(x).strip() for x in raw if str(x).strip()]
        if raw in (None, ""):
            return []
        return [str(raw).strip()]
    return "" if raw is None else str(raw)


def shape(payload: dict) -> dict:
    """按字段表把表单 JSON 收成内容文件的结构。

    只补形状（缺的表、缺的键），不替用户编内容：空着的就是空着，
    这样 schema.find_blanks() 和 render.py 才能照旧把空白逐条报出来。
    """
    content: dict = {}
    for block in schema.BLOCKS:
        given = payload.get(block.key)

        if block.section_key:
            title = ((payload.get(block.section_key) or {}).get("title") or "").strip()
            content[block.section_key] = {"title": title or block.section_default}

        if not block.repeat:
            table = given if isinstance(given, dict) else {}
            content[block.key] = {
                f.key: _value(f, table.get(f.key)) for f in block.fields
            }
            continue

        rows = given if isinstance(given, list) else []
        content[block.key] = [
            {f.key: _value(f, (row or {}).get(f.key)) for f in block.fields}
            for row in rows
            if isinstance(row, dict)
        ]

    # status 不是版面上的字段（fill.py 也只是原样写回），但要保住读进来的那个值，
    # 免得把 content.example.toml 的 "example" 在网页里存成 "real"。
    given_doc = payload.get("document")
    if isinstance(given_doc, dict) and given_doc.get("status"):
        content["document"]["status"] = str(given_doc["status"])
    return content


def for_preview(content: dict) -> dict:
    """预览专用：给空的数组表塞一条空行，好让区块的骨架也画出来。

    只用于渲染，不写盘——写盘走 shape() 的原样，空就是空。
    """
    preview = json.loads(json.dumps(content))       # 深拷贝，别动调用方的 dict
    for block in schema.BLOCKS:
        if block.repeat and not preview.get(block.key):
            preview[block.key] = [
                {f.key: ([] if f.kind in ("list", "lines") else "")
                 for f in block.fields}
            ]
    # 要投出去的那一份页脚是空的，预览就照这个来：所见即所得。
    preview["document"].setdefault("preview_note", "")
    preview["document"].setdefault("edition", "")
    return preview


# ---------- 路径闸门 ----------

def safe_name(name: str, pattern: str, base: Path) -> Path:
    """把用户给的文件名收成 base 下的一个确切路径，越界就拒绝。

    只收纯文件名：带 / 、带 .. 、带盘符的一律挡掉，再用 glob 卡一次白名单，
    最后比对 resolve() 之后的父目录——符号链接也绕不过去。
    """
    if not name or name != Path(name).name or name.startswith("."):
        raise ValueError(f"文件名不合法：{name!r}")
    if not Path(name).match(pattern):
        raise ValueError(f"只接受匹配 {pattern} 的文件：{name!r}")
    path = (base / name).resolve()
    if path.parent != base.resolve():
        raise ValueError(f"路径越界：{name!r}")
    return path


def safe_basename(name: str) -> str:
    """生成物的文件名主干。中文照常，但不许出现路径分隔符和前导点。"""
    cleaned = re.sub(r"[\\/\x00-\x1f]", "", str(name)).strip().lstrip(".")
    return cleaned[:120] or "resume"


def listing(base: Path, pattern: str) -> list[str]:
    return sorted(p.name for p in base.glob(pattern) if p.is_file())


# ---------- 渲染 ----------

class Studio:
    """一次会话用到的目录与版式，外加预览 / 生成两件事。"""

    def __init__(self, content_dir: Path, out_dir: Path, css_path: Path):
        self.content_dir = content_dir
        self.out_dir = out_dir
        self.css_path = css_path

    def theme(self, name: str | None) -> dict:
        path = safe_name(name or render.DEFAULT_THEME.name, THEME_GLOB, HERE)
        if not path.exists():
            raise ValueError(f"版式文件不存在：{path.name}")
        return render.load_theme(path)

    def preview(self, content: dict, theme_name: str | None) -> tuple[str, int]:
        """返回预览用的 HTML 和它实际占的页数。

        页数是这个工具的核心承诺（超一页就拒绝生成），所以预览阶段就把它算出来
        摆在眼前——不能等到点"生成 PDF"才发现超了。
        """
        theme = self.theme(theme_name)
        stylesheet = render.build_stylesheet(theme, self.css_path)
        markup = render.ResumeBuilder(for_preview(content), theme, stylesheet).render_html()
        with PREVIEW_LOCK:
            pages = len(render.HTML(string=markup, base_url=str(HERE)).render().pages)
        return markup, pages

    def build(self, content: dict, theme_name: str | None, basename: str) -> dict:
        theme = self.theme(theme_name)
        stylesheet = render.build_stylesheet(theme, self.css_path)
        with PREVIEW_LOCK:
            outputs = render.write_outputs(
                content, theme, stylesheet, self.out_dir, basename
            )
        return {
            "out_dir": str(self.out_dir),
            "files": {
                kind: (path.name if path else None) for kind, path in outputs.items()
            },
        }


# ---------- HTTP ----------

class Handler(BaseHTTPRequestHandler):
    server_version = "onepage-resume-webui"
    studio: Studio
    bind_host: str

    # 预览是防抖后连着来的，每条都打一行日志会把真正的错误埋掉。
    def log_message(self, fmt: str, *args) -> None:
        pass

    def log_error(self, fmt: str, *args) -> None:
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    # ---- 安全 ----

    def allowed_host(self) -> bool:
        """校验 Host 头，防 DNS 重绑定。

        只听回环时才有意义：这时候合法的 Host 只可能是 localhost 或回环 IP。
        换成 --host 0.0.0.0 就没法这么判了（人家用什么域名进来都对），
        那种场景的门禁本来也不该由这一层负责。
        """
        try:
            if not ipaddress.ip_address(self.bind_host).is_loopback:
                return True
        except ValueError:
            return True                      # 主机名形式的绑定，交给上层去管

        raw = self.headers.get("Host", "")
        host = raw.rsplit(":", 1)[0] if raw.count(":") == 1 else raw
        if host.startswith("["):             # IPv6 字面量：[::1]:8765
            host = host[1:host.find("]")] if "]" in host else host[1:]
        if host in ("localhost", ""):
            return True
        try:
            return ipaddress.ip_address(host).is_loopback
        except ValueError:
            return False

    # ---- 回应 ----

    def send_bytes(self, body: bytes, content_type: str,
                   status: HTTPStatus = HTTPStatus.OK,
                   download: str | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        # 简历内容不该留在磁盘缓存里，也不该被 MIME 嗅探或带着 Referer 出门。
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        if download:
            self.send_header("Content-Disposition", disposition(download))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def send_json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_bytes(body, "application/json; charset=utf-8", status)

    def fail(self, status: HTTPStatus, message: str) -> None:
        self.send_json({"error": message}, status)

    def body_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            raise ValueError("请求体是空的。")
        if length > MAX_BODY:
            raise ValueError("请求体过大。")
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("请求体应该是一个 JSON 对象。")
        return payload

    # ---- 路由 ----

    def do_GET(self) -> None:
        self.route()

    def do_HEAD(self) -> None:
        self.route()

    def do_POST(self) -> None:
        self.route()

    def route(self) -> None:
        if not self.allowed_host():
            self.fail(HTTPStatus.MISDIRECTED_REQUEST, "Host 头不被接受。")
            return

        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        try:
            if self.command in ("GET", "HEAD"):
                if path in ("/", "/index.html"):
                    self.static("index.html")
                elif path == "/api/bootstrap":
                    self.bootstrap()
                elif path == "/api/content":
                    self.read_content(query)
                elif path == "/api/artifact":
                    self.artifact(query)
                elif path.startswith("/static/"):
                    self.static(path[len("/static/"):])
                else:
                    self.fail(HTTPStatus.NOT_FOUND, "没有这个地址。")
                return

            if path == "/api/preview":
                self.do_preview()
            elif path == "/api/save":
                self.do_save()
            elif path == "/api/render":
                self.do_render()
            else:
                self.fail(HTTPStatus.NOT_FOUND, "没有这个地址。")
        except ValueError as error:                     # 含 JSON / TOML 解析失败
            self.fail(HTTPStatus.BAD_REQUEST, str(error))
        except FileNotFoundError as error:
            self.fail(HTTPStatus.NOT_FOUND, str(error))
        except Exception as error:                      # noqa: BLE001 - 兜底成 JSON
            self.log_error("%s %s 出错：%r", self.command, path, error)
            self.fail(HTTPStatus.INTERNAL_SERVER_ERROR, f"{type(error).__name__}: {error}")

    # ---- 各个接口 ----

    def static(self, name: str) -> None:
        path = (WEB_DIR / name).resolve()
        if path.parent != WEB_DIR.resolve() or not path.is_file():
            raise FileNotFoundError(f"静态文件不存在：{name}")
        if path.suffix not in STATIC_TYPES:
            raise FileNotFoundError(f"不提供这种文件：{name}")
        self.send_bytes(path.read_bytes(), STATIC_TYPES[path.suffix])

    def bootstrap(self) -> None:
        """网页启动时要的一切：字段表、可选的内容文件与版式、目录位置。"""
        studio = self.studio
        files = listing(studio.content_dir, CONTENT_GLOB)
        default = next(
            (name for name in render.CONTENT_CANDIDATES if name in files),
            files[0] if files else None,
        )
        self.send_json({
            "blocks": schema.describe(),
            "contents": files,
            "protected": sorted(PROTECTED_CONTENT),
            "default_content": default,
            "themes": listing(HERE, THEME_GLOB),
            "default_theme": render.DEFAULT_THEME.name,
            "content_dir": str(studio.content_dir),
            "out_dir": str(studio.out_dir),
            "png": shutil.which("pdftoppm") is not None,
        })

    def read_content(self, query: dict) -> None:
        name = (query.get("name") or [""])[0]
        path = safe_name(name, CONTENT_GLOB, self.studio.content_dir)
        if not path.is_file():
            raise FileNotFoundError(f"内容文件不存在：{path.name}")

        with path.open("rb") as stream:
            raw = tomllib.load(stream)             # 坏 TOML → ValueError → 400

        # 定制版（写了 extends）：显示合并后的样子，但不给存。
        # 存盘是整份重写，会把 extends 和 [keep] 抹平成全量拷贝，而且不报错——
        # 下次改基底时才发现这一份没跟着变。所以只读，改它请直接编辑那十几行。
        derives_from = raw.get("extends")
        content = render.load_content(path) if derives_from else raw

        self.send_json({
            "name": path.name,
            "content": shape(content),
            "blanks": schema.find_blanks(content),
            "writable": path.name not in PROTECTED_CONTENT and not derives_from,
            "extends": derives_from,
        })

    def artifact(self, query: dict) -> None:
        name = (query.get("name") or [""])[0]
        if not name or name != Path(name).name or name.startswith("."):
            raise ValueError(f"文件名不合法：{name!r}")
        suffix = Path(name).suffix
        if suffix not in ARTIFACT_TYPES:
            raise ValueError(f"只提供 {' / '.join(ARTIFACT_TYPES)}：{name!r}")
        path = (self.studio.out_dir / name).resolve()
        if path.parent != self.studio.out_dir.resolve() or not path.is_file():
            raise FileNotFoundError(f"生成物不存在：{name}")
        self.send_bytes(path.read_bytes(), ARTIFACT_TYPES[suffix], download=name)

    def do_preview(self) -> None:
        payload = self.body_json()
        content = shape(payload.get("content") or {})
        markup, pages = self.studio.preview(content, payload.get("theme"))
        self.send_json({
            "html": markup,
            "pages": pages,
            "blanks": schema.find_blanks(content),
        })

    def do_save(self) -> None:
        payload = self.body_json()
        name = payload.get("name") or "content.toml"
        path = safe_name(name, CONTENT_GLOB, self.studio.content_dir)
        if path.name in PROTECTED_CONTENT:
            raise ValueError(
                f"{path.name} 是仓库里跟踪的虚构示例，不能写。"
                "换个名字，比如 content.toml 或 content.acme.toml。"
            )

        if path.exists():
            with path.open("rb") as stream:
                if "extends" in tomllib.load(stream):
                    raise ValueError(
                        f"{path.name} 是定制版（有 extends），不能从网页存回去——"
                        "整份重写会把 extends 和 [keep] 抹掉，它就变成全量拷贝了。"
                        "改它请直接编辑那个文件；或者换个文件名另存一份。"
                    )

        content = shape(payload.get("content") or {})
        backup = None
        if path.exists():                   # 与 fill.py 一致：覆盖前留一份 .bak
            backup = path.with_suffix(path.suffix + ".bak")
            shutil.copy2(path, backup)
        path.write_text(fill.dump_toml(content), encoding="utf-8")
        self.send_json({
            "path": str(path),
            "name": path.name,
            "backup": backup.name if backup else None,
            "blanks": schema.find_blanks(content),
        })

    def do_render(self) -> None:
        payload = self.body_json()
        content = shape(payload.get("content") or {})
        blanks = schema.find_blanks(content)
        if blanks:
            # 和 render.py 同一个立场：宁可停下，也不出一份带空标题的 PDF——
            # 那种 PDF 看上去是"成功了"的，最容易就这么发出去。
            raise ValueError("还有 %d 处空白没填，先补齐：\n%s"
                             % (len(blanks), "\n".join(blanks)))

        basename = safe_basename(
            payload.get("basename")
            or content["document"].get("output_basename")
            or "resume"
        )
        try:
            result = self.studio.build(content, payload.get("theme"), basename)
        except RuntimeError as error:       # 超过一页
            self.fail(HTTPStatus.UNPROCESSABLE_ENTITY, str(error))
            return
        self.send_json(result)


def disposition(name: str) -> str:
    """Content-Disposition。HTTP 头只能放 latin-1，中文文件名走 RFC 5987。"""
    ascii_name = re.sub(r"[^\x20-\x7e]", "_", name).replace('"', "")
    quoted = urllib.parse.quote(name, safe="")
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quoted}"


# ---------- 启动 ----------

def _in_wsl() -> bool:
    """在 WSL 里跑？WSL_DISTRO_NAME 是 WSL2 一定会设的。"""
    if os.environ.get("WSL_DISTRO_NAME"):
        return True
    try:
        return "microsoft" in Path("/proc/version").read_text().lower()
    except OSError:
        return False


def _open_browser(url: str) -> bool:
    """打开浏览器，返回是否真的开成了。

    WSL 里不能用 webbrowser：它挑中 xdg-open，而 xdg-open 在没装 Linux 浏览器的
    发行版里会失败——但 webbrowser 不等子进程，照样返回 True。所以 WSL 下自己
    调 Windows 那边的浏览器，并且看退出码。
    """
    if _in_wsl():
        # wslview（wslu 包）是首选；没装就退到 interop 里一定在的 powershell.exe。
        if shutil.which("wslview"):
            if subprocess.run(["wslview", url], check=False,
                              capture_output=True).returncode == 0:
                return True
        if shutil.which("powershell.exe"):
            return subprocess.run(
                ["powershell.exe", "-NoProfile", "-Command", "Start-Process", url],
                check=False, capture_output=True,
            ).returncode == 0
        return False
    try:
        return webbrowser.open(url, new=2)
    except Exception:
        return False


def _open_soon(url: str, delay: float = 0.6) -> None:
    """服务一起来就开浏览器。放在线程里，开不开都不影响服务本身。"""
    time.sleep(delay)
    if _open_browser(url):
        print(f"已在浏览器里打开：{url}", flush=True)
    else:
        # 没开成不是错误，只是得自己点一下——把网址再说一遍，别让人去翻上面。
        print(f"没能自动打开浏览器，请手工访问：{url}", flush=True)


def serve(host: str, port: int, studio: Studio, open_browser: bool = True) -> None:
    handler = type("BoundHandler", (Handler,), {"studio": studio, "bind_host": host})
    server = ThreadingHTTPServer((host, port), handler)
    shown = f"[{host}]" if ":" in host else host
    url = f"http://{shown}:{port}"

    # flush：make ui 之类的场景 stdout 不是终端，缓冲会让这几行迟迟不出来，
    # 而用户正等着这个网址。
    print(f"填空表单：  {url}", flush=True)
    print(f"内容目录：  {studio.content_dir}")
    print(f"生成物：    {studio.out_dir}")
    try:
        is_loopback = ipaddress.ip_address(host).is_loopback
    except ValueError:
        is_loopback = False
    if not is_loopback:
        print()
        print("⚠️  警告：这个服务没有登录、没有口令，门禁就是「只听本机」。")
        print(f"   现在绑在 {host}，同一网络里的任何人都能读到你的姓名、手机、"
              "邮箱，也能写你的内容文件。")
        print("   除非外面另有一层认证，请改回默认的 127.0.0.1。")
    print()
    # 只在本机回环地址上自动开浏览器；改成 --no-open 关掉（比如远程/无桌面环境）。
    # 开成没开成由 _open_soon 自己报——它知道结果，这里还不知道。
    if open_browser and is_loopback:
        threading.Thread(target=_open_soon, args=(url,), daemon=True).start()
    print("Ctrl-C 停止。", flush=True)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
    finally:
        server.server_close()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="在浏览器里填这份一页简历：左边填字，右边实时看 A4 效果。",
    )
    parser.add_argument("--host", default=DEFAULT_HOST,
                        help=f"绑定地址，默认 {DEFAULT_HOST}（只有本机能连）。"
                             "改成 0.0.0.0 会把你的真实简历敞开给整个局域网，"
                             "而这个服务没有任何认证。")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT,
                        help=f"端口，默认 {DEFAULT_PORT}。")
    parser.add_argument("--content-dir", metavar="DIR", default=str(HERE),
                        help="内容文件所在目录，默认本仓库目录。"
                             "真实简历建议放仓库外，比如 ~/.private/resume。")
    parser.add_argument("--out-dir", metavar="DIR", default=str(render.DEFAULT_OUT_DIR),
                        help="生成物目录，默认 build/。")
    parser.add_argument("--css", metavar="PATH", default=str(render.DEFAULT_CSS),
                        help="版式 CSS，默认 resume.css。")
    parser.add_argument("--no-open", action="store_true",
                        help="不自动打开浏览器（比如远程、无桌面环境）。默认只在绑到 "
                             "127.0.0.1 时才自动开。")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    content_dir = Path(args.content_dir).expanduser().resolve()
    if not content_dir.is_dir():
        raise SystemExit(f"错误：内容目录不存在：{content_dir}")
    css_path = Path(args.css).expanduser().resolve()
    if not css_path.is_file():
        raise SystemExit(f"错误：版式 CSS 不存在：{css_path}")

    studio = Studio(
        content_dir=content_dir,
        out_dir=Path(args.out_dir).expanduser().resolve(),
        css_path=css_path,
    )
    # 字体缺失是最容易被忽略的失败模式，开服前先把话说在前面（和 render.py 一致）。
    render.check_fonts(studio.theme(None))
    serve(args.host, args.port, studio, open_browser=not args.no_open)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
