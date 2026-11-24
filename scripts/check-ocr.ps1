param([Parameter(Mandatory)][string]$PackageDir)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Drawing.Common

$directory = [IO.Path]::GetFullPath($PackageDir)
$exe = Join-Path $directory "SimpleScreenshot.exe"
$pipeName = "SimpleScreenshot-Test-" + [guid]::NewGuid().ToString("N")
$pipe = [IO.Pipes.NamedPipeServerStream]::new($pipeName, [IO.Pipes.PipeDirection]::InOut, 1,
    [IO.Pipes.PipeTransmissionMode]::Byte, [IO.Pipes.PipeOptions]::Asynchronous)
$process = $null
$writer = $null
$reader = $null

try {
    $fixture = [System.Drawing.Bitmap]::new(640, 140)
    $graphics = [System.Drawing.Graphics]::FromImage($fixture)
    $font = [System.Drawing.Font]::new("Arial", 40.0)
    $memory = [IO.MemoryStream]::new()
    try {
        $graphics.Clear([System.Drawing.Color]::White)
        $graphics.DrawString("Screenshot 123", $font, [System.Drawing.Brushes]::Black, 25.0, 35.0)
        $fixture.Save($memory, [System.Drawing.Imaging.ImageFormat]::Bmp)
        $data = $memory.ToArray()
    }
    finally {
        $memory.Dispose()
        $font.Dispose()
        $graphics.Dispose()
        $fixture.Dispose()
    }

    $process = Start-Process -FilePath $exe -ArgumentList @("--ocr-worker", $pipeName) -PassThru
    if (-not $pipe.WaitForConnectionAsync().Wait(15000)) { throw "OCR 工作进程未连接。" }
    $writer = [IO.BinaryWriter]::new($pipe, [Text.Encoding]::UTF8, $true)
    $reader = [IO.BinaryReader]::new($pipe, [Text.Encoding]::UTF8, $true)
    $writer.Write([int]$data.Length)
    $writer.Write($data, 0, $data.Length)
    $writer.Flush()
    $count = $reader.ReadInt32()
    if ($count -eq -1) { throw $reader.ReadString() }
    if ($count -le 0 -or $count -gt 1000) { throw "预期可识别文字，实际收到 $count 个片段。" }
    $text = [Text.StringBuilder]::new()
    for ($index = 0; $index -lt $count; $index++) {
        [void]$text.Append($reader.ReadString())
        for ($coordinate = 0; $coordinate -lt 4; $coordinate++) { [void]$reader.ReadSingle() }
    }
    if ($text.ToString() -notmatch 'Screenshot\s+123') { throw "实际识别结果不符：$text" }
    Write-Host "打包后的 OCR 工作进程识别结果：$text"
}
finally {
    if ($null -ne $writer) { $writer.Dispose() }
    if ($null -ne $reader) { $reader.Dispose() }
    $pipe.Dispose()
    if ($null -ne $process) {
        if (-not $process.WaitForExit(2000)) { $process.Kill() }
        $process.Dispose()
    }
}
