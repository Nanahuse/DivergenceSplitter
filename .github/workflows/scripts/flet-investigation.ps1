param([Parameter(Mandatory=$true)][ValidateSet('pep508-git')][string]$Approach)
$ErrorActionPreference = 'Stop'
$out = Join-Path $PWD "artifacts/flet-build-investigation/$Approach"
$buildOutput = Join-Path $PWD "artifacts/flet-build-output/$Approach"
New-Item -ItemType Directory -Force $out | Out-Null
function Save-Text([string]$name, [string]$value) { $value | Out-File (Join-Path $out $name) -Encoding utf8 }
$prepare = 'NOT RUN'; $metadata = 'NOT RUN'; $preflight = 'NOT RUN'; $encoding = 'NOT RUN'; $build = 'NOT RUN'; $buildCode = 'NOT RUN'; $packageContent = 'NOT RUN'; $opencvContent = 'NOT RUN'; $opencvRuntime = 'NOT RUN'; $exeFound = 'NO'; $exePath = 'NOT FOUND'; $cli = 'NOT RUN'; $cliCode = 'NOT RUN'; $invalid = 'NOT RUN'; $invalidCode = 'NOT RUN'; $gui = 'NOT RUN'; $guiExitCode = 'N/A'; $stage = 'unknown'
$infraFailure = $false
git rev-parse HEAD | Tee-Object (Join-Path $out commit.txt)
uv --version | Tee-Object (Join-Path $out environment.txt)
uv run python --version | Tee-Object -Append (Join-Path $out environment.txt)
uv sync --locked --all-packages --group build --extra ndi
if ($LASTEXITCODE -ne 0) { throw "uv sync failed with exit code $LASTEXITCODE" }
$env:FLET_CLI_NO_RICH_OUTPUT = '1'
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
@"
FLET_CLI_NO_RICH_OUTPUT=$env:FLET_CLI_NO_RICH_OUTPUT
PYTHONUTF8=$env:PYTHONUTF8
PYTHONIOENCODING=$env:PYTHONIOENCODING
"@ | Out-File (Join-Path $out environment.txt) -Append -Encoding utf8
uv run flet --version | Tee-Object -Append (Join-Path $out environment.txt)
if ($LASTEXITCODE -ne 0) { throw "flet --version failed with exit code $LASTEXITCODE" }
uv run --no-sync flet build windows --help *>&1 | Tee-Object (Join-Path $out flet-build-cli-help.txt)
if ($LASTEXITCODE -ne 0) { throw "flet build windows --help failed with exit code $LASTEXITCODE" }
$cliHelp = Get-Content -Raw (Join-Path $out flet-build-cli-help.txt)
if ($cliHelp -notmatch '--artifact' -or $cliHelp -notmatch '--product' -or $cliHelp -notmatch '--no-compile-packages') { throw 'Flet CLI does not advertise required build options' }

try {
  uv run python tools/prepare_flet_build_experiment.py $Approach
  if ($LASTEXITCODE -ne 0) { throw "metadata helper failed with exit code $LASTEXITCODE" }
  $prepare = 'PASS'
} catch {
  $prepare = 'FAIL'; $infraFailure = $true; $stage = 'experiment-preparation'; Save-Text preparation-error.txt $_.Exception.Message
}

if ($prepare -eq 'PASS') {
  Copy-Item packages/divergencesplitter-ui/pyproject.toml $out/ui-pyproject.toml
  Copy-Item packages/divergencesplitter-runtime/pyproject.toml $out/runtime-pyproject.toml
  Copy-Item packages/divergencesplitter-ui/src/main.py $out/main.py
  $validation = @"
import sys, tomllib
from pathlib import Path
ui = tomllib.loads(Path('packages/divergencesplitter-ui/pyproject.toml').read_text(encoding='utf-8'))
runtime = tomllib.loads(Path('packages/divergencesplitter-runtime/pyproject.toml').read_text(encoding='utf-8'))
mode = '$Approach'
assert ui['tool']['flet']['app'] == {'path': 'src', 'module': 'main'}
expected_dev = {
 'pep508-git': {'divergencesplitter-runtime','divergencesplitter'},
}[mode]
assert set(ui['tool']['flet']['dev_packages']) == expected_dev
expected_win = {
 'pep508-git': ['divergencesplitter','ndi-python>=6.3.2.4'],
}[mode]
assert ui['tool']['flet']['windows']['dependencies'] == expected_win
assert ui['tool']['flet']['windows']['compile']['packages'] is False
assert ui['tool']['flet']['windows']['cleanup']['packages'] is False
if mode == 'pep508-git':
    assert any(x.startswith('livesplit-bridge-client @ git+') for x in runtime['project']['dependencies'])
    assert any(x.startswith('windows-capture-device-list @ git+') for x in runtime['project']['dependencies'])
print('TOML: PASS\nentry: PASS\ndev_packages: PASS\nwindows_dependencies: PASS\npep508_refs: ' + ('PASS' if mode == 'pep508-git' else 'N/A'))
"@
  uv run python -c $validation 2>&1 | Tee-Object (Join-Path $out experiment-metadata-validation.txt)
  if ($LASTEXITCODE -eq 0) { $metadata = 'PASS'; Save-Text toml-validation.txt 'PASS' } else { $metadata = 'FAIL'; $infraFailure = $true; $stage = 'experiment-metadata-validation'; Save-Text toml-validation.txt 'FAIL' }
}

if ($metadata -eq 'PASS') {
  $preflightScript = @"
import tomllib
from pathlib import Path
from urllib.parse import urljoin
from pathlib import PurePosixPath
ui_path = Path('packages/divergencesplitter-ui/pyproject.toml').resolve()
runtime_path = Path('packages/divergencesplitter-runtime/pyproject.toml').resolve()
ui = tomllib.loads(ui_path.read_text(encoding='utf-8'))
rt = tomllib.loads(runtime_path.read_text(encoding='utf-8'))
dev = ui['tool']['flet']['dev_packages']
requirements = list(ui['project'].get('dependencies', [])) + list(ui['tool']['flet']['windows']['dependencies'])
requirements.extend(rt['project'].get('dependencies', []))
resolved = []
for req in requirements:
    name = req.split(';', 1)[0].split('>', 1)[0].split('=', 1)[0].strip().lower().replace('_','-')
    local = next((p for n,p in dev.items() if n.lower().replace('_','-') == name), None)
    if local:
        package_root = (ui_path.parent / local).resolve()
        resolved.append(f'{name} @ {package_root.as_uri()}')
    else:
        resolved.append(req)
Path('artifacts/flet-build-investigation/$Approach/dependency-preflight-requirements.txt').write_text('\n'.join(resolved)+'\n', encoding='utf-8')
"@
  uv run python -c $preflightScript 2>&1 | Tee-Object (Join-Path $out preflight-generation.log)
  if ($LASTEXITCODE -eq 0) {
    $venv = Join-Path $PWD "artifacts/preflight-env/$Approach"
    uv venv --python 3.14 $venv
    if ($LASTEXITCODE -eq 0) { uv pip install --python "$venv/Scripts/python.exe" pip }
    if ($LASTEXITCODE -eq 0) {
      & "$venv/Scripts/python.exe" -m pip install --dry-run --ignore-installed --no-input --extra-index-url https://pypi.flet.dev -r (Join-Path $out dependency-preflight-requirements.txt) 2>&1 | Tee-Object (Join-Path $out dependency-preflight.log)
      if ($LASTEXITCODE -eq 0) { $preflight = 'PASS' } else { $preflight = 'FAIL'; $stage = 'dependency-preflight' }
    } else { $preflight = 'FAIL'; $stage = 'dependency-preflight' }
  } else { $preflight = 'FAIL'; $stage = 'dependency-preflight' }
}

if ($preflight -eq 'PASS') {
  $encodingCommand = "import sys; print('stdout encoding: ' + str(sys.stdout.encoding)); print('√'); from rich.console import Console; Console().print('√')"
  uv run python -c $encodingCommand 2>&1 | Tee-Object (Join-Path $out encoding-preflight.txt)
  $encodingCode = $LASTEXITCODE
  $encodingLog = Get-Content -Raw (Join-Path $out encoding-preflight.txt)
  Get-Content (Join-Path $out encoding-preflight.txt) | Out-File (Join-Path $out environment.txt) -Append -Encoding utf8
  if ($encodingCode -eq 0 -and ([regex]::Matches($encodingLog, '√').Count -ge 2)) { $encoding = 'PASS' }
  else { $encoding = 'FAIL'; $stage = 'encoding-preflight' }
}

if ($encoding -eq 'PASS') {
  if (Test-Path $buildOutput) { Remove-Item -LiteralPath $buildOutput -Recurse -Force }
  New-Item -ItemType Directory -Force (Split-Path $buildOutput) | Out-Null
  uv run --no-sync flet build windows packages/divergencesplitter-ui --yes --no-rich-output --verbose --artifact DivergenceSplitter --product DivergenceSplitter --no-compile-packages --output $buildOutput *>&1 | Tee-Object (Join-Path $out flet-build.log)
  $buildCode = $LASTEXITCODE
  $build = if ($buildCode -eq 0) { 'PASS' } else { 'FAIL' }
  if ($buildCode -eq 0) { $stage = '—' }
  Save-Text build_exit_code.txt "$buildCode"
  $log = Get-Content -Raw (Join-Path $out flet-build.log)
  if ($buildCode -ne 0) {
    if ($log -match '(?i)UnicodeEncodeError|charmap codec can.t encode|cp1252') { $stage = 'encoding-output' }
    elseif ($log -match '(?i)(clone|checkout|git install).{0,120}(failed|error|fatal)|fatal:') { $stage = 'git-dependency' }
    elseif ($log -match '(?i)(Could not find a version|No matching distribution|Failed to build).{0,160}(ndi-python|NDIlib)|(ndi-python|NDIlib).{0,160}(Could not find|No matching|Failed|ERROR:)') { $stage = 'ndi-dependency' }
    elseif ($log -match '(?i)Could not find a version|No matching distribution|serious_python|pip install.*(failed|error)') { $stage = 'python-dependency-packaging' }
    elseif ($log -match '(?i)Flutter.{0,100}(failed|error|exception)|Unable to install Flutter') { $stage = 'flutter-sdk-setup' }
    elseif ($log -match '(?i)Flutter project.{0,80}(failed|error)|Generating.{0,80}(failed|error)') { $stage = 'flutter-project-generation' }
    elseif ($log -match '(?i)FAILURE: Build failed|flutter build.{0,100}(failed|error)|Error:.*build') { $stage = 'flutter-build' }
  }
} else { Save-Text build_exit_code.txt 'NOT RUN'; if ($encoding -eq 'NOT RUN' -and $stage -eq 'unknown') { $stage = 'dependency-preflight' } }

if (Test-Path $buildOutput) {
  Get-ChildItem $buildOutput -Recurse -File | ForEach-Object { "{0}`t{1}" -f $_.FullName,$_.Length } | Out-File (Join-Path $out output-manifest.txt) -Encoding utf8
} else { Save-Text output-manifest.txt 'build output directory not created' }

$exe = Join-Path $buildOutput 'DivergenceSplitter.exe'
if (Test-Path -LiteralPath $exe -PathType Leaf) {
  $exeFound = 'YES'; $exePath = (Resolve-Path -LiteralPath $exe).Path
  Save-Text app-exe.txt $exePath
} else { $exe = $null; Save-Text app-exe.txt 'NOT FOUND: expected build output root DivergenceSplitter.exe' }

if ($exe) {
  & $exe --help *> (Join-Path $out cli-help.log); $cliCode = $LASTEXITCODE; $cli = if ($cliCode -eq 0) {'PASS'} else {"FAIL ($cliCode)"}
  Save-Text cli-help-result.txt "exit_code=$cliCode"
  & $exe --definitely-invalid-option *> (Join-Path $out cli-invalid.log); $invalidCode = $LASTEXITCODE; Save-Text cli-invalid-result.txt "exit_code=$invalidCode"
  $invalid = if ($invalidCode -eq 2) {'PASS'} else {"FAIL ($invalidCode)"}
  try {
    $guiStdout = Join-Path $out 'gui-stdout.log'
    $guiStderr = Join-Path $out 'gui-stderr.log'
    $proc = Start-Process -FilePath $exe -PassThru -RedirectStandardOutput $guiStdout -RedirectStandardError $guiStderr -ErrorAction Stop
    $processId = $proc.Id
    Start-Sleep -Seconds 5
    if ($proc.HasExited) { $gui = 'EXITED'; $guiExitCode = $proc.ExitCode }
    else { $gui = 'ALIVE'; $guiExitCode = 'N/A'; Stop-Process -Id $processId -Force }
    Save-Text gui-startup.txt "process start: SUCCESS`nPID: $processId`n5-second state: $gui`nexit code: $guiExitCode"
  } catch { $gui = 'ERROR'; Save-Text gui-startup.txt "process start: ERROR`n$($_.Exception.Message)" }
} elseif ($build -eq 'NOT RUN' -and $stage -eq 'unknown') { $stage = if ($encoding -eq 'FAIL') {'encoding-preflight'} else {'dependency-preflight'} }

if ($build -eq 'PASS' -and (Test-Path $buildOutput)) {
  $files = @(Get-ChildItem -LiteralPath $buildOutput -Recurse -File)
  $relativeFiles = @($files | ForEach-Object { [System.IO.Path]::GetRelativePath($buildOutput,$_.FullName).Replace('\','/') })
  $opencvPaths = @($files | Where-Object { $_.Directory.Name -eq 'cv2' } | ForEach-Object { $_.Directory.FullName } | Sort-Object -Unique)
  $opencvPath = if ($opencvPaths.Count -gt 0) { $opencvPaths[0] } else { $null }
  Save-Text opencv-package-path.txt $(if ($opencvPath) { $opencvPath } else { 'NOT FOUND' })
  $opencvChecks = [ordered]@{}
  foreach ($requiredFile in @('config.py', 'config-3.py', '__init__.py', 'cv2.pyd')) {
    $opencvChecks["cv2/$requiredFile"] = [bool]($opencvPath -and (Test-Path -LiteralPath (Join-Path $opencvPath $requiredFile) -PathType Leaf))
  }
  $opencvChecks['OpenCV loader source files retained'] = ($opencvChecks['cv2/config.py'] -and $opencvChecks['cv2/config-3.py'])
  $opencvChecks.GetEnumerator() | ForEach-Object { "{0}: {1}" -f $_.Key, $(if ($_.Value) {'PASS'} else {'FAIL'}) } | Out-File (Join-Path $out opencv-content-check.txt) -Encoding utf8
  $opencvContent = if (@($opencvChecks.Values | Where-Object { -not $_ }).Count -eq 0) {'PASS'} else {'FAIL'}
  $sizeBytes = ($files | Measure-Object -Property Length -Sum).Sum
  Save-Text build-output-size.txt "bytes=$sizeBytes`nmegabytes=$([math]::Round($sizeBytes / 1MB, 2))"
  $checks = [ordered]@{
    'divergencesplitter' = [bool](@($relativeFiles | Where-Object { $_ -match '^site-packages/divergencesplitter/' }).Count -gt 0)
    'divergencesplitter_runtime' = [bool](@($relativeFiles | Where-Object { $_ -match '^site-packages/divergencesplitter_runtime/' }).Count -gt 0)
    'livesplit' = [bool](@($relativeFiles | Where-Object { $_ -match '^site-packages/livesplit/' }).Count -gt 0)
    'livesplit_bridge' = [bool](@($relativeFiles | Where-Object { $_ -match '^site-packages/livesplit_bridge/' }).Count -gt 0)
    'windows_capture_device_list' = [bool](@($relativeFiles | Where-Object { $_ -match '^site-packages/windows_capture_device_list/' }).Count -gt 0)
    'NDIlib package' = [bool](@($relativeFiles | Where-Object { $_ -match '^site-packages/NDIlib/' }).Count -gt 0)
    'NDIlib extension' = [bool](@($relativeFiles | Where-Object { $_ -match '(?i)^site-packages/NDIlib/NDIlib.*\.pyd$' }).Count -gt 0)
    'NDI runtime DLL' = [bool](@($relativeFiles | Where-Object { $_ -match '(?i)^site-packages/NDIlib/.*\.dll$' }).Count -gt 0)
    'windows_capture_device_list extension' = [bool](@($relativeFiles | Where-Object { $_ -match '(?i)^site-packages/windows_capture_device_list/.*\.pyd$' }).Count -gt 0)
    'NumPy' = [bool](@($relativeFiles | Where-Object { $_ -match '^site-packages/numpy/' }).Count -gt 0)
    'NumPy native extension' = [bool](@($relativeFiles | Where-Object { $_ -match '(?i)^site-packages/numpy/.*\.pyd$' }).Count -gt 0)
    'OpenCV (cv2)' = [bool](@($relativeFiles | Where-Object { $_ -match '^site-packages/cv2/' }).Count -gt 0)
    'OpenCV extension' = [bool](@($relativeFiles | Where-Object { $_ -match '(?i)^site-packages/cv2/.*\.pyd$' }).Count -gt 0)
    'OpenCV config.py source' = $opencvChecks['cv2/config.py']
    'OpenCV config-3.py source' = $opencvChecks['cv2/config-3.py']
    'OpenCV __init__.py source' = $opencvChecks['cv2/__init__.py']
    'OpenCV cv2.pyd' = $opencvChecks['cv2/cv2.pyd']
  }
  $checks.GetEnumerator() | ForEach-Object { "{0}: {1}" -f $_.Key, $(if ($_.Value) {'PASS'} else {'FAIL'}) } | Out-File (Join-Path $out package-content-check.txt) -Encoding utf8
  $packageContent = if (@($checks.Values | Where-Object { -not $_ }).Count -eq 0) {'PASS'} else {'FAIL'}
  $pythonExeCandidates = @((Join-Path $buildOutput 'python.exe'), (Join-Path (Join-Path $buildOutput 'python') 'python.exe'))
  $packagedPython = $pythonExeCandidates | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
  if ($packagedPython) {
    $env:PYTHONPATH = Join-Path $buildOutput 'site-packages'
    & $packagedPython -c 'import cv2; print(cv2.__version__)' *>&1 | Tee-Object (Join-Path $out opencv-import-smoke.log)
    $opencvRuntime = if ($LASTEXITCODE -eq 0) {'PASS'} else {'FAIL'}
  } else {
    $runtimeLogs = @((Join-Path $out cli-help.log),(Join-Path $out cli-invalid.log),(Join-Path $out gui-stdout.log),(Join-Path $out gui-stderr.log)) | Where-Object { Test-Path $_ } | ForEach-Object { Get-Content -Raw $_ }
    $runtimeText = $runtimeLogs -join "`n"
    if ($runtimeText -match '(?i)OpenCV loader: missing configuration|ImportError.{0,100}cv2|No module named .cv2') { $opencvRuntime = 'FAIL' }
    elseif ($gui -eq 'ALIVE') { $opencvRuntime = 'PASS (application alive; no OpenCV import error in captured logs)' }
    else { $opencvRuntime = 'NOT CONFIRMED' }
  }
  Save-Text opencv-runtime-result.txt $opencvRuntime
} else { Save-Text package-content-check.txt 'NOT RUN: Flet build did not succeed'; Save-Text opencv-content-check.txt 'NOT RUN: Flet build did not succeed'; Save-Text opencv-package-path.txt 'NOT FOUND'; Save-Text build-output-size.txt 'NOT AVAILABLE'; $packageContent = 'NOT RUN'; $opencvContent = 'NOT RUN'; $opencvRuntime = 'NOT RUN' }

if ($build -eq 'PASS') {
  if ($exeFound -ne 'YES') { $stage = 'app-exe-missing' }
  elseif ($opencvContent -eq 'FAIL') { $stage = 'opencv-package-content' }
  elseif ($opencvRuntime -eq 'FAIL') { $stage = 'opencv-runtime-import' }
  elseif ($packageContent -eq 'FAIL') { $stage = 'package-content' }
  elseif ($cli -ne 'PASS' -or $invalid -ne 'PASS') { $stage = 'cli-smoke' }
  else { $stage = '—' }
} elseif ($build -eq 'NOT RUN' -and $stage -eq 'unknown') { $stage = if ($encoding -eq 'FAIL') {'encoding-preflight'} else {'dependency-preflight'} }

Save-Text failure-stage.txt $stage
Save-Text result.txt "Approach: pep508-git`nPreparation result: $prepare`nMetadata validation result: $metadata`nDependency preflight result: $preflight`nEncoding preflight result: $encoding`nBuild result: $build`nBuild exit code: $buildCode`nPackage content result: $packageContent`nOpenCV content result: $opencvContent`nOpenCV runtime result: $opencvRuntime`nEXE found: $exeFound`nApp EXE path: $exePath`nCLI smoke result: $cli`nCLI --help exit code: $cliCode`nInvalid CLI result: $invalid`nInvalid option exit code: $invalidCode`nGUI smoke result: $gui`nGUI exit code: $guiExitCode`nFailure stage: $stage`nOutput directory: $buildOutput"
Get-Content (Join-Path $out result.txt) | Out-File $env:GITHUB_STEP_SUMMARY -Append -Encoding utf8
"build_result=$build" | Out-File $env:GITHUB_OUTPUT -Append -Encoding utf8
if ($infraFailure) { exit 1 }
exit 0
