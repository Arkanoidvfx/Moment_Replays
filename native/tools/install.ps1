# Copies the built plugin into an OBS. OBS loads it at its next start.
#
# OBS 33 and newer look for a plugin in <plugins>\moment-replays\moment-replays.dll (+ data\) and call every older
# place "Legacy" (https://obsproject.com/kb/legacy-plugin-developer-info). OBS 30 to 32 only know
# <plugins>\moment-replays\bin\64bit\moment-replays.dll. The layout is picked from the OBS version:
#
#   install.ps1                       -> the installed OBS, C:\ProgramData\obs-studio\plugins\moment-replays (no admin rights)
#   install.ps1 -Portable <OBS root>  -> a portable OBS: <OBS>\plugins\moment-replays (33+) or <OBS>\obs-plugins\64bit (30 to 32)
#   install.ps1 -Layout new|legacy    -> overrides the choice
#   install.ps1 -Remove               -> takes the plugin out of every place it may be in (settings stay)
#
# A copy in the other layout is removed, so OBS never finds two. If a running OBS holds that DLL it cannot be
# deleted: it is renamed to .dll.old (OBS only loads *.dll) and the plugin deletes it at its next start.
param([string]$Portable, [ValidateSet('auto', 'new', 'legacy')][string]$Layout = 'auto', [switch]$Remove)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$dll = Join-Path $root 'build\RelWithDebInfo\moment-replays.dll'
$name = 'moment-replays'

function Remove-PluginFile([string]$path) {
    if (-not (Test-Path -LiteralPath $path)) { return }
    try { Remove-Item -LiteralPath $path -Force -Confirm:$false }
    catch {
        if ($path -notlike '*.dll') { "  could not be deleted, left in place (OBS does not load it): $path"; return }
        # Loaded by a running OBS: a rename is allowed.
        $old = "$path.old"
        if (Test-Path -LiteralPath $old) { Remove-Item -LiteralPath $old -Force -Confirm:$false -ErrorAction SilentlyContinue }
        Rename-Item -LiteralPath $path -NewName (Split-Path $old -Leaf)
        "  in use by a running OBS, renamed to $(Split-Path $old -Leaf): $path"
    }
}
function Remove-IfEmpty([string]$dir) {
    if ((Test-Path -LiteralPath $dir) -and -not (Get-ChildItem -LiteralPath $dir -Force)) { Remove-Item -LiteralPath $dir -Force -Confirm:$false }
}

if ($Portable) {
    $obsExe = Join-Path $Portable 'bin\64bit\obs64.exe'
    $new = @{ Bin = Join-Path $Portable "plugins\$name"; Data = Join-Path $Portable "plugins\$name\data" }
    $legacy = @{ Bin = Join-Path $Portable 'obs-plugins\64bit'; Data = Join-Path $Portable "data\obs-plugins\$name" }
} else {
    $obsExe = Join-Path $env:ProgramFiles 'obs-studio\bin\64bit\obs64.exe'
    $top = Join-Path $env:ProgramData "obs-studio\plugins\$name"
    $new = @{ Bin = $top; Data = Join-Path $top 'data' }
    $legacy = @{ Bin = Join-Path $top 'bin\64bit'; Data = Join-Path $top 'data' }
}

function Remove-Layout($place, [bool]$withData) {
    # Leftovers first: the DLL itself may turn into a .dll.old below.
    foreach ($file in "$name.dll.old", "$name.dll.new", "$name.pdb", "$name.dll") { Remove-PluginFile (Join-Path $place.Bin $file) }
    if ($withData -and (Test-Path -LiteralPath $place.Data)) { Remove-Item -LiteralPath $place.Data -Recurse -Force -Confirm:$false }
}

if ($Remove) {
    Remove-Layout $legacy $true
    Remove-Layout $new $true
    if (-not $Portable) { Remove-IfEmpty (Join-Path $top 'bin\64bit'); Remove-IfEmpty (Join-Path $top 'bin'); Remove-IfEmpty $top }
    'Removed.'
    return
}

if ($Layout -eq 'auto') {
    $major = if (Test-Path -LiteralPath $obsExe) { [int]((Get-Item -LiteralPath $obsExe).VersionInfo.FileVersion -split '\.')[0] } else { 33 }
    $Layout = if ($major -ge 33) { 'new' } else { 'legacy' }
    "OBS $major -> $Layout layout"
}
$use, $other = if ($Layout -eq 'new') { $new, $legacy } else { $legacy, $new }

# The other layout's copy goes first; its data folder only when it is not the one about to be filled.
Remove-Layout $other ($other.Data -ne $use.Data)
if (-not $Portable) { Remove-IfEmpty (Join-Path $top 'bin\64bit'); Remove-IfEmpty (Join-Path $top 'bin') }

New-Item -ItemType Directory -Force $use.Bin, $use.Data | Out-Null
$target = Join-Path $use.Bin "$name.dll"
Remove-PluginFile $target
Copy-Item -LiteralPath $dll -Destination $target
Copy-Item -LiteralPath ($dll -replace '\.dll$', '.pdb') -Destination $use.Bin -Force -ErrorAction SilentlyContinue # readable crash reports
Copy-Item (Join-Path $root 'data\*') $use.Data -Recurse -Force
"Installed to $($use.Bin)"
"SHA-256 " + (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLower()
