param([Parameter(Mandatory)][string]$PackageDir)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Drawing

$directory = [IO.Path]::GetFullPath($PackageDir)
$exe = Join-Path $directory "SimpleScreenshot.exe"
$type = [Reflection.Assembly]::LoadFrom($exe).GetType("SimpleScreenshot.OcrClient", $true)
$recognize = $type.GetMethod("Recognize", [Reflection.BindingFlags]"Instance, NonPublic")
$client = [Activator]::CreateInstance($type, $true)
$fixture = $null

try {
    $fixture = [System.Drawing.Bitmap]::new(640, 140)
    $graphics = [System.Drawing.Graphics]::FromImage($fixture)
    $font = [System.Drawing.Font]::new("Arial", 40.0)
    try {
        $graphics.Clear([System.Drawing.Color]::White)
        $graphics.DrawString("Screenshot 123", $font, [System.Drawing.Brushes]::Black, 25.0, 35.0)
    }
    finally {
        $font.Dispose()
        $graphics.Dispose()
    }

    foreach ($request in 1, 2) {
        $task = $recognize.Invoke($client, @($fixture))
        $spans = $task.GetAwaiter().GetResult()
        $text = ($spans | ForEach-Object { $_.Item1 }) -join ""
        if ($text -notmatch 'Screenshot\s+123') { throw "Packaged OCR request ${request}: unexpected result '$text'." }
        Write-Host "Packaged OCR request ${request}: $text"
    }
}
finally {
    if ($null -ne $fixture) { $fixture.Dispose() }
    ([IDisposable]$client).Dispose()
}
