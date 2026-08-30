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

dtype = torch.bfloat16 if torch.cuda.is_available() else torch.float32
pipe = AutoPipelineForText2Image.from_pretrained(job["repo"], torch_dtype=dtype)
# 저VRAM: CPU 오프로드 (16GB에서 FLUX/SDXL 돌리기)
try:
    pipe.enable_model_cpu_offload()
except Exception:
    if torch.cuda.is_available():
        pipe.to("cuda")

steps = int(job.get("steps", 25))
size = int(job.get("size", 768))
res = []
for i, p in enumerate(job["prompts"]):
    print("생성 %d/%d: %s" % (i + 1, len(job["prompts"]), p["name"]), flush=True)
    kw = {"num_inference_steps": steps, "height": size, "width": size}
    try:
        out = pipe(p["prompt"], **kw)
    except TypeError:
        out = pipe(p["prompt"], num_inference_steps=steps)  # 일부 파이프라인 호환
    img = out.images[0]
    buf = io.BytesIO(); img.save(buf, format="PNG")
    res.append({"name": p["name"], "b64": base64.b64encode(buf.getvalue()).decode()})

json.dump({"images": res}, open(job["out"], "w"))
print("DONE", flush=True)
