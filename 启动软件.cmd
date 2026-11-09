@echo off
chcp 65001 >nul
cd /d "%~dp0"
powershell.exe -NoProfile -Command "$p=Join-Path (Get-Location) '设置.json'; if(Test-Path -LiteralPath $p){$s=Get-Content -LiteralPath $p -Raw -Encoding UTF8|ConvertFrom-Json}else{$s=Get-Content -LiteralPath 'settings.example.json' -Raw -Encoding UTF8|ConvertFrom-Json}; if($s.models_dir -eq 'models' -or -not $s.models_dir){$s.models_dir=Join-Path (Get-Location) 'models'}; [IO.File]::WriteAllText($p,($s|ConvertTo-Json -Depth 5),(New-Object Text.UTF8Encoding($false)))"
start "" "素材归档助手.exe"
