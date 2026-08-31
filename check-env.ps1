# 환경 점검 (검증본) — 시작 전에 빠진 게 있나 확인한다.
# 사용: powershell -ExecutionPolicy Bypass -File check-env.ps1
#      경로가 다르면: -HunyuanDir "D:\...\Hunyuan3D-2" -EnvFile "D:\...\.env"
# 이건 후삼국에서 실제로 쓴 파이프라인 기준이다:
#   이미지=OpenAI gpt-image-1(.env) / 3D=독립 Hunyuan3D-2(로컬) / 언리얼=UnrealClaude MCP
param(
    [string]$HunyuanDir = "$env:USERPROFILE\Desktop\image3d\Hunyuan3D-2",
    [string]$EnvFile = ""
)

$ok = 0; $ng = 0
function Chk($name, $pass, $detail) {
    if ($pass) { Write-Host ("  [OK] {0,-24} {1}" -f $name, $detail) -ForegroundColor Green; $script:ok++ }
    else       { Write-Host ("  [--] {0,-24} {1}" -f $name, $detail) -ForegroundColor Yellow; $script:ng++ }
}
function Ver($cmd, $arg) {
    $c = Get-Command $cmd -ErrorAction SilentlyContinue
    if (-not $c) { return $null }
    try { (& $cmd $arg 2>$null | Select-Object -First 1) } catch { "설치됨" }
}

Write-Host "`n=== A. 로컬 소프트웨어 ===" -ForegroundColor Cyan
$ueDirs = @(Get-ChildItem "C:\Program Files\Epic Games" -Directory -ErrorAction SilentlyContinue | Where-Object { $_.Name -like "UE_*" })
Chk "Unreal Engine" ($ueDirs.Count -gt 0) ($(if ($ueDirs) { ($ueDirs.Name -join ', ') + "  <- 프로젝트 버전 고정" } else { "미설치 — Epic Launcher" }))
$pyv = Ver 'python' '--version'; if (-not $pyv) { $pyv = Ver 'py' '--version' }
Chk "python (py 포함)" ([bool]$pyv) ($(if ($pyv) { $pyv } else { "미설치 — python.org (py 런처 포함)" }))
foreach ($t in @(@('uv','--version'), @('node','--version'), @('git','--version'))) {
    $v = Ver $t[0] $t[1]; Chk $t[0] ([bool]$v) ($(if ($v) { $v } else { "미설치" }))
}
$blenderDirs = @(Get-ChildItem "C:\Program Files\Blender Foundation" -Directory -ErrorAction SilentlyContinue)
Chk "Blender (선택)" ($blenderDirs.Count -gt 0) ($(if ($blenderDirs) { $blenderDirs.Name -join ', ' } else { "블록아웃-레퍼런스 쓸 때만 필요" }))

Write-Host "`n=== B. 이미지 생성 (OpenAI gpt-image-1) ===" -ForegroundColor Cyan
$keyFound = $false; $keyWhere = ""
# 키 탐색: -EnvFile → VRKIT_ENV_FILE → web\.env → ~\.vrkit\.env (프로젝트 경로 하드코딩 금지)
$candidates = @()
if ($EnvFile) { $candidates += $EnvFile }
if ($env:VRKIT_ENV_FILE) { $candidates += $env:VRKIT_ENV_FILE }
$candidates += @("$PSScriptRoot\web\.env", "$env:USERPROFILE\.vrkit\.env")
foreach ($p in $candidates) {
    if ($p -and (Test-Path $p)) {
        if (Select-String -Path $p -Pattern 'OPENAI_API_KEY\s*=\s*\S' -Quiet -ErrorAction SilentlyContinue) { $keyFound = $true; $keyWhere = $p; break }
    }
}
if (-not $keyFound -and ([Environment]::GetEnvironmentVariable("OPENAI_API_KEY","User") -or [Environment]::GetEnvironmentVariable("OPENAI_API_KEY","Machine"))) { $keyFound = $true; $keyWhere = "환경변수" }
Chk "OPENAI_API_KEY" $keyFound ($(if ($keyFound) { "있음 @ $keyWhere (값 출력 안 함)" } else { ".env 파일에 OPENAI_API_KEY= 없음. -EnvFile 로 경로 지정" }))

Write-Host "`n=== C. 3D 생성 (독립 Hunyuan3D-2 로컬) — ★모델 설치까지 확인 ===" -ForegroundColor Cyan
Chk "Hunyuan3D-2 레포" (Test-Path $HunyuanDir) ($(if (Test-Path $HunyuanDir) { $HunyuanDir } else { "없음 — git clone Tencent/Hunyuan3D-2 (-HunyuanDir로 경로 지정)" }))
$venvCandidates = @("$HunyuanDir\..\venv\Scripts\python.exe", "$HunyuanDir\venv\Scripts\python.exe")
$venvPy = $venvCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
Chk "venv (PyTorch)" ([bool]$venvPy) ($(if ($venvPy) { $venvPy } else { "venv 없음 — Hunyuan용 파이썬 가상환경 미생성" }))
if ($venvPy) {
    $cu = try { & $venvPy -c "import torch;print('cuda' if torch.cuda.is_available() else 'cpu')" 2>$null } catch { "" }
    Chk "torch CUDA" ($cu -eq "cuda") ($(if ($cu -eq "cuda") { "GPU 사용 가능" } elseif ($cu) { "$cu — GPU 인식 안 됨(느림)" } else { "torch import 실패 — 확장 빌드 필요(lessons V2)" }))
}
# ★ 모델 가중치 다운로드 여부 (설치 안 했을 수도 있는 부분)
$hfCache = "$env:USERPROFILE\.cache\huggingface\hub\models--tencent--Hunyuan3D-2"
$hyCache = "$env:USERPROFILE\.cache\hy3dgen"
$modelDown = (Test-Path $hfCache) -or (Test-Path $hyCache)
Chk "★ Hunyuan 모델 다운로드" $modelDown ($(if ($modelDown) { "가중치 캐시 있음" } else { "아직 안 받음 — 첫 실행 시 HF에서 수 GB 자동 다운로드됨(인터넷 필요)" }))

Write-Host "`n=== D. 언리얼 조종 (UnrealClaude MCP) ===" -ForegroundColor Cyan
$cfgPath = Join-Path $env:USERPROFILE ".claude.json"
$hasUnreal = $false
if (Test-Path $cfgPath) {
    try {
        $j = Get-Content $cfgPath -Raw -Encoding UTF8 | ConvertFrom-Json
        $names = @(); if ($j.mcpServers) { $names = $j.mcpServers.PSObject.Properties.Name }
        foreach ($proj in $j.projects.PSObject.Properties) { if ($proj.Value.mcpServers) { $names += $proj.Value.mcpServers.PSObject.Properties.Name } }
        $hasUnreal = ($names | Where-Object { $_ -match 'unreal' }).Count -gt 0
    } catch {}
}
Chk "unrealclaude MCP 등록" $hasUnreal ($(if ($hasUnreal) { ".claude.json에 등록됨" } else { "미등록 — claude mcp add --scope user unrealclaude -- node <플러그인>\Resources\mcp-bridge\index.js" }))
$up = Get-Process UnrealEditor -ErrorAction SilentlyContinue
Chk "Unreal 에디터 실행중" ([bool]$up) ($(if ($up) { "PID $($up.Id) — 임포트/배치/렌더에 필요" } else { "미실행 — 임포트 단계 전에 열 것 (그전 이미지·3D는 가능)" }))
$port3000 = Test-NetConnection -ComputerName 127.0.0.1 -Port 3000 -InformationLevel Quiet -WarningAction SilentlyContinue
Chk "REST :3000 (execute_script)" $port3000 ($(if ($port3000) { "열림 (플러그인 서버 응답)" } else { "닫힘 — 에디터+플러그인 켜야 열림" }))

Write-Host "`n=== 결과: OK $ok / 확인필요 $ng ===" -ForegroundColor Cyan
if ($ng -gt 0) { Write-Host "확인필요 항목을 SETUP.md(V1~V4)대로 채운 뒤 시작한다. 특히 ★모델·키·MCP 3개가 핵심." -ForegroundColor Yellow }
else { Write-Host "전부 준비됨 — RUN.md로 시작 가능." -ForegroundColor Green }
Write-Host ""
