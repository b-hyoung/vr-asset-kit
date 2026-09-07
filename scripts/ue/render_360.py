# -*- coding: utf-8 -*-
"""배치·조명 검증: 한 지점에서 8방향 전부 찍고 평균 밝기를 잰다.

    python -u scripts/ue_exec.py scripts/ue/render_360.py "360 check" --grep CHECK360

왜 8방향인가 (실측 08-31): 한 방향만 렌더해 "잘 나왔다"고 보고했는데, 사용자가 실제로
보고 있던 방향은 완전한 암흑이었다. 모니터는 한 방향만 보지만 **VR 은 어디든 돌아본다.**
→ 이 스크립트가 place 단계의 기본 검증 도구다. 한 컷으로 판정하지 말 것.

환경변수:
  VRKIT_360_OUT     출력 폴더 (기본: <프로젝트>/Saved/vrkit360)
  VRKIT_360_AT      관측점 "x,y,z" (기본: 0,0,165 — 눈높이)
  VRKIT_360_MINLUM  통과 기준 평균 밝기 (기본: 6.0)
"""
import unreal, os, json

OUT = os.environ.get("VRKIT_360_OUT") or os.path.join(
    unreal.Paths.project_saved_dir(), "vrkit360")
AT = [float(v) for v in (os.environ.get("VRKIT_360_AT") or "0,0,165").split(",")]
MINLUM = float(os.environ.get("VRKIT_360_MINLUM") or 6.0)
W, H, FOV = 640, 480, 90.0

world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
RL = unreal.RenderingLibrary
os.makedirs(OUT, exist_ok=True)

rows = []
for i in range(8):
    yaw = i * 45.0
    rt = RL.create_render_target2d(world, W, H, unreal.TextureRenderTargetFormat.RTF_RGBA8)
    a = eas.spawn_actor_from_class(unreal.SceneCapture2D,
                                   unreal.Vector(*AT), unreal.Rotator(0, 0, yaw))
    c = a.get_component_by_class(unreal.SceneCaptureComponent2D)
    c.set_editor_property("texture_target", rt)
    c.set_editor_property("capture_source", unreal.SceneCaptureSource.SCS_FINAL_COLOR_LDR)
    c.set_editor_property("fov_angle", FOV)
    pp = c.get_editor_property("post_process_settings")
    # ★ 자동노출은 어두운 씬을 억지로 밝혀 '실제로 안 보이는' 걸 가린다 → 고정 노출로 잠근다
    for k in ("auto_exposure_min_brightness", "auto_exposure_max_brightness"):
        try:
            pp.set_editor_property("override_" + k, True)
            pp.set_editor_property(k, 1.0)
        except Exception:
            pass
    pp.set_editor_property("override_auto_exposure_bias", True)
    pp.set_editor_property("auto_exposure_bias", 0.0)
    c.set_editor_property("post_process_settings", pp)
    c.capture_scene()

    # 밝기는 언리얼 안에서 바로 잰다 (외부 도구 없이 판정 가능하도록).
    # ★ 전체 읽기(read_render_target)는 API 문서가 "incredibly inefficient" 라고 명시한다.
    #   → UV 격자 표본으로 충분하다. 평균 밝기는 108점이면 안정적이다.
    lum = -1.0
    err = None
    try:
        acc = n = 0.0
        for iy in range(9):
            for ix in range(12):
                c = RL.read_render_target_uv(world, rt, (ix + 0.5) / 12.0, (iy + 0.5) / 9.0)
                acc += 0.2126 * c.r + 0.7152 * c.g + 0.0722 * c.b
                n += 1
        lum = acc / n
    except Exception as e:
        err = repr(e)[:90]
        print("   lum_err", err)

    RL.export_render_target(world, rt, OUT, "dir_%03d.png" % int(yaw))
    eas.destroy_actor(a)
    # ★ 측정 실패(-1)를 통과로 두면 안 된다 — 깨진 측정이 PASS 로 보고되는 게
    #   이 하네스가 막으려는 바로 그 실패다 (실측 08-31: 실제로 그렇게 나왔다).
    rows.append({"yaw": int(yaw), "lum": round(lum, 1),
                 "ok": (lum >= MINLUM), "err": err})
    print("SHOT dir_%03d lum=%.1f" % (int(yaw), lum), flush=True)

dark = [r["yaw"] for r in rows if not r["ok"]]
broken = [r["yaw"] for r in rows if r["lum"] < 0]
print("CHECK360 " + json.dumps({
    "at": AT, "min_required": MINLUM, "out": OUT,
    "rows": rows, "dark_directions": dark, "measure_failed": broken,
    "verdict": "PASS" if not dark else "FAIL",
}, ensure_ascii=False))
if broken:
    print("→ 밝기 측정 자체가 실패했다. 판정 불가 — 통과로 처리하지 말 것.")
elif dark:
    print("→ 어두운 방향이 있다. 그림자 없는 채움광을 넣고 다시 잴 것 (place.md).")
