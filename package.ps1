# Zips the .py and .md files next to this script into ez-kg.zip.
$ErrorActionPreference = 'Stop'
$zip = Join-Path $PSScriptRoot 'ez-kg.zip'
Compress-Archive -Path (Join-Path $PSScriptRoot '*.py'), (Join-Path $PSScriptRoot '*.md') -DestinationPath $zip -Force
Write-Host "Wrote $zip"
