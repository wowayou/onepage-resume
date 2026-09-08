@echo off
rem ============================================================
rem  onepage-resume  Windows 双击入口
rem
rem  它做的事：在默认 WSL 发行版里 cd 到本仓库，跑 make boot
rem  （系统依赖 + venv + 渲染示例冒烟），然后把网页版 UI 起来，
rem  并在 Windows 浏览器里打开 http://127.0.0.1:8765 。
rem
rem  说明：
rem   - 需要已装 WSL2 和一个 Ubuntu 发行版。
rem   - 本仓库若在 C:\ 盘（会映射成 /mnt/c/...），功能正常但 I/O 慢、
rem     实时预览会迟钝；长期用建议把仓库 clone 进 WSL 的 /home 再在这里用。
rem   - 靠 WSL2 把 127.0.0.1 转发进发行版（默认就开着）。要是关了，下面那个
rem     等待循环会等满 30 秒然后告诉你——见 README「排障」的 localhostForwarding 一条。
rem ============================================================
setlocal EnableExtensions
set "BASE=%~dp0"
if "%BASE:~-1%"=="\" set "BASE=%BASE:~0,-1%"

rem ---- 0. WSL 在不在 ----
where wsl >nul 2>nul
if errorlevel 1 goto no_wsl
wsl.exe --status >nul 2>nul
if errorlevel 1 goto no_wsl

rem ---- 1. 确认仓库路径能被 WSL 看到 ----
wsl.exe --cd "%BASE%" -e bash -lc "test -f Makefile" >nul 2>nul
if errorlevel 1 goto not_reachable

rem ---- 2. 一条命令装齐环境（幂等，已装会跳过）----
echo [onepage-resume] 仓库（WSL 视角）：%BASE%
echo [onepage-resume] 正在 make boot：系统依赖 + venv + 渲染示例，首次要几分钟...
wsl.exe --cd "%BASE%" -e bash -lc "make boot"
if errorlevel 1 goto boot_failed
echo [onepage-resume] 环境就绪。

rem ---- 3. 起网页服务（独立小窗口里跑），等服务就绪再由 Windows 这边开浏览器 ----
rem 用 --no-open 关掉 WSL 里的自动开浏览器，避免在两边各开一个标签。
start "onepage-resume · 网页服务" /min wsl.exe --cd "%BASE%" -e bash -lc ".venv/bin/python webui.py --no-open"

echo [onepage-resume] 等待网页服务就绪（最多约 30 秒）...
for /l %%i in (1,1,30) do (
    powershell -NoProfile -Command "try{if((Invoke-WebRequest 'http://127.0.0.1:8765' -UseBasicParsing -TimeoutSec 1).StatusCode -eq 200){exit 0}}catch{exit 1}" >nul 2>nul
    if not errorlevel 1 goto up
    timeout /t 1 /nobreak >nul
)
echo [onepage-resume] 等了 30 秒还连不上 http://127.0.0.1:8765 。
echo 两种可能：
echo   - 服务没起来：看上方 make boot 的报错，或那个最小化小窗口里的报错。
echo   - 服务起来了但 Windows 连不进去：WSL2 的 localhostForwarding 被关了，
echo     见 README「排障」里对应的一条。
goto end

:up
start "" http://127.0.0.1:8765
echo [onepage-resume] 浏览器应已打开（http://127.0.0.1:8765）。
echo 网页服务在那个最小化的小窗口里，关掉它即停止。
goto end

:no_wsl
echo [onepage-resume] 没检测到 WSL。
echo 请先安装 WSL2 和一个 Ubuntu 发行版：
echo   wsl --install -d Ubuntu
echo 装完重开本文件即可。
goto end

:not_reachable
echo [onepage-resume] WSL 看不到这个目录（Makefile 没找到）。
echo 常见原因：
echo   - 仓库放在了 WSL 文件系统里（如 \\wsl$\Ubuntu\home\...）：请在 WSL 终端里
echo     cd 到仓库目录后直接运行：  make boot ^&^& make ui
echo   - 默认发行版尚未完成初始化：先开一次 WSL 终端让它跑完安装。
goto end

:boot_failed
echo [onepage-resume] make boot 失败了。把上面的报错贴给 README 的"排障"对照。
goto end

:end
endlocal
pause
