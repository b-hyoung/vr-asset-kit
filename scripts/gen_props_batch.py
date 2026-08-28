# -*- coding: utf-8 -*-
# 여러 프롭 image->3D 배치. shape 1회 + paint 1회 로드로 효율화.
import os, sys, json, torch
from PIL import Image
from hy3dgen.rembg import BackgroundRemover
from hy3dgen.shapegen import Hunyuan3DDiTFlowMatchingPipeline, FloaterRemover, DegenerateFaceRemover, FaceReducer
from hy3dgen.texgen import Hunyuan3DPaintPipeline

# BASE(이미지 폴더): (1) CLI 인자  (2) 환경변수 VRKIT_DOCS_OUT  (3) 제네릭 기본값.
# ★ 특정 프로젝트 경로(husamguk 등) 하드코딩 금지 — 웹 state 기반으로 넘겨라.
BASE = (sys.argv[1] if len(sys.argv) > 1 else None) \
    or os.environ.get("VRKIT_DOCS_OUT") \
    or os.path.join(os.path.expanduser("~"), "Desktop", "vr_docs", "out")
OUT  = os.path.join(BASE, "export")
os.makedirs(OUT, exist_ok=True)

# 제작할 프롭 목록: <BASE>/props.json  ([[이미지, 출력glb], ...]) 있으면 사용.
# 없으면 비어 있음(예시를 코드에 박아 두지 않는다). 아래는 형식 예시 주석일 뿐:
#   [["prop_rock.png","prop_rock.glb"]]
_props_json = os.path.join(BASE, "props.json")
if os.path.exists(_props_json):
    with open(_props_json, "r", encoding="utf-8") as f:
        PROPS = [tuple(x) for x in json.load(f)]
else:
    PROPS = []
    print("NO_PROPS: %s 에 props.json 이 없습니다. [[이미지,출력glb],...] 형식으로 만들어 넘기세요." % BASE, flush=True)
    sys.exit(0)

rembg = BackgroundRemover()
imgs = []
for img_name,_ in PROPS:
    im = Image.open(os.path.join(BASE, img_name)).convert("RGBA")
    im = rembg(im); imgs.append(im)
    print("loaded", img_name, flush=True)

print("=== SHAPEGEN load ===", flush=True)
shape = Hunyuan3DDiTFlowMatchingPipeline.from_pretrained('tencent/Hunyuan3D-2')
meshes = []
for i,im in enumerate(imgs):
    m = shape(image=im)[0]
    print("shape %d faces %d" % (i, len(m.faces)), flush=True)
    meshes.append(m)
del shape; torch.cuda.empty_cache()

flo=FloaterRemover(); deg=DegenerateFaceRemover(); fr=FaceReducer()
for i in range(len(meshes)):
    try:
        meshes[i] = fr(deg(flo(meshes[i])), max_facenum=20000)
        print("reduced %d -> %d" % (i, len(meshes[i].faces)), flush=True)
    except Exception as e:
        print("reduce skip %d: %r" % (i, e), flush=True)

print("=== TEXGEN load ===", flush=True)
paint = Hunyuan3DPaintPipeline.from_pretrained('tencent/Hunyuan3D-2')
for i,(_,outname) in enumerate(PROPS):
    try:
        mt = paint(meshes[i], image=imgs[i])
        p = os.path.join(OUT, outname)
        mt.export(p)
        print("SAVED", outname, os.path.getsize(p), flush=True)
    except Exception as e:
        print("PAINT_FAIL %d: %r" % (i, e), flush=True)
        try:
            meshes[i].export(os.path.join(OUT, outname.replace(".glb","_shape.glb")))
            print("SAVED_SHAPE_ONLY", outname, flush=True)
        except Exception: pass
print("BATCH_DONE", flush=True)
