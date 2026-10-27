#requires -Version 7.3
# Run comparison commands in the same MSVC/UTF-8 environment locally and in CI.
param([Parameter(Mandatory)][string]$Script, [string[]]$ScriptArguments = @())
$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true
$comparisonVswhere = "${env:ProgramFiles(x86)}/Microsoft Visual Studio/Installer/vswhere.exe"
$comparisonVs = & $comparisonVswhere -latest -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
if (-not $comparisonVs) { throw 'MSVC x64 tools required.' }
Import-Module "$comparisonVs/Common7/Tools/Microsoft.VisualStudio.DevShell.dll"
Enter-VsDevShell -VsInstallPath $comparisonVs -Arch amd64 -HostArch amd64 -SkipAutomaticLocation
$env:PATH = "$comparisonVs/Common7/IDE/CommonExtensions/Microsoft/CMake/CMake/bin;$comparisonVs/Common7/IDE/CommonExtensions/Microsoft/CMake/Ninja;$env:PATH"
$env:VCPKG_ROOT = Join-Path (Split-Path -Parent $PSScriptRoot) 'build/vcpkg'
& chcp.com 65001 | Out-Null
& $Script @ScriptArguments
if ($LASTEXITCODE) { exit $LASTEXITCODE }
