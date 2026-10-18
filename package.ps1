# Zips the .py and .md files next to this script, except CLAUDE.md, plus the skills folder, into ez-kg.zip.
$ErrorActionPreference = 'Stop'
$zip = Join-Path $PSScriptRoot 'ez-kg.zip'
$files = Get-ChildItem (Join-Path $PSScriptRoot '*') -Include *.py, *.md -Exclude CLAUDE.md
Compress-Archive -LiteralPath (@($files.FullName) + (Join-Path $PSScriptRoot 'skills')) -DestinationPath $zip -Force
Write-Host "Wrote $zip"
