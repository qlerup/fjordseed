# Install for the current Windows user. Does not require administrator rights.
[CmdletBinding()]
param(
    [string]$InstallDir = (Join-Path $env:LOCALAPPDATA 'FjordEncode'),
    [string]$ArchiveDirectory = '',
    [switch]$NoShortcut,
    [switch]$SourceOnly
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
if ($env:OS -ne 'Windows_NT') { throw 'This desktop app requires Windows.' }
Get-Command tar.exe -ErrorAction Stop | Out-Null
Get-Command python.exe -ErrorAction Stop | Out-Null
$pythonGui = & python.exe -c "import sys, tkinter; from pathlib import Path; print(Path(sys.executable).with_name('pythonw.exe'))"
if ($LASTEXITCODE -ne 0 -or -not $pythonGui -or -not (Test-Path -LiteralPath $pythonGui)) {
    throw 'Install Python 3.13 with tkinter and add Python to PATH first.'
}

$InstallDir = [IO.Path]::GetFullPath($InstallDir)
if (-not $ArchiveDirectory) { $ArchiveDirectory = Join-Path $InstallDir 'downloads' }
$ArchiveDirectory = [IO.Path]::GetFullPath($ArchiveDirectory)
New-Item -ItemType Directory -Force -Path $InstallDir, $ArchiveDirectory | Out-Null
$tools = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'tools.json') -Raw | ConvertFrom-Json

foreach ($name in @('nvenc', 'ffmpeg', 'mkvtoolnix')) {
    $tool = $tools.$name
    $archive = Join-Path $ArchiveDirectory $tool.file
    $valid = (Test-Path -LiteralPath $archive) -and
        ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash -eq $tool.sha256)
    if (-not $valid) {
        Write-Host "Downloading $name $($tool.version)..."
        Invoke-WebRequest -UseBasicParsing -Uri $tool.url -OutFile $archive
    }
    if ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash -ne $tool.sha256) {
        throw "Checksum verification failed for $name. Nothing from that archive was executed."
    }
    Write-Host "Extracting $name..."
    if ($name -eq 'ffmpeg') {
        $destination = Join-Path $InstallDir 'ffmpeg'
        New-Item -ItemType Directory -Force -Path $destination | Out-Null
        & tar.exe -xf $archive -C $destination --strip-components=1
    } else {
        & tar.exe -xf $archive -C $InstallDir
    }
    if ($LASTEXITCODE -ne 0) { throw "Extraction failed for $name." }
}

foreach ($file in @('fjord_encode.pyw', 'fjord_ui.py', 'encode_core.py', 'nvidia_decoder.py', 'workspace_sync.py', 'shared_runner.py', 'windows_drop.py', 'remote_agent.py', 'remote_panel.py', 'windows_secret.py', 'windows_background.py', 'windows_startup.py', 'windows_instance.py', 'fjord.ico')) {
    $source = Join-Path $PSScriptRoot $file
    $destination = Join-Path $InstallDir $file
    if ([IO.Path]::GetFullPath($source) -ne [IO.Path]::GetFullPath($destination)) {
        Copy-Item -LiteralPath $source -Destination $destination -Force
    }
}

& (Join-Path $InstallDir 'NVEncC64.exe') --check-device
if ($LASTEXITCODE -ne 0) { throw 'NVEncC could not detect a compatible NVIDIA GPU.' }
& (Join-Path $InstallDir 'ffmpeg\bin\ffprobe.exe') -version | Select-Object -First 1
if ($LASTEXITCODE -ne 0) { throw 'FFprobe could not start.' }
& (Join-Path $InstallDir 'mkvtoolnix\mkvpropedit.exe') --version
if ($LASTEXITCODE -ne 0) { throw 'MKVToolNix could not start.' }

$executable = Join-Path $InstallDir 'Fjord-konvertering.exe'
if (-not $SourceOnly) {
    & python.exe (Join-Path $PSScriptRoot 'build_windows.py') --install-dir $InstallDir
    if ($LASTEXITCODE -ne 0) { throw 'Could not build Fjord-konvertering.exe. Close the app before updating.' }
}

if (-not $NoShortcut) {
    $shortcutPath = Join-Path ([Environment]::GetFolderPath('Desktop')) 'Fjord-konvertering.lnk'
    $shortcut = (New-Object -ComObject WScript.Shell).CreateShortcut($shortcutPath)
    if (-not $SourceOnly) {
        $shortcut.TargetPath = $executable
        $shortcut.Arguments = ''
    } else {
        $shortcut.TargetPath = $pythonGui
        $shortcut.Arguments = '"' + (Join-Path $InstallDir 'fjord_encode.pyw') + '"'
    }
    $shortcut.WorkingDirectory = $InstallDir
    $shortcut.IconLocation = Join-Path $InstallDir 'fjord.ico'
    $shortcut.Description = 'Fjord GPU video conversion'
    $shortcut.Save()
}
Write-Host "Installed in $InstallDir"
