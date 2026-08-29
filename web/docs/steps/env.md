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
