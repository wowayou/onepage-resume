# onepage-resume

[![render](https://github.com/wowayou/onepage-resume/actions/workflows/render.yml/badge.svg)](https://github.com/wowayou/onepage-resume/actions/workflows/render.yml)
[![license: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

**填空式**的一页简历生成器：`python fill.py` 一题一题地问，问完直接出 PDF / HTML / PNG。
不想被问就 `python fill.py --blank` 拿一份空白表单，在编辑器里把每个空填上。

答案存成 TOML，版面用 CSS 排——内容和版式始终是分开的两个文件。

排版交给 WeasyPrint 的 CSS 盒模型，间距由引擎计算——不手工算坐标，所以不会出现
"标题压住上一段文字"这种事。内容超过一页时程序**报错拒绝生成**，不会偷偷给你第二页。

![示例预览](examples/preview.png)

> 上图是仓库里的 `content.example.toml` 渲染出来的。人名、公司、数字全是编的；
> 顶部那两条链接是模板作者的（[eigentime.org](https://eigentime.org) ·
> [github.com/wowayou](https://github.com/wowayou)），当署名用，你自己那份换掉就行。

## 它适合谁

- 想要一份克制、能过 ATS、黑白打印也清楚的一页简历（中文、英文都行）；
- 不想从零排版，也不想被在线编辑器绑住：回答一串问题就有一份 PDF；
- 愿意把内容和版式分开：改内容只动 TOML，调版式只动 `theme.toml`；
- 需要按岗位做多个定制版，而且**不想让真实姓名手机邮箱进 Git**。

不适合：需要多页、需要花哨图形、需要在线编辑器的场景。

---

## 隐私模型（先读这段）

这个仓库是公开的，所以它被设计成**工具和数据分离**：

| | 在哪 | 进 Git 吗 |
|---|---|---|
| 程序、版式、设计令牌 | 本仓库 | ✅ 跟踪 |
| `content.example.toml` 虚构示例 | 本仓库 | ✅ 跟踪 |
| **你的真实内容** `content.toml` | 本仓库目录内，或仓库外任意路径 | ❌ 被 `.gitignore` 挡住 |
| `fill.py` 留的备份 `content.toml.bak` | 内容文件旁边 | ❌ 被 `.gitignore` 挡住 |
| **生成物** `build/` | 本仓库 `build/` 或你指定的目录 | ❌ 被 `.gitignore` 挡住 |

四道防线：

1. `.gitignore` 里是 `content*.toml` + `!content.example.toml`——**除了示例，任何
   内容文件都进不去**。按公司做定制版叫 `content.acme.toml` 也一样安全。
   `*.toml.bak` 另有一条：`content.toml.bak` 后缀变了，不匹配 `content*.toml`，
   而备份里装的是一模一样的真实内容。
2. `build/` 整个目录忽略。PDF 的正文是可被全文搜索的，手机号进了 Git 历史就得重写
   历史才删得掉。
3. `./scripts/check-privacy.sh`（= `make check`）在提交前扫一遍**被跟踪的**文件里
   有没有手机号、真实邮箱、私人内容文件或生成物。

   再建一个 `.identifiers` 文件（已在 .gitignore 里），一行一个写上你的姓名、
   个人域名、雇主名，改示例时手滑粘了真东西进去会被当场拦住：

   ```bash
   cat > .identifiers <<'EOF'
   张三
   yourdomain.com
   某某科技有限公司
   EOF
   ```

   有些标识是你**故意**公开的——比如示例简历里当署名的个人域名。这种在竖线右边
   列出允许出现的文件（空格分隔），出现在别处照样报错：

   ```
   yourdomain.com | content.example.toml
   ```
4. **预览图不许过期。** README 顶部那张 `examples/preview.png` 是渲染产物：改了示例
   内容或版式却忘了重渲，README 上就会一直挂着旧内容。`examples/preview.sha256`
   记着三份输入（`content.example.toml` + `theme.toml` + `resume.css`）的哈希，
   对不上 `make check` 就报错。改完示例跑一次 `make preview`，它会重渲、覆盖图片、
   更新哈希，两个文件一起提交。

   ⚠️ **不要把这些串写进脚本本身**——脚本是公开仓库的一部分，写进去等于亲手
   公开你本想拦截的东西。`.identifiers` 存在才做这项检查，不存在就跳过。

**更稳的做法**：把真实内容文件放在本仓库之外（比如另一个私有仓库、或
`~/.private/resume/me.toml`），用 `--content` 指过来。这样连"误改 .gitignore"
这条路都堵死了：

```bash
python render.py --content ~/.private/resume/me.toml --out-dir ~/.private/resume/build
```

---

## 快速开始

```bash
git clone https://github.com/<你的账号>/onepage-resume.git
cd onepage-resume

# 系统依赖见下一节，先装好再继续
make setup                       # 建 venv 装 weasyprint
make example                     # 渲染虚构示例，确认环境是通的

make fill                        # 填空：一题一题问，写出 content.toml
make render                      # 出 build/<你起的文件名>.pdf
```

没有 `make` 就用原始命令：

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python fill.py
.venv/bin/python render.py
```

### 两种填法，挑一种

**一、被问着填**（第一次用推荐）

```bash
python fill.py
```

一题一题往下走，每题都带一句解释和一个例子。回车 = 跳过选填项；数组类的
（联系方式、技能、经历、项目）每填完一条会问你要不要再来一条；Ctrl-C 随时退出，
**不会写半份文件**。

再跑一次就是"改一处"：它会先把已有的 `content.toml` 读进来，每题显示当前值，
回车保留、输入覆盖。覆盖前旧文件会备份成 `content.toml.bak`（同样不进 Git）。

**二、自己在编辑器里填**

```bash
python fill.py --blank           # 生成 content.toml：每个空都在，但都空着
python fill.py --blank --sample  # 想先看版面，就用带示例答案的那一份
$EDITOR content.toml
```

表单里每个空上面都有一行注释，写清楚这个空是干什么的、该写多长、例子长什么样。
数组表想加一条就整段复制粘贴。

**空没填完会怎样**：渲染时被拦下来，逐条告诉你哪个表的哪个字段还空着——
不会渲染出一份带着空标题的 PDF，那种"看上去成功了"的 PDF 最容易被直接发出去。

```bash
python fill.py --check           # 只检查，不渲染
```

---

## 环境准备

WeasyPrint 不是纯 Python，它要 `dlopen` 系统的 pango / cairo / harfbuzz /
fontconfig。中文字体推荐 Noto Sans CJK SC + Noto Serif CJK SC——**字体会被嵌进
PDF**，所以对方电脑上没装也能看到一样的排版。

### Ubuntu / Debian / WSL2

```bash
sudo apt update
sudo apt install -y python3-venv python3-pip \
  libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b libfontconfig1 libcairo2 \
  fonts-noto-cjk fonts-noto-cjk-extra fonts-noto-core \
  poppler-utils
```

`poppler-utils` 提供 `pdftoppm`，只用来出 PNG 预览；不装的话 PDF 照常生成，
程序会打印一行"跳过"。

### macOS

```bash
brew install pango cairo harfbuzz poppler
brew install --cask font-noto-sans-cjk font-noto-serif-cjk
```

### 原生 Windows

**只是打开、投递已有的 PDF：什么都不用装**，字体已嵌入。

要在原生 Windows 上**重新生成**，有两个坎：一是那几个 DLL 不随 pip 包附带，得另装
GTK3 runtime 并加进 PATH；二是没有 Noto 系列时衬线会回落到 SimSun，而 **SimSun 没有
真 Bold**，姓名和栏目名会变成伪粗体，与验证过的版本不一致。

所以在 Windows 上推荐走 WSL2（见下一节），而不是折腾原生环境。

程序在生成前会检查字体：Linux / macOS 走 `fc-list`，原生 Windows 读注册表。
中文字体完全缺失时报警告，回落到非首选字体时给提示——不会静默生成一份方块 PDF。

---

## 在另一台机器的 WSL2 上生成自己的简历

从零开始的完整步骤。假设新机器上 WSL2 和 Ubuntu 已经装好了。

### 1. 进 WSL，确认在 Linux 文件系统里

```bash
cd ~            # 就是 /home/<你>，不要用 /mnt/c/...
pwd             # 应该显示 /home/<你>
```

> ⚠️ **不要把仓库放在 `/mnt/c/` 下面。** 跨文件系统的 I/O 慢一个数量级，
> WeasyPrint 读字体和写 PDF 都会明显卡；文件权限也会一团糟。

### 2. 装系统依赖

```bash
sudo apt update
sudo apt install -y git python3-venv python3-pip \
  libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b libfontconfig1 libcairo2 \
  fonts-noto-cjk fonts-noto-cjk-extra fonts-noto-core \
  poppler-utils
fc-cache -fv                        # 刷新字体缓存
fc-list | grep -i "Noto Sans CJK"   # 有输出才算装上了
```

### 3. 克隆工具仓库并装依赖

```bash
git clone https://github.com/<你的账号>/onepage-resume.git ~/onepage-resume
cd ~/onepage-resume
make setup
make example        # 出 build/example/resume.pdf 就说明环境通了
```

**先跑 `make example`。** 环境问题（缺 DLL、缺字体）会在这一步暴露，
这时候还没有牵涉你的真实数据，排查干净。

### 4. 把你的真实内容文件弄过来

这一份**不在**公开仓库里，得手动搬。三条路，按推荐程度：

- **放进你的私有仓库**（推荐）：真实内容常年住在一个 private repo 里，
  新机器上 `git clone` 那个私有仓库，然后用 `--content` 指过去。
  换机器、回滚、多版本都有 Git 兜底。
- **加密后随便传**：`age` 或 `gpg -c` 加密成一个文件，走网盘 / 邮件都行，
  在新机器上解密。
- **手动重填**：`make fill` 照着旧的抄一遍。最笨但零传输风险。

❌ **不要**把真实内容 push 进这个公开仓库来"同步"，哪怕只是一次、哪怕马上删掉——
Git 历史留着，GitHub 的缓存和各种镜像爬虫也留着。

### 5. 生成

内容文件放在仓库里（叫 `content.toml`）：

```bash
cd ~/onepage-resume
make render
# 或： .venv/bin/python render.py
```

内容文件放在仓库外：

```bash
cd ~/onepage-resume
.venv/bin/python render.py \
  --content ~/private-resume/content.toml \
  --out-dir ~/private-resume/build
```

第一行会打印这次用的是哪个内容文件。看到"虚构示例"字样，说明你的文件没被找到——
检查文件名拼写。

### 6. 在 Windows 里打开 / 投递

```bash
explorer.exe build            # 在 Windows 资源管理器里打开生成目录
# 或者直接拷到 Windows 桌面
cp build/resume.pdf /mnt/c/Users/<你的Windows用户名>/Desktop/
```

投递前肉眼过一遍 `build/resume.png`，再发 `build/resume.pdf`。

### 7. 提交前体检（只有你改了工具本身才需要）

```bash
make check      # 或 ./scripts/check-privacy.sh
git status      # 不该出现 content.toml / build/ 里的任何东西
```

---

## 文件职责

- `schema.py` —— **字段表：这份简历一共有哪些"空"，只在这里定义一次。**
  `fill.py` 照着它提问，`fill.py --blank` 照着它生成空白表单，`render.py` 照着它
  检查空白。加一个字段只改这一处，三边自动跟上——分开写迟早会出现"问卷问了但渲染
  不认"的字段。
- `fill.py` —— 填空程序。交互提问、生成空白表单、检查空白，最后写出内容 TOML。
- `content.example.toml` —— 虚构示例，仓库里跟踪的就是它。改版面结构（新增技能行、
  调整经历顺序）时才动它，改完把同样的改动同步到你自己的内容文件，并跑一次
  `make preview` 刷新预览图，否则 `make check` 会拦下来。
- `content.toml` / `content.local.toml` / `content.*.toml` —— **你要投出去的那一份。**
  全部被 gitignore。查找优先级：`content.local.toml` → `content.toml` →
  `content.example.toml`。
- `theme.toml` —— 设计令牌：字体、颜色、页边距、字号、间距、线宽。每一项都会变成
  一个 CSS 变量。
- `theme.en.toml` —— 英文版式。用 `extends = "theme.toml"` 继承上面那份，只写不同的
  几项（竖脊更宽——英文栏目名塞不进两个中文字的宽度；行距更紧——纯西文不需要中文
  那么松的行距）。写英文简历时 `--theme theme.en.toml`。
- `resume.css` —— 版式规则。文件开头写了五条设计约束，改版式前先读。
- `render.py` —— 渲染程序。正常维护内容时不要编辑。
- `examples/preview.png` —— README 顶部那张图，由 `make preview` 生成。跟踪。
- `examples/preview.sha256` —— 上面那张图对应的输入哈希，`make check` 用它判断图是否
  过期。跟踪，由 `make preview` 写入，不要手改。
- `build/` —— 生成物。不跟踪。

## 命令行参数

```
python fill.py [--out PATH] [--blank] [--sample] [--check]
```

- `--out` 写到哪，默认 `content.toml`。写成 `-` 就打到标准输出。
  真实内容建议写到仓库外：`python fill.py --out ~/.private/resume/me.toml`。
- `--blank` 不提问，直接生成一份空白表单。
- `--sample` 配合 `--blank`：把示例答案填进去，用来先看版面。**投递前必须自己重填。**
- `--check` 只检查 `--out` 指的那个文件还有哪些空没填。

```
python render.py [--content PATH] [--theme PATH] [--css PATH]
                 [--out-dir DIR] [--name BASENAME]
```

- `--content` 内容 TOML 路径。省略时按上面的优先级在脚本目录里找。
- `--theme` / `--css` 换一套设计令牌或版式。英文简历用 `--theme theme.en.toml`；
  自己做变体时新建一份，开头写 `extends = "theme.toml"`，只列要改的令牌。
- `--out-dir` 生成物目录，默认 `build/`。
- `--name` 生成物文件名主干；不给就读 `[document]` 的 `output_basename`，
  再不给就是 `resume`。想投出去的附件叫 `张三-SEO-简历.pdf`，在内容文件里写
  `output_basename = "张三-SEO-简历"` 即可。

---

## 投递前检查

1. 删掉不适用于目标岗位的技能或项目。**不要靠缩小字号硬塞。**
2. 把 `[document]` 的 `preview_note` 和 `edition` 清空，页脚那行整条消失。
   带着"示例内容"字样投出去，等于告诉对方这是没填完的模板。
3. 重新生成，确认第一行打印的是你自己的内容文件。
4. 打开 `build/*.png` 复核，再发 `build/*.pdf`。
5. `git status` 应该是干净的。

## 改内容时的四个注意点

- **嫌挤先加间距，不要缩字号。** `theme.toml` 里 `section-gap` / `entry-gap` /
  `bullet-gap` / `skill-row-gap` 四个值专门管块与块之间的停顿。版面显得密，通常是因为
  没有停顿，不是因为字太大——缩字号只会让它既密又难读。加到装不下时程序会报错，
  那时该砍的是内容里的字。
- **一句话别拖到换行后只剩两三个字。** 这种"孤儿行"是全页最伤阅读的东西。改完看一眼
  PNG，发现了就把句子删掉几个字，通常砍掉句尾的评论性收尾就够了。
- **不可断空格**：示例里 `Looker Studio`、`Top 10`、`Cloudflare Pages` 中间是
  U+00A0 不换行空格，用来防止词组被拆到两行。新增同类词组时照着写，
  在 TOML 里也可以写成转义 `\u00A0`。
- **字重只有两档**：Noto CJK 只有 Regular 和 Bold。`resume.css` 里不要写
  `font-weight: 500`，会被静默降级成 Regular，标签和正文就分不出来了——
  HR 黑白打印时尤其明显。

## 排障

| 症状 | 原因 | 处理 |
|---|---|---|
| PDF 里中文是方块 | 没装 CJK 字体 | `sudo apt install fonts-noto-cjk && fc-cache -fv` |
| `cannot load library 'libgobject-2.0-0'` | 缺 pango / glib 系统库 | 按"环境准备"装齐 apt 包 |
| `渲染出了 2 页` | 内容超了 | 砍内容，别缩字号 |
| 打印"虚构示例" | 没找到你的内容文件 | 检查文件名，或用 `--content` 指定 |
| 没有 PNG | 缺 `pdftoppm` | `sudo apt install poppler-utils` |
| 字重不对 / 伪粗体 | 回落到了 SimSun | 装 Noto Serif CJK SC，或直接用 WSL2 |

## License

MIT，见 [LICENSE](LICENSE)。示例内容里的人名、公司、数字均为虚构；
顶部两条链接指向模板作者 [eigentime.org](https://eigentime.org)。
拿去改成你自己的，不用署名，留着也不介意。
