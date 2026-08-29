# -*- coding: utf-8 -*-
"""
환경·도구 진단 — check-env.ps1 항목을 파이썬으로 포팅.
이미지=OpenAI gpt-image-1(.env) / 3D=독립 Hunyuan3D-2(로컬) / 언리얼=UnrealClaude MCP
각 검사는 독립적으로 try/except — 하나 실패해도 나머지는 진행.
"""
import os, glob, json, shutil, subprocess, socket

USER = os.path.expanduser("~")


def _run(cmd, timeout=6):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           encoding="utf-8", errors="replace")
        out = ((p.stdout or "") + (p.stderr or "")).strip().splitlines()
        return out[0].strip() if out else ""
    except Exception:
        return None


def _port_open(port, host="127.0.0.1"):
    try:
        s = socket.create_connection((host, port), timeout=1.5)
        s.close()
        return True
    except Exception:
        return False


def spec():
    """진단 전에 먼저 보여줄 체크리스트 정의 (검사 실행 없이 빠르게).
    run() 이 채우는 항목 이름과 1:1로 맞춘다."""
    return {"items": [
        {"category": "A. 로컬 소프트웨어", "name": "Unreal Engine", "required": False, "step": "4.5 임포트~6 렌더", "need": "UE_5.x — 임포트/배치/렌더에 필요"},
        {"category": "A. 로컬 소프트웨어", "name": "python (py 포함)", "required": True, "step": "전 단계", "need": "모든 스크립트 실행"},
        {"category": "A. 로컬 소프트웨어", "name": "uv", "required": False, "step": "환경(선택)", "need": "파이썬 패키지 관리 (선택)"},
        {"category": "A. 로컬 소프트웨어", "name": "node", "required": False, "step": "MCP 브릿지", "need": "MCP 브릿지 실행"},
        {"category": "A. 로컬 소프트웨어", "name": "git", "required": False, "step": "환경(선택)", "need": "버전관리"},
        {"category": "A. 로컬 소프트웨어", "name": "Blender (선택)", "required": False, "step": "4 에셋제작(선택)", "need": "블록아웃/레퍼런스 쓸 때만"},
        {"category": "B. 이미지 생성", "name": "OPENAI_API_KEY", "required": False, "step": "2 앵커·4 제작 (gpt-image 선택 시만)", "need": "기본은 로컬 이미지. gpt-image-1 엔진 고를 때만 필요"},
        {"category": "C. 3D (Hunyuan3D-2)", "name": "Hunyuan3D-2 레포", "required": False, "step": "4 에셋제작", "need": "이미지→3D 로컬 레포"},
        {"category": "C. 3D (Hunyuan3D-2)", "name": "venv (PyTorch)", "required": False, "step": "4 에셋제작", "need": "Hunyuan 실행 가상환경"},
        {"category": "C. 3D (Hunyuan3D-2)", "name": "torch CUDA", "required": False, "step": "4 에셋제작", "need": "GPU 가속 (없으면 느림)"},
        {"category": "C. 3D (Hunyuan3D-2)", "name": "★ Hunyuan 모델 다운로드", "required": True, "step": "4 에셋제작", "need": "3D 생성 가중치 (수 GB)"},
        {"category": "D. 언리얼 (UnrealClaude MCP)", "name": "unrealclaude MCP 등록", "required": True, "step": "4.5 임포트~5 배치", "need": "언리얼 직접 조종"},
        {"category": "D. 언리얼 (UnrealClaude MCP)", "name": "Unreal 에디터 실행중", "required": False, "step": "4.5 임포트~6 렌더", "need": "임포트 단계 전에 열 것"},
        {"category": "D. 언리얼 (UnrealClaude MCP)", "name": "REST :3000 (execute_script)", "required": False, "step": "4.5 임포트~6 렌더", "need": "에디터+플러그인 서버"},
    ]}


def run(hunyuan_dir=None, env_file=None):
    items = []

    def add(cat, name, ok, detail, required=False):
        items.append({"category": cat, "name": name, "ok": bool(ok),
                      "detail": detail, "required": required})

    # === A. 로컬 소프트웨어 ===
    A = "A. 로컬 소프트웨어"
    try:
        ue = glob.glob(r"C:\Program Files\Epic Games\UE_*")
        add(A, "Unreal Engine", len(ue) > 0,
            (", ".join(os.path.basename(x) for x in ue) + "  ← 프로젝트 버전 고정") if ue else "미설치 — Epic Launcher")
    except Exception as e:
        add(A, "Unreal Engine", False, "확인 실패: %r" % e)

    pyv = _run(["python", "--version"]) or _run(["py", "--version"])
    add(A, "python (py 포함)", bool(pyv), pyv or "미설치 — python.org (py 런처 포함)", required=True)

    for t in ["uv", "node", "git"]:
        v = _run([t, "--version"]) if shutil.which(t) else None
        add(A, t, bool(v), v or "미설치")

    try:
        bl = glob.glob(r"C:\Program Files\Blender Foundation\*")
        add(A, "Blender (선택)", len(bl) > 0,
            (", ".join(os.path.basename(x) for x in bl)) if bl else "블록아웃-레퍼런스 쓸 때만 필요")
    except Exception:
        add(A, "Blender (선택)", False, "확인 실패")

    # === B. 이미지 생성 (기본 로컬, gpt-image 선택 시 OpenAI 키) ===
    B = "B. 이미지 생성"
    key_found, key_where = False, ""
    candidates = []
    if env_file:
        candidates.append(env_file)
    candidates.append(os.path.join(USER, "Desktop", "bobs_project", "Core-CBT", ".env"))
    for p in candidates:
        try:
            if p and os.path.isfile(p):
                with open(p, encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        s = line.strip()
                        if s.startswith("OPENAI_API_KEY") and "=" in s and s.split("=", 1)[1].strip():
                            key_found, key_where = True, p
                            break
            if key_found:
                break
        except Exception:
            pass
    if not key_found and os.environ.get("OPENAI_API_KEY"):
        key_found, key_where = True, "환경변수"
    add(B, "OPENAI_API_KEY", key_found,
        ("있음 @ " + key_where + " (값 숨김)") if key_found else "없음 — 기본은 로컬 이미지라 필수 아님. gpt-image 쓸 때만 .env에 설정",
        required=False)

    # === C. 3D 생성 (독립 Hunyuan3D-2 로컬) ===
    C = "C. 3D (Hunyuan3D-2)"
    hd = hunyuan_dir or os.path.join(USER, "Desktop", "image3d", "Hunyuan3D-2")
    repo = os.path.isdir(hd)
    add(C, "Hunyuan3D-2 레포", repo, hd if repo else "없음 — git clone Tencent/Hunyuan3D-2")
    venv_cands = [os.path.join(hd, "..", "venv", "Scripts", "python.exe"),
                  os.path.join(hd, "venv", "Scripts", "python.exe")]
    venv_py = next((c for c in venv_cands if os.path.isfile(c)), None)
    add(C, "venv (PyTorch)", bool(venv_py), venv_py or "venv 없음 — Hunyuan용 가상환경 미생성")
    if venv_py:
        cu = _run([venv_py, "-c", "import torch;print('cuda' if torch.cuda.is_available() else 'cpu')"], timeout=25)
        add(C, "torch CUDA", cu == "cuda",
            "GPU 사용 가능" if cu == "cuda" else ((cu + " — GPU 인식 안 됨(느림)") if cu else "torch import 실패 — 확장 빌드 필요"))
    hf = os.path.join(USER, ".cache", "huggingface", "hub", "models--tencent--Hunyuan3D-2")
    hy = os.path.join(USER, ".cache", "hy3dgen")
    md = os.path.isdir(hf) or os.path.isdir(hy)
    add(C, "★ Hunyuan 모델 다운로드", md,
        "가중치 캐시 있음" if md else "아직 안 받음 — 첫 실행 시 HF에서 수 GB 자동 다운로드",
        required=True)

    # === D. 언리얼 조종 (UnrealClaude MCP) ===
    D = "D. 언리얼 (UnrealClaude MCP)"
    cfg = os.path.join(USER, ".claude.json")
    has_unreal = False
    try:
        if os.path.isfile(cfg):
            with open(cfg, encoding="utf-8", errors="ignore") as f:
                j = json.load(f)
            names = list((j.get("mcpServers") or {}).keys())
            for pv in (j.get("projects") or {}).values():
                if isinstance(pv, dict):
                    names += list((pv.get("mcpServers") or {}).keys())
            has_unreal = any("unreal" in n.lower() for n in names)
    except Exception:
        pass
    add(D, "unrealclaude MCP 등록", has_unreal,
        ".claude.json에 등록됨" if has_unreal else "미등록 — claude mcp add --scope user unrealclaude ...",
        required=True)

    up = _run(["tasklist", "/FI", "IMAGENAME eq UnrealEditor.exe", "/NH"], timeout=8)
    running = bool(up) and "UnrealEditor" in up
    add(D, "Unreal 에디터 실행중", running,
        "실행중 — 임포트/배치/렌더에 필요" if running else "미실행 — 임포트 단계 전에 열 것 (이미지·3D는 가능)")

    p3 = _port_open(3000)
    add(D, "REST :3000 (execute_script)", p3,
        "열림 (플러그인 서버 응답)" if p3 else "닫힘 — 에디터+플러그인 켜야 열림")

    # 각 항목에 "어느 단계에서 필요한지"(step) 부착 — spec()과 이름으로 매칭
    step_map = {i["name"]: i.get("step", "") for i in spec()["items"]}
    for it in items:
        it["step"] = step_map.get(it["name"], "")

    total = len(items)
    ok = sum(1 for i in items if i["ok"])
    required_missing = [i["name"] for i in items if i["required"] and not i["ok"]]
    return {"items": items, "ok": ok, "total": total, "required_missing": required_missing}
