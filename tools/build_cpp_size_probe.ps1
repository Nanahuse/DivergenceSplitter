#requires -Version 7.3
param(
    [string]$NdiSdkDirectory = $env:NDI_SDK_DIR,
    [string]$NdiLicenseFile = $env:NDI_LICENSE_FILE,
    [string]$Python = 'python'
)
$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true
$probeRepo = Split-Path -Parent $PSScriptRoot
$probeSource = Join-Path $probeRepo 'experiments/cpp-size-probe'
$probeBuild = Join-Path $probeRepo 'build/cpp-size-probe'
$probeStage = Join-Path $probeRepo 'dist/cpp-size-probe'
$probeReports = Join-Path $probeRepo 'build/size-probe/cpp-report'
$probeTimings = [ordered]@{ binary_cache_hit = $env:PROBE_BINARY_CACHE_HIT; phases_seconds = [ordered]@{} }
$probeTotalTimer = [Diagnostics.Stopwatch]::StartNew()
$probeSourceRef = if ($env:GITHUB_SHA) { $env:GITHUB_SHA } else { "local working tree based on $(git -C $probeRepo rev-parse HEAD)" }
if (-not $env:VCPKG_ROOT) { throw 'Set VCPKG_ROOT to the pinned vcpkg checkout.' }
$probeManifest = Get-Content (Join-Path $probeSource 'vcpkg.json') -Raw | ConvertFrom-Json
$probeCommit = git -C $env:VCPKG_ROOT rev-parse HEAD
if ($probeCommit.Trim() -ne $probeManifest.'builtin-baseline') {
    throw 'VCPKG_ROOT must be checked out at the manifest builtin-baseline commit.'
}
if (Test-Path $probeStage) { throw "Use a fresh install directory; existing stage would skew measurement: $probeStage" }
if ($NdiSdkDirectory -and -not $NdiLicenseFile) { throw 'NDI_LICENSE_FILE from the same official SDK is required.' }
Push-Location $probeSource
try {
    $probePhaseTimer = [Diagnostics.Stopwatch]::StartNew()
    & cmake --preset windows-release "-DNDI_SDK_DIR=$NdiSdkDirectory" "-DNDI_LICENSE_FILE=$NdiLicenseFile"
    $probeTimings.phases_seconds.configure_including_dependency_install = $probePhaseTimer.Elapsed.TotalSeconds
    $probePhaseTimer.Restart()
    & cmake --build --preset windows-release
    $probeTimings.phases_seconds.release_build = $probePhaseTimer.Elapsed.TotalSeconds
    $probePhaseTimer.Restart()
    & ctest --preset windows-release
    $probeTimings.phases_seconds.ctest = $probePhaseTimer.Elapsed.TotalSeconds
    $probePhaseTimer.Restart()
    & cmake --install $probeBuild
    $probeTimings.phases_seconds.install_and_deploy = $probePhaseTimer.Elapsed.TotalSeconds
} finally { Pop-Location }
$probePhaseTimer.Restart()
& $Python (Join-Path $PSScriptRoot 'prepare_cpp_distribution.py') --root $probeStage --installed (Join-Path $probeBuild 'vcpkg_installed') --manifest (Join-Path $probeSource 'vcpkg.json')
$probeTimings.phases_seconds.validate_and_smoke = $probePhaseTimer.Elapsed.TotalSeconds
$probeMeasureArgs = @(
    (Join-Path $PSScriptRoot 'measure_distribution.py'), '--root', $probeStage,
    '--output', $probeReports, '--kind', 'cpp', '--label', 'C++23 Qt Widgets dependency probe',
    '--vcpkg-installed', (Join-Path $probeBuild 'vcpkg_installed'), '--provenance', $probeSourceRef
)
$probeLegacyReport = Join-Path $probeRepo 'build/size-probe/legacy-report/report.json'
if (Test-Path $probeLegacyReport) { $probeMeasureArgs += @('--legacy-report', $probeLegacyReport) }
$probePhaseTimer.Restart()
& $Python @probeMeasureArgs
$probeTimings.phases_seconds.measure_and_zip = $probePhaseTimer.Elapsed.TotalSeconds
$probePhaseTimer.Restart()
& $Python (Join-Path $PSScriptRoot 'verify_cpp_size_probe_zip.py') --archive (Join-Path $probeReports 'cpp.zip') --extract-to (Join-Path $probeRepo 'build/size-probe/zip-extracted') --output (Join-Path $probeReports 'zip-verification.json')
$probeTimings.phases_seconds.zip_extract_and_launch = $probePhaseTimer.Elapsed.TotalSeconds
$probeTimings.total_seconds = $probeTotalTimer.Elapsed.TotalSeconds
$probeTimings | ConvertTo-Json -Depth 5 | Set-Content -Encoding utf8 (Join-Path $probeReports 'timings.json')
