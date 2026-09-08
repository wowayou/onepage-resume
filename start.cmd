@echo off
rem ============================================================
rem  onepage-resume -- Windows double-click entry
rem
rem  What it does: enter the default WSL distro, cd to this repo, run
rem  "make boot" (system deps + venv + example smoke test), start the
rem  web UI, wait for the port, then open the browser on the Windows side.
rem
rem  Notes:
rem   - Needs WSL2 and an Ubuntu distro.
rem   - The repo may live on C:\ (mapped to /mnt/c/...): it works, but I/O
rem     is slow and live preview lags. For regular use, clone into /home
rem     inside WSL instead.
rem   - Relies on WSL2 forwarding 127.0.0.1 into the distro, which is on by
rem     default. If it is off, the wait loop below times out and says so.
rem
rem  THIS FILE IS ASCII-ONLY WITH CRLF LINE ENDINGS, ON PURPOSE.
rem  cmd.exe parses a .cmd under the console's OEM codepage, so UTF-8 bytes
rem  are misread -- a GBK lead byte swallows the newline and the next line
rem  gets run as a command. LF endings break goto and labels the same way.
rem  Both are enforced by .gitattributes and by tests/test_start_cmd.py.
rem  Chinese documentation lives in README.md.
rem ============================================================
setlocal EnableExtensions
set "BASE=%~dp0"
if "%BASE:~-1%"=="\" set "BASE=%BASE:~0,-1%"

rem ---- 0. Is WSL there? ----
where wsl >nul 2>nul
if errorlevel 1 goto no_wsl
wsl.exe --status >nul 2>nul
if errorlevel 1 goto no_wsl

rem ---- 1. Can WSL see this repo? ----
wsl.exe --cd "%BASE%" -e bash -lc "test -f Makefile" >nul 2>nul
if errorlevel 1 goto not_reachable

rem ---- 2. One command to set the environment up (idempotent) ----
echo [onepage-resume] Repo: %BASE%
echo [onepage-resume] Running make boot: system deps + venv + example render.
echo [onepage-resume] The first run takes a few minutes.
wsl.exe --cd "%BASE%" -e bash -lc "make boot"
if errorlevel 1 goto boot_failed
echo [onepage-resume] Environment ready.

rem ---- 3. Start the service, wait for the port, then open the browser ----
rem --no-open turns off the WSL-side auto-open so we do not get two tabs.
start "onepage-resume web service" /min wsl.exe --cd "%BASE%" -e bash -lc ".venv/bin/python webui.py --no-open"

echo [onepage-resume] Waiting for the web service (up to 30 seconds)...
for /l %%i in (1,1,30) do (
    powershell -NoProfile -Command "try{if((Invoke-WebRequest 'http://127.0.0.1:8765' -UseBasicParsing -TimeoutSec 1).StatusCode -eq 200){exit 0}}catch{exit 1}" >nul 2>nul
    if not errorlevel 1 goto up
    timeout /t 1 /nobreak >nul
)
echo [onepage-resume] Gave up after 30 seconds: cannot reach http://127.0.0.1:8765
echo Two possible causes:
echo   - The service never started. Check the make boot output above, or the
echo     errors in that minimized window.
echo   - The service is up but Windows cannot reach it: WSL2
echo     localhostForwarding is off. See the troubleshooting table in README.md.
goto end

:up
start "" http://127.0.0.1:8765
echo [onepage-resume] Browser should be open now: http://127.0.0.1:8765
echo The web service runs in that minimized window. Close it to stop.
goto end

:no_wsl
echo [onepage-resume] No WSL found.
echo Install WSL2 and an Ubuntu distro first:
echo   wsl --install -d Ubuntu
echo Then run this file again.
goto end

:not_reachable
echo [onepage-resume] WSL cannot see this directory (no Makefile found).
echo Common causes:
echo   - The repo lives inside the WSL filesystem (\\wsl$\Ubuntu\home\...).
echo     Open a WSL shell, cd to the repo, and run:  make boot ^&^& make ui
echo   - The default distro has not finished its first-run setup. Open a WSL
echo     terminal once and let it complete.
goto end

:boot_failed
echo [onepage-resume] make boot failed. Match the errors above against the
echo troubleshooting table in README.md.
goto end

:end
endlocal
pause
