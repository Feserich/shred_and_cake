# Local Windows build (PowerShell): .\packaging\build.ps1  ->  dist\skibasar.exe
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
uv run --group build pyinstaller --noconfirm --clean packaging/skibasar.spec
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

# Double-click launchers next to the exe
Set-Content -Encoding ASCII dist\Skibasar-starten.bat "@echo off`r`nskibasar.exe"
Set-Content -Encoding ASCII dist\Skibasar-mit-Telefonen.bat "@echo off`r`nskibasar.exe --lan"
Write-Host "Fertig: dist\skibasar.exe"
