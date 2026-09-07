# START_HERE — 이 킷을 처음 받았다면 여기부터

> **`START.bat` 더블클릭.** 끝입니다. 나머지는 Claude가 안내합니다.

이 킷은 **AI(Claude Code)가 실행하고 사람은 판정만** 하는 구조입니다.
문서를 다 읽고 시작하는 게 아니라, **Claude를 켜서 물어보면서** 시작합니다.

---

## 1. 시작 전에 딱 두 개만

| 필요한 것 | 확인 | 없으면 |
|---|---|---|
| **Python 3** (`py` 런처 포함) | `py --version` | [python.org](https://www.python.org/downloads/) — 설치 화면에서 **"py launcher" 체크** |
| **Claude Code** | `claude --version` | `npm install -g @anthropic-ai/claude-code` |
| **NVIDIA 그래픽카드** | `nvidia-smi` | 로컬 모델을 쓰려면 필수. VRAM 12GB 이상 권장 |

> Blender·언리얼·API 키는 **지금 필요 없습니다.** 나중에 필요한 단계에 가서 Claude가 짚어줍니다.
> 미리 다 깔고 싶으면 `SETUP.md`를 보세요. (전부 통과시키려면 시간이 꽤 걸립니다)

### 기본으로 쓰는 모델 (로컬)

처음부터 이 두 개가 **미리 선택되어 있습니다.** 바꾸고 싶으면 웹 콘솔 STEP 1에서 언제든 고르면 됩니다.

| 역할 | 모델 | 받는 용량 | VRAM |
|---|---|---|---|
| 이미지 | **SDXL Turbo** (`stabilityai/sdxl-turbo`) | 약 7GB | ~7GB |
| 3D | **Hunyuan3D-2 mini** (`tencent/Hunyuan3D-2mini`) | 약 12GB | 형상 5GB · 텍스처 9GB |

둘 다 HuggingFace 로그인이나 라이선스 동의가 **필요 없습니다.** (FLUX·SD3.5는 로그인+동의가 필요해서 기본에서 뺐습니다.)

⚠️ **GPU용 PyTorch가 먼저 깔려 있어야 합니다.** 안 그러면 19GB를 다 받고도 그래픽카드를 못 써서
생성이 몇십 배 느려집니다 — 그런데 **에러가 안 나서 눈치채기 어렵습니다.**
그래서 킷이 아예 다운로드를 막고 안내합니다. 안내가 뜨면 `PyTorch (GPU)` 를 먼저 설치하세요.

## 2. `START.bat` 더블클릭

이때 자동으로 일어나는 일:

1. Python / Claude Code 설치 확인
2. `web/.env.example` → `web/.env` 복사 (키 넣는 파일)
3. **웹 콘솔** 기동 → 브라우저 자동으로 열림 *(검은 창이 하나 더 뜹니다 — 닫지 마세요)*
   포트 8787이 이미 쓰이는 중이면 **8788, 8789… 로 알아서 옮겨갑니다.**
4. **기본 모델 확인** — 안 받아져 있으면 용량을 알려주고 **받을지 물어봅니다.** 승인해야만 받습니다.
   (`-YesModels` 로 묻지 않게, `-SkipModelCheck` 로 건너뛸 수 있습니다)
5. **Claude 실행** — `AGENTS.md`의 부트스트랩 절차를 읽고 환경 진단부터 안내 시작

## 3. 그 다음은 이렇게 굴러갑니다

```
브라우저(웹 콘솔)          =  입력·확정·게이트   ← 사람이 누름
검은 창(Claude)            =  실제 실행          ← AI가 함
```

- 웹에서 **프로젝트 생성 → 주제·배경 입력 → 확정(게이트)**
- Claude가 그 다음 단계를 실행 (이미지 → 3D → 언리얼 임포트/배치/조명 → export)
- **Claude는 게이트를 스스로 넘지 못합니다.** "웹에서 확정해 주세요"라고 멈추면 브라우저로 가서 누르세요. 그게 정상 동작입니다.

전체 9단계 흐름과 각 단계의 함정은 `web/docs/steps/` 안에 있고, Claude가 그때그때 읽습니다.

---

## 수동으로 시작하기 (START.bat 안 쓸 때)

```powershell
# 1) 키 파일
copy web\.env.example web\.env      # OPENAI_API_KEY 채우기

# 2) 웹 콘솔 (창 하나 잡아둠) — pip 설치 불필요, 표준 라이브러리만 씁니다
py web\server.py 8787               # → http://127.0.0.1:8787

# 3) 다른 창에서 Claude
claude "AGENTS.md 읽고 시작해줘"
```

웹 콘솔만 띄우고 Claude는 직접 켜고 싶다면:

```powershell
.\START.bat -NoClaude          # 브라우저까지 안 열려면 -NoBrowser 추가
.\START.bat -Port 9000         # 포트 지정
```

⚠️ `python`이 아니라 **`py`** 입니다. 이 킷의 하드룰입니다 (`python`이 깨진 환경이 많음).

## 막히면

| 증상 | 원인 / 해결 |
|---|---|
| 웹 콘솔 창이 바로 꺼짐 | 새로 뜬 검은 창의 오류 메시지를 보세요. 포트 충돌은 자동 회피되므로 대개 다른 원인입니다 |
| 브라우저에 아무것도 안 뜸 | 서버 창이 살아 있는지 확인. 주소는 `localhost`가 아니라 `127.0.0.1:<포트>` (START.bat이 출력한 주소) |
| 스크립트 실행이 차단됨 | `START.bat`이 `-ExecutionPolicy Bypass`로 호출하므로 정상이면 안 걸립니다. 직접 돌릴 땐 `powershell -ExecutionPolicy Bypass -File start.ps1` |
| `'claude'는 내부 또는 외부 명령이 아닙니다` | 설치 후 창을 새로 열어야 PATH가 잡힘 |
| 이미지 생성 단계에서 키 오류 | `web/.env` 의 `OPENAI_API_KEY` 가 비어 있음 |
| 언리얼/Blender 단계에서 막힘 | `SETUP.md` 의 B1~B4 (MCP 3종 + 3D 모델). Claude에게 "SETUP.md 기준으로 뭐가 빠졌는지 봐줘" |

## 이 킷을 또 다른 사람에게 넘길 때

**`PACK.bat` 더블클릭** → 상위 폴더에 `vr-asset-kit-share-<날짜>.zip` 이 생깁니다.

폴더를 그냥 복사해서 주면 안 됩니다. `.gitignore`는 git으로 줄 때만 막아주고,
폴더/zip으로 주면 아래가 전부 따라갑니다:

| 딸려가는 것 | 왜 문제인가 |
|---|---|
| `web/projects/` | **내 주제·배경·에셋 목록·통과된 게이트**가 그대로. 받은 사람 화면에 이전 작업이 채워진 채로 뜸 (+ 생성물 수백 MB) |
| `web/.env` | **API 키** |
| `web/.install/` | 설치 로그 (내 PC 절대경로) |

`PACK.bat`은 이것들을 빼고 묶은 뒤, 빠진 게 맞는지 zip 직전에 한 번 더 검사합니다.

> 그래도 섞여 들어갔다면: 받는 쪽 웹 콘솔이 **다른 PC에서 만들어진 프로젝트는 자동으로 열지 않고**
> "새 프로젝트 만들기"를 안내합니다. 이미 열어버렸다면 상단 **`↺ 입력 초기화`** 로 주제·배경·에셋을 비울 수 있습니다.

## 문서 지도

| 파일 | 누가 읽나 |
|---|---|
| **`START.bat`** / `start.ps1` | 실행 — 더블클릭 진입점 (bat은 ps1을 부르는 4줄짜리 껍데기) |
| **`PACK.bat`** / `pack.ps1` | 이 킷을 **남에게 줄 때** — 내 작업 흔적 빼고 zip 생성 |
| **`START_HERE.md`** (이 문서) | 사람 — 처음 받았을 때 |
| **`AGENTS.md`** | AI — 레포에서 제일 먼저 읽는 문서 |
| `web/AGENT_CONTRACT.md` | AI — 어기면 안 되는 강제 규칙 5개 |
| `SETUP.md` / `check-env.ps1` | 사람 — 환경 전부 갖출 때 |
| `RUN.md` | 실측 검증된 실행 런북 (웹 이전 방식, 참고용) |
| `lessons.md` | 실패에서 승격된 규칙 |
