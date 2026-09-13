# 方案：网页填空界面整体优化

日期：2026-09-13 · 状态：**已批准（2026-09-13，按推荐默认值）** → 分工作包执行 → 逐包验收
读者：执行改动的 agent（每个工作包一个会话）与验收人。

> 十行速读
>
> 1. 五个诉求拆成 WP0–WP5 六个工作包，**顺序执行 WP0 → WP1 → WP2 → WP3 → WP4**，WP5 只做决策不写代码。
> 2. 每个工作包开一个分支（`wp1-files` 这种名字），小步提交，**不 push、不合并**，验收通过后由用户合并。
> 3. 全局不变量见第 2 节，违反任何一条都不予验收。
> 4. 每个工作包的"验收标准"就是验收时会逐条跑的清单；测试用例名也按那里写。
> 5. 改了 `render.py` / `theme.toml` / `resume.css` / `content.example.toml` 任何一份，必须 `make preview` 并把 `examples/preview.png` + `examples/preview.sha256` 一起提交，否则 `make check` 必挂。
> 6. 不加 Python 第三方依赖，不加 npm 包，不加构建步骤。
> 7. 字段表只在 `schema.py`；版式令牌表只在新的 `theme_schema.py`；网页表单和版式面板都是照着 `describe()` 长的。
> 8. 隐私边界不动：只听 127.0.0.1、Host / Origin 校验、三类路径闸门。新目录 `.history/` 必须进 `.gitignore` 和 `check-privacy.sh`。
> 9. `start.cmd` 纯 ASCII + CRLF，`tests/test_start_cmd.py` 必须继续过。
> 10. 完成时按第 6 节的格式汇报；"做了什么"和"没做什么"都要写。

---

## 0. 已拍板（2026-09-13）

用户对下列默认值一并批准，执行 agent 不必再问：

1. `.bak` 由 `.history/` 快照**替代**，不并存；每个文件保留最近 30 份。
2. 生成物重名：网页默认询问（`if_exists = fail`），命令行默认覆盖（等于旧行为）。
3. 自定义版式文件放仓库根目录 `theme.<名>.toml`；会出现在 `git status`，不含隐私，随用户决定是否提交。
4. 内容文件 `[document]` 增加可选的 `theme` 字段作为默认版式，纳入 WP3 正式范围。
5. 托管版走路线 A（纯浏览器静态页）；域名、英文界面、存档格式、隐私声明文案四项在开 WP5 spike 前再问。
6. 前端拆成多个经典脚本，不引入构建步骤。

---

## 1. 诉求 → 判断 → 工作包

| # | 用户诉求 | 判断（一句话） | 落到 |
|---|---|---|---|
| 1 | 保存 TOML 会不断覆盖，要不要重新设计 | 要。现在每次保存覆盖文件并覆盖唯一一份 `.bak`，第二次保存就把上一版销毁了；另存为撞名时报的还是"被其他窗口修改"这种错话。改成：保存 / 另存为 / 新建三个动作分开，每次覆盖前留带时间戳的快照，撞名当场问覆盖还是改名。 | WP1 |
| 2 | 生成时弹窗让用户自己选位置；重名与异常处理 | 服务跑在 WSL、浏览器在 Windows，**选位置的对话框只能由浏览器出**（File System Access API），服务端出不了 Windows 对话框。生成仍先落到 `build/`（保住 CLI 一致性和"失败不替换旧文件"），再由浏览器"另存到…"。重名默认询问。 | WP2 |
| 3 | 版式抽成抽象实现，方便调字体、颜色、背景 | 能。分三层：**令牌表**（`theme_schema.py`，定义一次）→ **版式文件**（`theme*.toml`，可继承，可指定样式表）→ **样式表**（`resume*.css`）。网页里加一个"版式面板"照令牌表长出来，改了实时预览，能存成新版式文件。HTML 结构本轮不抽模板（只有一种结构，抽了没收益）。 | WP3 |
| 4 | "读取"按钮是什么意思；整个界面的功能都梳理一遍 | "读取"= 把输入框里那个 `content*.toml` 文件名读进表单，本质是"打开文件"，但做成了"文本框 + 按钮"，所以看不懂。换成"文件下拉（选即打开）+ 新建 + 保存 + 另存为 + 历史版本"，每个控件的行为在 WP1 里逐个定义。 | WP1 |
| 5 | 启停不顺手；要不要换语言；以后放到 eigentime.org 当服务 | 本地工具**不换语言**（WeasyPrint 是这个项目的核心资产，测试也都围着它）。启停做成幂等：已在运行就直接开浏览器，端口被占报人话，`make ui-stop`，页面里可"停止服务"。托管版是另一个产品：浏览器就是渲染引擎，前端自然是 TS；本轮只做路线决策，不写代码。 | WP4 / WP5 |

### 非目标（本轮明确不做）

- 多页简历、登录、多人协作、云端存储。
- 背景图片 / 水印（打印与 ATS 都不友好；`colors.paper` 已能改纸面颜色）。
- 重写渲染引擎或把本地工具换语言。
- 改内容文件格式（唯一例外是 WP3 里已批准的可选字段 `document.theme`）。
- 托管版代码（WP5 只出决策和 spike 定义）。

---

## 2. 全局不变量（执行 agent 必读）

1. **定义一次。** 字段表只在 `schema.py`；版式令牌表只在 `theme_schema.py`（WP3 新建）。前端不许手写字段或令牌列表。文件名规范化、重名判断等规则放服务端，前端通过接口问，不复制一份规则。
2. **零新依赖。** `requirements.txt` 只有 `weasyprint`；测试只用 `unittest` 与 `node --test`；前端不引入 npm 包、不引入构建步骤、不引入 jsdom。
3. **隐私边界不动。** 默认只听 `127.0.0.1`；Host 头校验、Origin 校验、`Sec-Fetch-Site` 检查保留；能碰的文件仍是三类：内容目录 `content*.toml`、仓库目录 `theme*.toml`（WP3 加 `resume*.css` 只读）、生成物目录 `.pdf/.html/.png`。所有新接口都走 `safe_name()`。新增的 `.history/` 目录必须同时进 `.gitignore` 与 `scripts/check-privacy.sh`。
4. **不删用户数据。** 仓库里的 `content.local.toml`、`content.web-seo.toml`、`content.local.toml.bak`、`build/` 下的一切，执行 agent 一律不碰、不读。测试只用临时目录。
5. **CLI 兼容。** `fill.py` / `render.py` 现有参数与行为不变（只允许新增参数，且默认值等于旧行为）。定制版（`extends`）在 CLI 与网页里仍只读。
6. **`start.cmd` 纯 ASCII + CRLF**，端口只在 `WEBUI_PORT` 定义一次，`-d` 后不加引号，块外用 `if not "%errorlevel%"=="0"`。这些都由 `tests/test_start_cmd.py` 盯着。
7. **预览图不许过期。** 改了 `render.py` / `theme.toml` / `resume.css` / `content.example.toml` 任一，跑 `make preview`，提交 `examples/preview.png` 与 `examples/preview.sha256`。
8. **README 是唯一文档。** 行为变了就在同一个分支里改 README 对应小节（每个 WP 下面列了要改哪些节）。不新建第二份用户文档。
9. **文案风格。** UI 文案、注释、报错都用简体中文，说人话、说为什么，与现有代码一致。报错要能直接照着去改（"换个名字，比如 content.acme.toml"），不要只说"失败"。
10. **分支与提交。** 一个 WP 一个分支；提交信息说清动机；不在 `main` 上直接提交；不 push、不合并；不提交任何 `content*.toml`（示例除外）与 `build/`。
11. **改动范围。** 只改本 WP 列出的文件和为其服务的测试 / README；顺手"优化"无关代码不予验收。
12. **测试先行的三件事。** 每个 WP 的"测试"小节列的用例必须存在且通过；`make test` 全绿；`make check` 通过。

---

## 3. 现状与问题清单（带位置）

执行前先读这些位置，不要凭猜测改。

**保存模型**
- `content_io.py:171-190` `save_content()`：唯一一份 `.bak`，每次保存被覆盖；版本不符统一抛 `ConflictError`，报错文案把"目标已存在"和"被别的窗口改了"混成一句（`:180`）。
- `webui/app.js:482-517` `save()`：`revision` 只在文件名与当前文件相同时才带（`:497`），所以"另存为一个已存在的名字"必然撞 409，而用户看到的是"请重新读取后再保存"。
- `webui/index.html:22-36`：顶栏是"文本框 + datalist + 读取"，没有"新建"，没有"另存为"，文件名要自己敲完整的 `content.xxx.toml`。
- `webui/app.js:448-480` `load()`：用原生 `confirm()` 问要不要丢弃改动；读取失败只有一条 2.6 秒的 toast。
- `fill.py:312-315` `write_out()` 也走 `save_content`，所以保存模型改动会同时改到命令行。

**生成与导出**
- `render.py:373-396` `write_outputs()`：同名生成物静默替换（`:395`），没有"存在就问"的选项。
- `webui.py:511-527` `do_render()`：只能写到启动时的 `out_dir`；前端 `showDownloads()`（`app.js:555-573`）只给"查看 / 下载"链接，位置由浏览器下载设置决定。
- `webui.py:462-474` `artifact()`：下载正常；没有"列出生成物"和"在文件夹里显示"的接口。

**版式**
- `render.py:139-164` `build_root_css()`：只检查五个组是不是表和 `[page]` 的四个键；令牌拼错会静默变成一个没人用的 CSS 变量；令牌没有类型、没有人话说明。
- `theme.toml` / `theme.en.toml`：令牌值散在文件里，没有一处说明"每个令牌是什么、是颜色还是长度"。
- `webui.py:182-186` `Studio.theme()`：版式只能按文件名选；样式表固定为启动参数 `--css`。
- 前端只有一个 `<select id="theme-name">`（`index.html:29-32`），换版式重渲，没有任何可调项。

**界面功能**
- 状态栏的"空白 N 处"只在 `title` 里列字符串（`app.js:406-413`），点不动、跳不到对应输入框；`schema.find_blanks()` 只返回字符串（`schema.py:328-372`）。
- 错误统一用 toast（`app.js:70-76`），多行服务端错误 6.5 秒后消失，用户来不及看。
- 没有帮助入口；"版式"下拉与"内容文件"输入框并排，看不出哪个管什么。

**启停**
- `webui.py:585-590` `serve()`：端口被占时 `server_type((host, port), handler)`（`:590`）直接抛 `OSError`，`main()`（`:644-662`）不接，用户看到的是 traceback。
- 没有"已在运行"检测：第二次 `make ui` 只会撞端口；`start.cmd` 每次双击都跑一遍 `make boot`（`start.cmd:96-99`）再起服务。
- 没有停止命令；只能 Ctrl-C 或关掉 `start.cmd` 那个最小化窗口。
- `Handler.log_message` 有意吞掉所有请求日志（`webui.py:252-253`），出问题时没有可看的东西。

---

## 4. 跨工作包的共同设计

### 4.1 接口错误协议（WP0 落地，之后所有接口遵守）

所有非 2xx 响应都是 JSON：

```json
{"error": "给人看的多行文案", "code": "machine_code", "...": "按 code 附带的字段"}
```

| code | HTTP | 含义 | 附带字段 |
|---|---|---|---|
| `bad_request` | 400 | 参数 / 形状错误（兜底） | — |
| `invalid_name` | 400 | 文件名不合法 | `name` |
| `not_found` | 404 | 文件不存在 | `name` |
| `exists` | 409 | 目标已存在（另存为 / 生成物） | `name`，生成物另附 `suggested` |
| `modified` | 409 | 文件版本与读取时不同 | `revision`（磁盘上现在的） |
| `protected` | 403 | 仓库跟踪的示例 / 版式，只读 | `name` |
| `variant` | 403 | 定制版，只读 | `name`, `extends` |
| `blanks` | 400 | 还有空白 | `blanks`（字符串），`locations`（结构化，见 4.3） |
| `overflow` | 422 | 超过一页 | `pages` |
| `unsupported` | 501 | 当前环境做不到（比如找不到文件管理器） | — |
| `internal` | 500 | 兜底 | — |

Python 侧：`content_io.ExistsError` 与 `content_io.ModifiedError` 都继承现有 `ConflictError`（旧的 `except ConflictError` 仍然接得住）；`webui.py` 新增 `class ApiError(Exception)` 携带 `status / code / extra`，`route()` 里统一映射。前端 `api()` 把 `code` 与附带字段挂到抛出的 `Error` 上。

### 4.2 文件模型（WP1）

- **当前文件**有三种状态：`未命名`（新建后未保存）、`可写`、`只读`（示例 / 定制版，附原因）。
- **保存**（Ctrl-S）= 写回当前文件，`mode = "update"`，必须带读取时的 `revision`。未命名 → 转成另存为。只读 → 提示并引导另存为。
- **另存为** = `mode = "create"`；目标存在时前端先问，用户确认后改 `mode = "overwrite"`（服务端自己读当前 revision，仍拒绝示例 / 定制版）。
- **新建** = 空表单，状态为未命名。
- **快照**：任何覆盖前，旧字节写到 `<内容目录>/.history/<文件名>/<UTC 时间戳>-<旧 revision 前 8 位>.toml`，保留最近 30 份，多的按名字排序删旧。新旧字节相同则既不写也不快照（返回 `unchanged: true`）。**不再生成 `.bak`**（`.gitignore` 里的 `*.toml.bak` 规则保留，挡住历史遗留文件）。`fill.py` 同样受益。
- **草稿**：浏览器 `localStorage` 每个文件名一份未保存改动，保存成功即清除；打开文件时发现草稿就问"恢复 / 丢弃"。
- **文件名规范化**只在服务端：`acme` → `content.acme.toml`，`acme.toml` → `content.acme.toml`，`content.acme` → `content.acme.toml`，`content` → `content.toml`；NFC 归一；再过 `plain_name()` 与 `content*.toml` 闸门；与现有文件**仅大小写不同**视为已存在（Windows / macOS 文件系统不分大小写）。前端通过 `GET /api/stat` 拿规范化结果和存在性，不自己算。

### 4.3 结构化空白（WP0）

`schema.find_blank_locations(content) -> list[dict]`，每项：

```python
{"block": "experiences", "index": 1, "field": "bullets", "item": 2, "section": False,
 "message": "[[experiences]] 第 2 条的 bullets[2] —— 有空白条目"}
```

`find_blanks()` 改为返回上面的 `message` 列表——字符串接口不变，现有测试不动。`index` / `item` 从 0 计数（`message` 里仍从 1 计数）；`section: True` 表示栏目名那张表的 `title`。前端用它把"空白 N 处"变成可点的列表，点一条就滚到对应输入框并高亮。

### 4.4 生成与导出模型（WP2）

- 生成仍写到服务端 `out_dir`（默认 `build/`），保留"超页 / PNG 失败不替换旧文件"的临时目录逻辑。
- 重名策略 `if_exists ∈ {fail, overwrite, rename}`：网页默认 `fail`（撞了就问），CLI 默认 `overwrite`（等于现在的行为）。`rename` 自动挑 `<名>-2` / `-3`…，三种后缀一起看，保证 html / pdf / png 主干一致。
- "选位置"由浏览器做：`window.showSaveFilePicker`（Chromium 系；`http://127.0.0.1` 是安全上下文，可用）。不支持的浏览器退回普通下载，并明说"按你浏览器的下载设置保存"。
- "在文件夹中显示"由服务端做：WSL → `explorer.exe /select,<wslpath -w 路径>`；Linux 桌面 → `xdg-open <目录>`；macOS → `open -R <文件>`。注意 `explorer.exe` 成功也常返回 1，**不能按退出码判断**，只按"命令存在"判断；找不到命令 → `unsupported`。

### 4.5 版式模型（WP3）

三层：

```
theme_schema.py   令牌表：每个令牌的 组 / 键 / 人话名 / 解释 / 类型
theme*.toml       版式文件：令牌的值；可 extends；可选 name / description / stylesheet
resume*.css       样式表：版式规则；theme 用 stylesheet = "resume.css" 选它
```

- 令牌类型：`font-stack` / `color` / `length` / `number` / `enum`。校验规则（保守，防止值里夹带 `}` `;` `</style>` 之类进入 `<style>`）：
  - `color`：`#RGB` / `#RRGGBB` / `#RRGGBBAA`
  - `length`：`^-?\d+(\.\d+)?(pt|mm|cm|in|px|em|rem|%)$`
  - `number`：`^\d+(\.\d+)?$`
  - `font-stack`：不含 `; { } < >` 和控制字符
  - `enum`：枚举成员
- `build_root_css()` 按令牌表迭代；缺令牌、多令牌、类型不对都报错并列出全部问题。
- 版式文件的顶层可选键：`name`（展示名）、`description`、`stylesheet`（默认 `resume.css`，只接受仓库目录里匹配 `resume*.css` 的文件；CLI / webui 的 `--css` 显式给了则覆盖）。
- 网页"版式面板"照 `theme_schema.describe()` 长出来；改动作为 `theme_overrides` 随 `/api/preview` 与 `/api/render` 一起发，所见即所得；"保存为版式…"写 `theme.<名>.toml`，只写与基底不同的令牌（和 `theme.en.toml` 一个写法）。`theme.toml`、`theme.en.toml` 是仓库跟踪的，只读。
- 已批准：内容文件 `[document]` 加 `theme = "theme.en.toml"`（进 `DOCUMENT_METADATA`，读写原样保留），作为这份内容的默认版式，CLI 与网页都认；显式 `--theme` 或网页里手选的版式优先。

### 4.6 前端结构（WP0）

`webui/app.js` 拆成多个**经典脚本**（不是 ES module，避免测试基座和构建步骤），`index.html` 按顺序引入，顶层 `const/let` 在经典脚本之间共享全局词法作用域，所以不需要命名空间：

```
ui.js       对话框（<dialog>）、toast、可关闭的错误横幅
form.js     表单生成（现 buildForm / fieldView / cardView / blockView）
preview.js  防抖、预览请求、页数与空白显示、fitPaper
files.js    打开 / 保存 / 另存为 / 新建 / 历史 / 草稿
export.js   生成对话框、导出、另存到…、在文件夹中显示
theme.js    版式面板（WP3 建）
app.js      state、el、api()、启动、事件绑定（最后加载）
```

`tests/test_app.cjs` 改为读 `index.html` 里 `/static/*.js` 的顺序拼接后再 `vm.runInContext`；假 DOM 需要补 `<dialog>` 的 `showModal / close / returnValue` 与 `querySelector` 最小实现。禁止 `confirm()` / `prompt()` / `alert()`。

### 4.7 启停模型（WP4）

- 启动幂等：绑定失败且探测到端口上是本服务（`Server: onepage-resume-webui` 头）→ 打印"已在运行"、按需开浏览器、退出码 0；是别的程序 → 人话报错、退出码 1、无 traceback。
- 运行记录 `tempfile.gettempdir()/onepage-resume-webui-<port>.json`：`pid / port / host / started / content_dir / out_dir`。`--status` 读它并探测；`--stop` 校验 pid 确属 `webui.py` 后发 SIGTERM，等最多 5 秒。
- SIGTERM / SIGINT 优雅退出并删除运行记录；陈旧记录（pid 不活）启动时覆盖。
- `POST /api/shutdown`（同源保护已有）：页面"停止服务"按钮，确认后调用；服务在线程里 `server.shutdown()`。
- 可选 `--idle-exit N`：页面每 30 秒 `POST /api/heartbeat`，超过 N 分钟没人访问就自行退出；默认 0（关闭）。

---

## 5. 工作包

每个工作包：目标 → 改动 → 行为规格 → 边界与异常 → 测试 → README → 验收标准。

### WP0 底座（行为不变的重构）

**目标**：为后面四个包铺路，用户可见行为除错误 JSON 多一个 `code` 字段外零变化。

**改动**
- `content_io.py`：`ExistsError` / `ModifiedError`（继承 `ConflictError`）；`save_content()` 内部分别抛这两个，文案分开："{name} 已存在，换个名字或选择覆盖。" / "{name} 在你读取之后被改过（可能是另一个窗口或编辑器），请重新读取后再保存。"
- `webui.py`：`ApiError`；`route()` 的异常映射改成 4.1 的表；`fail()` 接受 `code` 与 `extra`。
- `schema.py`：`find_blank_locations()`；`find_blanks()` 改为它的 `message` 视图。
- `webui/ui.js` 新建：`dialog()`、`toast()`、`banner()`。`banner()` 固定在状态栏下方，可关闭，可展开多行；错误一律走 banner，成功走 toast。
- 前端按 4.6 拆文件；`app.js` 的 `load()` 里的 `confirm()` 改为 `dialog()`。
- `tests/test_app.cjs`：按 4.6 改基座。

**测试**
- `tests/test_content.py`：`test_exists_and_modified_are_distinct_errors`（新文件撞名 → ExistsError；版本不符 → ModifiedError；两者仍是 ConflictError）。
- `tests/test_webui.py`：`test_error_json_carries_a_code`（撞名 409 `exists`、版本不符 409 `modified`、示例 403 `protected`、定制版 403 `variant`、空白 400 `blanks` 且带 `locations`、超页 422 `overflow`）。
- `tests/test_content.py` 或新 `tests/test_schema.py`：`test_blank_locations_cover_every_message`（`find_blanks()` 与 `find_blank_locations()` 一一对应）、`test_blank_locations_point_at_real_fields`（block/field 都在 `BLOCKS` 里）。
- `tests/test_app.cjs`：现有 8 个用例在拆分后全部通过；新增 `dialog resolves with the pressed button`。

**README**：无（行为未变）。

**验收标准**
- `make test`、`make check` 全绿；`git diff --stat` 里没有 WP0 之外的文件。
- `curl -s -X POST -H 'Content-Type: application/json' -d '{"name":"content.example.toml","content":{}}' 127.0.0.1:8765/api/save` 返回 403 且 `"code":"protected"`。
- 浏览器里读取 / 保存 / 生成三个流程与改前一致；页面没有任何 `confirm()` 弹窗。

### WP1 文件模型与顶栏重构（诉求 1、4）

**目标**：保存不再销毁上一版；撞名有明确处理；顶栏每个控件看一眼就知道干什么。

**改动**
- `content_io.py`：
  - `save_content(path, text, expected_revision, *, mode="update")` 实现 4.2 的三种 mode 与快照；`HISTORY_DIR = ".history"`、`HISTORY_KEEP = 30`；`history_dir(path)`、`list_history(path)`、`read_history(path, snapshot_id)`；快照文件用 `atomic_write`（已是 0600）；快照 id 只接受 `^\d{8}T\d{6}Z-[0-9a-f]{8}\.toml$` 且必须位于该文件的历史目录内。
  - `normalize_content_name(raw) -> str`（4.2 的规则）；`content_exists(base, name) -> Path | None`（大小写不敏感匹配）。
  - 去掉 `.bak` 写入。
- `fill.py`：`write_out()` 打印"上一版已存到 .history/…"。
- `webui.py`：
  - `GET /api/bootstrap`：`contents` + `protected` 合并为 `files: [{name, writable, reason, extends}]`（reason 如 "仓库里的示例，只读" / "定制版，继承 content.local.toml，只读"）。
  - `GET /api/stat?kind=content&name=<raw>` → `{name（规范化后）, exists, writable, reason}`；名字不合法 → 400 `invalid_name`。
  - `POST /api/save`：接受 `mode`；响应加 `unchanged`、`snapshot`（本次快照 id 或 null）。
  - `GET /api/history?name=` → `[{id, time, size}]`；`GET /api/history/read?name=&id=` → `{content（shape 后）, blanks}`。
- 前端：
  - 顶栏改为：`[文件 ▾]`（选即打开）`[新建]` `[保存]` `[另存为…]` `[历史版本…]` `[版式 ▾]`（WP3 会再改） `[生成 PDF…]`（WP2 会再改） `[?]`。去掉文本框、datalist 与"读取"。
  - `[?]`：五行帮助（选文件或新建 → 填、右边实时看 → Ctrl-S 保存，历史可回退 → 生成 PDF… 选位置 → 投递前看 PNG），加当前内容目录与生成物目录路径。
  - 状态栏：`页数` · `空白 N 处`（可点，展开结构化列表，点条目跳转高亮） · `PDF 实渲 / HTML 近似` · 文件名 + 状态徽标（未命名 / 未保存 / 已保存 HH:MM / 只读：原因）。
  - 草稿：`touched()` 后 1 秒防抖写 `localStorage["onepage-resume:draft:<name|untitled>"] = {content, theme, savedRevision, time}`；保存成功或"丢弃"时删除；打开文件时若草稿的 `savedRevision` 等于文件当前 revision → 问"恢复 / 丢弃"；不等 → 也问，但标明"文件在这之后被改过"。
- `.gitignore`：加 `.history/`；`scripts/check-privacy.sh` 第 1 项的 grep 加 `(^|/)\.history/`。

**每个控件的行为规格**

| 控件 | 正常 | 有未保存改动 | 当前是只读 / 未命名 |
|---|---|---|---|
| 文件 ▾ | 读取所选文件，重建表单，重预览 | 对话框：保存后切换 / 放弃改动 / 取消 | 同左 |
| 新建 | 空表单，状态"未命名"，版式不变 | 同上先问 | — |
| 保存 / Ctrl-S | `update`，成功 toast"已保存 HH:MM"，`unchanged` 时 toast"内容没变，没有写盘" | — | 未命名 → 打开另存为；只读 → banner"这份是 X，只读；用另存为存成你的" |
| 另存为… | 对话框：名字输入（placeholder `content.acme.toml`），300ms 防抖调 `/api/stat` 显示"将写入 content.acme.toml（新文件）" / "已存在，保存将覆盖（会先留快照）" / "只读，不能覆盖"；主按钮随之变"保存" / "覆盖" / 禁用 | 同左 | 同左 |
| 历史版本… | 列表（时间、大小、相对"多久前"）；"读入表单" → 表单替换为快照内容，状态变"未保存"，banner"已读入 X 的历史版本，保存即覆盖当前文件" | 先问 | 只读文件也可看历史（如果有） |
| 空白 N 处 | 点开列表，点条目滚动到输入框并高亮 1.5 秒 | — | — |
| 关闭页面 | — | `beforeunload` 提示（保留现状） | — |

**边界与异常**
- 文件列表里某个文件解析失败（坏 TOML、继承成环）：打开时 banner 显示服务端错误，表单保持原样，下拉选回原文件。
- `/api/save` 返回 `modified`：banner 给两个按钮"重新读取（丢弃我的改动）" / "另存为其他名字"；不提供"强制覆盖"。
- 另存为的名字与当前文件相同：等价于保存。
- 名字与现有文件仅大小写不同：按"已存在"处理。
- 快照目录不可写（权限）：保存失败并说明，不写主文件。
- 快照数达到 30：写新的、删最旧的，且删除失败不影响本次保存（打印警告）。
- 草稿读取失败（`localStorage` 被禁用 / 抛异常）：忽略草稿功能，不报错。
- 未命名状态下按 Ctrl-S 连按两次：只弹一个对话框（`saving` 锁）。

**测试**
- `tests/test_content.py`：`test_save_modes_matrix`（create / update / overwrite × 不存在 / 存在 / 被改 / 示例 / 定制版 共 15 格，逐格断言异常类型或成功）、`test_snapshot_is_written_before_overwrite`、`test_unchanged_save_writes_nothing`（mtime 与目录内容都不变）、`test_history_is_pruned_to_keep`、`test_snapshot_files_are_private`（0600）、`test_history_id_gate_rejects_traversal`、`test_normalize_content_name_table`（至少 10 组输入输出）、`test_case_insensitive_collision_counts_as_exists`、`test_no_bak_is_written_anymore`。
- `tests/test_webui.py`：`test_bootstrap_lists_files_with_reasons`、`test_stat_normalizes_and_reports_existence`、`test_save_as_existing_returns_exists_then_overwrite_succeeds`、`test_history_endpoints_round_trip`、`test_history_read_refuses_foreign_ids`。
- `tests/test_app.cjs`：`switching files with unsaved edits asks first`、`untitled save opens save-as`、`save-as on an existing name asks before overwriting`、`modified conflict offers reload or save-as, never force`、`draft is restored only after the user says so`、`blank list click focuses the matching input`。
- `tests/test_variants.py`：`test_fill_still_refuses_variants_after_save_refactor`（现有用例改名或保留即可，确保没回归）。

**README**：改「〇、浏览器里填」的保存段落（`.bak` → `.history/`、保存 / 另存为 / 新建 / 历史 / 草稿）；「隐私模型」表格加 `.history/` 一行、四道防线第 1 条提 `.history/`；「一、被问着填」里的 `.bak` 说明；「文件职责」里 `content_io.py` 与 `webui/` 两条；「排障」表"网页版存不了"一行；「投递前检查」第 5 条提历史目录。

**验收标准**
- 连续保存三次不同内容后，`.history/<name>/` 有 2 份快照，主文件是第三版；再保存相同内容，目录不变、响应 `unchanged: true`。
- 另存为到已存在的名字：对话框显示"已存在"，主按钮变"覆盖"；确认后 200，目标的旧内容进了目标自己的 `.history/`。
- 另存为 `content.example.toml`：对话框禁用主按钮并说明只读；直接调接口 → 403 `protected`。
- 打开定制版：状态栏徽标写"只读：定制版，继承 X"；Ctrl-S → banner 引导另存为，文件未变。
- 空白列表点击后焦点落在正确的输入框（用示例内容删掉一条 bullet 验证）。
- 把 `.history/` 手工加进 git 索引再跑 `make check` 会报错（验完 `git rm --cached` 恢复）。
- `python fill.py --out <临时文件>` 覆盖已有文件时打印历史路径且不再产生 `.bak`。
- 页面上找不到"读取"按钮与文本框；`?` 弹层能打开。

### WP2 生成与导出（诉求 2）

**目标**：生成前知道会写到哪、撞名怎么办；生成后能把 PDF 存到自己选的位置。

**改动**
- `render.py`：`write_outputs(..., if_exists="overwrite")`；`next_free_basename(out_dir, basename)`；`render.py --if-exists {overwrite,rename,fail}`（默认 `overwrite`）；`fail` 时 `SystemExit("错误：build/X.pdf 已存在…用 --if-exists rename 自动改名")`。
- `webui.py`：
  - `POST /api/render`：`if_exists` 默认 `fail`；409 `exists` 附 `suggested`；成功响应加 `basename`（实际用的）。
  - `GET /api/artifacts` → `[{name, kind, size, mtime}]`（只列 `.pdf/.html/.png`，按 mtime 倒序）。
  - `GET /api/stat?kind=artifact&name=` → `{name, exists, suggested}`。
  - `POST /api/reveal` `{name}` → 4.4 的实现；`unsupported` 时说明路径让用户自己找。
- 前端 `export.js`：
  - "生成 PDF…" 对话框：文件名（预填 `document.output_basename`，防抖 `/api/stat`，非法名内联报错）；已存在时单选"覆盖 / 自动改名为 `<suggested>` / 取消"；版式显示当前选择；复选"生成后让我选择保存位置"（默认勾选，仅当 `window.showSaveFilePicker` 存在；否则显示"你的浏览器不支持选择位置，将按浏览器下载设置保存"并禁用）。
  - 结果区：`PDF 查看 / 下载 / 另存到…`、`PNG 查看 / 下载 / 另存到…`（无 PNG 时说明缺 `pdftoppm`）、`HTML 下载`、`在文件夹中显示`。
  - "另存到…"：`showSaveFilePicker({suggestedName, types})` → `fetch('/api/artifact?name=…')` → `blob` → `writable.write` → toast"已保存到 <文件名>"；`AbortError` 静默；其它错误 banner。
  - 生成期间按钮禁用；生成完成时若 `previewVersion` 已变，仍展示结果但 banner 说明"这是生成前的内容"（保留现有逻辑，只是文案更明确）。

**边界与异常**
- `output_basename` 为空或等于默认 `resume`：对话框仍允许，但提示"建议写成 姓名-岗位-简历"。
- 生成物目录不存在：服务端创建；不可写 → 500 `internal`，文案带路径。
- `rename` 时三种后缀有任一存在就跳过该序号。
- 超页 422 → banner 显示页数；空白 400 → banner + 空白列表展开。
- `reveal` 在没有桌面的 Linux（`xdg-open` 缺）→ 501 `unsupported`，对话框显示完整路径与"复制路径"按钮。

**测试**
- `tests/test_content.py`（RenderSafetyTest）：`test_if_exists_fail_refuses_when_any_suffix_exists`、`test_if_exists_rename_picks_next_free_across_suffixes`、`test_if_exists_overwrite_is_the_cli_default`。
- `tests/test_webui.py`：`test_render_defaults_to_fail_and_suggests_a_name`、`test_render_rename_reports_actual_basename`、`test_artifacts_listing_only_shows_artifacts`、`test_reveal_uses_explorer_in_wsl`（mock `_in_wsl`、`shutil.which`、`subprocess.run`，断言命令形状且不看退出码）、`test_reveal_refuses_names_outside_out_dir`、`test_reveal_reports_unsupported_without_tools`。
- `tests/test_app.cjs`：`generate dialog asks on conflict and sends the chosen policy`、`save-to uses the picker when present and falls back to download otherwise`（用假的 `showSaveFilePicker`）、`reveal button is offered only after a successful build`。

**README**：「〇、浏览器里填」生成段落（对话框、重名策略、"另存到…"仅 Chromium、"在文件夹中显示"）；「命令行参数」`render.py` 加 `--if-exists`；「排障」加"另存到…按钮没出现"（浏览器不支持）。

**验收标准**
- 同名再生成：对话框出现三选一；选"自动改名"后结果区文件名带 `-2`，`build/` 里旧文件未动。
- CLI `python render.py --content content.example.toml --out-dir /tmp/x` 连跑两次都成功（默认覆盖）；加 `--if-exists fail` 第二次退出码非 0 且无 traceback。
- Windows Chrome 里点"另存到…"弹出系统保存对话框，保存到桌面后文件可打开；Firefox 下按钮不出现、改为说明文字（验收时用假 `showSaveFilePicker` 缺失模拟）。
- "在文件夹中显示"在 WSL 里打开资源管理器并选中文件。

### WP3 版式抽象与版式面板（诉求 3）

**目标**：令牌有表、有类型、有人话；网页里能改字体 / 颜色 / 尺寸并实时看；能存成自己的版式文件。

**改动**
- `theme_schema.py` 新建：`GROUPS`、`Token(group, key, label, hint, kind, choices=())`；覆盖 `theme.toml` 现有全部令牌（fonts 2、colors 6、page 4、layout 9、type 14、rules 5）；`describe()`；`validate(theme) -> list[str]`；`apply_overrides(theme, overrides)`（未知组 / 键报错）。
- `render.py`：`build_root_css()` 改为按令牌表迭代 + 校验；`resolve_stylesheet(theme, explicit_css) -> Path`（闸门 `resume*.css`，仓库目录）；`run()` 用它。`check_fonts()` 不变。
- `content_io._load()`：版式允许顶层 `name` / `description` / `stylesheet`（字符串校验）。
- `theme.toml` 加 `name = "默认 · 中文"`、`description = "……"`；`theme.en.toml` 加 `name = "English"`。（会让预览哈希变化 → `make preview`。）
- `webui.py`：
  - `Studio.theme(name, overrides)` 返回合并后的版式与样式表路径；`PROTECTED_THEMES = {"theme.toml", "theme.en.toml"}`。
  - `GET /api/bootstrap`：`themes: [{name, label, description, protected}]`、`theme_tokens: theme_schema.describe()`、`fonts_installed: [...]`（启动时 `fc-list` 一次并缓存；查不到 → `[]`）。
  - `GET /api/theme?name=` → `{name, label, extends, stylesheet, tokens（合并后的值）, own（该文件自己写了哪些键）, writable, revision}`。
  - `POST /api/preview` / `POST /api/render`：接受 `theme_overrides`。
  - `POST /api/theme/save` `{name, base, overrides, mode, revision}` → 写 `theme.<x>.toml`（`extends = base`，`name`，只写 overrides）；名字规范化 `x` → `theme.x.toml`；示例版式只读。`content_io.save_content` 抽出通用的 `save_text(path, raw, expected_revision, mode, *, history)`，内容走 `history=True`，版式走 `history=False`。
  - `GET /api/stat?kind=theme&name=`。
- 前端 `theme.js`：预览栏顶部一个可折叠"版式"面板：版式下拉（label + description，只读徽标）；"调整"展开按组折叠的令牌编辑器（`color` → `<input type=color>` + 十六进制框；`font-stack` → 文本框 + 每个家族名旁 ✓/✗（按 `fonts_installed` 包含匹配，CJK 家族缺失时红字"中文会显示为方块"）；`length` / `number` → 文本框，失焦校验；`enum` → select）；改动 300ms 防抖重预览；"重置"清空 overrides；"保存为版式…"对话框（名字、`/api/stat?kind=theme`、覆盖确认）。当前版式与 overrides 进草稿（WP1 的 draft 加 `theme` / `theme_overrides`）。
- 已批准（放在 WP3 最后做）：`schema.DOCUMENT_METADATA` 加 `theme`；`render.run()` 里若 `--theme` 未显式给且内容里有 `document.theme` 则用它（值走 `safe_name(..., THEME_GLOB, HERE)` 闸门）；网页打开文件时按它选版式，用户手选后以手选为准；`fill.py` 与网页保存时原样保留该键。测试：`tests/test_theme.py::test_document_theme_survives_round_trip_and_is_the_default`（往返保留；CLI 未给 `--theme` 时采用；显式 `--theme` 优先；非法值报错）。

**边界与异常**
- 令牌值含 `}` / `;` / `</style>`：400，文案指出是哪个令牌。
- `stylesheet = "../x.css"` 或 `app.css`：400；文件不存在：400 带文件名。
- 面板里改了但切换版式：问"放弃当前调整？"
- 版式文件的 `name` 只在文件自己定义时展示，继承来的不展示（否则每个定制版式都叫"默认"）。
- `fc-list` 不存在（macOS 没装 fontconfig）：`fonts_installed: []`，面板不显示 ✓/✗，显示"查不到系统字体清单"。

**测试**
- 新 `tests/test_theme.py`：`test_schema_covers_every_token_in_theme_toml_and_nothing_more`、`test_english_theme_validates`、`test_validators_reject_injection_and_wrong_units`（含 `</style>`、`;}`、`10px;` 、`abc`）、`test_unknown_token_is_an_error_not_a_silent_css_var`、`test_stylesheet_gate`（`../x.css`、`app.css`、缺失）、`test_overrides_merge_and_reject_unknown`、`test_root_css_for_default_theme_is_unchanged`（与改前的 `build_root_css()` 输出逐行相同——改前先把输出存进测试当基线）、`test_describe_is_json_serializable`。
- `tests/test_webui.py`：`test_theme_endpoint_reports_own_keys_and_protection`、`test_theme_save_creates_a_variant_with_only_overrides`、`test_theme_save_refuses_tracked_themes`、`test_preview_applies_overrides`（响应 HTML 里 `--seal:` 的值变了）、`test_render_applies_overrides`、`test_bootstrap_carries_theme_tokens_and_fonts`。
- `tests/test_app.cjs`：`theme panel is built from theme_tokens`、`token edits travel as theme_overrides in preview requests`、`reset clears overrides and re-previews`。
- 现有 `tests/test_content.py::RenderSafetyTest` 里的令牌相关用例保持通过。

**README**：「文件职责」加 `theme_schema.py`，改 `theme.toml` / `theme.en.toml` / `resume.css` 三条；「改内容时的四个注意点」前加一节「改版式」（面板、保存为版式、`stylesheet` 键、先看 ✓/✗ 再换字体、示例版式只读）；「命令行参数」说明 `--theme` 指到自定义版式与 `--css` 的优先级。

**验收标准**
- `make preview` 后 `make check` 通过；`examples/preview.png` 与改前肉眼一致（默认版式渲染结果不变）。
- 面板把 `colors.seal` 改成 `#8A1C1C`，预览里竖脊和栏目名变红；"保存为版式…"存成 `theme.red.toml`，文件内容只有 `extends`、`name` 和 `[colors] seal`；`python render.py --content content.example.toml --theme theme.red.toml --out-dir /tmp/red` 出的 PDF 是红的。
- 在 `theme.toml` 里把 `rail = "33pt"` 拼成 `rali` 跑 `make example` → 报错点名 `layout.rali` 未知且 `layout.rail` 缺失（验完还原）。
- 令牌值填 `</style><script>` → 400，文案带令牌名。
- 面板里英文版式选中后 `fonts` 组的 ✓/✗ 与本机 `fc-list` 一致。

### WP4 启停与单实例（诉求 5 的本地部分）

**目标**：`make ui` 幂等；端口被占说人话；有停止命令；页面里能停。

**改动**
- `webui.py`：
  - `probe(host, port) -> "ours" | "foreign" | "free"`（`socket.create_connection` + `GET /api/bootstrap`，看 `Server` 头前缀）。
  - `serve()` 前调用；`ours` → 打印 URL，`open_browser` 时开浏览器，返回 0；`foreign` → `SystemExit("错误：端口 8765 被别的程序占用，换一个：webui.py --port 9000")`。
  - `RUN_FILE`、`write_run_file()`、`read_run_file()`、`--status`、`--stop`（`os.kill(pid, 0)` 存活 + Linux 读 `/proc/<pid>/cmdline` / macOS `ps -p <pid> -o command=` 含 `webui.py` 才发 SIGTERM；等 5 秒；仍在 → 提示手工处理，不 SIGKILL）。
  - `signal.signal(SIGTERM, …)` 优雅退出；`finally` 删运行记录。
  - `POST /api/shutdown` `{confirm: true}` → 202 `{"stopping": true}` → 线程 `server.shutdown()`。
  - `--idle-exit N` + `POST /api/heartbeat`（默认关闭）。
  - `--log`：打开后 `log_message` 不再吞 GET（默认仍吞；`--log` 打到 stderr）。
- `Makefile`：`ui`（不变但因幂等不会再撞端口）、`ui-bg`（`setsid nohup … --no-open >"$(TMPDIR)/onepage-resume-webui.log" 2>&1 &` 并打印日志路径与 URL）、`ui-stop`、`ui-status`；`help` 同步。
- `start.cmd`：在 `make boot` 之前 `call :runwsl ".venv/bin/python webui.py --status --port %WEBUI_PORT%"`，退出码 0 → 直接 `goto up`；启动命令加 `--idle-exit 60`（关掉最小化窗口仍可停，60 分钟没人用也自停）。保持 ASCII / CRLF / 端口单点定义。
- 前端：`?` 弹层里加"停止服务"（确认对话框 → `/api/shutdown` → 页面顶部横幅"服务已停止，关掉这个标签页即可；再次使用请 make ui 或双击 start.cmd"，所有按钮禁用）；`--idle-exit` 开着时每 30 秒心跳（页面隐藏时停发）。

**边界与异常**
- 运行记录存在但 pid 不活：启动时覆盖并打印"清理了陈旧的运行记录"。
- `--stop` 找不到运行记录但端口上有本服务（比如用别的临时目录启的）：提示"服务在运行但不是这里启动的，请到它的终端 Ctrl-C 或在页面里点停止服务"。
- `--host 0.0.0.0`：探测仍连 `127.0.0.1`；警告保留。
- 心跳只在 `--idle-exit > 0` 时由 bootstrap 告知前端（`idle_exit: N`），否则前端不发。
- 关闭中收到新请求：返回 503 `{"code":"internal","error":"服务正在停止"}`。

**测试**
- `tests/test_webui.py`：`test_probe_recognises_our_own_server`（起 `ServerTestCase` 的服务，探测 → `ours`）、`test_probe_calls_a_plain_socket_foreign`（起一个只 accept 不回话的 socket）、`test_starting_on_a_busy_foreign_port_exits_with_a_message`（`main([...])` → `SystemExit`，文案含端口，无 traceback）、`test_run_file_lifecycle`、`test_stop_refuses_a_pid_that_is_not_webui`、`test_shutdown_endpoint_requires_confirm_and_same_origin`、`test_idle_exit_triggers_after_silence`（注入假时钟）。
- `tests/test_start_cmd.py`：`test_it_checks_status_before_boot`（`--status` 出现在 `make boot` 之前）；现有全部用例通过。
- `tests/test_app.cjs`：`stop button disables the page after the server acknowledges`、`heartbeat is sent only when idle_exit is announced`。

**README**：「已经在 WSL 里了，怎么起？」加 `make ui-stop` / `make ui-status` / `--idle-exit`；「命令行参数」`webui.py` 加 `--status` / `--stop` / `--idle-exit` / `--log`；「排障」加"端口被占用"与"页面说服务已停止"；`start.cmd` 那条说明改成"已在运行就直接开浏览器"。

**验收标准**
- 两个终端各跑一次 `make ui`：第二次打印"已在运行"并退出码 0，浏览器多开一个标签页。
- 用 `python3 -m http.server 8765` 占住端口再 `make ui`：一行人话报错、退出码 1、无 traceback。
- `make ui-status` 退出码 0 且打印 URL；`make ui-stop` 后 3 秒内端口释放、运行记录文件消失；再 `make ui-status` 退出码 1。
- 页面点"停止服务"→ 确认 → 横幅出现、服务进程退出。
- `webui.py --idle-exit 1 --no-open`，关掉所有标签页 → 约 1 分钟后进程自行退出，日志一行说明。
- `tests/test_start_cmd.py` 全过；`file start.cmd` 仍是 ASCII + CRLF。

### WP5 托管版（诉求 5 的 eigentime.org 部分）——只做决策，本轮不写代码

**为什么是另一个产品**：本地工具的一切前提在公网上都反了。

| 维度 | 本地工具（现在） | 公网服务（eigentime.org） |
|---|---|---|
| 信任模型 | 用户自己的机器，没有认证也安全 | 任何人都能来，包括脚本 |
| 简历数据 | 落在自己磁盘 | 是 PII；经过服务器就要承诺不落盘、不记日志 |
| 渲染 | WeasyPrint，每次 ~1 秒 CPU | 按键级预览 = 免费的 DoS 面 |
| 一页判定 | WeasyPrint 说了算 | 取决于谁渲染 |
| 运维 | 无 | 域名、证书、容器、限流、监控 |

**三条路线**

| | A. 纯浏览器（静态页） | B. 无状态渲染 API | C. 浏览器内 Typst（WASM） |
|---|---|---|---|
| 渲染引擎 | 用户的浏览器：Paged.js 分页预览 + "打印为 PDF" | Python/WeasyPrint 容器（Fly.io / Cloud Run / VPS + Cloudflare Tunnel；Workers 跑不了原生库） | typst.ts，在浏览器里直接产 PDF 字节 |
| 复用现有代码 | `schema`（构建期导出 JSON）、`theme` 令牌、`resume.css` 原样；`ResumeBuilder` 约 100 行移植到 JS，用 golden test 钉住两边 HTML 一致 | 几乎全部 | 版式要用 Typst 重写，CSS 作废 |
| 隐私 | **内容不出浏览器**，可以当卖点写在页面上 | 内容经过服务器 | 内容不出浏览器 |
| 成本 / 运维 | 零（Cloudflare Pages，和 eigentime.org 同一套） | 容器月费 + 维护 + 限流 + Turnstile | 零，但 CJK 字体体积大（需子集 / 懒加载） |
| PDF 一致性 | Chromium 最佳；Safari / Firefox 有差异；PDF 元数据只有标题 | 与本地一致 | 自成一体，确定性好 |
| "选位置"（诉求 2） | 打印对话框天然就是 | 同本地方案 | 同本地方案 |

**推荐**：**A**（已批准）。理由：隐私就是这个工具的卖点，零运维贴合 eigentime.org 现有的 Astro + Cloudflare Pages；本地 Python 版继续作为"精修 / 打印验证版"存在，两边共享的是 schema、令牌、CSS 和 golden test，而不是代码。语言问题由此自然回答：本地不换，托管前端是 TS。B 只在"必须与本地 PDF 字节级一致"时才值得。

**需要用户拍板的问题**（第 1 项已定为 A；其余在开 spike 前再问）
1. ~~路线 A / B / C。~~ 已定：A。
2. 放在 `eigentime.org/resume/` 还是子域。
3. 是否接受"Chromium 出 PDF 效果最好，其它浏览器有差异"的说明。
4. 是否要英文界面（示例内容已有英文版式）。
5. 存档格式：托管版用 JSON（浏览器内解析 TOML 需要自写解析器）还是坚持 TOML。
6. 隐私声明文案与是否要一个"本页不发送任何数据"的可验证说明（DevTools 网络面板零请求）。

**Spike 定义**（拍板后执行，一个会话）：`site/` 下一个不依赖后端的静态原型：读构建期导出的 `schema.json` 长表单（复用 `form.js`）、浏览器内渲染 HTML + `resume.css`、Paged.js 显示页数、"打印为 PDF"、导入 / 导出存档。验收：示例内容在 Chrome 里 1 页且换行与 WeasyPrint 版肉眼一致；PDF < 1 MB；DevTools 里没有任何携带内容的网络请求；Lighthouse 可访问性 ≥ 90。

---

## 6. 执行方式与汇报格式

- 执行顺序：WP0 → WP1 → WP2 → WP3 → WP4。WP4 只依赖 WP0，可与 WP2 / WP3 并行（不同分支，都基于合并后的 WP1）。
- 规模：WP0 小；WP1 大；WP2 中；WP3 大；WP4 中。一个 WP 一个会话，做不完就在汇报里写清停在哪。
- 开工前：读本文第 2、3、4 节和本 WP 全文；`make test` 确认起点全绿；`git status` 干净。
- 汇报模板（写在最终消息里，不要写进仓库）：

```
WP<n> 汇报
做了：<按改动清单逐条，标明文件>
没做 / 有意跳过：<条目 + 原因>
测试：make test 输出摘要（用例数、失败数）；make check 结果；新增用例名单
手工验证：<起服务后实际点过 / curl 过的流程>
README：改了哪些小节
已知风险 / 待验收人注意：<…>
分支：<名字>，提交数 <n>
```

## 7. 验收清单（验收人执行）

每个 WP 在其分支上：

1. `git diff --stat main...HEAD` 对照改动清单，越界文件退回。
2. `make test`（Python + Node）与 `make check` 全绿；对照"测试"小节核对用例名存在。
3. 起服务（`make ui`），按该 WP"验收标准"逐条操作：接口用 `curl`，界面用 Windows Chrome 走 CDP（见附录）。
4. `python render.py --content content.example.toml --out-dir /tmp/accept` 仍是一页；`git status` 里没有内容文件或生成物。
5. README 对应小节已改且与实际行为一致（照着 README 操作一遍）。
6. `start.cmd`（WP4）：`tests/test_start_cmd.py` + 实际双击一次。
7. 结论写成"通过 / 退回（条目）"。

## 附录：真机验证前端的办法（WSL2 + Windows Chrome）

这台机器 WSL 里没有浏览器，用 Windows 侧 Chrome 走 CDP：

```
"/mnt/c/Program Files/Google/Chrome/Application/chrome.exe" --headless=new \
  --remote-debugging-port=9333 --remote-allow-origins=* \
  --user-data-dir="C:\Users\<Windows用户名>\AppData\Local\Temp\resume-cdp" \
  http://127.0.0.1:8765
```

- `--user-data-dir` 必须是 Windows 路径，指到 WSL 路径会静默失败。
- 不要用 `--dump-dom`（输出 0 字节）；用 Node 24 内建 `WebSocket` 连 `http://127.0.0.1:9333/json/list` 里的 `webSocketDebuggerUrl`，`Runtime.evaluate` 取值、`Page.captureScreenshot` 截图。
- 先发 `Emulation.setDeviceMetricsOverride`（如 1600×1000），headless 默认视口极窄。
- 同一 profile 的旧实例会占着端口：开跑前按命令行清掉旧 chrome.exe。
- 判断"PDF 是打开还是下载"：导航后读 `document.contentType`。
- Windows 能直连 WSL 里绑 127.0.0.1 的服务（`localhostForwarding` 默认开）；先用 `powershell.exe Invoke-WebRequest http://127.0.0.1:8765` 确认链路。
