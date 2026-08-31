# 0. 환경·도구 체크

시작 전에 **필요한 것이 준비됐는지 진단**한다. 하나라도 핵심(★)이 빠지면 진행 잠금.

## 핵심(★)
- **python** — 스크립트 실행
- **CUDA / GPU** — 3D 생성 가속 (NVIDIA 드라이버+CUDA)
- **Hunyuan 모델** — 3D 생성 가중치
- **unrealclaude MCP** — 언리얼 조종

## 순서대로 필요한 것
- 기반: python·node·git
- ① 이미지 생성: 로컬 이미지(기본) / gpt-image 쓸 때만 OpenAI 키
- ② 3D 생성: CUDA·Hunyuan 레포/venv/모델
- ③ 언리얼: UE·MCP·에디터 실행·:3000

> **진단 시작**을 눌러 상태를 확인한 뒤 확정한다.

## 실측 함정 (08-30~31) — 셋업·경로
- **`python`이 깨져 있음 → 반드시 `py` 사용** (기존 메모리 규칙).
- **계약서·state.json은 홈이 아니라 레포에 있음**: `Desktop/VR제작킷/vr-harness/`. 경로 하드코딩 말고 레포 기준으로 찾을 것.
- **OpenAI 키 탐색 순서**(스크립트·서버 공통, 특정 프로젝트 경로 하드코딩 금지): 환경변수 `OPENAI_API_KEY` → 환경변수 `VRKIT_ENV_FILE`(경로) → `web/.env` → `~/.vrkit/.env`. 키는 `web/.env`(git 제외)에 두면 됨(`web/.env.example` 참고).
- **hy3dgen은 시스템 `py`에 없음 → Hunyuan 레포 전용 `.venv` 사용.** 3D/텍스처 스크립트는 그 venv로 실행.
