# -*- coding: utf-8 -*-
"""
@UnrealClaude Script
@Description: Import all AI prop glbs, disable Nanite, build textured materials
"""
import unreal, json
SCR = r"C:\Users\ACE\AppData\Local\Temp\claude\C--Users-ACE-Desktop-Hanes\56f7e7e5-4eeb-45da-bfb1-eada2407f8b0\scratchpad"
PROPS = json.load(open(SCR+r"\aiprops.json", encoding="utf-8"))  # [{"glb":..,"name":..}, ...]
mel = unreal.MaterialEditingLibrary
tools = unreal.AssetToolsHelpers.get_asset_tools()
ar = unreal.AssetRegistryHelpers.get_asset_registry()
report = []
for P in PROPS:
    GLB=P["glb"]; NAME=P["name"]; DEST="/Game/Husamguk/AIProps/"+NAME
    task = unreal.AssetImportTask()
    task.set_editor_property("filename", GLB); task.set_editor_property("destination_path", DEST)
    task.set_editor_property("automated", True); task.set_editor_property("save", True); task.set_editor_property("replace_existing", True)
    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
    tex=None; mesh=None
    for a in ar.get_assets_by_path(DEST, recursive=True):
        cn=str(a.asset_class_path.asset_name); full=str(a.package_name)+"."+str(a.asset_name)
        if cn=="Texture2D" and tex is None: tex=full
        elif cn=="StaticMesh": mesh=full
    if not mesh:
        report.append((NAME,"NO_MESH")); continue
    sm=unreal.EditorAssetLibrary.load_asset(mesh)
    try:
        ns=sm.get_editor_property("nanite_settings"); ns.set_editor_property("enabled",False)
        sm.set_editor_property("nanite_settings",ns); unreal.EditorAssetLibrary.save_loaded_asset(sm)
    except Exception: pass
    if tex:
        mpath="/Game/Husamguk/AIProps/M_%s_AI"%NAME
        if unreal.EditorAssetLibrary.does_asset_exist(mpath): unreal.EditorAssetLibrary.delete_asset(mpath)
        m=tools.create_asset("M_%s_AI"%NAME,"/Game/Husamguk/AIProps",unreal.Material,unreal.MaterialFactoryNew())
        ts=mel.create_material_expression(m,unreal.MaterialExpressionTextureSample,-350,0)
        ts.set_editor_property("texture",unreal.EditorAssetLibrary.load_asset(tex))
        mel.connect_material_property(ts,"RGB",unreal.MaterialProperty.MP_BASE_COLOR)
        r=mel.create_material_expression(m,unreal.MaterialExpressionConstant,-350,200); r.set_editor_property("r",0.82)
        mel.connect_material_property(r,"",unreal.MaterialProperty.MP_ROUGHNESS)
        mel.recompile_material(m); unreal.EditorAssetLibrary.save_asset(m.get_path_name())
        b=sm.get_bounds()
        report.append((NAME,"OK",mesh,"/Game/Husamguk/AIProps/M_%s_AI.M_%s_AI"%(NAME,NAME),round(b.box_extent.z,1)))
    else:
        report.append((NAME,"NO_TEX",mesh))
for r in report: print("REPORT:", r)
print("DONE")
