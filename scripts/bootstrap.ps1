$ErrorActionPreference = 'Stop'
$projectPath = Split-Path -Parent $PSScriptRoot
Push-Location $projectPath
try {
    if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
        python -m venv --without-pip .venv
        if ($LASTEXITCODE -ne 0) { throw 'venv creation failed' }
    }
    $sitePackages = Join-Path $projectPath '.venv\Lib\site-packages'
    # Core has no external runtime dependencies. Keep a local editable path.
    [IO.File]::WriteAllText((Join-Path $sitePackages 'cua_guard_local.pth'), (Join-Path $projectPath 'src') + [Environment]::NewLine, [Text.UTF8Encoding]::new($false))
    & '.\.venv\Scripts\python.exe' -m unittest discover -s tests -v
    if ($LASTEXITCODE -ne 0) { throw 'tests failed' }
    & '.\.venv\Scripts\python.exe' -m cua_guard.demo
    if ($LASTEXITCODE -ne 0) { throw 'demo failed' }
} finally { Pop-Location }
