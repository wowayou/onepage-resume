# 常用动作。没有 make 也没关系，每条规则下面就是原始命令。
VENV ?= .venv
PY   := $(VENV)/bin/python
PIP  := $(VENV)/bin/pip

.PHONY: help setup render example check clean

help:
	@echo "make setup    创建 venv 并装依赖（系统依赖见 README）"
	@echo "make render   渲染你自己的简历到 build/"
	@echo "make example  渲染虚构示例，用来确认环境是通的"
	@echo "make check    提交前的隐私体检"
	@echo "make clean    删掉 build/"

setup:
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt

render:
	$(PY) render.py

example:
	$(PY) render.py --content content.example.toml --out-dir build/example

check:
	./scripts/check-privacy.sh

clean:
	rm -rf build
