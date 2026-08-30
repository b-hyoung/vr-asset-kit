# 환경 준비 체크리스트

새 PC에서 이 하네스를 돌리기 전에 통과해야 할 목록.
**전부 통과하기 전에 루프를 시작하지 않는다** — 중간에 막히면 어디까지 됐는지 추적이 어려워진다.

순서대로 하되, A~C는 서로 독립이라 병렬로 해도 된다. D(연결 확인)는 항상 마지막.

---

## A. 로컬 소프트웨어

| # | 항목 | 확인 | 비고 |
|---|---|---|---|
| A1 | **Blender** 4.x 이상 | `blender --version` | 절차적 모델링 + 이미지→3D 임포트 담당 |
| A2 | **Unreal Engine** | Epic Launcher에 설치 | ★ **버전을 프로젝트에 맞춰 고정** — 아래 주의 |
| A3 | **Python + uv** | `uv --version` | Blender MCP 설치·실행에 사용 |
| A4 | **Node.js** | `node --version` | Unreal 브리지 MCP가 node로 돌아감 |
| A5 | **Git** | `git --version` | 프로젝트 폴더가 저장소 |

⚠️ **A2 주의**: 언리얼 프로젝트는 한번 올린 버전에서 **내려올 수 없다.**
5.8로 연 프로젝트를 5.7로 열 수 없으므로, 팀·다른 PC와 버전을 먼저 맞춘 뒤 프로젝트를 만든다.
설치된 버전 확인(윈도우): `Get-ChildItem "C:\Program Files\Epic Games" -Directory`

---

## B. MCP 서버 3종

Claude Code가 Blender·Unreal을 조종하는 통로. `claude mcp list`로 등록 상태를 본다.

### B1. Blender MCP (`blender-assets`)
에셋 생성의 주력. 절차적 모델링 + PolyHaven/Sketchfab 다운로드 + **Hyper3D·Hunyuan3D 이미지→3D 변환**까지 이 하나에 들어 있다.

- 설치: `uvx blender-mcp install-addon` → Blender에서 애드온 활성화
- 실행 경로 예시: `<venv>\Scripts\blender-mcp.exe`
- **Blender 쪽 설정 (빠뜨리기 쉬움)**:
  1. Blender 실행 → 3D 뷰포트 사이드바(`N`) → **BlenderMCP** 탭
  2. **Start MCP Server** 클릭 (기본 포트 **9876**)
  3. 쓸 통합만 체크: PolyHaven / Sketchfab / **Hyper3D Rodin** / **Hunyuan3D**
  4. 각 통합의 API 키를 그 패널에 입력 (환경변수가 아니라 **Blender UI 안**에 들어간다)

⚠️ **이중 설치 함정**: Blender MCP는 커뮤니티판(ahujasid)과 다른 배포판이 따로 있다.
둘 다 켜면 포트 9876이 충돌하고 어느 쪽이 응답하는지 알 수 없다. **한쪽만 활성화**할 것.

### B2. Unreal MCP (`unrealclaude` 등 브리지)
임포트·배치·캡처 담당.

- 브리지 서버 등록 (예: `node <경로>\unrealclaude-bridge\index.js`)
- **언리얼 쪽 설정**: 대상 프로젝트에서 해당 **플러그인을 활성화**하고 에디터를 재시작

### B3. 이미지 생성
질문 시트(`harness/questions.md`) 슬롯을 채워 프롬프트를 조립한 뒤 이미지를 만든다. 둘 중 하나:

- **(a) OpenAI `gpt-image-1`** — 환경변수 `OPENAI_API_KEY` 필요. 후삼국 때 쓰기로 확정했던 경로
- **(b) 연결된 이미지 생성 MCP** — 로컬 키 없이 바로 생성 가능. 계정에 붙어 있으면 이쪽이 준비 비용 0

새 프로젝트 시작할 때 (a)/(b) 중 무엇을 쓸지 **START.md에 명시**한다. 정하지 않으면 매번 되묻게 된다.

### B4. 3D 생성 모델 (이미지/텍스트 → GLB) ★ 별도 준비 항목
"이미지→3D" 경로 에셋을 만드는 실제 엔진. **Blender MCP 안에 통합되어 있지만 각각 키와 모드를 따로 켜야 한다.**

| 모델 | 모드 | 입력 | 키 | 비고 |
|---|---|---|---|---|
| **Hyper3D Rodin** | `MAIN_SITE` | 이미지 **로컬 절대경로** | hyper3d.ai 키 | free_trial 키는 **일일 생성 한도** 있음 |
| | `FAL_AI` | 이미지 **URL** | fal.ai 키 | 이미지를 어딘가 올려야 함 |
| **Hunyuan3D** | `OFFICIAL_API` | 텍스트 또는 이미지(로컬/URL) | 텐센트 **SecretId + SecretKey** | cloud.tencent.com |
| | `LOCAL_API` | 텍스트 또는 이미지 | 없음 (로컬 구동) | 생성·임포트가 한 단계로 끝남 |

⚠️ **모드가 플로우를 바꾼다.** Hyper3D를 `FAL_AI`로 쓰면 생성한 이미지를 **URL로 올려야** 하고,
`MAIN_SITE`면 **파일로 저장**하면 된다. 준비 단계에서 모드를 정하지 않으면
이미지를 다 만든 뒤 3D 변환에서 막힌다. → 정한 모드를 **START.md에 기록**한다.

키는 환경변수가 아니라 **Blender의 BlenderMCP 사이드바 패널**에 넣는다.
연결 확인: `get_hyper3d_status` / `get_hunyuan3d_status`

**Hyper3D vs Hunyuan3D**는 둘 다 "단일 오브젝트"에 강한 같은 급이다.
후삼국 프로젝트에서 "비교 후 결정"으로 남겨뒀고 **아직 비교하지 않았다.**
첫 에셋 하나로 양쪽 다 돌려보고 고르는 것이 이 프로젝트의 실제 첫 결정이다.

### B5. 기성 에셋 소스 (제작 대신 가져오기)
하네스의 "기존 에셋 재활용" 경로. 만들 필요 없는 건 만들지 않는다.

| 소스 | 강점 | 키 |
|---|---|---|
| **PolyHaven** | 모델 · 텍스처 · **HDRI 환경광** | 불필요 |
| **Sketchfab** | 현실적 모델, 종류가 가장 많음 | API 키 필요 (다운로드 가능 모델만) |

환경광(HDRI)은 거의 항상 PolyHaven에서 가져오는 게 맞다 — 생성 대상이 아니다.

---

## C. API 키

**키를 채팅·파일·커밋에 절대 쓰지 않는다.** 환경변수 또는 각 도구의 설정 UI에만 넣는다.

| 키 | 어디에 넣나 | 필요한 경우 |
|---|---|---|
| `OPENAI_API_KEY` | 시스템 환경변수 | 이미지 생성을 B3-(a)로 할 때 |
| Hyper3D 키 (hyper3d.ai 또는 fal.ai) | **Blender의 BlenderMCP 패널** | 3D 생성을 Hyper3D로 할 때 — **모드에 맞는 키** |
| Hunyuan3D SecretId + SecretKey | **Blender의 BlenderMCP 패널** | 3D 생성을 Hunyuan3D `OFFICIAL_API`로 할 때 |
| Sketchfab 키 | **Blender의 BlenderMCP 패널** | 기성 모델을 Sketchfab에서 받을 때 |

환경변수를 새로 설정했으면 **터미널과 Claude Code를 재시작**해야 반영된다.

---

## D. 연결 확인 (루프 시작 직전, 매번)

가장 흔한 실패는 설치 문제가 아니라 **앱이 안 떠 있는 것**이다.
MCP는 Blender·Unreal이 **실행 중일 때만** 연결된다. 껐다 켜면 다시 확인해야 한다.

| 확인 | 방법 | 기대 결과 |
|---|---|---|
| Blender 연결 | `get_addon_status` | 버전 정보 반환 (❌ "Could not connect to Blender" = Blender 미실행 or 서버 미시작) |
| 3D 생성 — Hyper3D | `get_hyper3d_status` | enabled + **모드**(MAIN_SITE / FAL_AI) 확인 |
| 3D 생성 — Hunyuan3D | `get_hunyuan3d_status` | enabled + **모드**(OFFICIAL_API / LOCAL_API) 확인 |
| 기성 에셋 — PolyHaven | `get_polyhaven_status` | enabled |
| 기성 에셋 — Sketchfab | `get_sketchfab_status` | enabled (키 필요) |
| Unreal 연결 | `unreal_status` | connected (❌ "NOT CONNECTED" = 에디터 미실행 or 플러그인 비활성) |
| 이미지 생성 | 테스트 1장 | 실제로 나오는지 |
| **3D 생성 왕복** | 테스트 에셋 1개를 생성→폴링→임포트까지 | ★ 여기까지 통과해야 루프 시작 가능 |

**체크 순서**: Blender 실행 → 사이드바에서 MCP 서버 Start → 언리얼 프로젝트 열기 → 위 5개 확인.

---

## E. VR 실기 테스트 (에셋 제작이 아니라 검수 단계에서 필요)

| 항목 | 비고 |
|---|---|
| Quest Link / Air Link 또는 무선 스트리밍 | PCVR로 확인할 때 |
| **활성 OpenXR 런타임** | ★ 여러 HMD 런타임(Oculus·SteamVR·PICO 등)이 설치돼 있으면 **활성 런타임이 하나만** 선택된다. Quest로 테스트하려면 Oculus로 전환해야 한다 — 안 그러면 헤드셋이 잡히지 않는다 |
| 언리얼 VR 템플릿 | 새 프로젝트를 VR 템플릿으로 생성 |

---

## 빠른 점검

윈도우에서 `check-env.ps1`을 실행하면 A·C 항목과 앱 실행 여부를 한 번에 확인한다.
B·D(MCP 연결)는 Claude Code 안에서 위 도구를 직접 호출해 확인한다.

---

## 준비가 안 된 채로 시작했을 때 생기는 일 (기록)

- Blender 미실행 → 모든 모델링 호출이 조용히 실패, 원인 파악에 시간 낭비
- 언리얼 에디터 미실행 → 에셋은 다 만들었는데 임포트 단계에서 전부 멈춤
- 이미지 생성 경로 미확정 → 질문 시트 슬롯을 다 채우고도 생성 못 함
- 언리얼 버전 안 맞춤 → 프로젝트를 처음부터 다시 만들어야 함 (되돌릴 수 없음)

---

# ★★ 실측 셋업 (검증본) — 후삼국에서 실제로 통한 파이프라인

> 위 A~E는 **계획(Blender-MCP 통합)** 기준이다. 후삼국을 완주하며 실제로 쓴 것은 아래다:
> **이미지=OpenAI gpt-image-1 / 3D=독립 Hunyuan3D-2(standalone, Blender MCP 아님) / 언리얼=UnrealClaude MCP 직접 구동.**
> 새 프로젝트는 이쪽을 그대로 따르면 된다. 자세한 함정은 `lessons.md` 참조.

## V1. OpenAI (이미지 생성 + 배치 심판)
- `.env` 파일에 `OPENAI_API_KEY=...` (예: `[프로젝트]\.env`). **키 값은 스크립트가 파일에서만 읽고, 채팅/코드/커밋에 절대 안 쓴다.**
- 쓰는 곳: `scripts/gen_prop_image.py`(gpt-image-1 컨셉), `scripts/cmp_openai*.py`(gpt-4o 심판).
- gpt-image-1은 조직 verification이 필요할 수 있음. 안 되면 스펙트럼/컨셉만 다른 이미지 MCP로 대체 가능.

## V2. Hunyuan3D-2 로컬 (image→3D) — ★무거운 셋업, 한 번만
로컬 GPU로 image→3D를 돌린다 (무료·무제한). RTX 40/50 계열 16GB+ 권장.
1. **레포**: `git clone https://github.com/Tencent/Hunyuan3D-2` (또는 `Hunyuan3D-2` 폴더)
2. **venv + PyTorch (CUDA)**: 그래픽카드에 맞는 CUDA로. (예: Blackwell/50계열 = **CUDA 12.8 + torch cu128**)
3. **커스텀 CUDA 확장 빌드**: `custom_rasterizer`, `differentiable_renderer` 를 각 setup.py로 빌드. Visual Studio(MSVC) 필요.
4. **모델 가중치**: 첫 실행 시 HuggingFace에서 `tencent/Hunyuan3D-2` 자동 다운로드(수 GB) — shape(dit) + paint(turbo). 인터넷 필요.
5. **빌드 함정(실측, lessons.md 상세)**:
   - CUDA 설치기 "Nsight VS Edition" hang → devenv.exe 죽이거나 Custom에서 Nsight/VS통합 언체크
   - 한글 로케일 torch cpp_extension UnicodeDecodeError → `ce.SUBPROCESS_DECODE_ARGS=('utf-8','replace')` 몽키패치
   - torch 2.11+MSVC `compiled_autograd.h` C2872 → 해당 분기 `if constexpr(false)`로 무력화
   - custom_rasterizer DLL 로드 실패 → **torch를 먼저 import** 후 custom_rasterizer
   - paint의 VAE `.safetensors 없음` → `.bin` 폴백이라 **무시 가능**
6. **실행**: `[venv]\Scripts\python.exe [Hunyuan3D-2]\gen_props_batch.py` (scripts/ 참고). shape 1회+paint 1회 로드로 여러 개 배치.

## V3. UnrealClaude MCP (언리얼 직접 구동) — UE 5.7
언리얼을 Claude가 직접 조종(임포트·스폰·배치·렌더). Windows에서 됨.
1. **선행**: Python 3.10+ , **uv** (`irm https://astral.sh/uv/install.ps1 | iex`), **node.js**
2. **플러그인**: Fab에서 "ClaudeUnreal/UnrealClaude" 설치 → 프로젝트에 추가 → Edit→Plugins에서 활성화 → 재시작.
   - (소스빌드 대안: `git clone --recurse-submodules` 후 `RunUAT.bat BuildPlugin ...` → 엔진 Plugins/Marketplace에 복사 → `Resources/mcp-bridge`에서 `npm install`)
   - ⚠️ 소스빌드가 **깨진 다른 마켓 플러그인** 때문에 막히면, 빌드 동안만 그 플러그인 폴더를 잠깐 옮겼다 복구
3. **MCP 등록 (STDIO 노드 브릿지)** — HTTP 아님:
   `claude mcp add --scope user unrealclaude -- node "[플러그인]\Resources\mcp-bridge\index.js"`
   - 포트 3000은 **REST API**(execute_script 직접 호출용), MCP 연결은 이 STDIO 브릿지
4. **자동승인**: Project Settings → Plugins → Unreal Claude → **Auto-approve script execution** 체크 (스크립트 팝업 없이 실행)
5. **확인**: 에디터 켠 상태에서 `claude mcp list` → `unrealclaude … Connected`. MCP 도구는 **세션 시작 시** 로드되므로, 등록 후엔 세션 재시작해야 잡힌다.
6. **파이썬 실행**: 노출 도구가 제한적이라 `scripts/ue_exec.py`로 `POST :3000/mcp/tool/execute_script` 직접 호출 (description 필수).

## V4. 최소 연결 확인 (루프 시작 전)
- [ ] `.env`에 OpenAI 키, `gen_prop_image.py` 테스트 1장 나옴
- [ ] Hunyuan3D 테스트 1개 image→glb 왕복
- [ ] `unrealclaude` Connected + `ue_exec.py`로 `import unreal; unreal.log(...)` 통과
- [ ] 임포트 테스트: glb 1개 임포트→Nanite off→SceneCapture 렌더 확인
