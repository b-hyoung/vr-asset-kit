# -*- coding: utf-8 -*-
"""
환경·도구 진단 — check-env.ps1 항목을 파이썬으로 포팅.
이미지=OpenAI gpt-image-1(.env) / 3D=독립 Hunyuan3D-2(로컬) / 언리얼=UnrealClaude MCP
각 검사는 독립적으로 try/except — 하나 실패해도 나머지는 진행.
"""
import os, glob, json, shutil, subprocess, socket

USER = os.path.expanduser("~")
WEB = os.path.dirname(os.path.abspath(__file__))  # .../vr-harness/web

# 파이프라인 순서(stage) — 이 순서대로 필요한 것을 묶어 보여준다.
STAGES = [
    {"key": "base",   "label": "기반 환경",
     "action": "기반환경 설치 확인",
     "todo": "빠진 게 있으면 '설치'를 눌러 가이드대로. 이미 다 OK면 그냥 통과."},
    {"key": "image",  "label": "① 이미지 생성",
     "action": "이미지 엔진 선택",
     "todo": "FLUX(로컬) 또는 gpt-image 중 하나를 눌러 확정. 클라우드면 키 입력."},
    {"key": "mesh",   "label": "② 3D 생성",
     "action": "3D 엔진 선택",
     "todo": "Hunyuan(로컬) 또는 Rodin(클라우드) 중 하나를 눌러 확정. 클라우드면 키 입력."},
    {"key": "unreal", "label": "③ 언리얼",
     "action": "언리얼 연결 확인",
     "todo": "임포트·배치 단계에서 필요. 지금은 상태 확인만(에디터는 나중에 켜도 됨)."},
]
# 항목 이름 → 어느 단계에서 필요한지
# CUDA/venv 는 기반(초기 설치), Blender 는 분석·블록아웃용이라 기반의 선택 항목.
NAME_STAGE = {
    "python (py 포함)": "base", "node": "base", "git": "base", "uv": "base",
    "CUDA / GPU (nvidia-smi)": "base", "PyTorch (GPU)": "base",
    "Blender (선택·분석)": "base",
    "FLUX.2 모델 (로컬)": "image", "OPENAI_API_KEY": "image",
    "Hunyuan3D-2 준비 (레포+모델)": "mesh", "RODIN_API_KEY (Hyper3D)": "mesh",
    "Unreal Engine": "unreal", "unrealclaude MCP 등록": "unreal",
    "Blender MCP 등록": "unreal",
    "Unreal 에디터 실행중": "unreal", "REST :3000 (execute_script)": "unreal",
}

# 미설치 항목 설치 가이드 (마크다운). 프론트에서 '설치' 버튼 → 모달로 표시.
GUIDES = {
    "python (py 포함)": "### Python 설치\n1. https://python.org 에서 3.11+ 설치\n2. 설치 시 **py 런처 포함**, **Add to PATH** 체크\n3. 확인: `py -3 --version`",
    "node": "### Node.js 설치\n1. https://nodejs.org (LTS)\n2. 확인: `node --version`\n\nMCP 브릿지 구동에 필요.",
    "git": "### Git 설치\n1. https://git-scm.com/download/win\n2. 확인: `git --version`",
    "uv": "### uv 설치 (선택)\n```\npip install uv\n```\n파이썬 패키지 관리 가속용.",
    "CUDA / GPU (nvidia-smi)": "### CUDA / GPU 준비\n1. **NVIDIA 드라이버** 최신: https://www.nvidia.com/Download/index.aspx\n2. **CUDA Toolkit** (PyTorch에 맞는 12.x): https://developer.nvidia.com/cuda-downloads\n3. 확인: `nvidia-smi`\n\n로컬 이미지(FLUX)·3D(Hunyuan) 모두 GPU 가속에 필요.",
    "PyTorch (GPU)": "### PyTorch (GPU)  — 로컬 FLUX/Hunyuan 돌릴 때만\n**지금 gpt-image만 쓰고 3D는 나중이면 미뤄도 됩니다.**\n\n메인 파이썬에 바로 설치해도 되고(간단), venv로 격리해도 됩니다.\n```\npip install torch --index-url https://download.pytorch.org/whl/cu121\n```\n격리하려면(권장):\n```\npy -3 -m venv venv && venv\\Scripts\\activate\npip install torch --index-url https://download.pytorch.org/whl/cu121\n```\n확인: `python -c \"import torch;print(torch.cuda.is_available())\"` → True",
    "Blender (선택·분석)": "### Blender (선택 — 분석/블록아웃용)\n1. https://www.blender.org/download/\n\n※ 3D 생성은 Hunyuan이 담당. Blender는 레퍼런스·블록아웃·검수 용도.",
    "FLUX.2 모델 (로컬)": "### FLUX.2 [dev] 모델 받기\n```\npip install -U diffusers transformers accelerate\nhf download black-forest-labs/FLUX.2-dev\n```\n또는 첫 실행 시 자동 다운로드(HF 캐시). 16GB VRAM은 fp8 권장.",
    "OPENAI_API_KEY": "### OpenAI 키 (gpt-image 쓸 때만)\n1. https://platform.openai.com/api-keys 에서 키 발급\n2. 이 화면 **엔진 선택에서 gpt-image → 키 입력 → 저장** 하면 `.env`에 저장됩니다.",
    "Hunyuan3D-2 준비 (레포+모델)": "### Hunyuan3D-2 (로컬 3D)\n```\ngit clone https://github.com/Tencent/Hunyuan3D-2\n```\n- venv에서 의존성 설치(레포 README)\n- 모델 가중치는 첫 실행 시 HF에서 자동 다운로드(수 GB)\n- 경로 지정: 환경변수 `HunyuanDir`",
    "RODIN_API_KEY (Hyper3D)": "### Rodin / Hyper3D 키 (클라우드 3D 쓸 때만)\n1. Hyper3D/Rodin에서 API 키 발급\n2. 3D 엔진 선택에서 **Rodin/Hyper3D → 키 입력 → 저장** 하면 `.env`에 저장됩니다.\n\n※ 로컬 Hunyuan을 쓰면 이 키는 불필요.",
    "Unreal Engine": "### Unreal Engine\n1. Epic Games Launcher → UE 5.x 설치 (프로젝트 버전 고정)\n2. 확인: `C:\\Program Files\\Epic Games\\UE_5.x`",
    "unrealclaude MCP 등록": "### UnrealClaude MCP 등록\n```\nclaude mcp add --scope user unrealclaude -- node <플러그인>\\Resources\\mcp-bridge\\index.js\n```\n`~/.claude.json` 에 등록됨.",
    "Blender MCP 등록": "### Blender MCP 등록 (선택 — 블록아웃/분석)\nBlender를 Claude로 조종해 블록아웃·레퍼런스·검수. **언리얼 임포트·배치 전** 편집 단계에서 사용.\n```\nclaude mcp add --scope user blender -- <blender-mcp 실행 명령>\n```\nBlender 쪽 addon(BlenderMCP)도 켜야 함. 로컬 3D를 Hunyuan만으로 하면 생략 가능.",
    "Unreal 에디터 실행중": "### 언리얼 에디터 실행\n임포트/배치/렌더 단계 전에 프로젝트를 연다. (이미지·3D 단계는 없어도 됨)",
    "REST :3000 (execute_script)": "### REST :3000 열기\n언리얼 에디터 + UnrealClaude 플러그인이 켜지면 :3000 이 열린다. 에디터를 먼저 실행.",
}


# 항목이 어떤 엔진 선택에 의존하는지(dep) — 프론트가 선택에 따라 관련/불필요 판단.
#  always     : 항상
#  local      : 로컬 생성(FLUX or Hunyuan) 하나라도 고르면
#  image:local: 이미지=로컬(FLUX/SD/Qwen)일 때
#  image:cloud: 이미지=gpt-image 일 때
#  mesh:local : 3D=Hunyuan(로컬)일 때
#  mesh:cloud : 3D=Rodin/Hyper3D(클라우드)일 때
DEP = {
    "python (py 포함)": "always", "node": "always", "git": "always", "uv": "always",
    "Blender (선택·분석)": "always",
    "CUDA / GPU (nvidia-smi)": "local", "PyTorch (GPU)": "local",
    "FLUX.2 모델 (로컬)": "image:local", "OPENAI_API_KEY": "image:cloud",
    "Hunyuan3D-2 준비 (레포+모델)": "mesh:local", "RODIN_API_KEY (Hyper3D)": "mesh:cloud",
    "Unreal Engine": "always", "unrealclaude MCP 등록": "always",
    "Blender MCP 등록": "always",
    "Unreal 에디터 실행중": "always", "REST :3000 (execute_script)": "always",
}


def _attach_meta(items):
    for it in items:
        it["stage"] = NAME_STAGE.get(it["name"], "base")
        it["guide"] = GUIDES.get(it["name"], "")
        it["dep"] = DEP.get(it["name"], "always")
    return items


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
    items = [
        {"name": "python (py 포함)", "required": True, "need": "모든 스크립트 실행"},
        {"name": "CUDA / GPU (nvidia-smi)", "required": True, "need": "이미지·3D GPU 가속 — NVIDIA 드라이버+CUDA"},
        {"name": "PyTorch (GPU)", "required": False, "need": "로컬 FLUX/Hunyuan 돌릴 때 필요 · 지금은 미뤄도 됨"},
        {"name": "node", "required": False, "need": "MCP 브릿지 실행"},
        {"name": "git", "required": False, "need": "버전관리 (선택)"},
        {"name": "uv", "required": False, "need": "파이썬 패키지 관리 (선택)"},
        {"name": "Blender (선택·분석)", "required": False, "need": "분석·블록아웃·검수용 (생성 아님)"},
        {"name": "FLUX.2 모델 (로컬)", "required": False, "need": "기본 이미지 엔진 — FLUX.2 [dev] diffusers (HF 캐시)"},
        {"name": "OPENAI_API_KEY", "required": False, "need": "대안 — gpt-image-1 엔진 고를 때만"},
        {"name": "Hunyuan3D-2 준비 (레포+모델)", "required": True, "need": "로컬 3D 생성 — 레포+가중치"},
        {"name": "RODIN_API_KEY (Hyper3D)", "required": False, "need": "클라우드 3D(Rodin/Hyper3D) 쓸 때만"},
        {"name": "Unreal Engine", "required": False, "need": "UE_5.x — 임포트/배치/렌더"},
        {"name": "unrealclaude MCP 등록", "required": True, "need": "언리얼 직접 조종"},
        {"name": "Blender MCP 등록", "required": False, "need": "블록아웃/분석 — 언리얼 임포트·배치 전 편집(선택)"},
        {"name": "Unreal 에디터 실행중", "required": False, "need": "임포트 단계 전에 열 것"},
        {"name": "REST :3000 (execute_script)", "required": False, "need": "에디터+플러그인 서버"},
    ]
    return {"stages": STAGES, "items": _attach_meta(items)}


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
        add(A, "Blender (선택·분석)", len(bl) > 0,
            (", ".join(os.path.basename(x) for x in bl) + " · 분석/블록아웃용") if bl else "선택 — 분석·블록아웃·검수 쓸 때만 (3D 생성은 Hunyuan)")
    except Exception:
        add(A, "Blender (선택·분석)", False, "확인 실패")

    # === B. 이미지 생성 (기본 로컬, gpt-image 선택 시 OpenAI 키) ===
    B = "B. 이미지 생성"
    # 로컬 이미지: FLUX.2 [dev] diffusers 모델 (HF 캐시). 서버 없이 스크립트 실행.
    flux_dir = os.environ.get("VRKIT_FLUX_DIR")
    flux_cands = ([flux_dir] if flux_dir else []) + [
        os.path.join(USER, ".cache", "huggingface", "hub", "models--black-forest-labs--FLUX.2-dev"),
        os.path.join(USER, ".cache", "huggingface", "hub", "models--black-forest-labs--FLUX.1-dev"),
    ]
    flux = next((p for p in flux_cands if p and os.path.isdir(p)), None)
    add(B, "FLUX.2 모델 (로컬)", bool(flux),
        ("가중치 캐시 있음: " + os.path.basename(flux)) if flux
        else "미다운로드 — HF black-forest-labs/FLUX.2-dev (diffusers, fp8). 첫 실행 시 받음",
        required=False)
    key_found, key_where = False, ""
    candidates = []
    if env_file:
        candidates.append(env_file)
    candidates.append(os.path.join(WEB, ".env"))  # 웹에서 저장한 키 우선
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

    # === CUDA/GPU (기반) ===
    gpu = _run(["nvidia-smi", "--query-gpu=name,driver_version", "--format=csv,noheader"], timeout=8)
    gpu_ok = bool(gpu) and "," in gpu and "not found" not in gpu.lower() and "error" not in gpu.lower()
    add("", "CUDA / GPU (nvidia-smi)", gpu_ok,
        ("GPU: " + gpu) if gpu_ok else "nvidia-smi 미검출 — NVIDIA 드라이버+CUDA 설치 필요",
        required=True)

    # === PyTorch (GPU) (기반) — 메인 파이썬 우선, 없으면 venv 후보. 특정 venv 강요 X ===
    hd = hunyuan_dir or os.path.join(USER, "Desktop", "image3d", "Hunyuan3D-2")
    _code = "import torch;print('cuda' if torch.cuda.is_available() else 'cpu')"
    res, where = None, ""
    for cmd, lab in [(["python", "-c", _code], "python"), (["py", "-3", "-c", _code], "py")]:
        r = _run(cmd, timeout=30)
        if r in ("cuda", "cpu"):
            res, where = r, lab
            break
    if res is None:  # 메인에 없으면 venv 후보 탐색
        for c in [os.path.join(hd, "..", "venv", "Scripts", "python.exe"),
                  os.path.join(hd, "venv", "Scripts", "python.exe"),
                  os.path.join(USER, "Desktop", "image3d", "venv", "Scripts", "python.exe")]:
            if os.path.isfile(c):
                r = _run([c, "-c", _code], timeout=30)
                if r in ("cuda", "cpu"):
                    res, where = r, "venv"
                    break
    if res == "cuda":
        add("", "PyTorch (GPU)", True, "GPU 인식 OK (%s)" % where)
    elif res == "cpu":
        add("", "PyTorch (GPU)", False, "torch 있으나 GPU 인식 못함 (%s) — CUDA 빌드 확인" % where)
    else:
        add("", "PyTorch (GPU)", False, "미설치 — 로컬 FLUX/Hunyuan 돌릴 때만 필요(지금은 미뤄도 됨)")

    # === ② 3D 생성: Hunyuan3D-2 준비 (레포+모델 통합) ===
    repo = os.path.isdir(hd)
    hf = os.path.join(USER, ".cache", "huggingface", "hub", "models--tencent--Hunyuan3D-2")
    hy = os.path.join(USER, ".cache", "hy3dgen")
    model = os.path.isdir(hf) or os.path.isdir(hy)
    both = repo and model
    if both:
        detail = "레포+모델 준비됨"
    elif repo and not model:
        detail = "레포 있음 · 모델 미다운로드(첫 실행 시 받음)"
    elif model and not repo:
        detail = "모델 캐시 있음 · 레포 없음 — git clone 필요"
    else:
        detail = "레포·모델 모두 없음 — git clone + 모델 다운로드"
    add("", "Hunyuan3D-2 준비 (레포+모델)", both, detail, required=True)

    # Rodin/Hyper3D 키 (클라우드 3D 대안)
    rk, rk_where = False, ""
    for p in [os.path.join(WEB, ".env"), os.path.join(USER, "Desktop", "bobs_project", "Core-CBT", ".env")]:
        try:
            if os.path.isfile(p):
                with open(p, encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        s = line.strip()
                        if s.startswith("RODIN_API_KEY") and "=" in s and s.split("=", 1)[1].strip():
                            rk, rk_where = True, p
                            break
            if rk:
                break
        except Exception:
            pass
    if not rk and os.environ.get("RODIN_API_KEY"):
        rk, rk_where = True, "환경변수"
    add("", "RODIN_API_KEY (Hyper3D)", rk,
        ("있음 @ " + rk_where + " (값 숨김)") if rk else "없음 — 클라우드 3D(Rodin) 쓸 때만. 3D 엔진에서 Rodin 선택 시 키 입력",
        required=False)

    # === D. 언리얼 조종 (UnrealClaude MCP) ===
    D = "D. 언리얼 (UnrealClaude MCP)"
    cfg = os.path.join(USER, ".claude.json")
    has_unreal = False
    has_blender = False
    try:
        if os.path.isfile(cfg):
            with open(cfg, encoding="utf-8", errors="ignore") as f:
                j = json.load(f)
            names = list((j.get("mcpServers") or {}).keys())
            for pv in (j.get("projects") or {}).values():
                if isinstance(pv, dict):
                    names += list((pv.get("mcpServers") or {}).keys())
            has_unreal = any("unreal" in n.lower() for n in names)
            has_blender = any("blender" in n.lower() for n in names)
    except Exception:
        pass
    add(D, "unrealclaude MCP 등록", has_unreal,
        ".claude.json에 등록됨" if has_unreal else "미등록 — claude mcp add --scope user unrealclaude ...",
        required=True)
    # Blender MCP — 블록아웃/편집을 Claude로 조종 (언리얼 임포트·배치 전 단계). 선택.
    add(D, "Blender MCP 등록", has_blender,
        ".claude.json에 등록됨" if has_blender else "미등록 — Blender 블록아웃/분석 쓸 때만 (선택)",
        required=False)

    up = _run(["tasklist", "/FI", "IMAGENAME eq UnrealEditor.exe", "/NH"], timeout=8)
    running = bool(up) and "UnrealEditor" in up
    add(D, "Unreal 에디터 실행중", running,
        "실행중 — 임포트/배치/렌더에 필요" if running else "미실행 — 임포트 단계 전에 열 것 (이미지·3D는 가능)")

    p3 = _port_open(3000)
    add(D, "REST :3000 (execute_script)", p3,
        "열림 (플러그인 서버 응답)" if p3 else "닫힘 — 에디터+플러그인 켜야 열림")

    _attach_meta(items)  # 파이프라인 단계(stage) + 설치 가이드(guide) 부착

    total = len(items)
    ok = sum(1 for i in items if i["ok"])
    required_missing = [i["name"] for i in items if i["required"] and not i["ok"]]
    return {"stages": STAGES, "items": items, "ok": ok, "total": total,
            "required_missing": required_missing}
