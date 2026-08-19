@echo off
rem ===========================================================================
rem  start-server.bat -- bring the AI Browser Toolkit server up, safely.
rem
rem  `abt serve` never returns; running it inside an agent's tool call wedges
rem  that call forever. This script launches it as a DETACHED process with its
rem  output redirected to a file (so no inherited pipe is held open), then polls
rem  /health until the server answers and exits. It is always safe to run: if a
rem  server is already up it changes nothing and exits 0.
rem
rem  Usage:
rem    start-server.bat                 check, install deps, start, wait for ready
rem    start-server.bat --status        only report whether the server is up
rem    start-server.bat --no-wait       start and return immediately (no polling)
rem    start-server.bat --browser edge --port 9000 --headless
rem                                     any other flags are passed to `abt serve`
rem
rem  Exit codes: 0 = server is up   1 = failed to come up   2 = deps failed
rem ===========================================================================

setlocal EnableExtensions EnableDelayedExpansion

set "REPO=%~dp0"
if "%REPO:~-1%"=="\" set "REPO=%REPO:~0,-1%"
set "VENV=%REPO%\.venv"
set "VPY=%VENV%\Scripts\python.exe"
set "ABT=%VENV%\Scripts\abt.exe"
set "OUTLOG=%REPO%\server.log"
set "ERRLOG=%REPO%\server.err"

set "PORT=8765"
set "BROWSER=chrome"
set "ARGS="
set "MODE=start"
set "NOWAIT="
rem How long to wait for readiness: Chrome on the persistent profile can take
rem ~2 minutes on a cold start, so poll rather than sleep a fixed amount.
set "WAIT_SECONDS=30"

rem --- parse args -----------------------------------------------------------
:parse
if "%~1"=="" goto parsed
if /I "%~1"=="--status" ( set "MODE=status" & shift & goto parse )
if /I "%~1"=="--no-wait" ( set "NOWAIT=1" & shift & goto parse )
if /I "%~1"=="--port" ( set "PORT=%~2" & set "ARGS=!ARGS! --port %~2" & shift & shift & goto parse )
if /I "%~1"=="-p" ( set "PORT=%~2" & set "ARGS=!ARGS! --port %~2" & shift & shift & goto parse )
if /I "%~1"=="--browser" ( set "BROWSER=%~2" & shift & shift & goto parse )
rem Quoted so pass-through values with spaces (e.g. --profile "C:\my dir") survive.
set ARGS=!ARGS! "%~1"
shift
goto parse
:parsed

set "STATUS_URL=http://127.0.0.1:%PORT%/health"

rem A server on a non-default port gets its own log files, so starting one never
rem truncates the logs of the server already running on 8765.
if not "%PORT%"=="8765" (
    set "OUTLOG=%REPO%\server-%PORT%.log"
    set "ERRLOG=%REPO%\server-%PORT%.err"
)

rem --- 1. is it already running? --------------------------------------------
call :probe
if not errorlevel 1 (
    echo [abt] Server already running on 127.0.0.1:%PORT% -- nothing to do.
    exit /b 0
)

if /I "%MODE%"=="status" (
    echo [abt] No server on 127.0.0.1:%PORT%.
    exit /b 1
)

echo [abt] No server on 127.0.0.1:%PORT% -- starting one.

rem --- 2. dependencies ------------------------------------------------------
if not exist "%VPY%" (
    echo [abt] Creating virtualenv at %VENV% ...
    set "BASEPY="
    py -3 -c "import sys" >nul 2>&1 && set "BASEPY=py -3"
    if not defined BASEPY (
        python -c "import sys" >nul 2>&1 && set "BASEPY=python"
    )
    if not defined BASEPY (
        echo [abt] ERROR: no Python found on PATH. Install Python 3.11+ first.
        exit /b 2
    )
    !BASEPY! -m venv "%VENV%"
    if errorlevel 1 (
        echo [abt] ERROR: could not create the virtualenv.
        exit /b 2
    )
)

rem Cheap import check -- if the package and its deps resolve, skip pip entirely.
set "NEED_INSTALL="
if not exist "%ABT%" set "NEED_INSTALL=1"
if not defined NEED_INSTALL (
    "%VPY%" -c "import abt, selenium, fastapi, uvicorn, pydantic, httpx, typer" >nul 2>&1
    if errorlevel 1 set "NEED_INSTALL=1"
)

if defined NEED_INSTALL (
    echo [abt] Installing dependencies ^(editable install of %REPO%^) ...
    "%VPY%" -m pip install --quiet --upgrade pip
    "%VPY%" -m pip install --quiet -e "%REPO%"
    if errorlevel 1 (
        echo [abt] ERROR: pip install failed.
        exit /b 2
    )
    "%VPY%" -c "import abt, selenium, fastapi, uvicorn, pydantic, httpx, typer" >nul 2>&1
    if errorlevel 1 (
        echo [abt] ERROR: dependencies still missing after install.
        exit /b 2
    )
    echo [abt] Dependencies OK.
) else (
    echo [abt] Dependencies already satisfied.
)

rem --- 3. launch detached ---------------------------------------------------
rem `start` gives the server its own console, and the redirects mean it does not
rem inherit this script's stdout/stderr. Both together are what keep the caller
rem from being held open by a process that never exits.
echo [abt] Launching: abt serve --browser %BROWSER%%ARGS%
start "abt server" /MIN cmd /c ""%ABT%" serve --browser %BROWSER%%ARGS% > "%OUTLOG%" 2> "%ERRLOG%""

if defined NOWAIT (
    echo [abt] Launched detached. Check readiness with: "%~f0" --status
    exit /b 0
)

rem --- 4. poll until ready --------------------------------------------------
echo [abt] Waiting up to %WAIT_SECONDS%s for %STATUS_URL% ...
set /a TRIES=%WAIT_SECONDS%/2
for /l %%i in (1,1,%TRIES%) do (
    rem ping is the sleep that works with no console input attached
    ping -n 3 127.0.0.1 >nul 2>&1
    call :probe
    if not errorlevel 1 (
        echo [abt] Server is up on 127.0.0.1:%PORT%.
        exit /b 0
    )
)

echo [abt] ERROR: server did not answer within %WAIT_SECONDS%s.
echo [abt] --- last lines of %ERRLOG% ---
powershell -NoProfile -Command "if (Test-Path '%ERRLOG%') { Get-Content -LiteralPath '%ERRLOG%' -Tail 20 }" 2>nul
exit /b 1

rem --- helper: errorlevel 0 when /health answers ----------------------------
:probe
curl.exe -s -m 5 -o nul "%STATUS_URL%" >nul 2>&1
exit /b %errorlevel%
