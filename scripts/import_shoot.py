# -*- coding: utf-8 -*-
"""
@UnrealClaude Script
@Description: Import an AI prop glb, disable Nanite, spawn+render for QC
"""
import unreal, math, json

SCR = r"C:\Users\ACE\AppData\Local\Temp\claude\C--Users-ACE-Desktop-Hanes\56f7e7e5-4eeb-45da-bfb1-eada2407f8b0\scratchpad"
with open(SCR+r"\aiprop.json", encoding="utf-8") as f:
    J = json.load(f)
GLB = J["glb"]; NAME = J["name"]
DEST = "/Game/Husamguk/AIProps/" + NAME

# import
task = unreal.AssetImportTask()
task.set_editor_property("filename", GLB)
task.set_editor_property("destination_path", DEST)
task.set_editor_property("automated", True); task.set_editor_property("save", True); task.set_editor_property("replace_existing", True)
unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])

# find imported static mesh
ar = unreal.AssetRegistryHelpers.get_asset_registry()
meshpath = None
for a in ar.get_assets_by_path(DEST, recursive=True):
    if str(a.asset_class_path.asset_name) == "StaticMesh":
        meshpath = str(a.package_name) + "." + str(a.asset_name); break
print("MESH:", meshpath)
if not meshpath:
    print("NO_MESH"); raise SystemExit
sm = unreal.EditorAssetLibrary.load_asset(meshpath)
# disable nanite
try:
    ns = sm.get_editor_property("nanite_settings"); ns.set_editor_property("enabled", False)
    sm.set_editor_property("nanite_settings", ns); unreal.EditorAssetLibrary.save_loaded_asset(sm)
except Exception as e: print("NANITE_ERR:", e)

b = sm.get_bounds(); R = b.sphere_radius
print("RADIUS:", round(R,1))

# spawn at staging area
eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
for a in list(eas.get_all_level_actors()):
    if a.get_actor_label()=="AIQC": eas.destroy_actor(a)
act = eas.spawn_actor_from_class(unreal.StaticMeshActor, unreal.Vector(4000,4000, b.box_extent.z))
act.set_actor_label("AIQC"); act.static_mesh_component.set_static_mesh(sm)

# render
center = unreal.Vector(4000,4000,b.box_extent.z*0.9)
d = max(R*2.4, 250); cam = unreal.Vector(4000-d, 4000-d*0.7, center.z + R*0.8)
dx,dy,dz = center.x-cam.x, center.y-cam.y, center.z-cam.z
yaw = math.degrees(math.atan2(dy,dx)); pitch = math.degrees(math.atan2(dz, math.sqrt(dx*dx+dy*dy)))
world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
RL = unreal.RenderingLibrary
rt = RL.create_render_target2d(world, 1280, 720, unreal.TextureRenderTargetFormat.RTF_RGBA8)
cap = eas.spawn_actor_from_class(unreal.SceneCapture2D, cam, unreal.Rotator(0,pitch,yaw))
cc = cap.get_component_by_class(unreal.SceneCaptureComponent2D)
cc.set_editor_property("texture_target", rt)
cc.set_editor_property("capture_source", unreal.SceneCaptureSource.SCS_FINAL_COLOR_LDR)
cc.set_editor_property("fov_angle", 55.0)
pp = cc.get_editor_property("post_process_settings")
pp.set_editor_property("auto_exposure_bias", 1.0); pp.set_editor_property("override_auto_exposure_bias", True)
cc.set_editor_property("post_process_settings", pp)
cc.capture_scene()
RL.export_render_target(world, rt, SCR, "aiprop.png")
eas.destroy_actor(cap)
print("WROTE aiprop.png"); print("DONE")
