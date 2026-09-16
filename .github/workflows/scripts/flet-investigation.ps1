param([Parameter(Mandatory=$true)][ValidateSet('workspace-dev-packages','pep508-git','all-dev-packages')][string]$Approach)
$ErrorActionPreference = 'Stop'
$out = Join-Path $PWD "artifacts/flet-build-investigation/$Approach"
$buildOutput = Join-Path $PWD "artifacts/flet-build-output/$Approach"
New-Item -ItemType Directory -Force $out | Out-Null
function Save-Text([string]$name, [string]$value) { $value | Out-File (Join-Path $out $name) -Encoding utf8 }
$prepare = 'NOT RUN'; $metadata = 'NOT RUN'; $preflight = 'NOT RUN'; $build = 'NOT RUN'; $buildCode = 'NOT RUN'; $exeFound = 'NO'; $cli = 'NOT RUN'; $invalid = 'NOT RUN'; $gui = 'NOT RUN'; $stage = 'unknown'
$infraFailure = $false
git rev-parse HEAD | Tee-Object (Join-Path $out commit.txt)
uv --version | Tee-Object (Join-Path $out environment.txt)
uv run python --version | Tee-Object -Append (Join-Path $out environment.txt)
uv run flet --version | Tee-Object -Append (Join-Path $out environment.txt)
uv sync --locked --all-packages --group build --extra ndi
if ($LASTEXITCODE -ne 0) { throw "uv sync failed with exit code $LASTEXITCODE" }

try {
  if ($Approach -eq 'all-dev-packages') {
    New-Item -ItemType Directory -Force .flet-dev-packages | Out-Null
    foreach ($repo in @('livesplit-bridge-client','windows-capture-device-list')) {
      git clone --depth 1 --branch v0.2.0 "https://github.com/Nanahuse/$repo.git" ".flet-dev-packages/$repo"
      if ($LASTEXITCODE -ne 0) { throw "git clone $repo failed with exit code $LASTEXITCODE" }
      "repository=$(git -C ".flet-dev-packages/$repo" remote get-url origin)`ntag=v0.2.0`ncommit=$(git -C ".flet-dev-packages/$repo" rev-parse HEAD)`npath=$(Resolve-Path ".flet-dev-packages/$repo")" | Out-File (Join-Path $out "$repo-source.txt") -Encoding utf8
    }
  }
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
 'workspace-dev-packages': {'divergencesplitter-runtime','divergencesplitter'},
 'pep508-git': {'divergencesplitter-runtime','divergencesplitter'},
 'all-dev-packages': {'divergencesplitter-runtime','divergencesplitter','livesplit-bridge-client','windows-capture-device-list'},
}[mode]
assert set(ui['tool']['flet']['dev_packages']) == expected_dev
expected_win = {
 'workspace-dev-packages': ['divergencesplitter'],
 'pep508-git': ['divergencesplitter','ndi-python>=6.3.2.4'],
 'all-dev-packages': ['divergencesplitter','livesplit-bridge-client','windows-capture-device-list','ndi-python>=6.3.2.4'],
}[mode]
assert ui['tool']['flet']['windows']['dependencies'] == expected_win
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
  if (Test-Path $buildOutput) { Remove-Item -LiteralPath $buildOutput -Recurse -Force }
  New-Item -ItemType Directory -Force (Split-Path $buildOutput) | Out-Null
  uv run --no-sync flet build windows packages/divergencesplitter-ui --yes --no-rich-output --verbose --output $buildOutput *>&1 | Tee-Object (Join-Path $out flet-build.log)
  $buildCode = $LASTEXITCODE
  $build = if ($buildCode -eq 0) { 'PASS' } else { 'FAIL' }
  if ($buildCode -eq 0) { $stage = '—' }
  Save-Text build_exit_code.txt "$buildCode"
  $log = Get-Content -Raw (Join-Path $out flet-build.log)
  if ($buildCode -ne 0) {
    if ($log -match 'Could not find a version|No matching distribution|serious_python') { $stage = 'python-dependency-packaging' }
    elseif ($log -match '(?i)(clone|checkout|git install).{0,120}(failed|error|fatal)|fatal:') { $stage = 'git-dependency' }
    elseif ($log -match '(?i)(Could not find a version|No matching distribution|Failed to build).{0,160}(ndi-python|NDIlib)|(ndi-python|NDIlib).{0,160}(Could not find|No matching|Failed|ERROR:)') { $stage = 'ndi-dependency' }
    elseif ($log -match 'Flutter.*(failed|error|exception)|Unable to install Flutter') { $stage = 'flutter-sdk-setup' }
    elseif ($log -match 'Flutter project|Generating.*project') { $stage = 'flutter-project-generation' }
    elseif ($log -match 'flutter.*build') { $stage = 'flutter-build' }
  }
} else { Save-Text build_exit_code.txt 'NOT RUN' }

if (Test-Path $buildOutput) { Get-ChildItem $buildOutput -Recurse -File | Select-Object FullName,Length | Out-File (Join-Path $out output-manifest.txt) -Encoding utf8 } else { Save-Text output-manifest.txt 'build output directory not created' }
$exe = if (Test-Path $buildOutput) { Get-ChildItem $buildOutput -Recurse -Filter DivergenceSplitter.exe -File | Select-Object -First 1 } else { $null }
if ($exe) {
  $exeFound = 'YES'; & $exe.FullName --help *> (Join-Path $out cli-help.log); $cliCode = $LASTEXITCODE; $cli = if ($cliCode -eq 0) {'PASS'} else {"FAIL ($cliCode)"}
  & $exe.FullName --definitely-invalid-option *> (Join-Path $out cli-invalid.log); $invalidCode = $LASTEXITCODE; Save-Text cli-invalid-result.txt "exit_code=$invalidCode"
  $proc = Start-Process -FilePath $exe.FullName -PassThru; Start-Sleep -Seconds 3; $gui = if ($proc.HasExited) {'EXITED'} else {'ALIVE'}; if (!$proc.HasExited) { Stop-Process -Id $proc.Id -Force }
} elseif ($build -eq 'NOT RUN') { $stage = if ($stage -eq 'unknown') {'dependency-preflight'} else {$stage} }

if ($build -eq 'PASS') {
  $needles = @('divergencesplitter','divergencesplitter-runtime','livesplit-bridge-client','windows-capture-device-list','ndi-python','numpy','opencv-contrib-python')
  foreach ($needle in $needles) { $found = $log -match [regex]::Escape($needle); "$needle`: $(if ($found) {'LOG MATCH'} else {'NO LOG MATCH'})" | Out-File (Join-Path $out packaged-dependencies.txt) -Append -Encoding utf8 }
}
Save-Text failure-stage.txt $stage
Save-Text result.txt "Approach: $Approach`nPreparation result: $prepare`nMetadata validation result: $metadata`nDependency preflight result: $preflight`nBuild result: $build`nBuild exit code: $buildCode`nEXE found: $exeFound`nCLI smoke result: $cli`nInvalid CLI result: $invalid`nGUI smoke result: $gui`nFailure stage: $stage`nOutput directory: $buildOutput"
Get-Content (Join-Path $out result.txt) | Out-File $env:GITHUB_STEP_SUMMARY -Append -Encoding utf8
if ($infraFailure) { exit 1 }
exit 0
