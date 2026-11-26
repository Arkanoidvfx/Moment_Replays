# A GitHub release of Moment Replays with SHA256.json, the file list the script's self-update reads.
# Without SHA256.json older scripts only say "update available" and install nothing.
#   .\release.ps1 v1.9 notes.md            checks, writes .tmp\release\SHA256.json (nothing leaves this PC)
#   .\release.ps1 v1.9 notes.md -Upload    creates the release from HEAD, which must already be on GitHub
param([Parameter(Mandatory)][string]$Tag, [Parameter(Mandatory)][string]$Notes, [switch]$Upload)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$repo = 'Arkanoidvfx/Moment_Replays'
$files = 'Moment_Replays.py', 'Recording_Started.wav', 'Recording_Stoped.wav', 'Replay_Failed.wav', 'Replay_Saved.wav', 'Moment_Input_Overlay.png'
if ($Tag -notmatch '^v\d+(\.\d+)*$') { throw "unexpected tag '$Tag'" }
if (-not (Test-Path -LiteralPath $Notes)) { throw "no notes file '$Notes'" }
if ((Get-Content -Raw .\Moment_Replays.py) -notmatch ('VERSION = "' + [regex]::Escape($Tag.Substring(1)) + '"')) { throw "CONSTANTS.VERSION is not $($Tag.Substring(1))" }
if (git status --porcelain -- $files) { throw 'the release files have uncommitted changes' }
$hashes = [ordered]@{}
foreach ($file in $files) { $hashes[$file] = (Get-FileHash -Algorithm SHA256 -LiteralPath $file).Hash.ToLower() }
New-Item -ItemType Directory -Force .tmp\release | Out-Null
[IO.File]::WriteAllText("$PSScriptRoot\.tmp\release\SHA256.json", (ConvertTo-Json $hashes))
$hashes
if (-not $Upload) { return }
gh release create $Tag @files .tmp\release\SHA256.json -R $repo --target (git rev-parse HEAD) --title "Moment Replays $Tag" --notes-file $Notes
if ($LASTEXITCODE -ne 0) { throw 'release create failed' }
