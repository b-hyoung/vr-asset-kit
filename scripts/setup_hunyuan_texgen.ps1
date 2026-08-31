# Hunyuan3D-2 texgen 커스텀 확장(custom_rasterizer, differentiable_renderer) 빌드 셋업
# ─ 하네스 실측(SETUP.md V2)의 빌드 함정을 미리 처리한 원클릭 스크립트 ─
#
# 왜 필요한가: texgen(로컬 텍스처 베이킹)은 CUDA/C++ 확장을 그 자리에서 컴파일해야 하는데,
#   torch 2.11(+cu128) 헤더 + 최신 MSVC(14.4x) 조합에서 rasterizer.cpp 가 C2872
#   ('std': ambiguous symbol / compiled_autograd.h) 로 깨진다.
#
# 이 스크립트가 하는 일 (파일을 직접 수정하지 않음 → 되돌릴 것 없음):
#   1) MSVC 컴파일에 /DTORCH_STABLE_ONLY 를 주입($env:CL) → 문제의 헤더 분기가 비워져 C2872 회피
#      (SETUP.md V2의 'compiled_autograd.h 분기 무력화'와 동일 효과, 파일 편집 없이)
#   2) PYTHONUTF8=1 → 한글 로케일 torch cpp_extension UnicodeDecodeError 회피
#   3) 각 확장 폴더의 setup.py 를 찾아 build_ext --inplace + install
#
# 사용:
#   powershell -ExecutionPolicy Bypass -File setup_hunyuan_texgen.ps1
#   powershell -ExecutionPolicy Bypass -File setup_hunyuan_texgen.ps1 -RepoDir "D:\...\Hunyuan3D-2" -Py "py -3"
#
# 주의(하드룰): 시스템/기본 툴체인은 건드리지 않는다. 실패가 연쇄(whack-a-mole)면
#   무거운 대안(호환 MSVC 14.3x 툴셋 설치)으로 전환할지 사용자에게 물어본다.

param(
    [string]$RepoDir = "",
    [string]$Py = "py -3"
)

$ErrorActionPreference = "Stop"

function Find-Repo {
    if ($RepoDir -and (Test-Path $RepoDir)) { return (Resolve-Path $RepoDir).Path }
    if ($env:HunyuanDir -and (Test-Path $env:HunyuanDir)) { return (Resolve-Path $env:HunyuanDir).Path }
    $cands = @(
        "$env:USERPROFILE\Desktop\image3d\Hunyuan3D-2",
        "$env:USERPROFILE\Desktop\Hunyuan3D-2",
        "$env:USERPROFILE\Hunyuan3D-2"
    )
    foreach ($c in $cands) { if (Test-Path $c) { return (Resolve-Path $c).Path } }
    return ""
}

$repo = Find-Repo
if (-not $repo) {
    Write-Host "❌ Hunyuan3D-2 레포를 못 찾음. -RepoDir 로 경로를 주거나 git clone 먼저:" -ForegroundColor Yellow
    Write-Host "   git clone https://github.com/Tencent/Hunyuan3D-2"
    exit 1
}
Write-Host "✅ 레포: $repo" -ForegroundColor Green

# 1) C2872 회피(컴파일 정의) + 2) 로케일 회피 — 이 프로세스에서만 적용
$env:CL = "/DTORCH_STABLE_ONLY $($env:CL)"
$env:PYTHONUTF8 = "1"
Write-Host "적용: CL=$($env:CL) / PYTHONUTF8=1" -ForegroundColor Cyan

# 2.5) ★ TORCH_CUDA_ARCH_LIST — 실측 08-31에서 이게 빠져 하루를 날렸다.
#   빠뜨리면 이 GPU 아키텍처(cubin)가 fatbinary 에 안 들어가고, 런타임에
#     RuntimeError: CUDA error: no kernel image is available for execution on the device
#   로 터진다. 메시지가 드라이버/버전 문제처럼 보이지만 실체는 "이 GPU용 커널이 없음"이다.
#   게다가 비동기 보고라 스택트레이스가 엉뚱한 conv2d 를 가리킨다
#   → 진짜 위치를 보려면 CUDA_LAUNCH_BLOCKING=1 로 재현할 것.
if (-not $env:TORCH_CUDA_ARCH_LIST) {
    $cc = ""
    try {
        $cc = (& nvidia-smi --query-gpu=compute_cap --format=csv,noheader | Select-Object -First 1).Trim()
    } catch {}
    if ($cc) { $env:TORCH_CUDA_ARCH_LIST = $cc; Write-Host "GPU compute capability 자동감지: $cc" -ForegroundColor Cyan }
    else { Write-Host "⚠ compute capability 감지 실패 — TORCH_CUDA_ARCH_LIST 를 직접 지정하세요(예 8.6)" -ForegroundColor Yellow }
}
Write-Host "적용: TORCH_CUDA_ARCH_LIST=$($env:TORCH_CUDA_ARCH_LIST)" -ForegroundColor Cyan

# 2.6) CUDA_HOME — nvcc 가 PATH 에 없으면 툴킷을 찾아 붙인다
if (-not $env:CUDA_HOME) {
    $tk = Get-ChildItem "C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA" -Directory -ErrorAction SilentlyContinue |
          Sort-Object Name -Descending | Select-Object -First 1
    if ($tk) { $env:CUDA_HOME = $tk.FullName }
}
if ($env:CUDA_HOME) {
    $env:PATH = "$env:CUDA_HOME\bin;$env:PATH"
    $env:DISTUTILS_USE_SDK = "1"
    Write-Host "적용: CUDA_HOME=$env:CUDA_HOME" -ForegroundColor Cyan
}

# torch 존재 확인
& $Py.Split(' ')[0] $Py.Split(' ')[1..9] -c "import torch;print('torch',torch.__version__,'cuda',torch.cuda.is_available())"
if (-not $?) { Write-Host "❌ torch import 실패 — venv/torch(CUDA) 먼저 준비" -ForegroundColor Yellow; exit 1 }

# 3) 확장 폴더(setup.py) 탐색 — custom_rasterizer / differentiable_renderer / mesh_processor
$extDirs = Get-ChildItem -Path $repo -Recurse -Filter "setup.py" -ErrorAction SilentlyContinue |
    Where-Object { $_.DirectoryName -match "rasterizer|differentiable|mesh_processor|texgen" } |
    Select-Object -ExpandProperty DirectoryName -Unique

if (-not $extDirs) {
    Write-Host "⚠ 확장 setup.py 를 못 찾음. 레포 구조 확인 필요(hy3dgen/texgen/...)." -ForegroundColor Yellow
    exit 1
}

$fail = 0
foreach ($d in $extDirs) {
    Write-Host "`n=== 빌드: $d ===" -ForegroundColor Cyan
    Push-Location $d
    try {
        & $Py.Split(' ')[0] $Py.Split(' ')[1..9] setup.py build_ext --inplace
        if ($?) { & $Py.Split(' ')[0] $Py.Split(' ')[1..9] setup.py install }
        if (-not $?) { $fail++; Write-Host "  ❌ 실패: $d" -ForegroundColor Yellow }
        else { Write-Host "  ✅ 완료: $d" -ForegroundColor Green }
    } catch {
        $fail++; Write-Host "  ❌ 예외: $_" -ForegroundColor Yellow
    } finally { Pop-Location }
}

Write-Host "`n=== 결과: 성공 $($extDirs.Count - $fail) / 전체 $($extDirs.Count) ===" -ForegroundColor Cyan
if ($fail -gt 0) {
    Write-Host "실패가 연쇄로 나오면(다른 심볼 C2872 등) 이건 whack-a-mole 신호다." -ForegroundColor Yellow
    Write-Host "→ 결정적 대안: 호환 MSVC 14.3x 툴셋 설치(무거움). 진행 전 사용자 확인." -ForegroundColor Yellow
} else {
    Write-Host "런타임 주의: 스크립트에서 반드시 'import torch' 를 먼저 한 뒤 custom_rasterizer 를 import." -ForegroundColor Green
    Write-Host "검증: texgen 으로 텍스처 1개 구워 품질 확인(계약서 규칙3)." -ForegroundColor Green
}
