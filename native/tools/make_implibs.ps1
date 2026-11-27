# Makes import libraries for obs.dll and obs-frontend-api.dll from their export tables, so the plugin links
# without building OBS. Which OBS the DLLs come from does not matter: the plugin is compiled against the
# OBS 30.0 headers, so it can only name functions that exist since 30.0.
# usage: make_implibs.ps1 <folder with obs.dll and obs-frontend-api.dll> <output folder>
param([Parameter(Mandatory)][string]$ObsBin, [Parameter(Mandatory)][string]$Out)
$ErrorActionPreference = 'Stop'
$vs = & "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe" -latest -products * -property installationPath
$vcvars = Join-Path $vs 'VC\Auxiliary\Build\vcvars64.bat'
New-Item -ItemType Directory -Force $Out | Out-Null
foreach ($name in 'obs', 'obs-frontend-api') {
    $dll = Join-Path $ObsBin "$name.dll"
    $dump = cmd /c "`"$vcvars`" >nul 2>&1 && dumpbin /nologo /exports `"$dll`""
    $names = $dump | ForEach-Object { if ($_ -match '^\s+\d+\s+[0-9A-F]+\s+[0-9A-F]{8}\s+(\S+)') { $Matches[1] } }
    if (-not $names) { throw "no exports read from $dll" }
    $def = Join-Path $Out "$name.def"
    Set-Content -Path $def -Encoding ascii -Value (@("LIBRARY `"$name.dll`"", 'EXPORTS') + ($names | ForEach-Object { "    $_" }))
    cmd /c "`"$vcvars`" >nul 2>&1 && lib /nologo /def:`"$def`" /machine:x64 /out:`"$(Join-Path $Out "$name.lib")`"" | Out-Null
    "{0}: {1} exports" -f $name, $names.Count
}
