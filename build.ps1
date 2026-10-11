$ErrorActionPreference = 'Stop'
$originalBuildPath = $env:PATH
Push-Location $PSScriptRoot
try {
    # Do not collect unrelated ICU DLLs from other tools (e.g. Poppler) on PATH.
    # Qt on Windows uses the native Windows ICU API, not versioned ICU exports.
    $env:PATH = "$env:SystemRoot\System32;$env:SystemRoot;" + (Join-Path $PSScriptRoot '.venv\Scripts')
    & .\.venv\Scripts\python.exe -m unittest discover -s tests -v
    if ($LASTEXITCODE -ne 0) { throw 'Tests fehlgeschlagen.' }
    # OneDrive can retain read-only handles on old analysis folders.
    # Use a fresh work directory; no recursive cleanup is necessary.
    $buildWork = Join-Path $PSScriptRoot ('build/run-' + [guid]::NewGuid().ToString('N'))
    & .\.venv\Scripts\python.exe -m PyInstaller --noconfirm --workpath $buildWork --onefile --windowed --name SiusClientV2 main.py
    if ($LASTEXITCODE -ne 0) { throw 'EXE konnte nicht erstellt werden.' }
    Write-Host 'Bereit: dist\SiusClientV2.exe'
}
finally {
    $env:PATH = $originalBuildPath
    Pop-Location
}
