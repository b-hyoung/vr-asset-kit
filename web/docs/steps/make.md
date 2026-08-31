# 4. 에셋별 제작 루프

에셋마다: **이미지 → 3D → Blender 수정 → 검수**.

## 규칙
- 이미지 슬롯 **8개(주제/구도/배제 등) 미충족 시 생성 금지**. 배제 슬롯이 최우선.
- 엔진 선택: 이미지(기본 로컬) · 3D(Hunyuan3D-2)
- 저폴리 목표: 프롭 ~2만 페이스, 텍스처 2048, glb ~3MB/에셋

> 실측: 프롬프트 빈칸을 모델이 임의로 채우면 원하는 이미지가 안 나옴 → 슬롯 다 채우고 생성.

## ⛔ CLIP 77토큰 예산 (실측 08-31 — 슬롯을 채우고도 실패한 이유)
- SD/SDXL 계열 텍스트 인코더는 **77토큰에서 조용히 자른다.** 구도·배제를 프롬프트 **뒤**에 붙이면
  그 부분이 통째로 사라져 "슬롯을 안 채운 것과 똑같은" 결과가 나온다 (배경 있는 장면·현대식 오브젝트).
- 대응: ① **생성 전 토큰 수를 센다**(`gen_props_image_batch.py` 는 77 초과 시 생성을 중단)
  ② 구도(2·3)·배제(7)를 **앞쪽**에 배치 ③ 전체를 60~75토큰으로 압축.
- **turbo/schnell 은 `guidance_scale=0` 이라 `negative_prompt` 가 작동하지 않는다.**
  배제 슬롯을 negative 에 넣으면 무시된다 → positive 안에 짧게 녹일 것.
  배제를 제대로 쓰려면 CFG 가 도는 모델(SDXL 1.0 등)로 바꿔야 한다.

## 이미지 생성 (실측 08-30) — 고품질·topic무관·로컬/클라우드
- **`scripts/gen_prop_image.py` 는 topic 무관**: 에셋 설명을 인자/`out/props.json`으로 받는다. **특정 예시(후삼국 등) 하드코딩 금지** — 하드코딩하면 주제와 무관한 이미지가 나와 "퀄리티 낮음"으로 보임.
- **엔진 선택**(비용 0 로컬 or 클라우드): `--engine <repo>` (로컬 diffusers) / `--engine gpt-image` (클라우드). `out/props.json` 항목의 `engine`/`repo`, 또는 env `VRKIT_IMAGE_ENGINE` 로도 지정.
  - 로컬: gen_spectrum 과 동일 안전장치(모델크기 vs 여유 VRAM 오프로드·slicing·OOM 폴백). 컨셉은 Hunyuan 입력이라 화질 중요 → **SDXL 1.0**(비게이트, 28스텝, 768px) 권장. 배경은 불투명 → **rembg 제거**.
  - 클라우드: **gpt-image-1 · 1024 · `quality:"high"` · 투명배경**. 키 필요, 장당 과금.
- 공통 STUDIO 템플릿(단일객체·아이소3/4·균일광·고디테일) 자동 부착.
- **키 탐색**: `OPENAI_API_KEY` → `VRKIT_ENV_FILE` → `web/.env` → `~/.vrkit/.env` (특정 프로젝트 경로 하드코딩 금지).

## 3D 생성 (실측 08-30) — 실행 함정
- **백그라운드 실행 시 cwd를 못 잡아 `hy3dgen` import 실패** → 스크립트 상단에 **레포 경로 명시 + `os.chdir(repo)`**.
- **엔진이 `Hunyuan3D-2mini`면 subfolder 필요**: `hunyuan3d-dit-v2-mini-turbo`. full(`Hunyuan3D-2`)과 혼동 금지 — 정확히 지정.
- **`Hunyuan3D-2mini` 레포에는 paint(texgen) 가중치가 없다** — shape 전용.
  texgen 은 `tencent/Hunyuan3D-2` 의 `hunyuan3d-paint-v2-0-turbo` 를 쓴다(엔진 변경이 아니라 같은 계열의 별도 모델).
- 실행은 반드시 **Hunyuan 레포 전용 `.venv`** 로.

## 3D 모델 VRAM 감당 기준 (★ 디스크 용량 ≠ VRAM)
**핵심: shape(메시 생성) VRAM 과 texgen(텍스처 베이킹) VRAM 은 완전히 다르다. texgen이 진짜 병목.**

| 모델 | 디스크 | shape VRAM | texgen VRAM | 16GB에서 |
|---|---|---|---|---|
| Hunyuan3D-2 (full) | ~28GB | ~6GB | **peak 16GB 근처** | shape ✅ 쾌적 / **texgen ⚠️ 빠듯 → offload·해상도↓** |
| Hunyuan3D-2mini (turbo) | ~8GB | ~5GB | ~8–10GB | ✅ 여유 (shape·texgen 모두) |

- **8GB GPU**: mini shape-only 권장(texgen은 빠듯 → cpu_offload 필수 or 클라우드).
- **12GB GPU**: mini 쾌적 / full shape 가능 / full texgen은 offload 필수.
- **16GB GPU**: full shape ✅. **full texgen은 peak가 16GB에 닿아 OOM 위험** → `enable_model_cpu_offload()` + 멀티뷰 해상도 낮추기. (이번 세션 실측: full texgen이 VRAM 최대 난관)
- **24GB+**: full texgen까지 offload 없이 여유.
- OOM 나면 순서: ① `enable_model_cpu_offload()` → ② `enable_attention_slicing()` → ③ 해상도/뷰 수 축소 → ④ mini로 교체 → ⑤ 클라우드 3D(Rodin/Hyper3D).

## 3D (Hunyuan3D-2 로컬) — 실행 전 준비

**shape(메시)는 가중치만 있으면 되지만, texgen(텍스처 베이킹)은 CUDA/C++ 확장을 빌드해야 함.**
torch 2.11(+cu128) + 최신 MSVC(14.4x)에서 `custom_rasterizer` 빌드가 **C2872('std' ambiguous, compiled_autograd.h)** 로 깨진다 (실측·SETUP.md V2).

### ✅ 미리 실행: 원클릭 빌드 셋업
```
powershell -ExecutionPolicy Bypass -File scripts/setup_hunyuan_texgen.ps1 -RepoDir <Hunyuan3D-2 경로>
```
- 파일을 편집하지 않고 **`$env:CL=/DTORCH_STABLE_ONLY`** 로 C2872 회피 + **`PYTHONUTF8=1`**(한글 로케일 함정) 후 확장 빌드.
- 실패가 **연쇄**로 나면(whack-a-mole) → 결정적 대안 **호환 MSVC 14.3x 툴셋 설치**(무거움) 전에 **사용자 확인**.

### ⛔ `no kernel image is available for execution on the device` (실측 08-31 — 가장 오래 잡아먹은 함정)
- **실체**: `custom_rasterizer` 가 **이 GPU 아키텍처 없이 빌드**된 것. 메시지 그대로 "이 GPU 용 커널이 fatbinary 에 없다".
  프리빌트 휠(`custom_rasterizer-0.1.0+torch251.cuda124` 등)을 그냥 설치하면 arch 가 안 맞을 수 있다.
- **함정**: 커널 실패가 **비동기로 보고**돼 스택트레이스가 엉뚱한 곳(diffusers 의 `conv2d`)을 가리킨다.
  VRAM 부족·cuDNN·onnxruntime 을 의심하게 만든다 — 전부 헛다리.
- **진짜 위치 확인**: `CUDA_LAUNCH_BLOCKING=1 TORCH_USE_CUDA_DSA=1` 로 재현하면
  스택에 `custom_rasterizer_kernel...pyd` 처럼 **범인 모듈명이 뜬다.** 여기서 갈린다:
  | 스택에 뜨는 것 | 원인 |
  |---|---|
  | `custom_rasterizer` / `differentiable_renderer` | 확장 빌드 arch/ABI 불일치 → 재빌드 |
  | multiview UNet 의 attention/index | 모델 내부(특정 shape OOB, half 오버플로) |
  | 여전히 `conv2d` | cuDNN 커널 선택 → `cudnn.benchmark=False` → `cudnn.enabled=False` |
- **해결**: 소스에서 `TORCH_CUDA_ARCH_LIST=<compute cap>` 로 재빌드.
  `scripts/setup_hunyuan_texgen.ps1` 이 이제 `nvidia-smi --query-gpu=compute_cap` 로 자동 감지해 넣는다.
- **주의**: 빌드용 venv 와 **실행용 venv 가 같은지** 확인할 것. 다른 venv 에 빌드해 두고
  실행 venv 에는 프리빌트 휠이 남아 있는 상태가 정확히 이 사고였다.

### 런타임 함정 (실측)
- **`custom_rasterizer` DLL 로드 실패** → 스크립트에서 **`import torch` 를 먼저** 한 뒤 import.
- **diffusers 커스텀 파이프라인 로드 실패**(`"hunyuanpaint contains custom code"`) → `multiview_utils.py`의 파이프라인 로드에 **`trust_remote_code=True`** 추가.
- **썸네일 렌더 시 pyglet 없음** → `pip install "pyglet<2"` (2.x 아님).
- **VAE `.safetensors` 없음 → `.bin` 폴백 경고** → 정상. 무시.
- **저폴리 임포트 메시가 Nanite면 언리얼 렌더에 안 보임** → Nanite 끄기.
- **glTF base color 미연결** → 임포트 텍스처로 `M_*_AI` 머티리얼 직접 생성(텍스처가 texgen 없이도 언리얼에서 해결됨).

### 폴백
- texgen 못 뚫으면 **shape-only 메시 + gpt-image 소스로 언리얼 머티리얼** 로 진행 가능(품질 판정은 사용자).
- 또는 **클라우드 3D(Rodin/Hyper3D)** 로 전환(로컬 빌드 불필요, 키 필요).
