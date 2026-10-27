#requires -Version 7.3
# Invoke through gui_dev_shell.ps1 after the webview2 candidate dependencies are configured.
param([string]$InstalledDirectory = 'build/gui-comparison/webview2/vcpkg_installed')
$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true
$probeRoot = [IO.Path]::GetFullPath('build/webview-host-probe')
New-Item -ItemType Directory -Force "$probeRoot/assets" | Out-Null
$probeHeader = Join-Path $probeRoot 'webview.h'
if (-not (Test-Path $probeHeader)) {
    Invoke-WebRequest 'https://raw.githubusercontent.com/webview/webview/0.12.0/core/include/webview/webview.h' -OutFile $probeHeader
}
if ((Get-FileHash $probeHeader -Algorithm SHA256).Hash -ne 'B1FF6E11431D031E5F7917E5301F4BCDF3910A2763A0720ABFD291994EEE7F7B') { throw 'Wrapper header hash mismatch' }
'<!doctype html><title>Wrapper probe</title><script>probe("roundtrip").then(r => document.body.textContent = JSON.stringify(r));</script><body>Probe</body>' | Set-Content "$probeRoot/assets/index.html" -Encoding utf8
$probeInstalled = (Resolve-Path $InstalledDirectory).Path
& cl.exe /nologo /std:c++20 /EHsc /utf-8 /DWEBVIEW_MSWEBVIEW2_EXPLICIT_LINK=1 /DWEBVIEW_MSWEBVIEW2_BUILTIN_IMPL=0 "/I$probeRoot" "/I$probeInstalled/x64-windows/include" experiments/gui-comparison/webview2/host_probe.cpp "/Fo$probeRoot/host-probe.obj" "/Fe$probeRoot/host-probe.exe" /link "/LIBPATH:$probeInstalled/x64-windows/lib" WebView2Loader.dll.lib ole32.lib shlwapi.lib version.lib user32.lib gdi32.lib advapi32.lib shell32.lib
Copy-Item "$probeInstalled/x64-windows/bin/WebView2Loader.dll" $probeRoot
# A disposable UDF is isolated from both the comparison app and other WebView2 apps.
$env:WEBVIEW2_USER_DATA_FOLDER = Join-Path $probeRoot 'user-data'
& "$probeRoot/host-probe.exe" "$probeRoot/assets"
