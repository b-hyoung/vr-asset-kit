# -*- coding: utf-8 -*-
"""고른 조명 프리셋 하나를 레벨에 적용한다 (에디터 안에서 실행).

    py -u scripts/apply_lighting.py --project <pid>      # ← 보통 이걸 쓴다(래퍼가 이 파일을 보냄)
    py -u scripts/ue_exec.py scripts/ue/apply_lighting.py "lighting" --grep LIGHT

⛔ 노을 고정 아님. 적용할 값은 **스크래치의 lighting.json** 에서만 읽는다
   (래퍼 scripts/apply_lighting.py 가 web/lighting.json 의 프리셋을 풀어서 써 둔다).
   파일이 없거나 id 가 "none" 이면 **아무것도 건드리지 않고** 끝낸다.

⛔ 기본 SkyLight 는 어떤 프리셋에서도 손대지 않는다 (사용자 하드룰).
⛔ 라이트 색은 set_light_color(LinearColor(r,g,b,1)) — FColor 위치인자는 BGRA 로 뒤집혀 파래진다.

환경변수:
  VRKIT_SCRATCH   스크래치 폴더 (기본: ~/Desktop/vr_scratch)
"""
import unreal, os, json

SCR = os.environ.get("VRKIT_SCRATCH") or os.path.join(
    os.path.expanduser("~"), "Desktop", "vr_scratch")
SPEC_PATH = os.path.join(SCR, "lighting.json")

if not os.path.isfile(SPEC_PATH):
    print("LIGHT skip | 선택된 프리셋 없음(%s 없음) — 조명 미개입" % SPEC_PATH)
    print("LIGHT done")
    raise SystemExit(0)

with open(SPEC_PATH, encoding="utf-8") as f:
    SPEC = json.load(f)

pid = SPEC.get("id") or ""
sun = SPEC.get("sun")
fog = SPEC.get("fog")
if pid == "none" or (not sun and not fog):
    print("LIGHT skip | id=%s — 조명을 건드리지 않는다" % (pid or "(빈값)"))
    print("LIGHT done")
    raise SystemExit(0)

eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)


def find(class_name):
    for a in eas.get_all_level_actors():
        if a.get_class().get_name() == class_name:
            return a
    return None


def lin(v):
    return unreal.LinearColor(float(v[0]), float(v[1]), float(v[2]),
                              float(v[3]) if len(v) > 3 else 1.0)


print("LIGHT preset | id=%s label=%s" % (pid, SPEC.get("label") or pid))

# ---- 태양(DirectionalLight) ----
if sun:
    dl = find("DirectionalLight")
    if not dl:
        print("LIGHT warn | DirectionalLight 액터가 없다 — 태양 적용 건너뜀")
    else:
        dc = dl.get_component_by_class(unreal.DirectionalLightComponent)
        pitch = float(sun.get("pitch", -3.0))
        yaw = float(sun.get("yaw", 0.0))
        dl.set_actor_rotation(unreal.Rotator(0.0, pitch, yaw), False)
        if sun.get("intensity") is not None:
            dc.set_editor_property("intensity", float(sun["intensity"]))
        if sun.get("color"):
            dc.set_light_color(lin(sun["color"]))          # ★ LinearColor 로만
        if sun.get("temperature") is not None:
            try:
                dc.set_editor_property("use_temperature", True)
                dc.set_editor_property("temperature", float(sun["temperature"]))
            except Exception as e:
                print("LIGHT warn | 색온도 적용 실패:", e)
        print("LIGHT sun | pitch=%s yaw=%s intensity=%s temp=%s"
              % (pitch, yaw, sun.get("intensity"), sun.get("temperature")))

# ---- 안개(ExponentialHeightFog) ----
if fog:
    fga = find("ExponentialHeightFog")
    if not fga:
        print("LIGHT warn | ExponentialHeightFog 액터가 없다 — 안개 적용 건너뜀")
    else:
        fc = fga.get_component_by_class(unreal.ExponentialHeightFogComponent)
        applied, failed = 0, []
        for k, v in fog.items():
            try:
                fc.set_editor_property(k, lin(v) if isinstance(v, list) else v)
                applied += 1
            except Exception:
                failed.append(k)          # 엔진 버전마다 없는 프로퍼티가 있다 — 치명적 아님
        print("LIGHT fog | 적용 %d개%s" % (applied, (" / 미지원: " + ",".join(failed)) if failed else ""))

# ⛔ SkyLight 는 읽지도 쓰지도 않는다 (하드룰). 어두우면 채움광을 따로 넣는다.
print("LIGHT skylight | 미개입(하드룰)")
print("LIGHT done | 다음: render_360 으로 8방향 평균 밝기 확인 — 판정은 사람/심판이 한다")
