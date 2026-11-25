$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Create .venv and install .[dev] dependencies as described in README first.' }
Push-Location (Join-Path $projectRoot 'frontend')
try {
    npm ci
    if ($LASTEXITCODE -ne 0) { throw 'npm ci failed' }
    npm run build
    if ($LASTEXITCODE -ne 0) { throw 'frontend build failed' }
} finally { Pop-Location }
Push-Location $projectRoot
try {
    & $python -m PyInstaller --noconfirm --windowed --name LinerParts --icon frontend/public/logo.ico --paths src --collect-data liner_parts --collect-all webview --collect-all pypdfium2 --collect-all pypdfium2_raw --hidden-import keyring.backends.Windows run_desktop.py
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller build failed' }
    # Windows 10/11 always use the OS Universal CRT. Do not redistribute the build
    # machine's system DLL, which can also be locked during installer extraction.
    # https://learn.microsoft.com/en-us/cpp/windows/universal-crt-deployment
    $bundledSystemRuntime = Join-Path $projectRoot 'dist/LinerParts/_internal/ucrtbase.dll'
    if (Test-Path -LiteralPath $bundledSystemRuntime) {
        Remove-Item -LiteralPath $bundledSystemRuntime
    }
    & $python scripts/collect-licenses.py
    if ($LASTEXITCODE -ne 0) { throw 'License collection failed' }
    Copy-Item -LiteralPath README.md,LICENSE,THIRD_PARTY_NOTICES.md -Destination dist/LinerParts
    Copy-Item -LiteralPath docs -Destination dist/LinerParts/docs -Recurse -Force
    & $python -m PyInstaller --noconfirm installer/Agamaship.spec
    if ($LASTEXITCODE -ne 0) { throw 'Single-file application build failed' }
    Write-Output 'Build complete: dist/Agamaship-Desktop.exe and dist/LinerParts/LinerParts.exe'
} finally { Pop-Location }
