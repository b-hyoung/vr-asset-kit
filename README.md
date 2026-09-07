# VR 제작 하네스 (공용 틀)

> ### 🚀 이 킷을 처음 받았다면 → **`START.bat` 더블클릭**
> 웹 콘솔이 뜨고 Claude가 켜지면서 환경 진단부터 안내합니다.
> 사람이 읽을 문서는 **[`START_HERE.md`](START_HERE.md)** 하나면 됩니다. (필요한 건 Python + Claude Code 둘뿐)
> AI가 읽을 문서는 **[`AGENTS.md`](AGENTS.md)**.
>
> 아래는 킷의 **구조 설명**입니다. 시작하려고 읽을 필요 없습니다.

AI가 VR 장면·에셋을 루프로 만들고, 사람은 게이트에서 **판정만** 하는 제작 틀.
프로젝트에 종속되지 않는 규칙만 여기 둔다. 프로젝트별 내용(주제, 에셋 리스트, 확정 결정)은
각 프로젝트 폴더의 `docs/`에 둔다.

## 구성

```
vr-asset-kit/
├─ START.bat        ★★ 받은 사람이 제일 먼저 누르는 것 (웹 콘솔 + Claude 한 번에)
├─ start.ps1        └ START.bat 이 부르는 실제 시작 스크립트 (-NoClaude / -Port 옵션)
├─ PACK.bat         ★ 남에게 줄 때 — 내 작업 흔적(projects·.env·설치로그) 빼고 zip
├─ pack.ps1         └ PACK.bat 이 부르는 실제 패킹 스크립트
├─ START_HERE.md    ★★ 사람용 시작 문서
├─ AGENTS.md        ★★ AI용 진입 문서 (하드룰·읽는 순서)
├─ web/             ★ 현재 주 흐름 — 웹 콘솔(준비·게이트) + 9단계 정의 + 단계별 실측 문서
│  ├─ AGENT_CONTRACT.md  강제 규칙 5개
│  ├─ server.py · flow.json · docs/steps/
├─ RUN.md           실측 검증된 실행 런북 (웹 이전 방식 — 참고용)
├─ SETUP.md         ★ 환경 준비 체크리스트 (+ V1~V4 실측 셋업: OpenAI키·독립Hunyuan·UnrealClaude)
├─ check-env.ps1    환경 자동 점검 (윈도우)
├─ harness/
│  ├─ meta.md        메타 하네스 — 루프 설계·수정 전 통과할 질문 8개
│  ├─ scene-loop.md  실행 하네스 — 장면 제작 루프 (배치 규칙)
│  ├─ questions.md   질문 시트 — 이미지 생성 슬롯 8개
│  └─ pipeline.md    ★ 검증본 도구·명령·값·레시피 (gpt-image→Hunyuan→언리얼→자동루프→조명 프리셋→export)
├─ scripts/         ★ 실제로 통한 재사용 스크립트 (gen_prop_image·gen_props_batch·ue_exec·import·export·심판 + assemble/loop 패턴)
├─ templates/
│  ├─ START.md            새 프로젝트 인수인계 문서
│  ├─ scene-brief.md      장면 브리프 (에셋 리스트 + 구성 규칙 + 완성 판정)
│  ├─ metacheck.md        메타 검증 보드 (meta.md 8질문 게이트)
│  └─ ambiguity-probe.md  ★모호어 분해 — 강도 스펙트럼 4장(은은/중간/뚜렷/하이) 생성해 고르게
└─ lessons.md       회고 로그 — 실제 실패에서 승격된 규칙 (8/24 언리얼 실전 교훈 포함)
```

## (구 방식 · 참고) MD 루프로 시작하기

> ⚠️ 아래 두 섹션은 **웹 콘솔 이전의 방식**입니다. 현재 주 흐름은 `web/`(AGENTS.md 기준)이고,
> 둘이 충돌하면 **웹 흐름이 우선**입니다. 웹 없이 문서만으로 돌릴 때만 참고하세요.

### ▶ "시작해줘" 하면 (다른 세션에서 바로 시작)

새 프로젝트에 이 하네스를 참조로 걸어두고 **"시작해줘"** 또는 **"RUN.md 읽고 진행해줘"** 라고 하면,
AI가 `RUN.md`를 따라: 셋업확인 → 인테이크 질문 → **강도 스펙트럼 4장 뽑아 고르게(앵커)** → 에셋 분할
→ 에셋별(gpt-image→Hunyuan3D→임포트→검수) → 자동 배치 루프 → 조명(고른 시간대 프리셋) → export 까지 진행한다.

### 새 프로젝트 시작하는 법 (구 방식)

0. **`SETUP.md`로 환경을 먼저 통과시킨다.** (윈도우: `check-env.ps1` 실행)
   Blender·언리얼·MCP가 준비 안 된 채로 시작하면 에셋을 다 만들고 임포트 단계에서 멈춘다.
1. 새 폴더를 만든다 (예: `my-vr-project/`), `git init`
2. `templates/`의 4개 파일을 새 폴더 `docs/`로 복사하고 대괄호 `[ ]` 자리를 채운다
3. 새 폴더에 `HARNESS.md`를 만들고 이 폴더 경로를 적는다 (아래 형식)
4. AI에게: **"docs/START.md 읽고 진행해줘"**

`HARNESS.md` 형식:
```markdown
# 하네스 참조
이 프로젝트는 공용 하네스를 따른다: <이 vr-harness 폴더의 절대경로>   # 예: C:\path\to\vr-harness\
작업 전 반드시 읽을 것:
- harness/meta.md (루프 설계 게이트)
- harness/scene-loop.md (실행 절차)
- harness/questions.md (이미지 생성 슬롯)
하네스 규칙은 여기서 고치지 말고 vr-harness 쪽에서 고친다.
```

## 하네스 수정 원칙

규칙은 **사전 상상으로 추가하지 않는다.** 실제 회전에서 실패한 것만 규칙이 된다.
프로젝트 회고에서 나온 규칙을 여기로 올릴 때는 `lessons.md`에 출처(프로젝트·날짜)를 남긴다.
