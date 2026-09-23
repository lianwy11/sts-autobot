# Create a desktop shortcut that launches the bot (no console window).
# Adjust $DriverDir / $GameDir for your machine.

param(
    [string]$RepoRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$GameDir = $env:STS_GAME_DIR,
    [string]$ShortcutName = "杀戮尖塔-自动版"
)

if (-not $GameDir) { $GameDir = "D:\Steam\steamapps\common\SlayTheSpire" }

$desktop = [Environment]::GetFolderPath('Desktop')
$lnkPath = Join-Path $desktop "$ShortcutName.lnk"

$sh = New-Object -ComObject WScript.Shell
$lnk = $sh.CreateShortcut($lnkPath)
$lnk.TargetPath = 'powershell.exe'
$lnk.Arguments = '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "' +
                (Join-Path $RepoRoot 'scripts\launch_sts_bot.ps1') + '"'
$lnk.WorkingDirectory = $RepoRoot
$lnk.IconLocation = (Join-Path $GameDir 'SlayTheSpire.exe') + ',0'
$lnk.Description = '杀戮尖塔自动版（AI 代打 + Steam 记录 + 后台运行）'
$lnk.Save()

Write-Host "Shortcut created: $lnkPath"
