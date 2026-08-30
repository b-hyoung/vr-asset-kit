# -*- coding: utf-8 -*-
# 프롭 image->3D: Hunyuan3D shapegen + texgen -> decimate -> glb.
# usage: venv/python gen_prop_3d.py <image.png> <out.glb>
import sys, os, torch
from PIL import Image
from hy3dgen.rembg import BackgroundRemover
from hy3dgen.shapegen import Hunyuan3DDiTFlowMatchingPipeline

IMG = sys.argv[1]
OUT = sys.argv[2]
print("LOAD image", IMG, flush=True)
img = Image.open(IMG).convert("RGBA")
img = BackgroundRemover()(img)

print("SHAPEGEN...", flush=True)
shape = Hunyuan3DDiTFlowMatchingPipeline.from_pretrained('tencent/Hunyuan3D-2')
mesh = shape(image=img)[0]
print("raw faces:", len(mesh.faces), flush=True)
del shape
torch.cuda.empty_cache()

# cleanup + decimate
try:
    from hy3dgen.shapegen import FloaterRemover, DegenerateFaceRemover, FaceReducer
    mesh = FloaterRemover()(mesh)
    mesh = DegenerateFaceRemover()(mesh)
    mesh = FaceReducer()(mesh, max_facenum=20000)
    print("reduced faces:", len(mesh.faces), flush=True)
except Exception as e:
    print("REDUCE_SKIP:", repr(e)[:160], flush=True)

print("TEXGEN...", flush=True)
from hy3dgen.texgen import Hunyuan3DPaintPipeline
paint = Hunyuan3DPaintPipeline.from_pretrained('tencent/Hunyuan3D-2')
mesh = paint(mesh, image=img)

mesh.export(OUT)
print("SAVED", OUT, os.path.getsize(OUT), flush=True)
