# VR 제작킷 시작 스크립트 — START.bat 이 이 파일을 부른다.
# 직접 실행: powershell -ExecutionPolicy Bypass -File start.ps1
param(
    [int]$Port = 0,          # 비우면 8787부터 빈 포트 자동 탐색
    [switch]$Claude,         # 시작할 때 Claude 도 같이 띄움 (기본은 웹 콘솔만)
    [switch]$NoBrowser,
    [switch]$SkipModelCheck,  # 기본 모델 확인 자체를 건너뜀
    [switch]$NoUpdate,        # 깃 최신본 받기를 건너뜀
    [switch]$YesModels        # 묻지 않고 바로 다운로드 시작
)

try { chcp 65001 > $null } catch {}
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch {}
Set-Location $PSScriptRoot

function Say($t, $c = 'Gray') { Write-Host $t -ForegroundColor $c }
function Fail($what, $how) {
    Say ""
    Say "  [X] $what" 'Red'
    Say "      $how" 'Yellow'
    Say ""
    Read-Host "  엔터를 누르면 창이 닫힙니다"
    exit 1
}

Say ""
Say "  ================================================" 'Cyan'
Say "   VR 제작킷 — 시작" 'Cyan'
Say "  ================================================" 'Cyan'
Say ""

# ---------- 1. Python (py 런처) ----------
if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
    Fail "Python 이 없습니다." "https://www.python.org/downloads/ 에서 설치하세요. 설치 화면의 'py launcher' 체크를 반드시 켤 것."
}
Say "  [OK] $(py --version)" 'Green'

# ---------- 2. Claude Code ----------
# 1~3단계(환경·주제·에셋)는 웹이 전부 처리한다. Claude 는 제작 단계에서 웹의 버튼으로 띄운다.
# 그래서 여기서는 없다고 시작을 막지 않는다 — 나중에 필요할 때 알려주기만 한다.
$hasClaude = [bool](Get-Command claude -ErrorAction SilentlyContinue)
if ($Claude -and -not $hasClaude) {
    Fail "Claude Code 가 없습니다." "npm install -g @anthropic-ai/claude-code  →  설치 후 창을 새로 열고 다시 실행하세요."
}
if ($hasClaude) { Say "  [OK] Claude Code" 'Green' }
else { Say "  [--] Claude Code 없음 — 제작 단계에서 필요합니다 (npm install -g @anthropic-ai/claude-code)" 'Yellow' }

# ---------- 3. web\.env (API 키 파일) ----------
if (-not (Test-Path "web\.env")) {
    Copy-Item "web\.env.example" "web\.env"
    Say "  [!] web\.env 를 새로 만들었습니다." 'Yellow'
    Say "      OPENAI_API_KEY 를 채워야 이미지 생성 단계가 돌아갑니다 (지금 비워둬도 시작은 됩니다)." 'Yellow'
} else {
    Say "  [OK] web\.env" 'Green'
}

# ---------- 3.2 깃 최신본 받기 ----------
# 팀에서 같이 쓰면 각자 옛 코드로 돌다가 "나만 안 된다"가 생긴다. 시작할 때 한 번 맞춘다.
# ★ 절대 강제로 덮어쓰지 않는다 — 내 작업이 있으면 그냥 알리고 넘어간다.
if (-not $NoUpdate -and (Test-Path (Join-Path $PSScriptRoot ".git"))) {
    if (Get-Command git -ErrorAction SilentlyContinue) {
        Say ""
        Say "  깃 최신본 확인 중 ..." 'Cyan'
        $dirty = & git status --porcelain 2>$null
        if ($LASTEXITCODE -ne 0) {
            Say "  [!] 깃 상태를 못 읽어 건너뜁니다." 'Yellow'
        } elseif ($dirty) {
            $n = ($dirty | Measure-Object -Line).Lines
            Say "  [!] 수정 중인 파일이 $n 개 있어 받지 않았습니다 (덮어쓰지 않으려고)." 'Yellow'
            Say "      커밋하거나 되돌린 뒤 다시 실행하면 최신본을 받습니다." 'DarkGray'
        } else {
            # --ff-only: 합치기 충돌을 만들지 않는다. 갈라져 있으면 실패하고 그대로 둔다.
            $before = (& git rev-parse --short HEAD 2>$null)
            $out = & git pull --ff-only 2>&1
            if ($LASTEXITCODE -eq 0) {
                $after = (& git rev-parse --short HEAD 2>$null)
                if ($before -eq $after) { Say "  [OK] 이미 최신입니다 ($after)" 'Green' }
                else { Say "  [OK] 최신본을 받았습니다: $before -> $after" 'Green' }
            } else {
                Say "  [!] 받기 실패 — 옛 코드로 계속합니다." 'Yellow'
                Say ("      " + (($out | Select-Object -First 2) -join " / ")) 'DarkGray'
            }
        }
    }
}

# ---------- 3.5 남의 작업이 남아 있나 ----------
# 폴더째 넘겨받으면 이전 사람의 프로젝트가 딸려온다. 지우지는 않고 알려만 준다.
$leftover = @(Get-ChildItem "web\projects" -Directory -ErrorAction SilentlyContinue)
if ($leftover.Count -gt 0) {
    Say "  [!] web\projects 에 프로젝트 $($leftover.Count)개가 이미 있습니다." 'Yellow'
    Say "      다른 PC에서 온 것이면 웹 콘솔이 자동으로 열지 않고 '새로 만들기'를 안내합니다." 'DarkGray'
}

# ---------- 4. 웹 콘솔 ----------
if ($Port -eq 0) {
    $Port = 8787
    while ($Port -lt 8800) {
        $busy = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
        if (-not $busy) { break }
        $Port++
    }
}
$url = "http://127.0.0.1:$Port"

Say ""
Say "  웹 콘솔을 띄웁니다 ... $url" 'Cyan'
Start-Process cmd -ArgumentList "/k title VR Kit Web Console - DO NOT CLOSE && py web\server.py $Port" -WorkingDirectory $PSScriptRoot | Out-Null

$up = $false
for ($i = 0; $i -lt 20; $i++) {
    Start-Sleep -Milliseconds 500
    try { Invoke-WebRequest $url -UseBasicParsing -TimeoutSec 2 | Out-Null; $up = $true; break } catch {}
}
if ($up) {
    Say "  [OK] 웹 콘솔 응답 확인" 'Green'
    if (-not $NoBrowser) { Start-Process $url }
} else {
    Say "  [!] 웹 콘솔이 아직 응답하지 않습니다. 새로 뜬 검은 창의 오류 메시지를 확인하세요." 'Yellow'
}

# ---------- 4.5 기본 모델 점검 ----------
# 팀에 나눠줄 때 제일 자주 막히는 지점. 뭘 골라야 하는지 모른 채 STEP 1에서 멈춘다.
# 기본값(engines.json)이 이미 심어져 있으니, 여기서는 "받아뒀는가"만 보고 안 받았으면 시작시켜 준다.
if ($up -and -not $SkipModelCheck) {
    try {
        $reg = Get-Content (Join-Path $PSScriptRoot 'web\engines.json') -Raw -Encoding UTF8 | ConvertFrom-Json
        $wanted = @(
            @{ label = '이미지'; repo = $reg.roles.image.default_repo },
            @{ label = '3D';     repo = $reg.roles.mesh_3d.default_repo }
        ) | Where-Object { $_.repo }

        $missing = @()
        Say ""
        Say "  기본 모델 확인 ..." 'Cyan'
        foreach ($w in $wanted) {
            $r = Invoke-RestMethod "$url/api/hf/present?repo=$([uri]::EscapeDataString($w.repo))" -TimeoutSec 30
            if ($r.present) {
                $sz = if ($r.size) { " ($($r.size)GB)" } else { "" }
                Say "    [OK] $($w.label): $($w.repo)$sz" 'Green'
            } else {
                Say "    [--] $($w.label): $($w.repo)  — 아직 없음" 'Yellow'
                $missing += $w
            }
        }

        if ($missing.Count -gt 0) {
            Say ""
            Say "  기본 모델이 없으면 이미지/3D 생성 단계에서 멈춥니다." 'Yellow'
            Say "  받을 용량(대략): SDXL Turbo 약 7GB · Hunyuan3D-2 mini 약 12GB" 'DarkGray'
            Say "  (저장소 전체가 아니라 실제 쓰는 파일만 받습니다. 회선에 따라 수십 분~몇 시간)" 'DarkGray'
            $go = $YesModels
            if (-not $go) {
                $ans = Read-Host "  지금 받기 시작할까요? (y/N)"
                $go = ($ans -match '^[yY]')
            }
            if ($go) {
                $blocked = $false
                foreach ($m in $missing) {
                    $body = @{ item = "model:$($m.repo)"; repo = $m.repo } | ConvertTo-Json -Compress
                    try {
                        Invoke-RestMethod "$url/api/install" -Method Post -Body $body -ContentType 'application/json' -TimeoutSec 30 | Out-Null
                        Say "    다운로드 시작: $($m.repo) — 새 창에서 진행됩니다" 'Cyan'
                    } catch {
                        # ★ 서버가 GPU 미준비를 이유로 막는 경우(409). 여기서 수십 GB 를 아낀다.
                        $resp = $_.Exception.Response
                        $txt = ""
                        if ($resp) {
                            $sr = New-Object IO.StreamReader($resp.GetResponseStream(), [Text.Encoding]::UTF8)
                            $txt = $sr.ReadToEnd()
                        }
                        if ($txt -match 'gpu_not_ready') {
                            $blocked = $true
                            Say "" 
                            Say "  [X] GPU 를 쓸 수 있는 PyTorch 가 없어 다운로드를 시작하지 않았습니다." 'Red'
                            Say "      지금 받으면 19GB 를 내려받고도 그래픽카드를 못 씁니다(느리기만 하고 에러는 안 남)." 'Yellow'
                            break
                        }
                        Say "    [!] $($m.repo) 시작 실패: $($_.Exception.Message)" 'Yellow'
                    }
                }
                if ($blocked) {
                    $ans2 = if ($YesModels) { 'y' } else { Read-Host "  GPU용 PyTorch 를 지금 설치할까요? (약 2.5GB) (y/N)" }
                    if ($ans2 -match '^[yY]') {
                        $b2 = @{ item = "PyTorch (GPU)" } | ConvertTo-Json -Compress
                        Invoke-RestMethod "$url/api/install" -Method Post -Body $b2 -ContentType 'application/json' -TimeoutSec 30 | Out-Null
                        Say "  설치 창을 띄웠습니다. 끝나면 START.bat 을 다시 실행하세요." 'Cyan'
                    } else {
                        Say "  웹 콘솔 STEP 1 의 'PyTorch (GPU)' 항목에서도 설치할 수 있습니다." 'DarkGray'
                    }
                } else {
                    Say "  받는 동안 웹 콘솔과 Claude 는 그대로 쓸 수 있습니다. 진행률은 STEP 1 에서도 보입니다." 'DarkGray'
                }
            } else {
                Say "  건너뜁니다. 나중에 웹 콘솔 STEP 1 에서 '⚡ 이 모델 설치' 로 받으면 됩니다." 'DarkGray'
            }
        }
    } catch {
        Say "  [!] 모델 확인을 건너뜁니다: $($_.Exception.Message)" 'Yellow'
    }
}

# ---------- 5. 안내 (Claude 는 기본으로 띄우지 않는다) ----------
if (-not $Claude) {
    Say ""
    Say "  준비 끝났습니다. 브라우저에서 이어서 진행하세요." 'Cyan'
    Say "    1) 환경·도구 체크   2) 주제·배경 → 앵커   3) 에셋 리스트 확정   ← 여기까지 웹에서" 'DarkGray'
    Say "    4) 에셋 제작부터는 화면의 [▶ Claude 실행] 버튼을 누르면 지시문까지 자동으로 들어갑니다." 'DarkGray'
    Say ""
    Say "  (시작부터 Claude 도 같이 띄우려면: START.bat -Claude)" 'DarkGray'
    exit 0
}

Say ""
Say "  Claude 를 시작합니다. 이 창에서 대화하세요." 'Cyan'
Say "  ------------------------------------------------" 'DarkGray'
Say ""

$prompt = "이 폴더는 VR 제작킷이다. 웹 콘솔이 " + $url + " 에 떠 있고 1~3단계(환경·주제·에셋)는 웹에서 사용자가 진행한다. AGENTS.md 와 web/AGENT_CONTRACT.md 를 읽고, 내가 묻는 것에 답하거나 게이트가 열린 단계를 진행해줘. 값을 추측해서 채우지 말 것."
& claude $prompt

Say ""
Say "  Claude 세션이 끝났습니다. 웹 콘솔 창은 따로 닫아주세요." 'DarkGray'
Read-Host "  엔터를 누르면 창이 닫힙니다"
