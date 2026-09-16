param([Parameter(Mandatory=$true)][string]$Approach, [Parameter(Mandatory=$true)][string]$BuildCommand)
$ErrorActionPreference = 'Stop'
$out = Join-Path $PWD "artifacts/flet-build-investigation/$Approach"
New-Item -ItemType Directory -Force $out | Out-Null
function Save-Text($name, $value) { $value | Out-File (Join-Path $out $name) -Encoding utf8 }

git rev-parse HEAD | Tee-Object (Join-Path $out commit.txt)
uv sync --locked --all-packages --group build --extra ndi
uv --version | Tee-Object (Join-Path $out environment.txt)
uv run python --version | Tee-Object -Append (Join-Path $out environment.txt)
uv run flet --version | Tee-Object -Append (Join-Path $out environment.txt)
uv tree | Tee-Object (Join-Path $out uv-tree.txt)

if ($Approach -in @('entry-only','workspace-dev-packages','pep508-git','all-dev-packages')) {
  uv run python tools/prepare_flet_build_experiment.py $Approach
}
if ($Approach -eq 'all-dev-packages') {
  New-Item -ItemType Directory -Force .flet-dev-packages | Out-Null
  git clone --depth 1 --branch v0.2.0 https://github.com/Nanahuse/livesplit-bridge-client.git .flet-dev-packages/livesplit-bridge-client
  git clone --depth 1 --branch v0.2.0 https://github.com/Nanahuse/windows-capture-device-list.git .flet-dev-packages/windows-capture-device-list
  foreach ($package in @('livesplit-bridge-client','windows-capture-device-list')) {
    "repository=$(git -C ".flet-dev-packages/$package" remote get-url origin)`ntag=v0.2.0`ncommit=$(git -C ".flet-dev-packages/$package" rev-parse HEAD)`npath=$(Resolve-Path ".flet-dev-packages/$package")" | Out-File (Join-Path $out "$package-source.txt") -Encoding utf8
  }
}
Copy-Item packages/divergencesplitter-ui/pyproject.toml $out/ui-pyproject.toml
Copy-Item packages/divergencesplitter-runtime/pyproject.toml $out/runtime-pyproject.toml
if (Test-Path packages/divergencesplitter-ui/src/main.py) { Copy-Item packages/divergencesplitter-ui/src/main.py $out/main.py }
uv run python -c "import tomllib; from pathlib import Path; [tomllib.loads(Path(p).read_text(encoding='utf-8')) for p in ['packages/divergencesplitter-ui/pyproject.toml','packages/divergencesplitter-runtime/pyproject.toml']]; print('PASS')" | Tee-Object (Join-Path $out toml-validation.txt)

& powershell -NoProfile -Command "$BuildCommand *>&1 | Tee-Object '$out/flet-build.log'; exit `$LASTEXITCODE"
$code = $LASTEXITCODE
Save-Text build_exit_code.txt $code
$stage = 'unknown'
$log = if (Test-Path "$out/flet-build.log") { Get-Content -Raw "$out/flet-build.log" } else { '' }
if ($log -match 'TOMLDecodeError|Invalid initial character|Invalid value') { $stage = 'toml-parse' }
elseif ($log -match 'Flutter.*(failed|error|exception)|Unable to install Flutter|Flutter SDK.*not found') { $stage = 'flutter-sdk-setup' }
elseif ($log -match 'main\.py not found|No Python app|project.*(discover|path)') { $stage = 'entry-point' }
elseif ($log -match '(?i)(clone|checkout|git install|git dependency).{0,120}(failed|error|fatal)|fatal:.*(repository|reference)') { $stage = 'git-dependency' }
elseif ($log -match '(?i)(Could not find a version|No matching distribution|Failed to build|ERROR:.*install).{0,160}(ndi-python|NDIlib)|(ndi-python|NDIlib).{0,160}(Could not find|No matching|Failed|ERROR:)') { $stage = 'ndi-dependency' }
elseif ($log -match '(?i)(Could not find a version|No matching distribution|serious_python|pip install|dependency resolution)') { $stage = 'python-dependency-packaging' }
elseif ($log -match 'Flutter project|Generating.*project') { $stage = 'flutter-project-generation' }
elseif ($log -match 'flutter.*build') { $stage = 'flutter-build' }
Save-Text failure-stage.txt ($(if ($code -eq 0) { '—' } else { $stage }))

$buildOutput = Join-Path $PWD "artifacts/flet-build-output/$Approach"
if (Test-Path $buildOutput) { Get-ChildItem $buildOutput -Recurse -File | Select-Object FullName,Length | Out-File "$out/output-manifest.txt" -Encoding utf8 } else { Save-Text output-manifest.txt 'build output directory not created' }
$exe = if (Test-Path $buildOutput) { Get-ChildItem $buildOutput -Recurse -Filter DivergenceSplitter.exe -File | Select-Object -First 1 } else { $null }
$exeFound = if ($exe) { 'YES' } else { 'NO' }
$cli = 'NOT RUN'
if ($exe) { & $exe.FullName --help *> "$out/cli-help.log"; $cli = if ($LASTEXITCODE -eq 0) { 'PASS' } else { "FAIL ($LASTEXITCODE)" } }
Save-Text result.txt "Approach: $Approach`nBuild result: $(if ($code -eq 0) {'PASS'} else {'FAIL'})`nBuild exit code: $code`nEXE found: $exeFound`nCLI smoke result: $cli`nGUI smoke result: NOT RUN`nFailure stage: $(Get-Content "$out/failure-stage.txt" -Raw)`nOutput directory: $(if ($exe) {$exe.DirectoryName} else {'not found'})"
Get-Content "$out/result.txt" | Out-File $env:GITHUB_STEP_SUMMARY -Append -Encoding utf8
exit 0
