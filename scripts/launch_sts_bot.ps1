# Launch the Slay the Spire automation bot with Steam integration.
# - character picker: choose the class before the automation starts
# - steam_appid.txt makes the Steam API connect (playtime + achievements).
# - MTS may spawn a SteamWorkshop helper that hangs after printing its list;
#   we terminate it so the loader can continue to launch the game.
param([switch]$NoLaunch, [switch]$Auto)

$game = 'D:\Steam\steamapps\common\SlayTheSpire'
$jre = Join-Path $game 'jre\bin\javaw.exe'
$logDir = 'D:\ZCodeWork\sts'

# ---------------- character picker ----------------
$charFile = Join-Path $logDir 'character.txt'
$modeFile = Join-Path $logDir 'mode.txt'
$current = 'IRONCLAD'
if (Test-Path $charFile) { $current = (Get-Content $charFile -Raw).Trim().ToUpper() }
if ($Auto) {
    Write-Host "(Auto: 保持 $current + 继续存档)"
    Set-Content -Path $modeFile -Value 'continue' -Encoding ASCII
} else {
    Write-Host ''
    Write-Host '=========== 杀戮尖塔代打 - 选择职业 ==========='
    Write-Host ("  当前设置: " + $current)
    Write-Host '  [1] 铁甲战士 IRONCLAD    [2] 静默猎手 THE_SILENT'
    Write-Host '  [3] 机械师   DEFECT      [4] 观战者   WATCHER'
    Write-Host '  [5] 每局随机 RANDOM      [6] 每局轮换 ROTATE'
    Write-Host '  [回车] 保持当前设置'
    $sel = [Console]::In.ReadLine()
    if ($null -ne $sel) { $sel = $sel.Trim() } else { $sel = '' }
    $map = @{ '1' = 'IRONCLAD'; '2' = 'THE_SILENT'; '3' = 'DEFECT';
              '4' = 'WATCHER'; '5' = 'RANDOM'; '6' = 'ROTATE' }
    if ($map.ContainsKey($sel)) {
        $current = $map[$sel]
        Set-Content -Path $charFile -Value $current -Encoding ASCII
    }
    Write-Host ("  职业已设定: " + $current)

    $mode = 'continue'
    $saves = Get-ChildItem -Path (Join-Path $game 'saves\*.autosave') -ErrorAction SilentlyContinue
    if ($saves) {
        Write-Host '  检测到进行中的存档: [回车]继续该存档  [n]放弃存档并用所选职业开新局'
        $ans = [Console]::In.ReadLine()
        if ($null -ne $ans) { $ans = $ans.Trim().ToLower() } else { $ans = '' }
        if ($ans -eq 'n') { $mode = 'new' }
    }
    Set-Content -Path $modeFile -Value $mode -Encoding ASCII
    Write-Host ("  模式: " + $mode)
    Write-Host '================================================'
}

if ($NoLaunch) { Write-Host '(NoLaunch: 跳过启动)'; exit 0 }

Start-Process -FilePath $jre `
    -ArgumentList '-jar', 'ModTheSpire.jar', '--mods', 'basemod,CommunicationMod,nofocuspause,achievementenabler', '--skip-intro' `
    -WorkingDirectory $game `
    -RedirectStandardOutput (Join-Path $logDir 'game_out.log') `
    -RedirectStandardError (Join-Path $logDir 'game_err.log')

$deadline = (Get-Date).AddMinutes(2)
while ((Get-Date) -lt $deadline) {
    $sw = Get-CimInstance Win32_Process -Filter "Name = 'java.exe'" -ErrorAction SilentlyContinue |
          Where-Object { $_.CommandLine -like '*SteamWorkshop*' }
    if ($sw) {
        Start-Sleep -Seconds 10   # give it time to print the workshop list
        Stop-Process -Id $sw.ProcessId -Force -ErrorAction SilentlyContinue
        break
    }
    Start-Sleep -Seconds 2
}

# Hang watchdog: the game occasionally hangs forever after a command (no
# error, no further states). A hidden watchdog restarts the bot when the
# driver log goes stale - the save is kept, so a hang costs minutes.
$wd = Join-Path $logDir 'watchdog.ps1'
if (Test-Path $wd) {
    Start-Process powershell -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-File',$wd -WindowStyle Hidden
}
