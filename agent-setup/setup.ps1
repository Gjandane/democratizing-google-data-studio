# Democratizing Google Data Studio: build agent setup for Windows (contracts/conventions.md, Build agent).
# Run it as the Build stage shows it, in Windows PowerShell 5.1 or PowerShell 7:
#   & ([scriptblock]::Create((irm https://raw.githubusercontent.com/Gjandane/democratizing-google-data-studio/main/agent-setup/setup.ps1))) -Server <origin> -Job <CODE>
# The setup step passes -Check <CODE> instead of -Job. Optional: -Update (fresh repo zip), -DryRun
# (rehearsal: no sign-in, the agent passes --dry-run), -Source <zip path or URL>, -Home <install folder>.
# Needs Google Chrome; installs uv when missing. No Git, .env or GCP project on this machine.
param(
    [string]$Server,
    [string]$Job,
    [string]$Check,
    [switch]$Update,
    [switch]$DryRun,
    [string]$Source,
    [Alias('Home')][string]$InstallDir
)

$RepoZip = 'https://github.com/Gjandane/democratizing-google-data-studio/archive/refs/heads/main.zip'
$Usage = 'Usage: setup.ps1 -Server <URL> (-Job <CODE> | -Check <CODE>) [-Update] [-DryRun] [-Source <zip>] [-Home <folder>]'
$EnvNames = 'DSS_CHROME_PROFILE', 'DSS_DATA_DIR', 'DSS_ENGINE_CMD'
$Result = @{ Code = 0 }
$ProgressPreference = 'SilentlyContinue'  # PS 5.1's Invoke-WebRequest crawls while it draws a progress bar

function Find-Chrome {
    # The engine's own lookup (dsengine chrome_path): DSS_CHROME_PATH alone when set, else the usual places.
    $candidates = if ($env:DSS_CHROME_PATH) { @($env:DSS_CHROME_PATH) } else { @(
        (Get-Command google-chrome, google-chrome-stable -CommandType Application -ErrorAction SilentlyContinue |
            Select-Object -ExpandProperty Source),
        (Join-Path $(if ($env:ProgramFiles) { $env:ProgramFiles } else { 'C:\Program Files' }) 'Google\Chrome\Application\chrome.exe'),
        (Join-Path "$env:LOCALAPPDATA" 'Google\Chrome\Application\chrome.exe'),
        'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe',
        '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
    ) }
    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path -LiteralPath $candidate -PathType Leaf)) { return $candidate }
    }
    return $null
}

function Install-Uv {
    if (Get-Command uv -ErrorAction SilentlyContinue) { return $true }
    Write-Host 'Installing uv (https://docs.astral.sh/uv/) ...'
    powershell -NoProfile -ExecutionPolicy Bypass -Command 'irm https://astral.sh/uv/install.ps1 | iex' | Out-Host
    $env:Path = (Join-Path $HOME '.local\bin') + [IO.Path]::PathSeparator + $env:Path
    return [bool](Get-Command uv -ErrorAction SilentlyContinue)
}

function Get-App([string]$app) {
    # Download (or copy, with -Source) the repo zip and put its one top folder at app/; the rest of
    # the install folder (chrome-profile/, data/) stays as it is.
    $temp = Join-Path $InstallDir ('download-' + [guid]::NewGuid().ToString('N').Substring(0, 8))
    New-Item -ItemType Directory -Path $temp -Force | Out-Null
    try {
        $zip = Join-Path $temp 'repo.zip'
        $from = if ($Source) { $Source } else { $RepoZip }
        if ($from -match '^https?://') {
            Write-Host "Downloading $from ..."
            [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
            Invoke-WebRequest -UseBasicParsing -Uri $from -OutFile $zip -ErrorAction Stop
        } else {
            Write-Host "Copying $from ..."
            Copy-Item -LiteralPath $from -Destination $zip -ErrorAction Stop
        }
        $unpacked = Join-Path $temp 'unpacked'
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        [IO.Compression.ZipFile]::ExtractToDirectory($zip, $unpacked)
        $top = @(Get-ChildItem -LiteralPath $unpacked -Directory)
        if ($top.Count -ne 1 -or -not (Test-Path -LiteralPath (Join-Path $top[0].FullName 'backend\pyproject.toml')) -or
            -not (Test-Path -LiteralPath (Join-Path $top[0].FullName 'engine\pyproject.toml'))) {
            throw 'The zip is not this repository (no backend/ and engine/ under one top folder)'
        }
        if (Test-Path -LiteralPath $app) { Remove-Item -LiteralPath $app -Recurse -Force -ErrorAction Stop }
        Move-Item -LiteralPath $top[0].FullName -Destination $app -ErrorAction Stop
    } finally {
        Remove-Item -LiteralPath $temp -Recurse -Force -ErrorAction SilentlyContinue
    }
}

function Invoke-Setup {
    if (-not $Server -or [bool]$Job -eq [bool]$Check) {
        Write-Host $Usage
        $Result.Code = 2; return
    }
    if (-not (Find-Chrome)) {
        Write-Host 'Google Chrome is required: https://www.google.com/chrome/'
        $Result.Code = 1; return
    }
    if (-not (Install-Uv)) {
        Write-Host 'uv did not install; install it from https://docs.astral.sh/uv/ and rerun the setup command'
        $Result.Code = 1; return
    }

    if (-not $InstallDir) { $InstallDir = Join-Path $env:LOCALAPPDATA 'dss-agent' }
    New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
    $InstallDir = (Resolve-Path -LiteralPath $InstallDir).ProviderPath
    $app = Join-Path $InstallDir 'app'
    $marker = Join-Path $app '.dss-installed'
    if ($Update -or -not (Test-Path -LiteralPath $marker)) {
        Get-App $app
        foreach ($part in 'backend', 'engine') {
            Write-Host "Installing the $part (uv sync) ..."
            uv sync --no-dev --frozen --project (Join-Path $app $part) | Out-Host
            if ($LASTEXITCODE -ne 0) {
                Write-Host "uv sync failed for the $part; rerun the setup command with -Update"
                $Result.Code = 1; return
            }
        }
        Set-Content -LiteralPath $marker -Value (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ') -Encoding ASCII
    } else {
        Write-Host "Using the existing install in $InstallDir (rerun with -Update for a fresh download)"
    }

    # The agent and the engine read these instead of the repo's data/ and .chrome-profile/.
    $env:DSS_CHROME_PROFILE = Join-Path $InstallDir 'chrome-profile'
    $env:DSS_DATA_DIR = Join-Path $InstallDir 'data'
    $env:DSS_ENGINE_CMD = 'uv run --no-dev --frozen --project ../engine dsengine'
    New-Item -ItemType Directory -Path $env:DSS_CHROME_PROFILE, $env:DSS_DATA_DIR -Force | Out-Null
    $engine = Join-Path $app 'engine'

    if ($DryRun) {
        Write-Host 'Dry run: skipping the Google sign-in'
    } else {
        $state = $null
        try { $state = (uv run --no-dev --frozen --project $engine dsengine check 2>$null) -join "`n" | ConvertFrom-Json } catch { }
        if ($state -and $state.signed_in -eq $true) {
            Write-Host 'Signed in to Google in the agent''s Chrome profile'
        } else {
            Write-Host 'Sign in to Google in the Chrome window that opens, and accept Data Studio''s terms if it asks.'
            uv run --no-dev --frozen --project $engine dsengine login | Out-Host
            if ($LASTEXITCODE -ne 0) {
                Write-Host 'Sign-in did not finish; rerun the setup command to try again'
                $Result.Code = 1; return
            }
        }
    }

    $backend = Join-Path $app 'backend'
    $agentArgs = if ($Job) { @('run', '--server', $Server, '--job', $Job) } else { @('check', '--server', $Server, '--code', $Check) }
    if ($Job -and $DryRun) { $agentArgs += '--dry-run' }
    uv run --no-dev --frozen --project $backend dss-agent @agentArgs | Out-Host
    $Result.Code = $LASTEXITCODE
}

$saved = @{}
foreach ($name in $EnvNames) { $saved[$name] = [Environment]::GetEnvironmentVariable($name, 'Process') }
try {
    Invoke-Setup
} catch {
    Write-Host "Setup failed: $($_.Exception.Message)"
    $Result.Code = 1
} finally {
    # The command runs in the visitor's own shell: leave its environment as it was.
    foreach ($name in $EnvNames) { [Environment]::SetEnvironmentVariable($name, $saved[$name], 'Process') }
}

# Under -Command or -File, exit sets the process's exit code; in an interactive shell it would close
# the window, so the code goes to $LASTEXITCODE instead.
$hostArgs = [Environment]::GetCommandLineArgs() | Select-Object -Skip 1
$batch = @($hostArgs | Where-Object { $_ -match '^[-/](c|com\w*|f|fi\w*|e|ec|enc\w*)$' }).Count -gt 0 -and
    @($hostArgs | Where-Object { $_ -match '^[-/]noe\w*$' }).Count -eq 0
if ($batch) { exit $Result.Code }
$global:LASTEXITCODE = $Result.Code
