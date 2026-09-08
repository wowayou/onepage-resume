@echo off
rem ============================================================
rem  onepage-resume -- Windows double-click entry
rem
rem  What it does: enter WSL, cd to this repo, run "make boot" (system deps
rem  + venv + example smoke test), start the web UI, wait for the port,
rem  then open the browser on the Windows side.
rem
rem  It works from both places the repo can live:
rem   - Inside WSL (\\wsl.localhost\<distro>\home\...): the UNC path is
rem     parsed back into a distro name plus a Linux path, so the repo is
rem     reached with "wsl -d <distro> --cd /home/...". This is the
rem     recommended location and the fast one.
rem   - On a Windows drive (C:\...): works, but I/O is slow and live
rem     preview lags, because WSL reaches it through /mnt/c.
rem
rem  Relies on WSL2 forwarding 127.0.0.1 into the distro, which is on by
rem  default. If it is off, the wait loop below times out and says so.
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
if not "%errorlevel%"=="0" goto no_wsl
wsl.exe --status >nul 2>nul
if not "%errorlevel%"=="0" goto no_wsl

rem ---- 1. Where does this repo live? ----
rem A \\wsl.localhost\<distro>\... or \\wsl$\<distro>\... path is turned into
rem the distro name plus a real Linux path. Handing the UNC string straight to
rem --cd happens to work when that distro is the default one, but silently
rem resolves into the WRONG distro when it is not -- hence the explicit -d.
set "WSLDISTRO="
set "LINUXDIR="
set "P=%BASE%"
if /i "%P:~0,16%"=="\\wsl.localhost\" goto strip_localhost
if /i "%P:~0,7%"=="\\wsl$\" goto strip_dollar
goto on_windows_drive

:strip_localhost
set "P=%P:~16%"
goto split_unc

:strip_dollar
set "P=%P:~7%"
goto split_unc

:split_unc
rem Cleared first: with tokens=1*, a path that is just the distro root leaves
rem %%b unset, and UNCREST would silently keep whatever it held before.
set "UNCREST="
for /f "tokens=1* delims=\" %%a in ("%P%") do (
    set "WSLDISTRO=%%a"
    set "UNCREST=%%b"
)
if not defined WSLDISTRO goto on_windows_drive
set "LINUXDIR=/%UNCREST:\=/%"
echo [onepage-resume] Repo is inside WSL: %WSLDISTRO% : %LINUXDIR%
goto check_repo

:on_windows_drive
echo [onepage-resume] Repo on a Windows drive: %BASE%
echo [onepage-resume] Note: reached through /mnt/..., so I/O is slow and the
echo                  live preview lags. Cloning into WSL /home is faster.
goto check_repo

rem ---- 2. Can WSL actually see the repo? ----
:check_repo
rem "if errorlevel 1" means ">= 1", so it sails straight past a negative exit
rem code -- and wsl.exe answers -1 for a distro it cannot find. Compare instead.
call :runwsl "test -f Makefile"
if not "%errorlevel%"=="0" goto not_reachable

rem ---- 3. One command to set the environment up (idempotent) ----
echo [onepage-resume] Running make boot: system deps + venv + example render.
echo [onepage-resume] The first run takes a few minutes.
call :runwsl "make boot"
if not "%errorlevel%"=="0" goto boot_failed
echo [onepage-resume] Environment ready.

rem ---- 4. Start the service, wait for the port, then open the browser ----
rem --no-open turns off the WSL-side auto-open so we do not get two tabs.
if defined WSLDISTRO goto start_unc
start "onepage-resume web service" /min wsl.exe --cd "%BASE%" -e bash -lc ".venv/bin/python webui.py --no-open"
goto wait_for_port

:start_unc
start "onepage-resume web service" /min wsl.exe -d %WSLDISTRO% --cd "%LINUXDIR%" -e bash -lc ".venv/bin/python webui.py --no-open"

:wait_for_port
echo [onepage-resume] Waiting for the web service (up to 30 seconds)...
rem Inside this paren block it has to stay "if not errorlevel 1": %errorlevel%
rem would be expanded once when the block is parsed, not on each pass. Fine
rem here, because powershell exits exactly 0 or 1.
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
echo [onepage-resume] No Makefile next to this script, so this is not the repo.
echo Where this script thinks it is:
if defined WSLDISTRO echo   distro %WSLDISTRO%, directory %LINUXDIR%
if not defined WSLDISTRO echo   %BASE%
echo Common causes:
echo   - This is a copy of start.cmd that was moved out of the repo (Desktop,
echo     Downloads, ...). It only works from the repo root, next to Makefile.
echo   - The distro has not finished its first-run setup. Open a WSL terminal
echo     once and let it complete.
echo Either way, from a WSL shell this always works:
echo   cd /path/to/onepage-resume ^&^& make boot ^&^& make ui
goto end

:boot_failed
echo [onepage-resume] make boot failed. Match the errors above against the
echo troubleshooting table in README.md.
goto end

rem ---- Run one bash command in the right distro and directory ----
rem Kept in one place so the UNC and Windows-drive cases cannot drift apart.
rem -d must NOT be quoted: wsl.exe takes the quotes as part of the name and
rem answers WSL_E_DISTRO_NOT_FOUND. Distro names have no spaces, so this is safe.
:runwsl
if defined WSLDISTRO goto runwsl_unc
wsl.exe --cd "%BASE%" -e bash -lc "%~1"
goto :eof
:runwsl_unc
wsl.exe -d %WSLDISTRO% --cd "%LINUXDIR%" -e bash -lc "%~1"
goto :eof

:end
endlocal
pause
