param([string]$OutputDirectory = "dist")

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$output = [IO.Path]::GetFullPath($OutputDirectory, $root)
$staging = Join-Path $output "staging"
$ocr = Join-Path $staging "ocr"
$models = Join-Path $ocr "models"
$licenses = Join-Path $ocr "licenses"
$exe = Join-Path $root "src/App/bin/Release/net48/SimpleScreenshot.exe"
$ocrOutput = Join-Path $root "src/Ocr/bin/Release/net48/win-x64"

if (-not (Test-Path -LiteralPath $exe) -or -not (Test-Path -LiteralPath (Join-Path $ocrOutput "onnxruntime.dll"))) {
    throw "请先以 Release 配置构建截图程序和 OCR 组件。"
}

if (Test-Path -LiteralPath $staging) { Remove-Item -LiteralPath $staging -Recurse -Force }
New-Item -ItemType Directory -Path $models, $licenses -Force | Out-Null
Copy-Item -LiteralPath $exe -Destination $staging
Get-ChildItem -LiteralPath $ocrOutput -Filter "*.dll" | Copy-Item -Destination $ocr

$vswhere = Join-Path ${env:ProgramFiles(x86)} "Microsoft Visual Studio/Installer/vswhere.exe"
$vs = & $vswhere -latest -products '*' -requires Microsoft.VisualStudio.Component.VC.Redist.14.Latest -property installationPath
if ($LASTEXITCODE -ne 0 -or -not $vs) { throw "请安装 Visual Studio C++ Redistributable 组件以打包便携版。" }
$runtimeDlls = "msvcp140.dll", "msvcp140_1.dll", "vcruntime140.dll", "vcruntime140_1.dll"
$crt = Get-ChildItem -LiteralPath (Join-Path $vs "VC/Redist/MSVC") -Directory |
    Where-Object { $_.Name -match '^\d+(\.\d+){1,3}$' } |
    Sort-Object { [version]$_.Name } -Descending |
    ForEach-Object {
        $x64 = Join-Path $_.FullName "x64"
        if (Test-Path -LiteralPath $x64) {
            Get-ChildItem -LiteralPath $x64 -Directory -Filter "Microsoft.VC*.CRT"
        }
    } |
    Where-Object {
        $candidate = $_.FullName
        @($runtimeDlls | Where-Object { -not (Test-Path -LiteralPath (Join-Path $candidate $_)) }).Count -eq 0
    } | Select-Object -First 1 -ExpandProperty FullName
if (-not $crt) { throw "未找到 Visual C++ 运行时的 x64 应用本地文件。" }
foreach ($dll in $runtimeDlls) {
    Copy-Item -LiteralPath (Join-Path $crt $dll) -Destination $ocr
}

$url = "https://files.pythonhosted.org/packages/ba/12/1e5497183bdbe782dbb91bad1d0d2297dba4d2831b2652657f7517bfc6df/rapidocr_onnxruntime-1.4.4-py3-none-any.whl"
$hash = "971d7d5f223a7a808662229df1ef69893809d8457d834e6373d3854bc1782cbf"
$wheel = Join-Path $output "rapidocr_onnxruntime-1.4.4.whl"
if (-not (Test-Path -LiteralPath $wheel) -or (Get-FileHash -LiteralPath $wheel).Hash -ne $hash) {
    Invoke-WebRequest -Uri $url -OutFile $wheel
}
if ((Get-FileHash -LiteralPath $wheel).Hash -ne $hash) { throw "RapidOCR wheel 校验失败。" }
$zip = [IO.Compression.ZipFile]::OpenRead($wheel)
try {
    foreach ($model in "ch_PP-OCRv4_det_infer.onnx", "ch_ppocr_mobile_v2.0_cls_infer.onnx", "ch_PP-OCRv4_rec_infer.onnx") {
        $entry = $zip.GetEntry("rapidocr_onnxruntime/models/$model")
        if (-not $entry) { throw "未找到 OCR 模型：$model" }
        [IO.Compression.ZipFileExtensions]::ExtractToFile($entry, (Join-Path $models $model), $true)
    }
}
finally { $zip.Dispose() }

$rapidLicense = Join-Path $licenses "RapidOCR-LICENSE.txt"
Invoke-WebRequest -Uri "https://raw.githubusercontent.com/RapidAI/RapidOCR/v1.4.4/LICENSE" -OutFile $rapidLicense
if ((Get-FileHash -LiteralPath $rapidLicense).Hash -ne "3e0af25fdd06aa9586ae97adb00ea927ebe5a3805ac77d2d3a81ce5f55693333") {
    throw "RapidOCR 许可文件校验失败。"
}
$nugetRoot = (dotnet msbuild (Join-Path $root "src/Ocr/SimpleScreenshot.Ocr.csproj") -getProperty:NuGetPackageRoot | Select-Object -Last 1).Trim()
if ($LASTEXITCODE -ne 0) { throw "无法查找 NuGet 缓存。" }
$onnx = Join-Path $nugetRoot "microsoft.ml.onnxruntime/1.24.4"
Copy-Item -LiteralPath (Join-Path $onnx "LICENSE") -Destination (Join-Path $licenses "ONNXRuntime-LICENSE.txt")
Copy-Item -LiteralPath (Join-Path $onnx "ThirdPartyNotices.txt") -Destination (Join-Path $licenses "ONNXRuntime-ThirdPartyNotices.txt")
foreach ($dependency in "system.buffers/4.5.1", "system.memory/4.5.5", "system.numerics.vectors/4.5.0", "system.runtime.compilerservices.unsafe/4.5.3") {
    $package = Join-Path $nugetRoot $dependency
    $name = ($dependency -split '/')[0]
    foreach ($notice in "LICENSE.TXT", "THIRD-PARTY-NOTICES.TXT") {
        $file = Join-Path $package $notice
        if (Test-Path -LiteralPath $file) {
            Copy-Item -LiteralPath $file -Destination (Join-Path $licenses "$name-$notice")
        }
    }
}

$archive = Join-Path $output "SimpleScreenshot-win-x64.zip"
Compress-Archive -Path (Join-Path $staging '*') -DestinationPath $archive -Force
Write-Host "已生成：$archive ($((Get-Item -LiteralPath $archive).Length) 字节)"
