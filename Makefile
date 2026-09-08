# 常用动作。没有 make 也没关系，每条规则下面就是原始命令。
VENV ?= .venv
PY   := $(VENV)/bin/python
PIP  := $(VENV)/bin/pip

.PHONY: help boot bootstrap setup fill ui blank render example preview dist check test clean

# README 里那张预览图的三份输入。任何一份变了，图就过期了。
PREVIEW_SRC := content.example.toml theme.toml resume.css

# 可分发包的版本号：优先 git tag，没有 tag 就用提交短哈希。
VERSION ?= $(shell git describe --tags --always --dirty 2>/dev/null || echo 0.0.0-dev)

help:
	@echo "make boot      开箱即用：一条命令装齐系统库 + 字体 + venv + 依赖并渲染示例冒烟"
	@echo "make dist      打一个可分发的 tar.gz（内容取自 git HEAD；真实内容与 build/ 永不进）"
	@echo "make setup    建 venv 并装 Python 依赖（系统库交给 make boot 那一步）"
	@echo "make ui       浏览器里填：左边填字，右边实时看 A4（只听本机）"
	@echo "make fill     填空：一题一题地填出 content.toml"
	@echo "make blank    生成一份空白表单，自己在编辑器里填"
	@echo "make render   渲染你自己的简历到 build/"
	@echo "make example  渲染虚构示例，用来确认环境是通的"
	@echo "make preview  重渲示例并更新 README 里的预览图（改完示例必跑）"
	@echo "make check    提交前的隐私体检"
	@echo "make test     跑测试（标准库 unittest，不需要额外依赖）"
	@echo "make clean    删掉 build/"

setup:
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt

fill:
	$(PY) fill.py

# 浏览器版的填空。默认只听 127.0.0.1，同一台机器之外连不进来；
# 这个服务没有登录也没有口令，别加 --host 0.0.0.0。
ui:
	$(PY) webui.py

blank:
	$(PY) fill.py --blank

render:
	$(PY) render.py

example:
	$(PY) render.py --content content.example.toml --out-dir build/example

# 改完 content.example.toml / theme.toml / resume.css 就跑这个，否则 README 上
# 那张图会停留在旧内容——上一次泄漏就是这么来的。
preview: example
	cp build/example/resume.png examples/preview.png
	cat $(PREVIEW_SRC) | sha256sum | cut -d' ' -f1 > examples/preview.sha256
	@echo "已更新 examples/preview.png 与 examples/preview.sha256"

check:
	./scripts/check-privacy.sh

test:
	$(PY) -m unittest discover -s tests -v

# 开箱即用：系统库（bootstrap）→ venv + Python 依赖（setup）→ 渲染示例冒烟。
# 在全新机器上，只跑这一条就能确认环境通了。
boot:
	./scripts/bootstrap.sh
	$(MAKE) setup
	$(MAKE) example
	@echo "✔ 环境就绪。接下去：make ui（浏览器里填）或 make fill（命令行填）。"

# 只装系统库（不需要 venv / Python 依赖时用）。
bootstrap:
	./scripts/bootstrap.sh

# 可分发包：把 git HEAD 的跟踪文件打成 tar.gz（含 bootstrap.sh + Makefile + README，
# 端到端可自包含）。注意取的是已提交内容——改完没 commit 的不会进去。
dist:
	@mkdir -p dist
	git archive --format=tar.gz --prefix=onepage-resume/ \
		-o dist/onepage-resume-$(VERSION).tar.gz HEAD
	@echo "生成 dist/onepage-resume-$(VERSION).tar.gz"

clean:
	rm -rf build
