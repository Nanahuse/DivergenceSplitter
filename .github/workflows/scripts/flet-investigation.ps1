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
}
Copy-Item packages/divergencesplitter-ui/pyproject.toml $out/ui-pyproject.toml
Copy-Item packages/divergencesplitter-runtime/pyproject.toml $out/runtime-pyproject.toml
if (Test-Path packages/divergencesplitter-ui/src/main.py) { Copy-Item packages/divergencesplitter-ui/src/main.py $out/main.py }

& powershell -NoProfile -Command "$BuildCommand *>&1 | Tee-Object '$out/flet-build.log'; exit `$LASTEXITCODE"
$code = $LASTEXITCODE
Save-Text build_exit_code.txt $code
$stage = 'artifact generation'
$log = if (Test-Path "$out/flet-build.log") { Get-Content -Raw "$out/flet-build.log" } else { '' }
if ($log -match 'entry|main.py') { $stage = 'entry point' }
if ($log -match 'dependency|resolve|package') { $stage = 'dependency resolution' }
if ($log -match 'Git|git+') { $stage = 'Git dependency' }
if ($log -match 'NDI|ndi-python|NDIlib') { $stage = 'NDI dependency' }
Save-Text failure-stage.txt ($(if ($code -eq 0) { '—' } else { $stage }))

Get-ChildItem -Recurse -File -ErrorAction SilentlyContinue | Select-Object FullName,Length | Out-File "$out/output-manifest.txt" -Encoding utf8
$exe = Get-ChildItem -Recurse -Filter DivergenceSplitter.exe -File -ErrorAction SilentlyContinue | Select-Object -First 1
$exeFound = if ($exe) { 'YES' } else { 'NO' }
$cli = 'NOT RUN'
if ($exe) { & $exe.FullName --help *> "$out/cli-help.log"; $cli = if ($LASTEXITCODE -eq 0) { 'PASS' } else { "FAIL ($LASTEXITCODE)" } }
Save-Text result.txt "Approach: $Approach`nBuild result: $(if ($code -eq 0) {'PASS'} else {'FAIL'})`nBuild exit code: $code`nEXE found: $exeFound`nCLI smoke result: $cli`nGUI smoke result: NOT RUN`nFailure stage: $(Get-Content "$out/failure-stage.txt" -Raw)`nOutput directory: $(if ($exe) {$exe.DirectoryName} else {'not found'})"
Get-Content "$out/result.txt" | Out-File $env:GITHUB_STEP_SUMMARY -Append -Encoding utf8
exit 0
