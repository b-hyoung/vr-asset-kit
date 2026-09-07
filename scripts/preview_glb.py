# -*- coding: utf-8 -*-
"""완성된 glb 를 4방향에서 렌더해 컨택트 시트로 만든다 (검수용).

usage: <venv>/python preview_glb.py <BASE> [only=a,b]
  <BASE>/export/*.glb 를 읽어 <BASE>/_mesh_preview.png 생성.

주의(실측): trimesh 오프스크린 렌더는 pyglet 이 필요하고 **1.x 여야 한다**
  → pip install "pyglet<2"  (2.x 는 API 가 달라 동작 안 함)
"""
import os, sys, glob, io

BASE = (sys.argv[1] if len(sys.argv) > 1 else None) or os.environ.get("VRKIT_DOCS_OUT")
if not BASE:
    print("NO_BASE"); sys.exit(1)
only = [a.split("=", 1)[1] for a in sys.argv[2:] if a.startswith("only=")]
keep = set(",".join(only).split(",")) if only else None

import numpy as np, trimesh
from PIL import Image, ImageDraw, ImageFont

files = sorted(glob.glob(os.path.join(BASE, "export", "*.glb")))
if keep:
    files = [f for f in files if os.path.splitext(os.path.basename(f))[0] in keep]
if not files:
    print("NO_GLB in", os.path.join(BASE, "export")); sys.exit(0)

S = 320                      # 뷰 1칸 크기
ANGLES = [0, 90, 180, 270]   # 요 4방향
PITCH  = 20                  # 0=정면. 크게 주면 탑다운이 돼 판단을 그르친다.


def render(path):
    scene = trimesh.load(path)
    if isinstance(scene, trimesh.Trimesh):
        scene = trimesh.Scene(scene)
    # 기본 카메라는 메시에 바짝 붙어 잘린다 → 대각선 기준으로 거리를 직접 준다.
    diag = float(np.linalg.norm(scene.extents))
    center = scene.centroid
    views = []
    for yaw in ANGLES:
        s = scene.copy()
        try:
            # ★ pitch 는 0 이 정면. 70 같은 값을 주면 탑다운이 돼 멀쩡한 메시도
            #   부서진 것처럼 보인다(실측 08-31 — 이걸로 인물 메시를 오판했다).
            s.set_camera(angles=(np.radians(PITCH), 0.0, np.radians(yaw)),
                         distance=diag * 1.4, center=center)
            png = s.save_image(resolution=(S, S), visible=True)
            views.append(Image.open(io.BytesIO(png)).convert("RGB"))
        except Exception as e:
            print("   render fail", yaw, repr(e)[:100])
            views.append(Image.new("RGB", (S, S), (60, 40, 40)))
    return views


try:
    font = ImageFont.truetype("C:/Windows/Fonts/malgun.ttf", 16)
except Exception:
    font = ImageFont.load_default()

LBL = 26
sheet = Image.new("RGB", (S * len(ANGLES), (S + LBL) * len(files)), (24, 24, 26))
d = ImageDraw.Draw(sheet)
for r, f in enumerate(files):
    name = os.path.splitext(os.path.basename(f))[0]
    print("[%d/%d] %s" % (r + 1, len(files), name), flush=True)
    for c, im in enumerate(render(f)):
        sheet.paste(im, (c * S, r * (S + LBL)))
    mb = os.path.getsize(f) / 1e6
    d.text((6, r * (S + LBL) + S + 5), "%s  —  %.2f MB" % (name, mb), fill=(235, 235, 235), font=font)

out = os.path.join(BASE, "_mesh_preview.png")
sheet.save(out)
print("SAVED", out, sheet.size)
