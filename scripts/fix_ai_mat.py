# -*- coding: utf-8 -*-
"""
@UnrealClaude Script
@Description: Find AI prop texture, build material, assign, re-render
"""
import unreal, math, json, os
# ★ 경로 하드코딩 금지 — 스크래치/게임경로는 환경변수/입력으로 받는다.
#   VRKIT_SCRATCH: aiprop.json 이 있는 폴더 (없으면 임시폴더)
#   VRKIT_GAME_PATH: 이 프로젝트의 /Game 경로 (없으면 aiprop.json의 game_path, 그것도 없으면 /Game/VRKit)
SCR = os.environ.get("VRKIT_SCRATCH") or os.path.join(os.environ.get("TEMP", os.getcwd()), "vrkit")
J = json.load(open(os.path.join(SCR, "aiprop.json"), encoding="utf-8"))
NAME = J["name"]
GAME = os.environ.get("VRKIT_GAME_PATH") or J.get("game_path") or "/Game/VRKit"
DEST = GAME + "/AIProps/" + NAME
ar = unreal.AssetRegistryHelpers.get_asset_registry()
tex=None; mesh=None; mats=[]
for a in ar.get_assets_by_path(DEST, recursive=True):
    cn = str(a.asset_class_path.asset_name); full=str(a.package_name)+"."+str(a.asset_name)
    if cn=="Texture2D": tex=full
    elif cn=="StaticMesh": mesh=full
    elif cn in ("Material","MaterialInstanceConstant"): mats.append(full)
print("TEX:", tex); print("MESH:", mesh); print("MATS:", mats)
if not (tex and mesh):
    print("MISSING"); raise SystemExit
mel = unreal.MaterialEditingLibrary
tools = unreal.AssetToolsHelpers.get_asset_tools()
mpath = GAME + "/AIProps/M_%s_AI" % NAME
if unreal.EditorAssetLibrary.does_asset_exist(mpath):
    unreal.EditorAssetLibrary.delete_asset(mpath)
m = tools.create_asset("M_%s_AI"%NAME, GAME + "/AIProps", unreal.Material, unreal.MaterialFactoryNew())
ts = mel.create_material_expression(m, unreal.MaterialExpressionTextureSample, -350, 0)
ts.set_editor_property("texture", unreal.EditorAssetLibrary.load_asset(tex))
mel.connect_material_property(ts, "RGB", unreal.MaterialProperty.MP_BASE_COLOR)
r = mel.create_material_expression(m, unreal.MaterialExpressionConstant, -350, 200); r.set_editor_property("r",0.82)
mel.connect_material_property(r, "", unreal.MaterialProperty.MP_ROUGHNESS)
mel.recompile_material(m); unreal.EditorAssetLibrary.save_asset(m.get_path_name())

eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
act=None
for a in eas.get_all_level_actors():
    if a.get_actor_label()=="AIQC": act=a; break
c = act.static_mesh_component
for i in range(c.get_num_materials()): c.set_material(i, m)
sm = unreal.EditorAssetLibrary.load_asset(mesh); b=sm.get_bounds(); R=b.sphere_radius
# render
center=unreal.Vector(4000,4000,b.box_extent.z*0.9); d=max(R*2.4,250)
cam=unreal.Vector(4000-d,4000-d*0.7,center.z+R*0.8)
dx,dy,dz=center.x-cam.x,center.y-cam.y,center.z-cam.z
yaw=math.degrees(math.atan2(dy,dx)); pitch=math.degrees(math.atan2(dz,math.sqrt(dx*dx+dy*dy)))
world=unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
RL=unreal.RenderingLibrary
rt=RL.create_render_target2d(world,1280,720,unreal.TextureRenderTargetFormat.RTF_RGBA8)
cap=eas.spawn_actor_from_class(unreal.SceneCapture2D,cam,unreal.Rotator(0,pitch,yaw))
cc=cap.get_component_by_class(unreal.SceneCaptureComponent2D)
cc.set_editor_property("texture_target",rt); cc.set_editor_property("capture_source",unreal.SceneCaptureSource.SCS_FINAL_COLOR_LDR); cc.set_editor_property("fov_angle",55.0)
pp=cc.get_editor_property("post_process_settings"); pp.set_editor_property("auto_exposure_bias",1.0); pp.set_editor_property("override_auto_exposure_bias",True)
cc.set_editor_property("post_process_settings",pp)
cc.capture_scene(); RL.export_render_target(world,rt,SCR,"aiprop.png"); eas.destroy_actor(cap)
print("WROTE aiprop.png"); print("DONE")
