#!/usr/bin/env bash
# 提交前的泄漏体检：只看 Git 真正跟踪的文件。
# 用法：  ./scripts/check-privacy.sh      （在 Makefile 里是 make check）
#
# 它拦四类东西：被跟踪的私人内容文件、被跟踪的生成物、
# 手机号 / 邮箱字面量、以及本人的真实标识串。
set -uo pipefail
cd "$(dirname "$0")/.."

fail=0
note() { printf '  %s\n' "$1"; }
bad()  { fail=1; printf '\033[31m✗ %s\033[0m\n' "$1"; }
ok()   { printf '\033[32m✓ %s\033[0m\n' "$1"; }

tracked=$(git ls-files)

# 1. 私人内容文件不该被跟踪
leaked=$(printf '%s\n' "$tracked" | grep -E '^content.*\.toml$' | grep -v '^content\.example\.toml$' || true)
if [ -n "$leaked" ]; then
  bad "这些内容文件被 Git 跟踪了（里面是真实信息）："
  printf '%s\n' "$leaked" | while read -r f; do note "$f"; done
  note "修：git rm --cached <文件>，然后确认 .gitignore 的 content*.toml 规则还在。"
else
  ok "没有私人内容文件被跟踪"
fi

# 2. 生成物不该被跟踪（PDF 的正文是可以直接被搜索的）
arts=$(printf '%s\n' "$tracked" | grep -E '^(build/|resume\.(pdf|html)$|preview\.png$)' || true)
if [ -n "$arts" ]; then
  bad "生成物被 Git 跟踪了：$(printf '%s ' $arts)"
else
  ok "没有生成物被跟踪"
fi

# 3. 手机号 / 非示例邮箱
hits=$(printf '%s\n' "$tracked" | xargs grep -nIE '1[3-9][0-9]{9}|[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}' 2>/dev/null \
       | grep -vE '@example\.(com|org|net)' || true)
if [ -n "$hits" ]; then
  bad "被跟踪的文件里出现了手机号或真实邮箱："
  printf '%s\n' "$hits" | cut -d: -f1,2 | sort -u | while read -r loc; do note "$loc"; done
else
  ok "没有手机号 / 真实邮箱"
fi

# 4. 本人的真实标识串。**不写在这个文件里**——本脚本是公开仓库的一部分，
#    把姓名和雇主名填进来等于亲手公开它们。改从 .identifiers 读，该文件在
#    .gitignore 里，一行一个，# 开头是注释。没有这个文件就跳过这一项。
ID_FILE="${IDENTIFIERS_FILE:-.identifiers}"
if [ -f "$ID_FILE" ]; then
  found=0
  while IFS= read -r id; do
    case "$id" in ''|\#*) continue ;; esac
    if printf '%s\n' "$tracked" | xargs grep -lIF -- "$id" 2>/dev/null | grep -q .; then
      files=$(printf '%s\n' "$tracked" | xargs grep -lIF -- "$id" 2>/dev/null | tr '\n' ' ')
      bad "被跟踪的文件里出现了 .identifiers 中的标识：$files"
      found=1
    fi
  done < "$ID_FILE"
  [ $found -eq 0 ] && ok "没有 .identifiers 里的标识串"
else
  note "（没有 $ID_FILE，跳过标识串检查。建议建一个，见 README）"
fi

echo
if [ $fail -eq 0 ]; then ok "体检通过"; else bad "体检未通过，先修再提交"; fi
exit $fail
