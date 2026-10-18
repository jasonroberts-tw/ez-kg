# Zips the .py and .md files next to this script, except CLAUDE.md, into ez-kg.zip.
$ErrorActionPreference = 'Stop'
$zip = Join-Path $PSScriptRoot 'ez-kg.zip'
Get-ChildItem (Join-Path $PSScriptRoot '*') -Include *.py, *.md -Exclude CLAUDE.md |
    Compress-Archive -DestinationPath $zip -Force
Write-Host "Wrote $zip"
