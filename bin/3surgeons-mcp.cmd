@echo off
REM MCP server launcher for the 3-Surgeons plugin (Windows batch).
REM Resolves the Python environment automatically:
REM   1. Plugin-local .venv\
REM   2. User-level %USERPROFILE%\.3surgeons\.venv\
REM   3. System python (with three_surgeons on PYTHONPATH)
REM   4. Auto-bootstrap if nothing found
REM
REM Called by Claude Code / Codex / Gemini via MCP config.

setlocal enabledelayedexpansion

set "SCRIPT_DIR=%~dp0"
REM Remove trailing backslash
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"
for %%I in ("%SCRIPT_DIR%\..") do set "PLUGIN_ROOT=%%~fI"

REM --- 1. Plugin-local venv ---
set "LOCAL_PY=%PLUGIN_ROOT%\.venv\Scripts\python.exe"
if exist "%LOCAL_PY%" (
    "%LOCAL_PY%" -c "import sys; assert sys.version_info>=(3,10); import mcp; import three_surgeons" >nul 2>&1
    if not errorlevel 1 (
        "%LOCAL_PY%" -m three_surgeons.mcp.server %*
        exit /b %errorlevel%
    )
)

REM --- 2. User-level venv ---
set "USER_PY=%USERPROFILE%\.3surgeons\.venv\Scripts\python.exe"
if exist "%USER_PY%" (
    "%USER_PY%" -c "import sys; assert sys.version_info>=(3,10); import mcp; import three_surgeons" >nul 2>&1
    if not errorlevel 1 (
        "%USER_PY%" -m three_surgeons.mcp.server %*
        exit /b %errorlevel%
    )
)

REM --- 3. System python with PYTHONPATH fallback ---
if defined PYTHONPATH (
    set "PYTHONPATH=%PLUGIN_ROOT%;%PYTHONPATH%"
) else (
    set "PYTHONPATH=%PLUGIN_ROOT%"
)

for %%P in (python3 python py) do (
    where %%P >nul 2>&1
    if not errorlevel 1 (
        %%P -c "import sys; assert sys.version_info>=(3,10); import mcp; import three_surgeons" >nul 2>&1
        if not errorlevel 1 (
            %%P -m three_surgeons.mcp.server %*
            exit /b !errorlevel!
        )
    )
)

REM --- 4. Auto-bootstrap ---
echo 3-Surgeons: No runtime found. Attempting auto-bootstrap... >&2

for %%P in (python3 python py) do (
    where %%P >nul 2>&1
    if not errorlevel 1 (
        for /f "tokens=*" %%V in ('%%P -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2^>nul') do set "PY_VER=%%V"
        %%P -c "import sys; exit(0 if sys.version_info>=(3,10) else 1)" >nul 2>&1
        if not errorlevel 1 (
            set "BOOTSTRAP_VENV=%PLUGIN_ROOT%\.venv"
            echo   Creating venv at !BOOTSTRAP_VENV! ... >&2
            %%P -m venv "!BOOTSTRAP_VENV!" 2>nul
            if not errorlevel 1 (
                set "EXTRAS=mcp"
                if defined CONTEXTDNA_ADAPTER set "EXTRAS=mcp,contextdna"
                echo   Installing three-surgeons[!EXTRAS!] ... >&2
                "!BOOTSTRAP_VENV!\Scripts\pip.exe" install -q -e "%PLUGIN_ROOT%[!EXTRAS!]" 2>nul
                if not errorlevel 1 (
                    echo   Bootstrap complete. >&2
                    "!BOOTSTRAP_VENV!\Scripts\python.exe" -m three_surgeons.mcp.server %*
                    exit /b !errorlevel!
                )
            )
            echo   Bootstrap failed for %%P >&2
        )
    )
)

REM --- No runtime found ---
echo { >&2
echo   "code": "3S-MCP-MISS", >&2
echo   "passed": false, >&2
echo   "message": "Cannot find Python >=3.10 with mcp and three_surgeons installed", >&2
echo   "fix": "cd %PLUGIN_ROOT% && python -m venv .venv && .venv\Scripts\pip install -e .[mcp]" >&2
echo } >&2
exit /b 1
