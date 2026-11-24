param([Parameter(Mandatory)][string]$PackageDir)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Drawing

$directory = [IO.Path]::GetFullPath($PackageDir)
$exe = Join-Path $directory "SimpleScreenshot.exe"
$app = [Reflection.Assembly]::LoadFrom($exe)
$type = $app.GetType("SimpleScreenshot.OcrClient", $true)
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

Add-Type -ReferencedAssemblies System.Drawing -TypeDefinition @'
using System;
using System.Drawing;
using System.Reflection;
using System.Threading.Tasks;

public static class OcrLayerCheck
{
    public static void VerifyFailure(Assembly app)
    {
        const BindingFlags flags = BindingFlags.Instance | BindingFlags.NonPublic;
        Type type = app.GetType("SimpleScreenshot.OcrLayer", true);
        bool reported = false;
        object layer = Activator.CreateInstance(type, flags, null, new object[] {
            (Action)(() => {}), (Action<string>)(_ => {}),
            (Action<string>)(message => reported = message == "Test OCR failure")
        }, null);
        Func<Task<Tuple<string, RectangleF>[]>> recognize = () =>
            Task.FromException<Tuple<string, RectangleF>[]>(new InvalidOperationException("Test OCR failure"));
        type.GetMethod("Start", flags).Invoke(layer, new object[] { recognize });
        if (!reported || (bool)type.GetProperty("Active", flags).GetValue(layer) ||
            (bool)type.GetProperty("Loading", flags).GetValue(layer))
            throw new InvalidOperationException("An OCR failure did not restore the normal interaction state.");
    }
}
'@
[OcrLayerCheck]::VerifyFailure($app)
Write-Host "Packaged OCR failure restores the normal interaction state."
