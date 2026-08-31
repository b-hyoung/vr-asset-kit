# -*- coding: utf-8 -*-
# 프롭 컨셉 생성 (gpt-image-1, text->image). 단일객체·투명배경·균일광(노을은 언리얼에서).
# ★ topic 무관: 에셋 설명을 인자/props.json 로 받는다 (후삼국 등 특정 예시 하드코딩 금지).
#
# usage:
#   py gen_prop_image.py <name> "<무엇인지 한 줄 설명>" ["<스타일 앵커>"]
#   py gen_prop_image.py <name>        → out/props.json 의 {name:{desc, style}} 조회
#
# out/props.json 예: { "well": {"desc":"돌 우물, 나무 지붕", "style":"조선 저잣거리, 노을"} }
import json, base64, os, sys, urllib.request, urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))

# 키: 환경변수 우선, 없으면 web/.env, 그다음 알려진 경로
def _load_key():
    if os.environ.get("OPENAI_API_KEY"):
        return os.environ["OPENAI_API_KEY"]
    cands = []
    if os.environ.get("VRKIT_ENV_FILE"):
        cands.append(os.environ["VRKIT_ENV_FILE"])
    cands += [os.path.join(HERE, "..", "web", ".env"),
              os.path.join(HERE, ".env"),
              os.path.join(os.path.expanduser("~"), ".vrkit", ".env")]
    for p in cands:
        try:
            if os.path.isfile(p):
                for line in open(p, encoding="utf-8", errors="ignore"):
                    s = line.strip()
                    if s.startswith("OPENAI_API_KEY") and "=" in s:
                        v = s.split("=", 1)[1].strip().strip('"').strip("'")
                        if v:
                            return v
        except Exception:
            pass
    return None

# ★ 고품질 게임 에셋 레퍼런스 템플릿 (topic 무관)
STUDIO = ("Single object, centered, full object in frame, isometric 3/4 view, "
          "plain transparent background, soft even studio lighting (no harsh shadows, no colored light). "
          "Clean high-detail game-asset reference, physically-based, crisp sharp focus, "
          "high fidelity, professional 3D concept art, no text, no watermark, no people, no clutter.")

# --engine 파싱 (엔진: "gpt-image"=클라우드 / diffusers repo=로컬). env·props.json에서도 받음.
argv = sys.argv[1:]
engine = os.environ.get("VRKIT_IMAGE_ENGINE", "")
if "--engine" in argv:
    i = argv.index("--engine"); engine = argv[i + 1] if i + 1 < len(argv) else engine
    del argv[i:i + 2]
argv = [a for a in argv if not a.startswith("--")]

name = argv[0] if len(argv) > 0 else None
desc = argv[1] if len(argv) > 1 else None
style = argv[2] if len(argv) > 2 else ""

if not name:
    print("usage: gen_prop_image.py <name> \"<desc>\" [style] [--engine gpt-image|<repo>]"); sys.exit(1)

# 설명이 없으면 props.json 에서 조회 (engine/repo도 항목에서 받을 수 있음)
if not desc or not engine:
    pj = os.path.join(HERE, "out", "props.json")
    if os.path.isfile(pj):
        try:
            m = json.load(open(pj, encoding="utf-8"))
            item = m.get(name, {})
            desc = desc or item.get("desc"); style = style or item.get("style", "")
            engine = engine or item.get("engine") or item.get("repo", "")
        except Exception:
            pass
if not desc:
    print("설명 없음: 인자로 desc를 주거나 out/props.json에 %s 를 넣어라" % name); sys.exit(1)

prompt = "%s. %s. %s" % (desc, style, STUDIO)
outp = os.path.join(HERE, "out", "prop_%s.png" % name)
os.makedirs(os.path.join(HERE, "out"), exist_ok=True)
is_cloud = (not engine) or engine.lower() in ("gpt-image", "gpt-image-1", "openai")


def gen_cloud():
    key = _load_key()
    if not key:
        print("NO_KEY"); return 1
    body = json.dumps({"model": "gpt-image-1", "prompt": prompt, "size": "1024x1024",
                       "n": 1, "quality": "high", "background": "transparent"}).encode()
    req = urllib.request.Request("https://api.openai.com/v1/images/generations", data=body,
                                 headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            data = json.loads(r.read())
        with open(outp, "wb") as im:
            im.write(base64.b64decode(data["data"][0]["b64_json"]))
        print("OK", outp); return 0
    except urllib.error.HTTPError as e:
        print("HTTP_FAIL", e.code, e.read().decode(errors="replace")[:500]); return 1
    except Exception as e:
        print("FAIL", repr(e)[:300]); return 1


def gen_local(repo):
    # gen_spectrum.py 와 동일한 안전장치: 모델크기 vs 여유 VRAM → 오프로드, slicing, OOM 폴백.
    # (배경은 불투명 PNG로 나옴 → downstream rembg가 제거. make.md 참고)
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
    for _m in ("enable_attention_slicing", "enable_vae_slicing", "enable_vae_tiling"):
        try:
            getattr(pipe, _m)()
        except Exception:
            pass
    try:
        pipe.set_progress_bar_config(disable=True)
    except Exception:
        pass
    steps = 4 if fast else 28          # 컨셉은 Hunyuan 입력 → 화질 위해 넉넉히
    size = 768                          # 16GB 안전, Hunyuan 입력엔 충분(실측: 500px도 동작)
    kw = {"num_inference_steps": steps, "height": size, "width": size}
    if fast:
        kw["guidance_scale"] = 0.0
    print("생성: %s (steps=%d, %dpx)" % (name, steps, size), flush=True)
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
    print("OK", outp); return 0


try:
    rc = gen_cloud() if is_cloud else gen_local(engine)
except Exception as e:
    print("FAIL", repr(e)[:300]); rc = 1
sys.exit(rc)

# ── (참고) 예시 프롬프트: 후삼국 마을. 이 파일에 하드코딩하지 말고 props.json/인자로 넘길 것.
#   well: "돌 우물(원형 돌담+나무 지붕+두레박)"  house_a: "일자형 한옥(기와 박공지붕)" 등
