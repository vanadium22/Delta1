function Get-AppPython {
    param([string]$Repository)
    if ($env:SWHY_DELTA1_PYTHON) { return $env:SWHY_DELTA1_PYTHON }
    foreach ($candidate in @('D:/conda/envs/swhy_delta1/python.exe',
        (Join-Path $Repository '.venvs/dashboard_app/Scripts/python.exe'),
        (Join-Path $Repository '.venv/Scripts/python.exe'),
        'P:/code_content/python_work_env/conda_env/swhy_delta1/python.exe')) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) { return $candidate }
    }
    return (Get-Command python -ErrorAction Stop).Source
}
