# -*- coding: utf-8 -*-
"""Hunyuan glb 터칭 — blender --background 전용.

    blender --background --python touch_props_blender.py -- <BASE> [only=a,b]

입력 : <BASE>/export/<name>.glb  +  <BASE>/props.json
출력 : <BASE>/export_touched/<name>.glb , <BASE>/touch_result.json

규칙과 근거는 web/docs/steps/blender.md. 이 스크립트는 그 규칙을 **검사해서 강제한다** —
산문으로만 적어두면 안 지켜진다는 게 전제다(실측 08-31: 지터 규칙이 문서에 있었는데도 안 씀).

⛔ 하드룰: UV·머티리얼을 건드리지 않는다.
   Smart UV Project 를 돌리면 Hunyuan 텍스처와 짝이 맞는 원본 UV 를 덮어써서 색이 날아간다.
   끝나고 UV 해시로 대조해 변했으면 실패로 막는다.
"""
import bpy, bmesh, sys, os, json, math, hashlib


# ── 인자 파싱 ('--' 뒤가 우리 몫)
argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
BASE = argv[0] if argv else os.environ.get("VRKIT_DOCS_OUT")
if not BASE:
    print("NO_BASE"); sys.exit(1)
only = [a.split("=", 1)[1] for a in argv[1:] if a.startswith("only=")]
KEEP = set(",".join(only).split(",")) if only else None

CFG = json.load(open(os.path.join(BASE, "props.json"), encoding="utf-8"))
SRC = os.path.join(BASE, "export")
DST = os.path.join(BASE, "export_touched")
os.makedirs(DST, exist_ok=True)

TARGET_FACES = int(CFG.get("touch_target_faces", 5000))
FLOATER_MIN = float(CFG.get("touch_floater_min_ratio", 0.02))   # 최대 조각 부피 대비
DEFAULT_H = 150.0                                               # real_h_cm 없을 때
# ⚠ UCX_ 동봉은 기본 끈다. glTF/Interchange 가 UCX_ 를 인식하는지 미확인이고,
#   인식 못 하면 convex hull 이 '보이는 회색 덩어리'로 씬에 그대로 렌더된다(실측 08-31).
#   충돌은 언리얼 임포트 단계에서 CTF_UseComplexAsSimple 로 처리한다 — 코드로 검증 가능.
EMBED_COLLISION = bool(CFG.get("touch_embed_collision", False))


def clear():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def import_glb(path):
    """glTF 임포트 오퍼레이터는 버전마다 이름이 달라져서 순서대로 시도한다."""
    errs = []
    for fn in (lambda: bpy.ops.import_scene.gltf(filepath=path),
               lambda: bpy.ops.wm.gltf_import(filepath=path)):
        try:
            fn(); return True
        except Exception as e:
            errs.append(repr(e)[:80])
    print("   IMPORT_FAIL", errs)
    return False


def export_glb(path):
    errs = []
    for kw in ({"filepath": path, "export_format": "GLB"},
               {"filepath": path}):
        try:
            bpy.ops.export_scene.gltf(**kw); return True
        except Exception as e:
            errs.append(repr(e)[:80])
    print("   EXPORT_FAIL", errs)
    return False


def meshes():
    return [o for o in bpy.data.objects if o.type == "MESH"]


def uv_signature(objs):
    """UV '매핑' 이 살아있는지 보는 지문.

    ★ 정확 해시를 쓰면 안 된다: 플로터 제거·데시메이트는 정점을 지우므로 UV 배열이
      정당하게 바뀐다. 하드룰이 막으려는 건 **재투영(Smart UV)으로 레이아웃이 갈아엎히는 것**이다.
      → 레이어 이름 + UV 바운딩박스 + 텍스처 개수로 본다. 재투영은 이 셋을 크게 흔든다.
    """
    name, mnu, mnv, mxu, mxv, tex = None, 9e9, 9e9, -9e9, -9e9, 0
    for o in sorted(objs, key=lambda x: x.name):
        me = o.data
        if me.uv_layers:
            if name is None:
                name = me.uv_layers[0].name
            for l in me.uv_layers[0].data:
                u, v = l.uv[0], l.uv[1]
                mnu = min(mnu, u); mxu = max(mxu, u)
                mnv = min(mnv, v); mxv = max(mxv, v)
        for m in me.materials:
            if m and m.use_nodes:
                tex += sum(1 for nd in m.node_tree.nodes if nd.type == "TEX_IMAGE")
    if name is None:
        return None
    return {"layer": name, "bbox": [mnu, mnv, mxu, mxv], "tex_nodes": tex}


def uv_ok(before, after, tol=0.08):
    """레이어 이름·텍스처 노드 수가 같고, UV 바운딩박스가 크게 안 변했으면 통과."""
    if before is None or after is None:
        return False
    if before["layer"] != after["layer"]:
        return False
    if after["tex_nodes"] < before["tex_nodes"]:
        return False
    return all(abs(a - b) <= tol for a, b in zip(before["bbox"], after["bbox"]))


def mat_count(objs):
    return sum(len(o.data.materials) for o in objs)


def world_bbox(objs):
    xs, ys, zs = [], [], []
    for o in objs:
        for c in o.bound_box:
            w = o.matrix_world @ __import__("mathutils").Vector(c)
            xs.append(w.x); ys.append(w.y); zs.append(w.z)
    return (min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs))


def drop_floaters(obj):
    """연결요소로 분리 → 가장 큰 것만 남긴다. Hunyuan 이 배경 잔재를 물체로 물고 나온다."""
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.mesh.separate(type="LOOSE")
    bpy.ops.object.mode_set(mode="OBJECT")
    parts = [o for o in bpy.context.selected_objects if o.type == "MESH"]
    if len(parts) <= 1:
        return parts[0] if parts else obj, 0

    def vol(o):
        d = o.dimensions
        return max(d.x * d.y * d.z, 1e-9)

    parts.sort(key=vol, reverse=True)
    biggest = parts[0]
    vmax = vol(biggest)
    removed = 0
    for p in parts[1:]:
        if vol(p) / vmax < FLOATER_MIN:
            bpy.data.objects.remove(p, do_unlink=True); removed += 1
    # 임계 이상으로 남은 조각은 본체와 합친다 (실제 부품일 수 있다)
    rest = [o for o in bpy.data.objects if o.type == "MESH" and o is not biggest]
    if rest:
        bpy.ops.object.select_all(action="DESELECT")
        for o in rest:
            o.select_set(True)
        biggest.select_set(True)
        bpy.context.view_layer.objects.active = biggest
        bpy.ops.object.join()
    return biggest, removed


def origin_to_bottom(obj):
    """원점을 밑바닥 중앙으로. 이걸 해두면 언리얼 배치에서 바닥 보정이 필요없다."""
    (mnx, mny, mnz), (mxx, mxy, mxz) = world_bbox([obj])
    import mathutils
    bpy.context.scene.cursor.location = mathutils.Vector(
        ((mnx + mxx) / 2.0, (mny + mxy) / 2.0, mnz))
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.origin_set(type="ORIGIN_CURSOR")
    obj.location = (0.0, 0.0, 0.0)
    bpy.context.view_layer.update()


def scale_to_height(obj, target_cm):
    """Hunyuan 은 전부 ~198cm 정육면체로 정규화해 낸다 → 실측 크기로 되돌린다."""
    (_, _, mnz), (_, _, mxz) = world_bbox([obj])
    h = max(mxz - mnz, 1e-6)
    s = (target_cm / 100.0) / h          # 블렌더 단위 = m
    obj.scale = (obj.scale[0] * s, obj.scale[1] * s, obj.scale[2] * s)
    bpy.context.view_layer.update()
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)


def decimate(obj, target):
    n = len(obj.data.polygons)
    if n <= target:
        return n
    m = obj.modifiers.new("dec", "DECIMATE")
    m.ratio = max(target / float(n), 0.01)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.modifier_apply(modifier=m.name)
    return len(obj.data.polygons)


def make_collision(obj, name):
    """convex hull 을 UCX_<name>_00 으로 만든다.
    ⚠ UCX_ 규약은 FBX 임포터에서 확립된 것이고, glTF/Interchange 인식 여부는 미확인.
      임포트 후 반드시 충돌이 붙었는지 검증하고, 안 붙으면 언리얼에서
      CTF_UseComplexAsSimple 로 폴백할 것 (web/docs/steps/blender.md)."""
    col = obj.copy()
    col.data = obj.data.copy()
    col.data.materials.clear()
    bpy.context.collection.objects.link(col)
    col.name = "UCX_%s_00" % name
    bm = bmesh.new()
    bm.from_mesh(col.data)
    try:
        bmesh.ops.convex_hull(bm, input=bm.verts)
    except Exception as e:
        print("   hull_fail", repr(e)[:60])
    bm.to_mesh(col.data)
    bm.free()
    return col


# ── 대상 목록
props = {p["name"]: p for p in CFG["props"]}
names = [n for n in props if (KEEP is None or n in KEEP)]
names = [n for n in names if os.path.isfile(os.path.join(SRC, n + ".glb"))]

report = {"ok": [], "failed": [], "detail": {}}
print("TOUCH 대상 %d개 | 목표 face %d | 출력 %s" % (len(names), TARGET_FACES, DST), flush=True)

for n in sorted(names):
    src = os.path.join(SRC, n + ".glb")
    dst = os.path.join(DST, n + ".glb")
    target_h = float(props[n].get("real_h_cm", DEFAULT_H))
    print("[%s] real_h=%.0fcm" % (n, target_h), flush=True)
    try:
        clear()
        if not import_glb(src):
            report["failed"].append(n); continue

        objs = meshes()
        uv_before = uv_signature(objs)
        mats_before = mat_count(objs)
        faces_before = sum(len(o.data.polygons) for o in objs)

        # 여러 오브젝트로 들어오면 먼저 하나로 합친다
        if len(objs) > 1:
            bpy.ops.object.select_all(action="DESELECT")
            for o in objs:
                o.select_set(True)
            bpy.context.view_layer.objects.active = objs[0]
            bpy.ops.object.join()
        obj = meshes()[0]
        obj.name = n

        obj, removed = drop_floaters(obj)
        obj.name = n
        origin_to_bottom(obj)
        scale_to_height(obj, target_h)
        faces_after = decimate(obj, TARGET_FACES)
        origin_to_bottom(obj)                      # 데시메이트로 바닥이 미세하게 밀린다
        col = make_collision(obj, n) if EMBED_COLLISION else None
        obj.data.name = n                          # 임포트 에셋 이름이 tmp*.ply 로 붙는 걸 막는다

        # ── 강제 검사 (blender.md 표와 1:1)
        body = [obj]
        uv_after = uv_signature(body)
        (_, _, mnz), (_, _, mxz) = world_bbox(body)
        height_cm = (mxz - mnz) * 100.0
        checks = {
            "uv_preserved": uv_ok(uv_before, uv_after),
            "materials_preserved": (mat_count(body) >= mats_before),
            "floor_aligned": (abs(mnz) <= 0.001),
            "scale_ok": (abs(height_cm - target_h) / target_h <= 0.02),
            "face_budget": (faces_after <= TARGET_FACES),
            # 헐을 안 넣을 때는 '본체 하나만' 나가는지 검사한다 (회색 덩어리 방지)
            "collision_ok": ((col is not None and col.name.startswith("UCX_"))
                             if EMBED_COLLISION else (len(meshes()) == 1)),
        }
        report["detail"][n] = {
            "faces": [faces_before, faces_after], "floaters_removed": removed,
            "height_cm": round(height_cm, 1), "checks": checks,
        }
        bad = [k for k, v in checks.items() if not v]
        if bad:
            print("   ✗ 검사 실패:", bad, flush=True)
            report["failed"].append(n); continue

        if not export_glb(dst):
            report["failed"].append(n); continue
        print("   ✓ %d→%d face, %.0fcm, 플로터 %d 제거" % (faces_before, faces_after, height_cm, removed), flush=True)
        report["ok"].append(n)
    except Exception as e:
        import traceback
        print("   EXC", repr(e)[:150], flush=True)
        traceback.print_exc()
        report["failed"].append(n)

json.dump(report, open(os.path.join(BASE, "touch_result.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)
print("TOUCH_DONE ok=%d failed=%d" % (len(report["ok"]), len(report["failed"])), flush=True)
sys.exit(0 if not report["failed"] else 3)
