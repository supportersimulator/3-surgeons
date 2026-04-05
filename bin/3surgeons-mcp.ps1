# MCP server launcher for the 3-Surgeons plugin (PowerShell).
# Resolves the Python environment automatically:
#   1. Plugin-local .venv\
#   2. User-level ~\.3surgeons\.venv\
#   3. System python (with three_surgeons on PYTHONPATH)
#   4. Auto-bootstrap if nothing found
#
# Called by Claude Code / Codex / Gemini via MCP config.

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ScriptDir  = Split-Path -Parent $MyInvocation.MyCommand.Path
$PluginRoot = (Resolve-Path (Join-Path $ScriptDir '..')).Path

function Test-McpRuntime {
    param([string]$PythonExe)
    try {
        $proc = Start-Process -FilePath $PythonExe -ArgumentList @(
            '-c',
            'import sys; assert sys.version_info>=(3,10); import mcp; import three_surgeons'
        ) -NoNewWindow -Wait -PassThru -RedirectStandardError ([IO.Path]::GetTempFileName()) -RedirectStandardOutput ([IO.Path]::GetTempFileName())
        return $proc.ExitCode -eq 0
    } catch {
        return $false
    }
}

function Invoke-McpServer {
    param([string]$PythonExe, [string[]]$ExtraArgs)
    $allArgs = @('-m', 'three_surgeons.mcp.server') + $ExtraArgs
    $proc = Start-Process -FilePath $PythonExe -ArgumentList $allArgs -NoNewWindow -Wait -PassThru
    exit $proc.ExitCode
}

# --- 1. Plugin-local venv ---
$LocalPy = Join-Path $PluginRoot '.venv\Scripts\python.exe'
if (Test-Path $LocalPy) {
    if (Test-McpRuntime $LocalPy) {
        Invoke-McpServer $LocalPy $args
    }
}

# --- 2. User-level venv ---
$UserPy = Join-Path $env:USERPROFILE '.3surgeons\.venv\Scripts\python.exe'
if (Test-Path $UserPy) {
    if (Test-McpRuntime $UserPy) {
        Invoke-McpServer $UserPy $args
    }
}

# --- 3. System python with PYTHONPATH fallback ---
if ($env:PYTHONPATH) {
    $env:PYTHONPATH = "$PluginRoot;$env:PYTHONPATH"
} else {
    $env:PYTHONPATH = $PluginRoot
}

foreach ($cmd in @('python3', 'python', 'py')) {
    $found = Get-Command $cmd -ErrorAction SilentlyContinue
    if ($found) {
        if (Test-McpRuntime $found.Source) {
            Invoke-McpServer $found.Source $args
        }
    }
}

# --- 4. Auto-bootstrap ---
Write-Host '3-Surgeons: No runtime found. Attempting auto-bootstrap...' -ForegroundColor Yellow

foreach ($cmd in @('python3', 'python', 'py')) {
    $found = Get-Command $cmd -ErrorAction SilentlyContinue
    if (-not $found) { continue }

    $pyExe = $found.Source
    try {
        $verProc = Start-Process -FilePath $pyExe -ArgumentList @(
            '-c', 'import sys; exit(0 if sys.version_info>=(3,10) else 1)'
        ) -NoNewWindow -Wait -PassThru -RedirectStandardError ([IO.Path]::GetTempFileName()) -RedirectStandardOutput ([IO.Path]::GetTempFileName())
        if ($verProc.ExitCode -ne 0) { continue }
    } catch { continue }

    $BootstrapVenv = Join-Path $PluginRoot '.venv'
    Write-Host "  Creating venv at $BootstrapVenv ..." -ForegroundColor Yellow

    try {
        $venvProc = Start-Process -FilePath $pyExe -ArgumentList @('-m', 'venv', $BootstrapVenv) -NoNewWindow -Wait -PassThru -RedirectStandardError ([IO.Path]::GetTempFileName())
        if ($venvProc.ExitCode -ne 0) { throw 'venv creation failed' }
    } catch {
        Write-Host "  Bootstrap failed for $cmd" -ForegroundColor Red
        continue
    }

    $extras = 'mcp'
    if ($env:CONTEXTDNA_ADAPTER) { $extras = 'mcp,contextdna' }

    $pipExe = Join-Path $BootstrapVenv 'Scripts\pip.exe'
    Write-Host "  Installing three-surgeons[$extras] ..." -ForegroundColor Yellow

    try {
        $pipProc = Start-Process -FilePath $pipExe -ArgumentList @(
            'install', '-q', '-e', "$PluginRoot[$extras]"
        ) -NoNewWindow -Wait -PassThru -RedirectStandardError ([IO.Path]::GetTempFileName())
        if ($pipProc.ExitCode -ne 0) { throw 'pip install failed' }
    } catch {
        Write-Host "  Bootstrap failed for $cmd" -ForegroundColor Red
        continue
    }

    Write-Host '  Bootstrap complete.' -ForegroundColor Green
    $bootstrapPy = Join-Path $BootstrapVenv 'Scripts\python.exe'
    Invoke-McpServer $bootstrapPy $args
}

# --- No runtime found ---
$diag = @{
    code    = '3S-MCP-MISS'
    passed  = $false
    message = 'Cannot find Python >=3.10 with mcp and three_surgeons installed'
    fix     = "cd $PluginRoot; python -m venv .venv; .venv\Scripts\pip install -e '.[mcp]'"
}
Write-Error ($diag | ConvertTo-Json -Compress)
exit 1
