# 남에게 줄 배포본 만들기 — 내 작업 흔적을 빼고 zip 하나로 묶는다.
# 사용: PACK.bat 더블클릭  또는  powershell -ExecutionPolicy Bypass -File pack.ps1
param(
    [string]$Out = ""      # 비우면 상위 폴더에 vr-asset-kit-share-<날짜>.zip
)

try { chcp 65001 > $null } catch {}
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch {}
Set-Location $PSScriptRoot

function Say($t, $c = 'Gray') { Write-Host $t -ForegroundColor $c }

Say ""
Say "  ================================================" 'Cyan'
Say "   배포본 만들기 (내 작업 흔적 제외)" 'Cyan'
Say "  ================================================" 'Cyan'
Say ""

# ---------- 담을 파일 목록 ----------
# git 이 있으면 git 에게 묻는 게 가장 정확하다:
#   -c(추적중) + -o(추적 안 되는 새 파일) --exclude-standard(.gitignore 적용)
# => .gitignore 가 막는 것(web/projects, web/.env, .install, __pycache__)은 자동 제외되고
#    아직 커밋 안 한 새 파일은 포함된다.
$files = @()
$useGit = $false
if (Get-Command git -ErrorAction SilentlyContinue) {
    git rev-parse --is-inside-work-tree 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) { $useGit = $true }
}

if ($useGit) {
    $files = git ls-files -co --exclude-standard
    Say "  [OK] git 기준으로 목록 작성 ($($files.Count)개)" 'Green'
} else {
    # git 이 없을 때의 대비책 — 제외 목록을 직접 건다.
    Say "  [!] git 이 없어 이름 규칙으로 거릅니다." 'Yellow'
    $skipDir = @('\.git\', '\web\projects\', '\web\.install\', '__pycache__', '\scripts\out\', '\web\static\gen\')
    $files = Get-ChildItem -Recurse -File | ForEach-Object {
        $rel = $_.FullName.Substring($PSScriptRoot.Length)
        $bad = $false
        foreach ($d in $skipDir) { if ($rel -like "*$d*") { $bad = $true; break } }
        if ($_.Name -eq '.env') { $bad = $true }
        if (-not $bad) { $rel.TrimStart('\') -replace '\', '/' }
    }
}

# ---------- 새어나가면 안 되는 것 최종 확인 ----------
# 목록 작성이 틀렸을 때 조용히 유출되는 게 최악이라 여기서 한 번 더 막는다.
$leak = $files | Where-Object {
    $_ -like 'web/projects/*' -and $_ -ne 'web/projects/.gitkeep' -or
    $_ -like '*/.env' -or $_ -eq 'web/.env' -or
    $_ -like 'web/.install/*' -or $_ -like '*__pycache__*'
}
if ($leak) {
    Say "  [X] 내보내면 안 되는 파일이 목록에 있습니다:" 'Red'
    $leak | ForEach-Object { Say "      $_" 'Red' }
    Say "      .gitignore 를 확인하세요. 중단합니다." 'Yellow'
    Read-Host "  엔터"
    exit 1
}

# ---------- 스테이징 후 zip ----------
$stamp = Get-Date -Format 'yyyyMMdd'
if (-not $Out) { $Out = Join-Path (Split-Path $PSScriptRoot -Parent) "vr-asset-kit-share-$stamp.zip" }
$stage = Join-Path $env:TEMP "vrkit-pack-$stamp-$PID\vr-asset-kit"
if (Test-Path (Split-Path $stage -Parent)) { Remove-Item (Split-Path $stage -Parent) -Recurse -Force }
New-Item -ItemType Directory -Path $stage -Force | Out-Null

foreach ($f in $files) {
    $src = Join-Path $PSScriptRoot $f
    if (-not (Test-Path $src)) { continue }
    $dst = Join-Path $stage $f
    New-Item -ItemType Directory -Path (Split-Path $dst -Parent) -Force | Out-Null
    Copy-Item $src $dst
}

# 받는 사람이 첫 실행에서 만들 자리만 비워둔다
New-Item -ItemType Directory -Path (Join-Path $stage 'web\projects') -Force | Out-Null
if (-not (Test-Path (Join-Path $stage 'web\projects\.gitkeep'))) {
    New-Item -ItemType File -Path (Join-Path $stage 'web\projects\.gitkeep') | Out-Null
}

if (Test-Path $Out) { Remove-Item $Out -Force }
Compress-Archive -Path $stage -DestinationPath $Out -CompressionLevel Optimal
Remove-Item (Split-Path $stage -Parent) -Recurse -Force

$mb = [math]::Round((Get-Item $Out).Length / 1MB, 1)
Say ""
Say "  [OK] 배포본 생성: $Out  ($mb MB)" 'Green'
Say ""
Say "  포함 안 된 것 (의도적):" 'DarkGray'
Say "    web/projects/  내 프로젝트 상태·생성물" 'DarkGray'
Say "    web/.env       API 키" 'DarkGray'
Say "    web/.install/  설치 로그(내 PC 경로)" 'DarkGray'
Say "    __pycache__/   파이썬 캐시" 'DarkGray'
Say ""
Say "  받는 사람은 압축을 풀고 START.bat 을 누르면 됩니다." 'Cyan'
Say ""
Read-Host "  엔터를 누르면 창이 닫힙니다"
