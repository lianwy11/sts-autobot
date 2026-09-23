# Build the two custom ModTheSpire mods (NoFocusPause, AchievementEnabler).
#
# Requirements: JDK 8 (any 1.8 JDK). The compile classpath needs ModTheSpire.jar
# and the game's desktop-1.0.jar.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts\build_mods.ps1 `
#       -GameDir "D:\Steam\steamapps\common\SlayTheSpire" `
#       -JdkDir  "C:\Program Files\Eclipse Adoptium\jdk-8.0.504.7-hotspot"

param(
    [string]$GameDir = "D:\Steam\steamapps\common\SlayTheSpire",
    [string]$JdkDir = $env:JAVA_HOME,
    [string]$RepoRoot = (Split-Path -Parent $PSScriptRoot)
)

$ErrorActionPreference = "Stop"

if (-not $JdkDir) { throw "Pass -JdkDir or set JAVA_HOME to a JDK 8 install." }

$javac = Join-Path $JdkDir "bin\javac.exe"
$jar   = Join-Path $JdkDir "bin\jar.exe"
$mtsJar = Join-Path $GameDir "ModTheSpire.jar"
$gameJar = Join-Path $GameDir "desktop-1.0.jar"

foreach ($p in @($javac, $jar, $mtsJar, $gameJar)) {
    if (-not (Test-Path $p)) { throw "Not found: $p" }
}

$mods = @(
    @{ Name = "nofocuspause";       Src = "mods\nofocuspause" },
    @{ Name = "achievementenabler"; Src = "mods\achievementenabler" }
)

$classpath = "$mtsJar;$gameJar"

foreach ($m in $mods) {
    $modDir = Join-Path $RepoRoot $m.Src
    $outDir = Join-Path $modDir "out"
    if (Test-Path $outDir) { Remove-Item -Recurse -Force $outDir }
    New-Item -ItemType Directory -Path $outDir | Out-Null

    Write-Host "=== Building $($m.Name) ==="
    & $javac -encoding UTF-8 -cp $classpath -d $outDir (Join-Path $modDir "src\$($m.Name)\*.java")
    if ($LASTEXITCODE -ne 0) { throw "javac failed for $($m.Name)" }

    $jarNames = @{ "nofocuspause" = "NoFocusPause.jar"; "achievementenabler" = "AchievementEnabler.jar" }
    $outJar = Join-Path $RepoRoot ("dist\" + $jarNames[$m.Name])

    # jar layout: ModTheSpire.json at the root + package folders
    Push-Location $modDir
    & $jar cf $outJar "ModTheSpire.json" -C $outDir .
    Pop-Location
    if ($LASTEXITCODE -ne 0) { throw "jar failed for $($m.Name)" }
    Write-Host "  -> $outJar"
}

Write-Host ""
Write-Host "Built jars are in dist\. Copy them to $GameDir\mods\ and add their"
Write-Host "mod IDs to the launch command: --mods basemod,CommunicationMod,nofocuspause,achievementenabler"
