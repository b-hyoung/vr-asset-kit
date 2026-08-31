# -*- coding: utf-8 -*-
"""프롭 컨셉 이미지 배치 생성 (로컬 diffusers). 파이프 1회 로드로 N장.

★ topic 무관: 모든 값은 <BASE>/props.json 에서 읽는다. 특정 프로젝트 예시 하드코딩 금지.
   (gen_prop_image.py 의 gen_local 안전장치를 그대로 따름 — 모델크기 vs 여유 VRAM 오프로드,
    slicing, OOM 폴백. 차이는 "파이프를 1번만 로드"하는 것뿐.)

usage: <venv>/python gen_props_image_batch.py <BASE>
       (BASE 미지정 시 env VRKIT_DOCS_OUT)

<BASE>/props.json:
{
  "repo": "stabilityai/sdxl-turbo",
  "style": "<슬롯4 강도 + 슬롯8 스타일 앵커>",
  "base_excl": "<슬롯7 배제 — ONLY ... NOT ...: no A, no B>",
  "size": 512, "steps": null,
  "props": [ {"name":"rock", "desc":"...", "excl":"<이 프롭만 배제 덮어쓰기(선택)>"} ]
}
결과: <BASE>/prop_<name>.png
"""
import os, sys, json

BASE = (sys.argv[1] if len(sys.argv) > 1 else None) or os.environ.get("VRKIT_DOCS_OUT")
if not BASE:
    print("NO_BASE: <BASE> 인자나 VRKIT_DOCS_OUT 을 주세요"); sys.exit(1)
CFG = json.load(open(os.path.join(BASE, "props.json"), encoding="utf-8"))
os.makedirs(BASE, exist_ok=True)

# ★ CLIP 텍스트 인코더는 77토큰에서 자른다. 긴 프롬프트를 그대로 넣으면
#   뒤쪽(= 구도 슬롯 2·3, 배제 슬롯 7)이 통째로 사라져 "장면·배경 있는 그림"이 나온다.
#   (실측 08-31: STUDIO+배제를 뒤에 붙였더니 전부 잘려 단일오브젝트가 안 나옴)
#   → 템플릿을 짧게 유지하고, 아래 _check_len 로 초과 시 즉시 경고한다.
TOKEN_LIMIT = 77

repo = CFG["repo"]
tone = CFG.get("tone", "")
templates = CFG.get("templates", {})
negative = CFG.get("negative", "")
props = CFG["props"]

# 재생성 루프용: 특정 프롭만 다시 (questions.md — 불합격 사유를 슬롯에 반영 후 재생성, 최대 3회)
#   usage: gen_props_image_batch.py <BASE> only=name1,name2
_only = [a.split("=", 1)[1] for a in sys.argv[2:] if a.startswith("only=")]
if _only:
    keep = set(",".join(_only).split(","))
    props = [p for p in props if p["name"] in keep]
    print("ONLY:", [p["name"] for p in props], flush=True)

print("모델 로딩: %s (처음이면 오래 걸림)" % repo, flush=True)
import torch
from diffusers import AutoPipelineForText2Image

rl = repo.lower()
fast = ("turbo" in rl) or ("schnell" in rl) or ("lightning" in rl)
dtype = torch.float16 if torch.cuda.is_available() else torch.float32

size_gb = None
try:
    from huggingface_hub import scan_cache_dir
    for r in scan_cache_dir().repos:
        if r.repo_id.lower() == rl:
            size_gb = r.size_on_disk / 1e9; break
except Exception:
    pass
free_gb = torch.cuda.mem_get_info()[0] / 1e9 if torch.cuda.is_available() else 0
use_offload = bool(size_gb and free_gb and size_gb * 1.15 > free_gb)
print("모델 ~%.1fGB / 여유 VRAM ~%.1fGB → %s" % (
    size_gb or -1, free_gb, "CPU 오프로드(느림)" if use_offload else "GPU 직접"), flush=True)

try:
    pipe = AutoPipelineForText2Image.from_pretrained(repo, torch_dtype=dtype, variant="fp16")
except Exception:
    pipe = AutoPipelineForText2Image.from_pretrained(repo, torch_dtype=dtype)
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
for _m in ("enable_attention_slicing", "enable_vae_slicing", "enable_vae_tiling"):
    try:
        getattr(pipe, _m)()
    except Exception:
        pass
try:
    pipe.set_progress_bar_config(disable=True)
except Exception:
    pass

# turbo/schnell 은 학습 해상도(512)를 벗어나면 형태가 무너진다 → Hunyuan 입력엔 형태가 더 중요.
steps = CFG.get("steps") or (4 if fast else 28)
size = int(CFG.get("size") or (512 if fast else 768))
print("설정: repo=%s steps=%d size=%dpx props=%d" % (repo, steps, size, len(props)), flush=True)

def _ntok(text):
    """CLIP 토큰 수 (특수토큰 포함). 77 초과분은 조용히 잘리므로 반드시 센다."""
    try:
        return len(pipe.tokenizer(text).input_ids)
    except Exception:
        return -1


over = [(p["name"], _ntok(templates.get(p.get("tmpl", "prop"), "{desc}, {tone}")
                          .format(desc=p["desc"], tone=tone))) for p in props]
over = [(n, t) for n, t in over if t > TOKEN_LIMIT]
if over:
    print("TOKEN_OVERFLOW (77 초과 → 뒤가 잘림, 구도·배제 슬롯이 날아감):", over, flush=True)
    print("생성 중단. props.json 의 desc/tone/templates 를 줄이세요.", flush=True)
    sys.exit(2)

ok, failed = [], []
for i, p in enumerate(props):
    name = p["name"]
    tmpl = templates.get(p.get("tmpl", "prop"), "{desc}, {tone}")
    prompt = tmpl.format(desc=p["desc"], tone=tone)
    outp = os.path.join(BASE, "prop_%s.png" % name)
    print("[%d/%d] %s (%d tok)" % (i + 1, len(props), name, _ntok(prompt)), flush=True)
    kw = {"num_inference_steps": steps, "height": size, "width": size}
    if fast:
        kw["guidance_scale"] = 0.0      # turbo/schnell 은 guidance 0
        # ★ guidance 0 이면 negative_prompt 가 아예 작동하지 않는다(CFG 미사용).
        #   → 배제 슬롯은 positive 안에 짧게 녹여 넣어야 한다.
    elif negative:
        kw["negative_prompt"] = negative
    try:
        try:
            out = pipe(prompt, **kw)
        except Exception:
            if not offloaded:
                try:
                    torch.cuda.empty_cache()
                except Exception:
                    pass
                pipe.enable_model_cpu_offload(); offloaded = True
                out = pipe(prompt, **kw)
            else:
                raise
        out.images[0].save(outp)
        print("   OK", outp, os.path.getsize(outp), flush=True)
        ok.append(name)
    except Exception as e:
        print("   FAIL", name, repr(e)[:200], flush=True)
        failed.append(name)

json.dump({"ok": ok, "failed": failed}, open(os.path.join(BASE, "images_result.json"), "w"))
print("BATCH_DONE ok=%d failed=%d" % (len(ok), len(failed)), flush=True)
