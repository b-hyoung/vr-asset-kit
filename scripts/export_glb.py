# -*- coding: utf-8 -*-
"""
@UnrealClaude Script
@Description: Export current level to self-contained GLB (read-only)
"""
import unreal, os, sys
# 출력 경로: (1) CLI 인자  (2) 환경변수 VRKIT_EXPORT_GLB  (3) 제네릭 기본값.
# ★ 특정 프로젝트(예: husamguk) 경로를 하드코딩하지 않는다. — 웹 state.inputs 기반으로 넘겨라.
OUT = (sys.argv[1] if len(sys.argv) > 1 else None) \
    or os.environ.get("VRKIT_EXPORT_GLB") \
    or os.path.join(os.path.expanduser("~"), "Desktop", "vr_export.glb")
world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
task = unreal.AssetExportTask()
task.set_editor_property("object", world)
task.set_editor_property("filename", OUT)
task.set_editor_property("automated", True)
task.set_editor_property("replace_identical", True)
task.set_editor_property("prompt", False)
for optcls in ("GLTFExportOptions",):
    try:
        opts = getattr(unreal, optcls)()
        try: opts.set_editor_property("export_uniform_scale", 1.0)
        except Exception: pass
        task.set_editor_property("options", opts)
        print("USING_OPTIONS", optcls)
    except Exception as e:
        print("opt_skip", optcls, repr(e)[:80])
ok = unreal.Exporter.run_asset_export_task(task)
ex = os.path.exists(OUT); sz = os.path.getsize(OUT) if ex else 0
print("EXPORT_OK", ok, "exists", ex, "size", sz, OUT)
print("DONE")
