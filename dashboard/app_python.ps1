function Get-AppPython {
    param([string]$Repository)
    $selection=Join-Path $Repository 'dashboard/localsetting/app/python.local.json'
    $bundled=Join-Path $Repository 'runtime/python/python.exe'
    if (Test-Path -LiteralPath $selection -PathType Leaf) {
        $profile=Get-Content -LiteralPath $selection -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($profile.schema -ne 'dashboard-python-selection-v1') { throw 'invalid_python_selection' }
        if ($profile.mode -eq 'bundled') { $selected=$bundled }
        elseif ($profile.mode -eq 'external') { $selected=[string]$profile.python }
        else { throw 'invalid_python_selection' }
        if (-not (Test-Path -LiteralPath $selected -PathType Leaf)) { throw 'selected_python_not_found' }
        return $selected
    }
    if ($env:SWHY_DELTA1_PYTHON) { return $env:SWHY_DELTA1_PYTHON }
    if (Test-Path -LiteralPath $bundled -PathType Leaf) { return $bundled }
    foreach ($candidate in @('D:/conda/envs/swhy_delta1/python.exe',
        (Join-Path $Repository '.venvs/dashboard_app/Scripts/python.exe'),
        (Join-Path $Repository '.venv/Scripts/python.exe'),
        'P:/code_content/python_work_env/conda_env/swhy_delta1/python.exe')) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) { return $candidate }
    }
    return (Get-Command python -ErrorAction Stop).Source
}
