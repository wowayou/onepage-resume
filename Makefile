# 常用动作。没有 make 也没关系，每条规则下面就是原始命令。
VENV ?= .venv
PY   := $(VENV)/bin/python
PIP  := $(VENV)/bin/pip

.PHONY: help setup fill blank render example preview check clean

# README 里那张预览图的三份输入。任何一份变了，图就过期了。
PREVIEW_SRC := content.example.toml theme.toml resume.css

help:
	@echo "make setup    创建 venv 并装依赖（系统依赖见 README）"
	@echo "make fill     填空：一题一题地填出 content.toml"
	@echo "make blank    生成一份空白表单，自己在编辑器里填"
	@echo "make render   渲染你自己的简历到 build/"
	@echo "make example  渲染虚构示例，用来确认环境是通的"
	@echo "make preview  重渲示例并更新 README 里的预览图（改完示例必跑）"
	@echo "make check    提交前的隐私体检"
	@echo "make clean    删掉 build/"

setup:
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt

fill:
	$(PY) fill.py

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

clean:
	rm -rf build
