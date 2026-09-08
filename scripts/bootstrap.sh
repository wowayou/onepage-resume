#!/usr/bin/env bash
# 开箱即用的前半：把 WeasyPrint 需要的系统库和 CJK 字体装齐。
#
# 幂等：已经装好的包不会再碰（避免每次都跳出来要 sudo）；只有确实缺东西
# 才去动包管理器。跑完 `make boot` 的另一半（venv + 依赖 + 渲染示例）自然跟上。
#
# 支持：Debian / Ubuntu / WSL2（apt-get）和 macOS（Homebrew）。
# 原生 Windows 不在这份脚本里——见仓库根目录的 start.cmd（走 WSL2）。

set -euo pipefail

cd "$(dirname "$0")/.."          # 仓库根目录

say() { printf '\033[1;36m[bootstrap]\033[0m %s\n' "$*"; }
die() { printf '\033[1;31m[bootstrap] 出错：\033[0m%s\n' "$*" >&2; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }

# ---------------- 先探清包管理器 ----------------

USE_BREW=""
if have apt-get; then
    USE_BREW=""
elif have brew; then
    USE_BREW="1"
else
    die "没认出包管理器：需要 apt-get（Debian/Ubuntu/WSL2）或 Homebrew（macOS）。原生 Windows 请用根目录 start.cmd（内部走 WSL2）。"
fi

# ---------------- 每个平台缺什么包 ----------------

apt_missing() {   # 输出：还缺哪些 apt 包（换行分隔；一个都不缺就什么都不输出）
    local p out=()
    for p in "$@"; do
        dpkg-query -W -f='${Status}' "$p" 2>/dev/null | grep -q "install ok installed" \
            || out+=("$p")
    done
    [ "${#out[@]}" -gt 0 ] && printf '%s\n' "${out[@]}"
}

brew_missing() {  # 输出：缺哪些 formula（同样：不缺就什么都不输出）
    local p out=()
    for p in "$@"; do
        brew list --versions "$p" >/dev/null 2>&1 || out+=("$p")
    done
    [ "${#out[@]}" -gt 0 ] && printf '%s\n' "${out[@]}"
}

FONTS_APT=(fonts-noto-cjk fonts-noto-cjk-extra fonts-noto-core)
FONTS_BREW_CASK=(font-noto-sans-cjk font-noto-serif-cjk)

if [ -n "$USE_BREW" ]; then
    mapfile -t SYS < <(brew_missing pango cairo harfbuzz poppler make)
    mapfile -t CASKS < <(brew_missing "${FONTS_BREW_CASK[@]}")
    [ "${#SYS[@]}" -eq 0 ] && [ "${#CASKS[@]}" -eq 0 ] && say "系统依赖已齐全，跳过安装。"
    if [ "${#SYS[@]}" -gt 0 ]; then
        say "将安装（brew）：${SYS[*]}"
        brew install "${SYS[@]}"
    fi
    if [ "${#CASKS[@]}" -gt 0 ]; then
        say "将安装字体（brew --cask）：${CASKS[*]}"
        brew install --cask "${CASKS[@]}"
    fi
else
    mapfile -t SYS < <(apt_missing \
        libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b libfontconfig1 libcairo2 \
        poppler-utils make ca-certificates python3-venv python3-pip "${FONTS_APT[@]}")
    if [ "${#SYS[@]}" -eq 0 ]; then
        say "系统依赖已齐全，跳过安装。"
    else
        say "还缺这些系统包：${SYS[*]}"
        apt_install() {   # $@ = 要装的包
            "${SUDO[@]}" apt-get update -qq
            "${SUDO[@]}" apt-get install -y --no-install-recommends "$@"
            fc-cache -f >/dev/null 2>&1 || true   # 刚装了字体，刷新缓存
        }
        SUDO=()
        if [ "$(id -u)" -eq 0 ]; then
            :
        elif have sudo && [ -t 0 ]; then
            SUDO=(sudo)               # 交互终端：sudo 可以正常要密码
        elif have sudo && sudo -n true 2>/dev/null; then
            SUDO=(sudo)               # 非交互但已配好免密 sudo
        else
            # 没有交互终端、sudo 又要密码：不硬失败，把命令打印出来让用户自己跑。
            # 若缺的正是 pango/cairo，随后的 make example 会以缺库报错点出来。
            say "没有交互终端，跳过自动安装。请手动执行下面这行再重跑 make boot："
            printf '    sudo apt-get update && sudo apt-get install -y --no-install-recommends %s\n' "${SYS[*]}"
        fi
        if [ "$(id -u)" -eq 0 ] || [ "${#SUDO[@]}" -gt 0 ]; then
            apt_install "${SYS[@]}"
        fi
    fi
fi

# ---------------- 校验：中文字体在不在 ----------------

# 别用 grep -q：pipefail 下它一命中就提前退出，让 fc-list 写管道撞 SIGPIPE，
# 整条被误判成失败（rc=141）。用 -i + 读全量输出的方式。
if have fc-list && fc-list | grep -i "Noto Sans CJK" >/dev/null; then
    say "中文字体 Noto Sans CJK 就绪。"
else
    say "没找到 Noto Sans CJK（fc-list 无输出可能是没装 fontconfig）。"
    say "到这一步渲染仍会回落其它字体——先用 make example 看看再决定要不要补。"
fi

say "系统依赖就绪。下一步：make setup && make example"
