param([string]$PartsDirectory=$PSScriptRoot)
$ErrorActionPreference='Stop'
$parts=@(Get-ChildItem -LiteralPath $PartsDirectory -File -Filter 'qwen3-vl-4b-models.zip.00*' | Sort-Object Name)
if($parts.Count -ne 4){throw '需要完整的4个模型分卷：001到004'}
$manifest=Get-Content -LiteralPath (Join-Path $PSScriptRoot 'assets-manifest.json') -Raw -Encoding UTF8 | ConvertFrom-Json
foreach($part in $parts){$expected=$manifest|Where-Object name -eq $part.Name; if(-not $expected -or (Get-FileHash -LiteralPath $part.FullName -Algorithm SHA256).Hash.ToLower() -ne $expected.sha256){throw ('分卷校验失败：'+$part.Name)}}
$zip=Join-Path $PSScriptRoot 'qwen3-vl-4b-models.zip'
if(Test-Path -LiteralPath $zip){throw '合并文件已存在，请先移动它，避免覆盖'}
$output=[IO.File]::Open($zip,[IO.FileMode]::CreateNew)
try{foreach($part in $parts){$inputStream=[IO.File]::OpenRead($part.FullName);try{$inputStream.CopyTo($output)}finally{$inputStream.Dispose()}}}finally{$output.Dispose()}
if(Test-Path -LiteralPath (Join-Path $PSScriptRoot 'models')){throw 'models目录已存在；为避免覆盖，已停止解压'}
Expand-Archive -LiteralPath $zip -DestinationPath $PSScriptRoot
Write-Output '模型已恢复，运行启动软件.cmd即可使用。'
