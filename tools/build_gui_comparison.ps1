#requires -Version 7.3
param(
    [Parameter(Mandatory)][ValidateSet('qt', 'qtquick', 'wx', 'imgui', 'webview2')][string]$Candidate,
    [string]$Python = 'python',
    [string]$InstalledDirectory = '',
    [ValidateSet('standard', 'features', 'optimized')][string]$QtConfiguration = 'standard'
)
$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true
# Keep MSVC /showIncludes output and CMake/Ninja decoding consistent on Japanese Windows.
& chcp.com 65001 | Out-Null
$comparisonRepo = Split-Path -Parent $PSScriptRoot
if ($Candidate -ne 'qt' -and $QtConfiguration -ne 'standard') { throw 'QtConfiguration requires Candidate qt.' }
$comparisonVariant = if ($QtConfiguration -eq 'standard') { $Candidate } else { "qt-$QtConfiguration" }
$comparisonBuild = Join-Path $comparisonRepo "build/gui-comparison/$comparisonVariant"
$comparisonStage = Join-Path $comparisonRepo "dist/gui-comparison/$comparisonVariant"
$comparisonReport = Join-Path $comparisonRepo "build/gui-comparison-reports/$comparisonVariant"
$comparisonManifest = Join-Path $comparisonRepo 'experiments/gui-comparison/vcpkg.json'
$comparisonTimings = [ordered]@{ binary_cache_hit = $env:PROBE_BINARY_CACHE_HIT; phases_seconds = [ordered]@{} }
$comparisonTotal = [Diagnostics.Stopwatch]::StartNew()
if (-not $env:VCPKG_ROOT) { throw 'VCPKG_ROOT must point to the pinned checkout.' }
$comparisonBaseline = (Get-Content $comparisonManifest -Raw | ConvertFrom-Json).'builtin-baseline'
$comparisonCommit = git -C $env:VCPKG_ROOT rev-parse HEAD
if ($comparisonCommit.Trim() -ne $comparisonBaseline) { throw 'vcpkg commit does not match the manifest baseline.' }
if (Test-Path $comparisonStage) { throw "Install directory must be new: $comparisonStage" }
$comparisonInstalled = if ($InstalledDirectory) { [IO.Path]::GetFullPath($InstalledDirectory) } else { Join-Path $comparisonBuild 'vcpkg_installed' }
$comparisonArguments = @('--fresh', '-S', (Join-Path $comparisonRepo 'experiments/gui-comparison'), '-B', $comparisonBuild,
    '-G', 'Ninja', '-DCMAKE_BUILD_TYPE=Release', "-DGUI_CANDIDATE=$Candidate",
    "-DCMAKE_TOOLCHAIN_FILE=$env:VCPKG_ROOT/scripts/buildsystems/vcpkg.cmake", "-DCMAKE_INSTALL_PREFIX=$comparisonStage",
    "-DVCPKG_INSTALLED_DIR=$comparisonInstalled")
if ($Candidate -eq 'qt') {
    $comparisonFeatures = if ($QtConfiguration -eq 'standard') { 'standard' } else { 'lean' }
    $comparisonOptimize = if ($QtConfiguration -eq 'optimized') { 'ON' } else { 'OFF' }
    $comparisonArguments += @("-DGUI_QT_FEATURES=$comparisonFeatures", "-DGUI_QT_OPTIMIZE_DEPLOY=$comparisonOptimize")
}
if ($Candidate -eq 'qtquick' -and $env:GUI_VCPKG_SCRATCH) {
    # qtdeclarative's generated files exceed MSVC path limits in deep checkouts.
    $comparisonScratch = [IO.Path]::GetFullPath($env:GUI_VCPKG_SCRATCH).Replace('\', '/')
    $comparisonArguments += "-DVCPKG_INSTALL_OPTIONS=--x-buildtrees-root=$comparisonScratch/buildtrees;--x-packages-root=$comparisonScratch/packages"
}
$comparisonPhase = [Diagnostics.Stopwatch]::StartNew()
& cmake @comparisonArguments
$comparisonTimings.phases_seconds.configure_including_dependencies = $comparisonPhase.Elapsed.TotalSeconds
if ($env:GITHUB_OUTPUT) { 'dependencies_configured=true' >> $env:GITHUB_OUTPUT }
$comparisonPhase.Restart()
& cmake --build $comparisonBuild --clean-first
$comparisonTimings.phases_seconds.release_build = $comparisonPhase.Elapsed.TotalSeconds
$comparisonPhase.Restart()
& ctest --test-dir $comparisonBuild --output-on-failure --output-junit gui-tests.xml
$comparisonTimings.phases_seconds.ctest = $comparisonPhase.Elapsed.TotalSeconds
$comparisonPhase.Restart()
& cmake --install $comparisonBuild
$comparisonTimings.phases_seconds.install_deploy = $comparisonPhase.Elapsed.TotalSeconds
$comparisonPhase.Restart()
$comparisonPackageArguments = @((Join-Path $PSScriptRoot 'package_gui_comparison.py'), '--candidate', $Candidate,
    '--root', $comparisonStage, '--installed', $comparisonInstalled, '--output', $comparisonReport, '--manifest', $comparisonManifest)
if ($Candidate -eq 'qt') {
    $comparisonPackageArguments += @('--qt-configuration', $QtConfiguration, '--qt-runtime-probe', (Join-Path $comparisonBuild 'qt-runtime-check.exe'))
}
& $Python @comparisonPackageArguments
$comparisonTimings.phases_seconds.package_and_zip_launch = $comparisonPhase.Elapsed.TotalSeconds
$comparisonTimings.total_seconds = $comparisonTotal.Elapsed.TotalSeconds
$comparisonTimings | ConvertTo-Json -Depth 5 | Set-Content -Encoding utf8 (Join-Path $comparisonReport 'timings.json')
