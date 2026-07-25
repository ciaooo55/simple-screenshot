param(
    [switch]$Clean
)

$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

$arguments = @("-m", "PyInstaller", "--noconfirm")
if ($Clean) {
    $arguments += "--clean"
}
$arguments += "SimpleScreenshot.spec"

& python @arguments
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller 构建失败，退出代码：$LASTEXITCODE"
}

Write-Host "构建完成：$PSScriptRoot\dist\SimpleScreenshot.exe"
