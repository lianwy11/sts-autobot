# Launch the Slay the Spire automation bot.
#
# What it does:
#   1. starts ModTheSpire with the bot's mod set (game's bundled JRE, no console)
#   2. works around an MTS hang: once Steam is connected, MTS spawns a
#      SteamWorkshop helper that may never exit, blocking game startup - the
#      script terminates it after it has printed its item list
#   3. captures game output to game_out.log (javaw has no console)
#
# Requires: steam_appid.txt (contents: 646570) in the game dir for Steam
# integration (playtime + achievements). See docs/STEAM.md.

param(
    [string]$GameDir = $env:STS_GAME_DIR,
    [string]$DriverDir = (Split-Path -Parent $PSScriptRoot),
    [string]$Mods = "basemod,CommunicationMod,nofocuspause,achievementenabler"
)

if (-not $GameDir) { $GameDir = "D:\Steam\steamapps\common\SlayTheSpire" }

$jre = Join-Path $GameDir "jre\bin\javaw.exe"
if (-not (Test-Path $jre)) { throw "Game JRE not found at $jre (set -GameDir)." }

$logOut = Join-Path $DriverDir "game_out.log"
$logErr = Join-Path $DriverDir "game_err.log"

Write-Host "Starting ModTheSpire from $GameDir (mods: $Mods)"
Start-Process -FilePath $jre `
    -ArgumentList '-jar', 'ModTheSpire.jar', '--mods', $Mods, '--skip-intro' `
    -WorkingDirectory $GameDir `
    -RedirectStandardOutput $logOut `
    -RedirectStandardError $logErr

# Let the SteamWorkshop helper finish reporting, then end it so the loader
# can continue (it blocks reading that subprocess's stdout until EOF).
$deadline = (Get-Date).AddMinutes(2)
while ((Get-Date) -lt $deadline) {
    $sw = Get-CimInstance Win32_Process -Filter "Name = 'java.exe'" -ErrorAction SilentlyContinue |
          Where-Object { $_.CommandLine -like '*SteamWorkshop*' }
    if ($sw) {
        Start-Sleep -Seconds 10
        Stop-Process -Id $sw.ProcessId -Force -ErrorAction SilentlyContinue
        Write-Host "SteamWorkshop helper released."
        break
    }
    Start-Sleep -Seconds 2
}

Write-Host "Game output: $logOut"
