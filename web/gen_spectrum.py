# -*- coding: utf-8 -*-
"""로컬 diffusers로 강도 스펙트럼 4장 생성.
사용: python gen_spectrum.py <job.json>
job.json: {"repo":..., "prompts":[{"name","prompt"}], "steps":int, "size":int, "out":path}
결과: out 경로에 {"images":[{"name","b64"}]} 저장. 진행은 stdout으로.
"""
import sys, json, base64, io

job = json.load(open(sys.argv[1], encoding="utf-8"))
print("모델 로딩 중: " + job["repo"] + " (처음이면 오래 걸릴 수 있어요)", flush=True)

import torch
from diffusers import AutoPipelineForText2Image

repo_l = job["repo"].lower()
fast = ("turbo" in repo_l) or ("schnell" in repo_l) or ("lightning" in repo_l)
dtype = torch.float16 if torch.cuda.is_available() else torch.float32


def _repo_cache_gb(repo):
    try:
        from huggingface_hub import scan_cache_dir
        for r in scan_cache_dir().repos:
            if r.repo_id.lower() == repo.lower():
                return r.size_on_disk / 1e9
    except Exception:
        pass
    return None


# 안전장치: 모델 크기 vs 여유 VRAM 비교 → 대형이면 CPU 오프로드(크래시 방지)
size_gb = _repo_cache_gb(job["repo"])
free_gb = torch.cuda.mem_get_info()[0] / 1e9 if torch.cuda.is_available() else 0
use_offload = bool(size_gb and free_gb and size_gb * 1.15 > free_gb)
print("모델 ~%.1fGB / 여유 VRAM ~%.1fGB → %s" % (
    size_gb or -1, free_gb, "CPU 오프로드(안전·느림)" if use_offload else "GPU 직접(빠름)"), flush=True)

pipe = AutoPipelineForText2Image.from_pretrained(job["repo"], torch_dtype=dtype)
offloaded = False
if torch.cuda.is_available():
    if use_offload:
        pipe.enable_model_cpu_offload(); offloaded = True
    else:
        try:
            pipe.to("cuda")
        except RuntimeError:
            pipe.enable_model_cpu_offload(); offloaded = True
            print("VRAM 부족 → CPU 오프로드로 전환", flush=True)
# 메모리 절약 (OOM 크래시 방지)
for _m in ("enable_attention_slicing", "enable_vae_slicing", "enable_vae_tiling"):
    try:
        getattr(pipe, _m)()
    except Exception:
        pass
try:
    pipe.set_progress_bar_config(disable=True)
except Exception:
    pass

steps = int(job.get("steps", 20 if not fast else 4))
size = int(job.get("size", 512))
res = []
for i, p in enumerate(job["prompts"]):
    print("생성 %d/%d: %s (steps=%d, %dpx)" % (i + 1, len(job["prompts"]), p["name"], steps, size), flush=True)
    kw = {"num_inference_steps": steps, "height": size, "width": size}
    if fast:
        kw["guidance_scale"] = 0.0   # turbo/schnell 은 guidance 0
    try:
        out = pipe(p["prompt"], **kw)
    except (RuntimeError, torch.cuda.OutOfMemoryError):
        # OOM 등 → 오프로드로 재시도
        if not offloaded:
            torch.cuda.empty_cache()
            pipe.enable_model_cpu_offload(); offloaded = True
            out = pipe(p["prompt"], **kw)
        else:
            raise
    except TypeError:
        out = pipe(p["prompt"], num_inference_steps=steps)
    img = out.images[0]
    buf = io.BytesIO(); img.save(buf, format="PNG")
    res.append({"name": p["name"], "b64": base64.b64encode(buf.getvalue()).decode()})

json.dump({"images": res}, open(job["out"], "w"))
print("DONE", flush=True)
