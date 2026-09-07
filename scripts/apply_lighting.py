# -*- coding: utf-8 -*-
"""고른 조명 프리셋을 언리얼에 적용한다 (로컬 실행 래퍼).

    py -u scripts/apply_lighting.py --project vr_20260907_102615   # state.json 의 선택을 따름
    py -u scripts/apply_lighting.py dusk                           # 프리셋 id 직접 지정
    py -u scripts/apply_lighting.py --list                         # 프리셋 목록
    py -u scripts/apply_lighting.py noon --dry-run                 # 값만 확인(에디터 미접속)

⛔ **노을은 기본값이 아니다.** 프리셋을 안 고른 프로젝트에서는 아무것도 적용하지 않는다.
   `none` 을 고르면 조명을 건드리지 않는다. 값 표: web/lighting.json (수정 가능).

동작: web/lighting.json 에서 프리셋을 풀어 스크래치에 lighting.json 으로 써 두고,
      scripts/ue/apply_lighting.py 를 ue_exec 로 에디터에 보낸다.
"""
import os, sys, json, subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TABLE = os.path.join(ROOT, "web", "lighting.json")
SCR = os.environ.get("VRKIT_SCRATCH") or os.path.join(
    os.path.expanduser("~"), "Desktop", "vr_scratch")


def load_table():
    with open(TABLE, encoding="utf-8") as f:
        return json.load(f)


def preset_of(table, pid):
    for p in table.get("presets", []):
        if p.get("id") == pid:
            return p
    return None


def from_project(proj):
    """state.json 의 inputs.lighting 을 읽는다 — 웹에서 사용자가 고른 값."""
    path = os.path.join(ROOT, "web", "projects", proj, "state.json")
    if not os.path.isfile(path):
        print("NO_PROJECT:", path)
        sys.exit(1)
    with open(path, encoding="utf-8") as f:
        st = json.load(f)
    return (st.get("inputs") or {}).get("lighting") or ""


def main():
    argv = sys.argv[1:]
    dry = "--dry-run" in argv
    argv = [a for a in argv if a != "--dry-run"]
    table = load_table()

    if "--list" in argv:
        for p in table.get("presets", []):
            print("%-15s %-14s %s" % (p.get("id"), p.get("label"), p.get("desc", "")))
        return 0

    pid = ""
    if "--project" in argv:
        i = argv.index("--project")
        pid = from_project(argv[i + 1])
        del argv[i:i + 2]
        if not pid:
            print("조명 프리셋이 선택되지 않았습니다 — 웹의 '조명·시간대 선택' 단계에서 고르세요.")
            print("⛔ 임의로 노을을 넣지 않습니다. 조명 미개입으로 끝냅니다.")
            return 0
    elif argv:
        pid = argv[0]

    if not pid:
        print(__doc__)
        return 2

    pr = preset_of(table, pid)
    if not pr:
        print("UNKNOWN_PRESET:", pid, "| 가능한 값:",
              ", ".join(p.get("id") for p in table.get("presets", [])))
        return 1

    spec = {"id": pr.get("id"), "label": pr.get("label"),
            "sun": pr.get("sun"), "fog": pr.get("fog")}
    print("PRESET:", spec["id"], "|", spec["label"])
    print(json.dumps(spec, ensure_ascii=False, indent=2))

    if pr.get("id") == "none" or (not pr.get("sun") and not pr.get("fog")):
        print("조명 미개입 프리셋 — 언리얼에 아무것도 보내지 않습니다.")
        return 0
    if dry:
        print("(--dry-run: 여기서 멈춤 — 에디터에 보내지 않음)")
        return 0

    os.makedirs(SCR, exist_ok=True)
    out = os.path.join(SCR, "lighting.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(spec, f, ensure_ascii=False, indent=2)
    print("WROTE:", out)

    exe = [sys.executable] if sys.executable else ["py", "-3"]
    cmd = exe + ["-u", os.path.join(ROOT, "scripts", "ue_exec.py"),
                 os.path.join(ROOT, "scripts", "ue", "apply_lighting.py"),
                 "lighting: " + str(spec["label"]), "--grep", "LIGHT"]
    print("RUN:", " ".join(cmd))
    return subprocess.call(cmd)


if __name__ == "__main__":
    sys.exit(main())
