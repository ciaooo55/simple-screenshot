$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

python -m PyInstaller --noconfirm --clean SimpleScreenshot.spec
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller 构建失败，退出代码：$LASTEXITCODE"
}

Write-Host "构建完成：$PSScriptRoot\dist\SimpleScreenshot.exe"
