# 4. 에셋별 제작 루프

에셋마다: **이미지 → 3D → Blender 수정 → 검수**.

## 규칙
- 이미지 슬롯 **8개(주제/구도/배제 등) 미충족 시 생성 금지**. 배제 슬롯이 최우선.
- 엔진 선택: 이미지(기본 로컬) · 3D(Hunyuan3D-2)
- 저폴리 목표: 프롭 ~2만 페이스, 텍스처 2048, glb ~3MB/에셋

> 실측: 프롬프트 빈칸을 모델이 임의로 채우면 원하는 이미지가 안 나옴 → 슬롯 다 채우고 생성.

## 이미지 생성 (실측 08-30) — 고품질·topic무관
- **`scripts/gen_prop_image.py` 는 topic 무관**: 에셋 설명을 인자/`out/props.json`으로 받는다. **특정 예시(후삼국 등) 하드코딩 금지** — 하드코딩하면 주제와 무관한 이미지가 나와 "퀄리티 낮음"으로 보임.
- 품질 고정: **gpt-image-1 · 1024 · `quality:"high"` · 투명배경** + 공통 STUDIO 템플릿(단일객체·아이소3/4·균일광·고디테일).
- **투명 요청에도 어두운 배경이 올 때가 있음** → downstream **rembg가 배경 제거**하므로 무해. 굳이 재생성 말 것.

## 3D 생성 (실측 08-30) — 실행 함정
- **백그라운드 실행 시 cwd를 못 잡아 `hy3dgen` import 실패** → 스크립트 상단에 **레포 경로 명시 + `os.chdir(repo)`**.
- **엔진이 `Hunyuan3D-2mini`면 subfolder 필요**: `hunyuan3d-dit-v2-mini-turbo`. full(`Hunyuan3D-2`)과 혼동 금지 — 정확히 지정.
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
