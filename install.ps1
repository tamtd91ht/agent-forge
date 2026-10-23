# Agent Forge installer for Windows. Run it from your project's root folder:
#
#   irm https://raw.githubusercontent.com/tamtd91ht/agent-forge/main/install.ps1 | iex
#
# What it does (ADR-0004):
#   1. installs or updates Agent Forge in ~/.agent-forge (its own Python venv + catalog);
#      nothing else on the machine is touched: no PATH change, nothing under ~/.claude
#   2. adds the /agent-forge-upgrade command to the current project (a tracked install that
#      `agent-forge rollback` can undo)
# Then open the project in Claude Code and run /agent-forge-upgrade.
#
# What it installs (safe by default, ADR-0007):
#   - a GitHub Release (the latest, or AGENT_FORGE_VERSION=vX.Y.Z to pin / roll back): the
#     wheel is downloaded from the release, its SHA-256 is checked against the release's
#     SHA256SUMS, and its Sigstore bundle is verified when `cosign` is on PATH (a warning
#     otherwise). A release that fails verification is not installed.
#   - never a moving branch unless you ask: when no release can be resolved (no network, no
#     release yet) the installer stops and installs nothing.
#
# Optional environment variables:
#   AGENT_FORGE_VERSION release tag to install, e.g. v0.3.0 (default: the latest GitHub Release)
#   AGENT_FORGE_REF     any branch or tag, installed from the GitHub archive WITHOUT checksum or
#                       signature verification (development only; overrides AGENT_FORGE_VERSION)
#   AGENT_FORGE_SOURCE  pip-installable source instead of GitHub (a local checkout)
#   AGENT_FORGE_INSTALL_DIR  install directory (default: ~/.agent-forge)

& {
    $ErrorActionPreference = 'Stop'
    $Repo = 'tamtd91ht/agent-forge'
    # Identity of the release workflow that signs every release file (docs/operations.md).
    $SignIdentityRe = "^https://github.com/$Repo/\.github/workflows/release\.yml@refs/tags/v"
    $SignIssuer = 'https://token.actions.githubusercontent.com'
    $Home_ = if ($env:AGENT_FORGE_INSTALL_DIR) { $env:AGENT_FORGE_INSTALL_DIR } else { Join-Path $HOME '.agent-forge' }
    $Venv = Join-Path $Home_ '.venv'
    $Bin = Join-Path $Home_ 'bin'
    $Project = (Get-Location).Path

    function Say($msg) { Write-Host "agent-forge: $msg" }
    function Fail($msg, $hint) {
        Say $msg
        if ($hint) { Say "hint: $hint" }
        throw "agent-forge: $msg"
    }
    function Fetch($url, $dest) {
        try {
            Invoke-WebRequest -Uri $url -OutFile $dest -UseBasicParsing -TimeoutSec 120
            return $true
        } catch {
            Remove-Item -Force -ErrorAction SilentlyContinue $dest
            return $false
        }
    }
    function LatestRelease {
        try {
            $r = Invoke-RestMethod -Uri "https://api.github.com/repos/$Repo/releases/latest" -UseBasicParsing -TimeoutSec 15
            return "$($r.tag_name)"
        } catch { return '' }
    }

    # 1. Python >= 3.11
    $py = $null
    foreach ($cand in @(@('py', '-3'), @('python'), @('python3'))) {
        $exe = $cand[0]
        if (-not (Get-Command $exe -ErrorAction SilentlyContinue)) { continue }
        $pyArgs = @($cand | Select-Object -Skip 1)
        $ok = & $exe @pyArgs -c 'import sys; print(int(sys.version_info >= (3, 11)))' 2>$null
        if ($LASTEXITCODE -eq 0 -and "$ok".Trim() -eq '1') { $py = $cand; break }
    }
    if (-not $py) {
        Fail 'Python 3.11 or newer is required. Install it from https://www.python.org/downloads/ and re-run this command.'
    }

    # 2. Resolve what to install: SOURCE > REF (unverified) > VERSION / latest release (verified).
    $Verified = 'none'
    $Download = $null
    if ($env:AGENT_FORGE_SOURCE) {
        $Source = $env:AGENT_FORGE_SOURCE
        $Ref = 'source'
    } elseif ($env:AGENT_FORGE_REF) {
        $Ref = $env:AGENT_FORGE_REF
        $Source = "https://github.com/$Repo/archive/$Ref.zip"
        Say "AGENT_FORGE_REF=$Ref`: installing from the GitHub archive WITHOUT checksum or signature verification (development only)"
    } else {
        $Ref = if ($env:AGENT_FORGE_VERSION) { $env:AGENT_FORGE_VERSION } else { LatestRelease }
        if (-not $Ref) {
            Fail "could not resolve the latest GitHub Release of $Repo (no network, or no release published yet); nothing was installed." `
                "pin a release with `$env:AGENT_FORGE_VERSION='vX.Y.Z' (https://github.com/$Repo/releases), or `$env:AGENT_FORGE_REF='main' for an unverified development install"
        }
        if ($Ref -notmatch '^v[0-9]') { Fail "AGENT_FORGE_VERSION must be a release tag like v0.3.0 (got '$Ref')" 'use AGENT_FORGE_REF for a branch' }
        $Version = $Ref.Substring(1)
        $Wheel = "agent_forge-$Version-py3-none-any.whl"
        $Base = "https://github.com/$Repo/releases/download/$Ref"
        $Download = Join-Path ([IO.Path]::GetTempPath()) ("agent-forge-" + [IO.Path]::GetRandomFileName())
        New-Item -ItemType Directory -Force -Path $Download | Out-Null
        Say "downloading release $Ref"
        if (-not (Fetch "$Base/$Wheel" (Join-Path $Download $Wheel))) {
            Fail "release $Ref has no $Wheel (https://github.com/$Repo/releases); nothing was installed." 'check the tag name, or pin another release with AGENT_FORGE_VERSION'
        }
        if (-not (Fetch "$Base/SHA256SUMS" (Join-Path $Download 'SHA256SUMS'))) {
            Fail "release $Ref has no SHA256SUMS; nothing was installed."
        }
        $Expected = ''
        foreach ($line in Get-Content (Join-Path $Download 'SHA256SUMS')) {
            $parts = $line.Trim() -split '\s+', 2
            if ($parts.Count -eq 2 -and $parts[1].TrimStart('*') -eq $Wheel) { $Expected = $parts[0].ToLower() }
        }
        if (-not $Expected) { Fail "SHA256SUMS of release $Ref does not list $Wheel; nothing was installed." }
        $Actual = (Get-FileHash -Algorithm SHA256 (Join-Path $Download $Wheel)).Hash.ToLower()
        if ($Actual -ne $Expected) {
            Fail "checksum mismatch for $Wheel (expected $Expected, got $Actual); nothing was installed." 'report this through SECURITY.md'
        }
        $Verified = 'sha256'
        if (Get-Command cosign -ErrorAction SilentlyContinue) {
            if (-not (Fetch "$Base/$Wheel.sigstore.json" (Join-Path $Download "$Wheel.sigstore.json"))) {
                Fail "release $Ref has no Sigstore bundle for $Wheel; nothing was installed."
            }
            & cosign verify-blob --bundle (Join-Path $Download "$Wheel.sigstore.json") `
                --certificate-identity-regexp $SignIdentityRe --certificate-oidc-issuer $SignIssuer `
                (Join-Path $Download $Wheel) 2>$null | Out-Null
            if ($LASTEXITCODE -ne 0) { Fail "Sigstore verification failed for $Wheel; nothing was installed." 'report this through SECURITY.md' }
            $Verified = 'sha256,sigstore'
        } else {
            Say 'cosign not found: SHA-256 checked, Sigstore signature not verified (install cosign to verify: https://docs.sigstore.dev/cosign/system_config/installation/)'
        }
        $Source = Join-Path $Download $Wheel
    }

    try {
        # 3. engine in ~/.agent-forge/.venv
        New-Item -ItemType Directory -Force -Path $Home_, $Bin | Out-Null
        $venvPy = Join-Path $Venv 'Scripts\python.exe'
        if (-not (Test-Path $venvPy)) {
            Say "creating $Venv"
            $pyArgs = @($py | Select-Object -Skip 1)
            & $py[0] @pyArgs -m venv $Venv
            if ($LASTEXITCODE -ne 0) { throw 'could not create the virtual environment' }
        }
        Say "installing Agent Forge $Ref"
        & $venvPy -m pip install --quiet --disable-pip-version-check --upgrade --force-reinstall $Source
        if ($LASTEXITCODE -ne 0) { throw 'pip install failed' }
    } finally {
        if ($Download) { Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $Download }
    }

    # 4. launchers: agent-forge (bash, used by Claude Code) and agent-forge.cmd (PowerShell / cmd).
    #    Written only when their content changed: a launcher that is running this installer
    #    (self-update, exit code 16) must not be rewritten under itself.
    function WriteIfChanged($path, $text) {
        $current = if (Test-Path $path) { [IO.File]::ReadAllText($path) } else { $null }
        if ($current -ne $text) {
            [IO.File]::WriteAllText("$path.new", $text)
            Move-Item -Force "$path.new" $path
        }
    }
    $sh = (@(
        '#!/bin/sh',
        '# Agent Forge launcher v2 (generated by the installer). Exit code 16 from the engine',
        '# means a newer release is waiting in UPDATE_TO: install it (verified) and re-run once.',
        'd="$(cd "$(dirname "$0")/.." && pwd)"',
        'export AGENT_FORGE_HOME="$d" AGENT_FORGE_LAUNCHER=2',
        'af="$d/.venv/bin/agent-forge"; [ -x "$af" ] || af="$d/.venv/Scripts/agent-forge.exe"',
        '"$af" "$@"; code=$?',
        '[ "$code" -eq 16 ] || exit "$code"',
        'AGENT_FORGE_VERSION="$(cat "$d/UPDATE_TO" 2>/dev/null)"; rm -f "$d/UPDATE_TO"',
        'export AGENT_FORGE_VERSION AGENT_FORGE_INSTALL_DIR="$d"',
        'if [ -n "$AGENT_FORGE_INSTALLER" ]; then bash "$AGENT_FORGE_INSTALLER"; else curl -fsSL https://raw.githubusercontent.com/tamtd91ht/agent-forge/main/install.sh | bash; fi || exit 13',
        'exec "$af" "$@" --no-self-update'
    ) -join "`n") + "`n"
    WriteIfChanged (Join-Path $Bin 'agent-forge') $sh
    $cmd = (@(
        '@echo off',
        'rem Agent Forge launcher v2 (generated by the installer). Exit code 16 from the engine',
        'rem means a newer release is waiting in UPDATE_TO: install it (verified) and re-run once.',
        'setlocal enabledelayedexpansion',
        'set "AGENT_FORGE_HOME=%~dp0.."',
        'set "AGENT_FORGE_LAUNCHER=2"',
        '"%~dp0..\.venv\Scripts\agent-forge.exe" %*',
        'set "code=!errorlevel!"',
        'if not "!code!"=="16" exit /b !code!',
        'set /p AGENT_FORGE_VERSION=<"%~dp0..\UPDATE_TO"',
        'del /q "%~dp0..\UPDATE_TO"',
        'set "AGENT_FORGE_INSTALL_DIR=%~dp0.."',
        'if defined AGENT_FORGE_INSTALLER (powershell -NoProfile -ExecutionPolicy Bypass -File "%AGENT_FORGE_INSTALLER%") else (powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://raw.githubusercontent.com/tamtd91ht/agent-forge/main/install.ps1 | iex")',
        'if errorlevel 1 exit /b 13',
        '"%~dp0..\.venv\Scripts\agent-forge.exe" %* --no-self-update',
        'exit /b !errorlevel!'
    ) -join "`r`n") + "`r`n"
    WriteIfChanged (Join-Path $Bin 'agent-forge.cmd') $cmd
    $af = Join-Path $Bin 'agent-forge.cmd'

    # 5. what was installed, for `agent-forge doctor`
    $installedVersion = ((& $af --version) -join '') -replace '^agent-forge\s*', ''
    $stamp = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
    [IO.File]::WriteAllText((Join-Path $Home_ 'VERSION'), "ref=$Ref`nverified=$Verified`ninstalled_at=$stamp`nversion=$installedVersion`n")

    # 6. catalog (workspace) in ~/.agent-forge
    if (Test-Path (Join-Path $Home_ 'agent-forge.yaml')) {
        & $af init --workspace $Home_ --refresh-registry | Out-Null
    } else {
        & $af init --workspace $Home_ | Out-Null
    }
    if ($LASTEXITCODE -ne 0) { throw 'could not prepare the Agent Forge workspace' }
    Say "installed $Ref in $Home_ (verified: $Verified)"

    # 7. the /agent-forge-upgrade command in this project
    $resolvedHome = (Resolve-Path $HOME).Path.TrimEnd('\')
    if ($Project.TrimEnd('\') -eq $resolvedHome -or $Project.StartsWith((Resolve-Path $Home_).Path)) {
        Say 'run this command again from your project root to add /agent-forge-upgrade to it.'
        return
    }
    & $af setup $Project
    if ($LASTEXITCODE -ne 0) { throw 'could not add /agent-forge-upgrade to this project' }
}
