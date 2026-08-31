# AGENTS.md — AI가 이 레포에서 처음 읽는 문서

이 레포는 **VR 에셋/장면을 AI가 만들고, 사람은 게이트에서 판정만** 하는 제작 하네스다.
너(실행 AI)는 아래 순서로 읽고, 하드룰을 지킨다. **추측으로 값을 채우거나 단계를 올리지 않는다.**

## 실행 모델 (두 부분)
- **웹 콘솔** (`web/`, `py web/server.py` → localhost) = **준비·입력·게이트**. 주제/앵커/에셋 확정, 환경 진단, 모델 선택.
- **너 + MCP** = **실제 실행**. 이미지 생성 → 3D → 언리얼 임포트/배치/조명/export.
- 값과 게이트는 **서버가 소유한 `web/projects/<id>/state.json`** 이 유일한 진실. 문서 본문 예시를 현재 값으로 쓰지 마라.

## 읽는 순서 (필수)
1. **`web/AGENT_CONTRACT.md`** — 강제 규칙 5개 (값은 state.json에서만, 단계 자가승급 금지, 자기채점 금지, 지정 엔진, 기본자산 보호).
2. **`web/projects/<id>/state.json`** — 현재 프로젝트의 주제·배경·앵커·에셋·게이트 상태.
3. **`web/flow.json`** — 9단계 정의(게이트·엔진·`doc_ref`).
4. 지금 단계의 **`web/docs/steps/<step>.md`** — 그 단계의 실측 함정·절차.
5. 환경이 안 잡혔으면 **`SETUP.md`**(V1~V4 실측 셋업) + `check-env.ps1`.

## 하드룰 (어기면 사용자 피해)
- **`python`이 깨져 있음 → 항상 `py` 사용.**
- **기본 자산/템플릿/레벨/기본 액터(SkyLight 등) 수정·삭제 금지.** 새 사본에서만. 파괴적 작업 전 사용자 확인.
- **게이트**: `state.steps.<이전>.gate_passed == true` 아니면 멈추고 "웹에서 확정해 주세요". `current_step`/`gate_passed` 직접 수정 금지.
- **값이 비면(topic=null 등) 스스로 채우지 말고** 웹 입력을 요청. (예시·이전 세션 기억을 현재 값으로 취급 금지)
- **언리얼: 레벨 전환(open/new/load_level) 금지 → 제자리 편집만** (MCP 레벨 전환이 플러그인 크래시 유발, `web/docs/steps/ue_import.md`).
- **자기 채점 금지** — 배치·품질 판정은 사용자 또는 지정 심판 엔진.

## 지도 (어디에 뭐가)
| 경로 | 용도 |
|---|---|
| `web/AGENT_CONTRACT.md` | 강제 규칙 (제일 먼저) |
| `web/flow.json` · `web/docs/steps/` | 9단계 정의 + 단계별 실측 문서 |
| `web/server.py` · `web/static/` | 웹 콘솔(준비·게이트·진단·모델선택) |
| `SETUP.md` | 환경 준비 + V1~V4 실측 셋업(OpenAI·Hunyuan3D 로컬·UnrealClaude) |
| `scripts/` | 실제로 통한 스크립트 (gen_prop_image·gen_prop_3d·import_*·ue_exec·fix_ai_mat) |
| `scripts/setup_hunyuan_texgen.ps1` | texgen 커스텀 확장 원클릭 빌드(C2872 회피) |
| `lessons.md` | 실패에서 승격된 규칙 로그 |
| `harness/` · `templates/` | (구) MD-루프용 참조 문서 — 웹 흐름과 중복. 웹 흐름이 우선. |

> 주의: `README.md`·`harness/`·`templates/` 일부에 옛 경로/후삼국 예시가 남아 있다. **현재 값은 오직 state.json.** 예시는 참고일 뿐.
