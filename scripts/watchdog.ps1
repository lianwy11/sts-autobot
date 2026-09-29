# Watchdog: the game can hang forever after processing a command (no error,
# no further states). If the driver log goes stale, restart the bot - the
# save is kept (mode.txt=continue) so a hang costs minutes, not progress.
param([int]$StaleMinutes = 4)
$logPath = 'D:\ZCodeWork\sts\driver_log.txt'
$lock = 'D:\ZCodeWork\sts\watchdog.lock'
if (Test-Path $lock) { exit }
New-Item $lock -ItemType File -Force | Out-Null
try {
    while ($true) {
        Start-Sleep -Seconds 60
        if (-not (Test-Path $logPath)) { continue }
        $age = (Get-Date) - (Get-Item $logPath).LastWriteTime
        if ($age.TotalMinutes -gt $StaleMinutes) {
            taskkill /IM javaw.exe /F 2>$null | Out-Null
            taskkill /IM python.exe /F 2>$null | Out-Null
            Start-Sleep -Seconds 3
            Start-Process powershell -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-File','D:\ZCodeWork\sts\launch_sts_bot.ps1' -WindowStyle Hidden
            Start-Sleep -Seconds 150   # let the relaunch settle before re-arming
        }
    }
} finally { Remove-Item $lock -Force -ErrorAction SilentlyContinue }
