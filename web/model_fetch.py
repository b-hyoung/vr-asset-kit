# -*- coding: utf-8 -*-
"""모델 다운로드 — **파이프라인이 실제로 쓰는 파일만** 받는다.

왜 필요한가 (실측):
  그냥 `snapshot_download(repo)` 하면 저장소 **전체**를 받는다. HF 이미지 모델 저장소는
  같은 가중치를 여러 형식으로 중복 배포한다:
    - stabilityai/sdxl-turbo        : 전체 55.5GB  → 실제 필요 ~7GB (fp16)
    - stabilityai/sd-3.5-medium     : 전체 48.9GB  → 실제 필요 ~16GB
  ONNX 내보내기, 단일파일 체크포인트(ComfyUI용), fp32/fp16 중복이 대부분이고
  diffusers 의 from_pretrained 는 그중 아무것도 쓰지 않는다.

방법:
  `DiffusionPipeline.download()` 는 model_index.json 을 읽어 **구성요소 폴더만** 받는다.
  덕분에 루트의 단일파일 체크포인트와 text_encoders/ 같은 중복 배포는 자동으로 제외된다.
  거기에 fp16 변형을 우선 시도해 용량을 절반으로 줄인다.

사용: py model_fetch.py <org/name>
"""
import sys

# 파이프라인이 안 쓰는 무거운 형식들 (안전망 — 폴더 안에 섞여 있는 경우 대비)
IGNORE = ["*.onnx", "*.onnx_data", "*.ckpt", "*.pth", "*.msgpack", "*.h5", "*.tflite"]


def main():
    if len(sys.argv) < 2:
        print("usage: model_fetch.py <org/name>")
        return 2
    repo = sys.argv[1]

    from diffusers import DiffusionPipeline

    # fp16 변형이 있으면 그쪽 — 용량이 대략 절반이고 어차피 GPU 에선 fp16 으로 돌린다
    for variant in ("fp16", None):
        label = variant or "기본(fp32)"
        try:
            print("[fetch] %s — %s 변형 시도" % (repo, label), flush=True)
            path = DiffusionPipeline.download(repo, variant=variant, ignore_patterns=IGNORE)
            print("[fetch] 완료: %s" % path, flush=True)
            print("DONE %s" % repo, flush=True)
            return 0
        except Exception as e:
            print("[fetch] %s 변형 실패: %s" % (label, repr(e)[:200]), flush=True)

    # diffusers 파이프라인이 아닌 저장소(예: 메시 모델)는 통째로 받되 무거운 형식은 제외
    print("[fetch] diffusers 파이프라인 아님 → snapshot_download(필터 적용)", flush=True)
    from huggingface_hub import snapshot_download
    path = snapshot_download(repo, ignore_patterns=IGNORE)
    print("[fetch] 완료: %s" % path, flush=True)
    print("DONE %s" % repo, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
