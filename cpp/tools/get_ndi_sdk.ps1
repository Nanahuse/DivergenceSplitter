param(
    [Parameter(Mandatory = $true)][string]$Destination
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$lock = Get-Content (Join-Path $PSScriptRoot 'ndi-sdk-lock.json') -Raw | ConvertFrom-Json
if (-not $env:NDI_SDK_URL_WINDOWS) { throw 'Required NDI_SDK_URL_WINDOWS Secret is not configured' }
$uri = $null
if (-not [Uri]::TryCreate($env:NDI_SDK_URL_WINDOWS.Trim(), [UriKind]::Absolute, [ref]$uri) -or
    $uri.Scheme -ne 'https' -or $uri.DnsSafeHost -ne 'downloads.ndi.tv') {
    throw 'NDI SDK URL must use the official HTTPS distribution host'
}
New-Item -ItemType Directory -Path $Destination -Force | Out-Null
$installer = Join-Path $Destination 'ndi-sdk.exe'
try {
    # Do not print the URL, response body, redirects, or request exceptions.
    try { Invoke-WebRequest -Uri $uri -OutFile $installer } catch { throw 'Official NDI SDK download failed' }
    if ((Get-FileHash $installer -Algorithm SHA256).Hash.ToLowerInvariant() -ne $lock.installer_sha256) {
        throw 'NDI SDK installer SHA-256 mismatch; review and update the pin explicitly'
    }
    if ((Get-Item $installer).VersionInfo.ProductVersion.Trim() -ne $lock.version) {
        throw 'NDI SDK installer product version does not match the pin'
    }
    $signature = Get-AuthenticodeSignature $installer
    if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'O=Vizrt AG') {
        throw 'NDI SDK installer signature is not valid for Vizrt AG'
    }
    $extractorZip = Join-Path $Destination 'innoextract.zip'
    Invoke-WebRequest -Uri "https://constexpr.org/innoextract/files/innoextract-$($lock.innoextract_version)-windows.zip" -OutFile $extractorZip
    if ((Get-FileHash $extractorZip -Algorithm SHA256).Hash.ToLowerInvariant() -ne $lock.innoextract_sha256) {
        throw 'innoextract SHA-256 mismatch'
    }
    $extractorDir = Join-Path $Destination 'extractor'
    Expand-Archive -LiteralPath $extractorZip -DestinationPath $extractorDir -Force
    & (Join-Path $extractorDir 'innoextract.exe') $installer --output-dir $Destination --silent
    if ($LASTEXITCODE -ne 0) { throw 'NDI SDK extraction failed' }
    $sdk = Join-Path $Destination 'app'
    foreach ($required in @('Include/Processing.NDI.Lib.h', 'Include/Processing.NDI.DynamicLoad.h',
        'Bin/x64/Processing.NDI.Lib.x64.dll', 'Bin/x64/Processing.NDI.Lib.Licenses.txt',
        'NDI SDK License Agreement.pdf')) {
        if (-not (Test-Path -LiteralPath (Join-Path $sdk $required) -PathType Leaf)) {
            throw "Extracted SDK is missing $required"
        }
    }
    $dll = Get-Item (Join-Path $sdk 'Bin/x64/Processing.NDI.Lib.x64.dll')
    if ($dll.VersionInfo.ProductVersion.Trim() -ne $lock.version) { throw 'NDI runtime version mismatch' }
    $pinnedFiles = @{
        'Bin/x64/Processing.NDI.Lib.x64.dll' = $lock.runtime_sha256
        'Bin/x64/Processing.NDI.Lib.Licenses.txt' = $lock.runtime_licenses_sha256
        'NDI SDK License Agreement.pdf' = $lock.agreement_sha256
    }
    foreach ($entry in $pinnedFiles.GetEnumerator()) {
        if ((Get-FileHash (Join-Path $sdk $entry.Key) -Algorithm SHA256).Hash.ToLowerInvariant() -ne $entry.Value) {
            throw "Extracted SDK pin mismatch: $($entry.Key)"
        }
    }
    if ($env:GITHUB_ENV) { "NDI_SDK_DIR=$sdk" | Out-File $env:GITHUB_ENV -Append -Encoding utf8 }
    Write-Output "Validated official NDI SDK $($lock.version) (installer SHA-256 and runtime version)"
} finally {
    # Never cache or upload the installer or extracted development files.
    Remove-Item -LiteralPath $installer -Force -ErrorAction SilentlyContinue
}
