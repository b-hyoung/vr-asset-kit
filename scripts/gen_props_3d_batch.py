# -*- coding: utf-8 -*-
"""프롭 이미지 → 3D 배치 (Hunyuan3D 로컬). shape 1회 + paint 1회 로드.

★ gen_props_batch.py 와 달리 **엔진/서브폴더를 props.json 에서 읽는다**
  (state.engine_choices 를 그대로 따르기 위함 — AGENT_CONTRACT §4).
  Hunyuan3D-2mini 는 shape 전용이고 paint 가중치가 없다 → texgen 은 Hunyuan3D-2 의
  hunyuan3d-paint-v2-0-turbo 를 쓴다. (make.md: mini 는 subfolder 지정 필수)

usage: <Hunyuan venv>/python gen_props_3d_batch.py <BASE> [only=a,b]
  <BASE>/props.json 의 props[].name 으로 <BASE>/prop_<name>.png 를 읽어
  <BASE>/export/<name>.glb 로 낸다. 이미 있으면 건너뛴다(재개 가능).

props.json 추가 키(선택):
  "mesh_repo":     "tencent/Hunyuan3D-2mini"
  "mesh_subfolder":"hunyuan3d-dit-v2-mini-turbo"
  "paint_repo":    "tencent/Hunyuan3D-2"
  "paint_subfolder":"hunyuan3d-paint-v2-0-turbo"
  "max_faces": 20000
  "cpu_offload": true
"""
import os, sys, json, time, traceback

# ── make.md 함정 ①: 백그라운드 실행이면 cwd 를 못 잡아 hy3dgen import 가 깨진다.
#    → 레포 경로를 명시하고 chdir 한다.
REPO = os.environ.get("VRKIT_HUNYUAN_REPO") or os.path.join(
    os.path.expanduser("~"), "tools", "Hunyuan3D-2")
if not os.path.isdir(os.path.join(REPO, "hy3dgen")):
    print("NO_HUNYUAN_REPO:", REPO, "— VRKIT_HUNYUAN_REPO 로 지정하세요"); sys.exit(1)
os.chdir(REPO)
sys.path.insert(0, REPO)

# ── make.md 함정 ②: custom_rasterizer DLL 은 torch 를 먼저 import 해야 로드된다.
import torch  # noqa: E402  (반드시 hy3dgen 보다 먼저)

BASE = (sys.argv[1] if len(sys.argv) > 1 else None) or os.environ.get("VRKIT_DOCS_OUT")
if not BASE:
    print("NO_BASE: <BASE> 인자나 VRKIT_DOCS_OUT 을 주세요"); sys.exit(1)
CFG = json.load(open(os.path.join(BASE, "props.json"), encoding="utf-8"))
OUT = os.path.join(BASE, "export")
os.makedirs(OUT, exist_ok=True)

MESH_REPO = CFG.get("mesh_repo", "tencent/Hunyuan3D-2mini")
MESH_SUB = CFG.get("mesh_subfolder", "hunyuan3d-dit-v2-mini-turbo")
PAINT_REPO = CFG.get("paint_repo", "tencent/Hunyuan3D-2")
PAINT_SUB = CFG.get("paint_subfolder", "hunyuan3d-paint-v2-0-turbo")
MAX_FACES = int(CFG.get("max_faces", 20000))
OFFLOAD = bool(CFG.get("cpu_offload", True))

# ── 실측 08-31 (RTX 3080 Ti / sm_86) — texgen 이 이 에러로 죽었다:
#     RuntimeError: CUDA error: no kernel image is available for execution on the device
#   ★ 진짜 원인: custom_rasterizer 가 이 GPU 아키텍처(sm_86) 없이 빌드된 프리빌트 휠이었다.
#     (site-packages 에 custom_rasterizer-0.1.0+torch251.cuda124 휠이 깔려 있었음)
#     메시지 그대로 "이 GPU 용 커널이 fatbinary 에 없다"는 뜻이다.
#   ★ 함정: 커널 실패가 비동기로 보고돼 스택트레이스가 엉뚱한 diffusers conv2d 를 가리킨다.
#     VRAM·cuDNN·onnxruntime 을 의심하게 만든다 — 전부 헛다리였다.
#     → 진짜 위치는 CUDA_LAUNCH_BLOCKING=1 로만 드러난다(스택에 .pyd 이름이 뜬다).
#   ★ 해결: 소스에서 TORCH_CUDA_ARCH_LIST=<compute cap> 로 재빌드.
#     scripts/setup_hunyuan_texgen.ps1 이 이제 arch 를 자동 감지해 넣는다.
if bool(CFG.get("disable_cudnn_for_texgen", False)):
    torch.backends.cudnn.enabled = False
    print("cudnn: OFF", flush=True)

names = [p["name"] for p in CFG["props"]]
only = [a.split("=", 1)[1] for a in sys.argv[2:] if a.startswith("only=")]
if only:
    keep = set(",".join(only).split(","))
    names = [n for n in names if n in keep]

todo = []
for n in names:
    img = os.path.join(BASE, "prop_%s.png" % n)
    glb = os.path.join(OUT, "%s.glb" % n)
    if not os.path.isfile(img):
        print("SKIP_NO_IMAGE", n, flush=True); continue
    if os.path.isfile(glb) and os.path.getsize(glb) > 0:
        print("SKIP_DONE", n, flush=True); continue
    todo.append((n, img, glb))

if not todo:
    print("NOTHING_TO_DO"); sys.exit(0)

free = torch.cuda.mem_get_info()[0] / 1e9 if torch.cuda.is_available() else 0
print("GPU 여유 %.1fGB | shape=%s/%s | paint=%s/%s | offload=%s | 대상 %d개"
      % (free, MESH_REPO, MESH_SUB, PAINT_REPO, PAINT_SUB, OFFLOAD, len(todo)), flush=True)

from PIL import Image
from hy3dgen.rembg import BackgroundRemover
from hy3dgen.shapegen import (Hunyuan3DDiTFlowMatchingPipeline, FloaterRemover,
                              DegenerateFaceRemover, FaceReducer)

# ── 1) 배경 제거 (SDXL 출력은 불투명 배경 → 반드시 제거. make.md)
rembg = BackgroundRemover()
imgs = {}
for n, img, _ in todo:
    imgs[n] = rembg(Image.open(img).convert("RGBA"))
    print("rembg", n, flush=True)

# ── 2) SHAPE
print("=== SHAPEGEN load ===", flush=True)
t0 = time.time()
shape = Hunyuan3DDiTFlowMatchingPipeline.from_pretrained(MESH_REPO, subfolder=MESH_SUB)
if OFFLOAD:
    try:
        shape.enable_flashvdm()
    except Exception:
        pass
meshes, shape_fail = {}, []
for n, _, _ in todo:
    try:
        m = shape(image=imgs[n])[0]
        raw = len(m.faces)
        m = FaceReducer()(DegenerateFaceRemover()(FloaterRemover()(m)), max_facenum=MAX_FACES)
        meshes[n] = m
        print("shape %-11s %6d -> %6d faces  (%.0fs)" % (n, raw, len(m.faces), time.time() - t0), flush=True)
    except Exception as e:
        print("SHAPE_FAIL", n, repr(e)[:200], flush=True)
        shape_fail.append(n)
del shape
torch.cuda.empty_cache()
print("=== shape done %.0fs ===" % (time.time() - t0), flush=True)

# 텍스처 실패에 대비해 shape-only 를 먼저 남긴다 (폴백 — make.md)
for n, m in meshes.items():
    try:
        m.export(os.path.join(OUT, "%s_shape.glb" % n))
    except Exception as e:
        print("shape_export_fail", n, repr(e)[:120], flush=True)

# ── 3) TEXGEN
print("=== TEXGEN load ===", flush=True)
result = {"textured": [], "shape_only": [], "shape_fail": shape_fail}
paint = None
try:
    from hy3dgen.texgen import Hunyuan3DPaintPipeline
    paint = Hunyuan3DPaintPipeline.from_pretrained(PAINT_REPO, subfolder=PAINT_SUB)
    if OFFLOAD:
        # 12GB 급에서는 offload 없이는 texgen peak 가 VRAM 에 닿는다 (make.md 표)
        try:
            paint.enable_model_cpu_offload()
            print("paint: cpu_offload ON", flush=True)
        except Exception as e:
            print("paint: offload 실패(계속)", repr(e)[:120], flush=True)
except Exception:
    print("TEXGEN_LOAD_FAIL — shape-only 로 진행", flush=True)
    traceback.print_exc()

for n, _, glb in todo:
    if n not in meshes:
        continue
    if paint is None:
        os.replace(os.path.join(OUT, "%s_shape.glb" % n), glb)
        result["shape_only"].append(n); continue
    t1 = time.time()
    try:
        mt = paint(meshes[n], image=imgs[n])
        mt.export(glb)
        print("PAINT_OK %-11s %8d bytes (%.0fs)" % (n, os.path.getsize(glb), time.time() - t1), flush=True)
        result["textured"].append(n)
        try:
            os.remove(os.path.join(OUT, "%s_shape.glb" % n))
        except OSError:
            pass
    except Exception as e:
        print("PAINT_FAIL", n, repr(e)[:200], flush=True)
        if os.environ.get("VRKIT_TRACE"):
            traceback.print_exc()
        try:
            os.replace(os.path.join(OUT, "%s_shape.glb" % n), glb)
            result["shape_only"].append(n)
        except OSError:
            pass
        torch.cuda.empty_cache()

json.dump(result, open(os.path.join(BASE, "mesh_result.json"), "w"), ensure_ascii=False, indent=1)
print("BATCH_DONE textured=%d shape_only=%d fail=%d"
      % (len(result["textured"]), len(result["shape_only"]), len(result["shape_fail"])), flush=True)
