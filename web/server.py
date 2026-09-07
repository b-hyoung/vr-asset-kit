#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
VR 제작킷 웹 대시보드 — 로컬 서버 (표준 라이브러리 전용, pip 설치 불필요)

역할 (Phase B):
  - 정적 대시보드 서빙 (static/)
  - flow.json (편집 가능한 플로우 정의) 읽기/쓰기
  - projects/<id>/state.json (프로젝트별 실행 상태) 소유 — 단일 진실 원천
  - 게이트 통과는 UI 클릭(POST)으로만 기록 → AI가 스스로 못 넘김 (버그 2 방지)
  - 새 프로젝트는 빈 값에서 시작, 예시는 명시적 클릭으로만 복사 (버그 1 방지)
  - 하네스 문서 실시간 조회 (우측 패널)
  - SSE 로 상태 변경 실시간 푸시

실행:  python server.py           (기본 포트 8787)
       python server.py 9000      (포트 지정)
"""
import json
import os
import sys
import time
import threading
import subprocess
import shutil
import urllib.request as _urlreq
import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, unquote

try:
    import diag  # 환경·도구 진단 (check-env.ps1 포팅)
except Exception:
    diag = None

BASE = os.path.dirname(os.path.abspath(__file__))          # .../vr-harness/web
HARNESS_ROOT = os.path.dirname(BASE)                        # .../vr-harness
STATIC = os.path.join(BASE, "static")
FLOW_PATH = os.path.join(BASE, "flow.json")
ENGINES_PATH = os.path.join(BASE, "engines.json")
LIGHTING_PATH = os.path.join(BASE, "lighting.json")   # 조명 프리셋 표(노을은 그중 하나일 뿐)
EXAMPLES_DIR = os.path.join(BASE, "examples")
PROJECTS_DIR = os.path.join(BASE, "projects")

_lock = threading.Lock()
# 프로젝트별 상태 버전 (SSE 가 이 값 변화를 감지해 푸시)
_versions = {}

# ---------- GPU 감지 + 모델별 "이 PC 기준" 판정 ----------
# 어제 크래시(튕김)의 원인: 총 VRAM이 아니라 '가용(free) VRAM'이 실사용 한도.
# texgen peak가 가용 VRAM에 닿으면 OOM → 크래시. 그래서 free 기준으로 판정한다.
_GPU_CACHE = {"t": 0, "info": None}


def _gpu_info():
    """nvidia-smi로 실제 GPU/VRAM 감지 (5초 캐시). 없으면 None."""
    now = time.time()
    if _GPU_CACHE["info"] is not None and now - _GPU_CACHE["t"] < 5:
        return _GPU_CACHE["info"]
    info = None
    exe = shutil.which("nvidia-smi")
    if exe:
        try:
            out = subprocess.run(
                [exe, "--query-gpu=name,memory.total,memory.free",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=6)
            line = (out.stdout or "").strip().splitlines()
            if line:
                name, tot, free = [x.strip() for x in line[0].split(",")[:3]]
                info = {"gpu": name,
                        "vram_total_gb": round(float(tot) / 1024, 1),
                        "vram_free_gb": round(float(free) / 1024, 1),
                        "has_gpu": True}
        except Exception:
            info = None
    if info is None:
        info = {"gpu": None, "vram_total_gb": None, "vram_free_gb": None, "has_gpu": False}
    _GPU_CACHE.update(t=now, info=info)
    return info


def _verdict(req_direct, req_offload_min, free, total):
    """모델 VRAM 요구를 이 PC 가용/총 VRAM과 비교해 판정.
    req_direct: VRAM 직접 로드에 필요한 대략치(GB) — 이하면 빠름.
    req_offload_min: cpu offload로도 최소 필요한 VRAM(GB) — peak 개념. 이게 free를 넘으면 위험.
    반환: (badge, level)  level: rec|ok|risk|no"""
    if not free:
        return ("GPU 미감지", "no")
    # 여유를 두고 판정 (데스크톱/기타 점유 고려)
    if req_direct <= free - 1.0:
        return ("이PC 추천 ✅", "rec")           # 직접 로드, 빠름
    if req_offload_min <= free - 1.5:
        return ("이PC 가능(오프로드·느림) ⚠️", "ok")  # RAM 오프로드로 실행
    if req_offload_min <= (total or 0):
        return ("이PC 위험(OOM 가능) ⛔", "risk")     # peak가 가용 근처 → 어제 크래시 유형
    return ("이PC 불가 ✖", "no")


def _is_image_repo(repo):
    """models.json 의 image 카탈로그에 있는 저장소인가 (직접 입력한 것도 image 로 간주)."""
    cat = read_json(os.path.join(BASE, "models.json"), {}) or {}
    mesh = {(m.get("repo") or "").lower() for m in (cat.get("mesh") or [])}
    return (repo or "").lower() not in mesh


def _diffusers_complete(repo):
    """이 모델을 **실제로 로드할 수 있는가**를 오프라인 해석으로 확인한다.

    캐시 크기나 .incomplete 유무는 믿을 수 없다 — 중단된 옛 다운로드의 고아 조각이
    남으면 영원히 '미완성'으로 보이고, 반대로 조각이 없어도 파일이 빌 수 있다.
    DiffusionPipeline.download(local_files_only=True) 는 빠진 파일을 정확히 잡아낸다.

    gen_spectrum.py 가 fp16 변형을 먼저 로드하므로 여기서도 같은 순서로 본다.
    반환: True(쓸 수 있음) / False(파일 빔) / None(diffusers 파이프라인이 아님 → 판정 보류)
    """
    try:
        from diffusers import DiffusionPipeline
        from huggingface_hub.errors import IncompleteSnapshotError
    except Exception:
        return None
    saw_incomplete = False
    for variant in ("fp16", None):
        try:
            DiffusionPipeline.download(repo, variant=variant, local_files_only=True)
            return True
        except IncompleteSnapshotError:
            saw_incomplete = True          # 파이프라인은 맞는데 파일이 빔
        except Exception:
            pass                           # model_index.json 없음 등 → 파이프라인 아님
    return False if saw_incomplete else None


def _annotate_models(catalog, info):
    """models.json에 이 PC 기준 판정 태그를 맨 앞에 주입 (원본 미변경, 사본 반환)."""
    import copy
    free = info.get("vram_free_gb")
    total = info.get("vram_total_gb")
    cat = copy.deepcopy(catalog)
    for m in cat.get("image", []):
        rd = m.get("req_direct_gb")
        ro = m.get("req_offload_gb", rd)
        if rd is None:
            continue
        badge, lvl = _verdict(rd, ro, free, total)
        m["verdict"] = lvl
        m.setdefault("tags", []).insert(0, badge)
    for m in cat.get("mesh", []):
        # 메시는 shape/texgen 따로 판정 (texgen이 병목)
        sg = m.get("shape_gb"); tg = m.get("texgen_gb")
        if sg is None:
            continue
        sb, sl = _verdict(sg, sg, free, total)
        tb, tl = _verdict(tg or sg, tg or sg, free, total)
        m["verdict"] = tl if tl in ("risk", "no") else sl
        m.setdefault("tags", []).insert(0, "texgen %s" % tb.replace("이PC ", ""))
        m["tags"].insert(0, "shape %s" % sb.replace("이PC ", ""))
    cat["_gpu"] = info
    return cat


# ---------- 그 자리 설치 (화이트리스트만) ----------
# 안전: 미리 정의된 명령만 실행. CUDA/UE 등 무거운 GUI 설치는 제외(가이드만).
_PYEXE = [sys.executable] if sys.executable else ["py", "-3"]
INSTALL_CMDS = {
    "uv": [_PYEXE + ["-m", "pip", "install", "-U", "uv"]],
    # ★ cu121 인덱스에는 torch 2.5.1 까지밖에 없다 → 최신 torch 를 조용히 다운그레이드시켜
    #   diffusers/transformers 와 깨진다. 실측(2026-09) 기준 cu126 에 최신 빌드가 있다.
    "PyTorch (GPU)": [_PYEXE + ["-m", "pip", "install", "-U", "torch",
                                "--index-url", "https://download.pytorch.org/whl/cu126"]],
    "node": [["winget", "install", "-e", "--id", "OpenJS.NodeJS.LTS",
              "--accept-package-agreements", "--accept-source-agreements"]],
    "git": [["winget", "install", "-e", "--id", "Git.Git",
             "--accept-package-agreements", "--accept-source-agreements"]],
    "Blender (선택·분석)": [["winget", "install", "-e", "--id", "BlenderFoundation.Blender",
                          "--accept-package-agreements", "--accept-source-agreements"]],
    "Unreal Engine": [["winget", "install", "-e", "--id", "EpicGames.EpicGamesLauncher",
                       "--accept-package-agreements", "--accept-source-agreements"]],
}
INSTALL_STATE = {}          # item -> {"running":bool, "code":int|None, "lines":[...]}
_install_lock = threading.Lock()

# 설치/다운로드 작업 파일 (서버 재시작해도 상태가 남도록 **디스크**에 둔다)
INSTALL_DIR = os.path.join(BASE, ".install")
INSTALL_RUNNER = os.path.join(BASE, "install_runner.py")


def _install_slug(item):
    """item("model:org/name" 등)을 파일명으로 쓸 수 있게 만든다."""
    return "".join(c if (c.isalnum() or c in "._-") else "_" for c in item)[:120]


def _install_paths(item):
    s = _install_slug(item)
    return (os.path.join(INSTALL_DIR, s + ".job.json"),
            os.path.join(INSTALL_DIR, s + ".log"),
            os.path.join(INSTALL_DIR, s + ".status.json"))


def _install_read(item):
    """디스크에서 진행 상태를 읽는다. 없으면 None."""
    _job, log_p, st_p = _install_paths(item)
    try:
        with open(st_p, encoding="utf-8") as f:
            st = json.load(f)
    except Exception:
        return None
    lines = []
    try:
        with open(log_p, encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()[-500:]
    except Exception:
        pass
    # 창을 강제로 닫는 등 러너가 죽으면 running=True 로 남는다 → 실제 pid 로 확인
    if st.get("running") and not _pid_alive(st.get("pid")):
        st["running"] = False
        st["code"] = st.get("code") if st.get("code") is not None else -1
        lines.append("(설치 창이 종료되어 중단된 것으로 처리합니다)")
    return {"running": bool(st.get("running")), "code": st.get("code"), "lines": lines}


def _pid_alive(pid):
    if not pid:
        return False
    try:
        out = subprocess.run(["tasklist", "/FI", "PID eq %d" % int(pid)],
                             capture_output=True, text=True, timeout=5).stdout
        return str(pid) in out
    except Exception:
        return False


def _spawn_install(item, cmds):
    """설치를 **별도 콘솔 창의 독립 프로세스**로 띄운다.
    서버 재시작으로 다운로드가 죽던 문제(daemon 스레드) 때문에 분리했다."""
    os.makedirs(INSTALL_DIR, exist_ok=True)
    job_p, log_p, st_p = _install_paths(item)
    with open(job_p, "w", encoding="utf-8") as f:
        json.dump({"item": item, "cmds": cmds, "log": log_p, "status": st_p}, f)
    # 시작 상태를 서버가 먼저 찍어둔다 (러너가 뜨기 전 UI 공백 방지)
    with open(st_p, "w", encoding="utf-8") as f:
        json.dump({"item": item, "running": True, "code": None, "pid": None, "t": time.time()}, f)

    env = os.environ.copy()
    env.update(_load_env_vars())
    env["PYTHONIOENCODING"] = "utf-8"
    cmd = (_PYEXE if _PYEXE else ["py"]) + [INSTALL_RUNNER, job_p]
    kwargs = {"env": env, "cwd": BASE, "close_fds": True}
    if os.name == "nt":
        # 새 콘솔 창 = 사용자가 진행을 직접 보고, 끝나면 창이 스스로 닫힌다
        kwargs["creationflags"] = subprocess.CREATE_NEW_CONSOLE
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen(cmd, **kwargs)

def _handoff_msg(pid, st):
    """Claude 에게 넘길 지시문 — 값은 state 에서만 만든다(클라이언트가 준 문자열을 실행하지 않는다)."""
    inp = st.get("inputs") or {}
    lid = inp.get("lighting") or ""
    if lid:
        light = ("- 조명: state.json inputs.lighting = %r 만 적용. 임의로 다른 시간대로 바꾸지 말 것." % lid)
    else:
        light = "- 조명: 아직 선택 안 됨 → 조명을 건드리지 말 것. 노을을 임의로 넣지 마라(사용자가 웹에서 고른다)."
    refs = st.get("ref_images") or []
    ref_line = ""
    if refs:
        ref_line = ("- 배경 참고 이미지: %s (씬에 합성하지 말고 에셋·배치의 기준으로만 쓸 것)"
                    % refs[0].get("path"))
    lines = [
        "이 VR 프로젝트를 이어서 진행해줘.",
        "- 계약서: web/AGENT_CONTRACT.md (먼저 읽을 것)",
        "- 상태: web/projects/%s/state.json — 값은 여기서만 읽는다" % pid,
        light,
    ]
    if ref_line:
        lines.append(ref_line)
    lines.append("웹에서 게이트 확정은 끝났다. 확정된 값으로 "
                 "[에셋 제작(이미지→3D) → 블렌더 터칭(안 어울리는 부분 정리) → "
                 "언리얼 임포트 → 배치 → 조명 → export] 를 수행해줘. "
                 "게이트가 안 열린 단계는 멈추고 웹에서 확정해 달라고 말해줘.")
    return "\n".join(lines)


def _spawn_claude(msg):
    """새 콘솔 창에서 Claude Code 를 지시문과 함께 띄운다.
    복사·붙여넣기 단계를 없애려는 것 — 사용자가 옮겨 적다 빠뜨리는 일이 실제로 있었다."""
    exe = shutil.which("claude")
    if not exe:
        raise RuntimeError("Claude Code 를 찾을 수 없습니다 (npm install -g @anthropic-ai/claude-code)")
    kwargs = {"cwd": HARNESS_ROOT, "close_fds": True}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_CONSOLE
    else:
        kwargs["start_new_session"] = True
    # 리스트로 넘긴다 — 문자열 조립을 하지 않아 따옴표/특수문자로 명령이 갈라지지 않는다.
    subprocess.Popen([exe, msg], **kwargs)


# 강도 스펙트럼 4장 생성 (선택 엔진: gpt-image=클라우드 / 그 외=로컬 diffusers)
SPECTRUM_STATE = {"running": False, "images": None, "error": None, "log": [],
                  "cancel": False, "cancelled": False}


class _Cancelled(Exception):
    """사용자가 생성을 취소했다 (실패가 아니다 — 에러로 보고하지 않는다)."""
_INTENS = [
    ("은은", "은은한 낮은대비 파스텔, soft muted"),
    ("중간", "자연스러운 사실적, natural"),
    ("뚜렷", "선명한 높은대비, vivid bold"),
    ("하이", "강렬한 하이대비 발광, hyper dramatic"),
]


def _build_prompt(topic, bg, style, max_words=60):
    """CLIP 77토큰(약 60단어) 안에서 스타일이 잘려나가지 않게 배경을 잘라 맞춘다.
    스타일이 뒤에 있어 그냥 이어붙이면 배경이 길 때 스타일이 통째로 truncate 된다."""
    # 번역기가 배경 앞에 주제를 그대로 되풀이하는 경우가 잦다 → 토큰만 먹으므로 지운다.
    t_norm = (topic or "").strip().lower().rstrip(",")
    b_norm = (bg or "").strip()
    if t_norm and b_norm.lower().startswith(t_norm):
        bg = b_norm[len(t_norm):].lstrip(" ,")
    tail = "%s, concept art" % style
    room = max_words - len(topic.split()) - len(tail.split())
    bw = bg.split()
    if room > 0 and len(bw) > room:
        bg = " ".join(bw[:room])
    return "%s, %s, %s" % (topic, bg, tail)


def _observe_image(key, b64, ext):
    """배경 그림에 보이는 것을 한국어 명사구로 뽑아낸다.

    왜 두 번 부르나 (실측 2026-09):
      그림 + "주제: X" 를 한 번에 주면 gpt-4o-mini 는 **글자 주제만 따르고 그림을 무시**한다.
      (그림=대장간 / 글자=어촌마을 로 충돌시켜 확인 — 결과는 전부 어촌마을이었다)
      반면 "이 그림에 보이는 것을 나열하라"는 정확히 답한다. 그래서 관찰을 먼저 글로 바꾼 뒤
      그 글을 근거로 에셋을 뽑는다.
    """
    mime = "image/jpeg" if ext in ("jpg", "jpeg") else "image/%s" % (ext or "png")
    body = json.dumps({
        "model": "gpt-4o-mini",
        "messages": [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": "data:%s;base64,%s" % (mime, b64)}},
            {"type": "text", "text": ("이 그림에 실제로 보이는 사물·재질·구조·빛을 "
                                      "한국어 명사구로 나열하라. 최대 15개, 쉼표로만 구분. "
                                      "설명 문장·추측 금지.")},
        ]}],
        "temperature": 0,
    }).encode()
    req = _urlreq.Request("https://api.openai.com/v1/chat/completions", data=body,
                          headers={"Authorization": "Bearer " + key,
                                   "Content-Type": "application/json"})
    out = json.load(_urlreq.urlopen(req, timeout=90))
    return (out["choices"][0]["message"]["content"] or "").strip()


def _spectrum_prompt(topic, bg, style):
    # gpt-image 는 토큰 여유가 크므로 원문을 더 살린다.
    return ("%s, %s, %s, concept art" % (topic, bg, style))[:900]


# 로컬 SDXL은 영어 CLIP → 한글 주제 이해 못함. OpenAI로 영어 번역(캐시).
_TRANSLATE_CACHE = {}
_STYLE_EN = {
    "은은": "soft muted low-contrast pastel lighting",
    "중간": "natural realistic medium contrast",
    "뚜렷": "vivid high-contrast bold colors",
    "하이": "hyper vivid dramatic glowing high-contrast",
}


def _has_korean(s):
    return any("가" <= ch <= "힣" for ch in (s or ""))


def _translate_en(topic, bg):
    key = (topic or "") + "|" + (bg or "")
    if key in _TRANSLATE_CACHE:
        return _TRANSLATE_CACHE[key]
    if not (_has_korean(topic) or _has_korean(bg)):
        _TRANSLATE_CACHE[key] = (topic, bg)
        return topic, bg
    ok = _openai_key()
    if not ok:
        return topic, bg
    try:
        # ★ 예전엔 "간결 번역"이라 시켜서 191자 배경이 3단어로 뭉개졌다.
        #   사용자가 적은 구체 요소(쇳물·물레방아·풀무 등)가 전부 사라져
        #   "주제·배경을 안 읽은 그림"이 나온다. CLIP 77토큰 ≈ 영어 60단어라 여유가 있다.
        prompt = ("다음을 이미지 생성 프롬프트용 영어로 옮겨라. JSON만 출력.\n"
                  "규칙:\n"
                  "- topic: 3~8단어 명사구.\n"
                  "- background: 쉼표로 나열한 영어 명사구, 최대 35단어. "
                  "원문의 구체적 시각 요소(사물·재질·빛·동작)를 최대한 살려라.\n"
                  "- '시각적 포인트' 같은 메타 표현과 설명문은 빼고 보이는 것만 적어라.\n"
                  "- 조명/대비/색조 같은 스타일 단어는 넣지 마라(따로 붙는다).\n"
                  '{"topic":"","background":""}\n주제: %s\n배경: %s' % (topic, bg))
        rb = json.dumps({"model": "gpt-4o-mini", "messages": [{"role": "user", "content": prompt}],
                         "response_format": {"type": "json_object"}, "temperature": 0.2}).encode()
        req = _urlreq.Request("https://api.openai.com/v1/chat/completions", data=rb,
                              headers={"Authorization": "Bearer " + ok, "Content-Type": "application/json"})
        d = json.loads(json.load(_urlreq.urlopen(req, timeout=30))["choices"][0]["message"]["content"])
        res = (d.get("topic") or topic, d.get("background") or bg)
        _TRANSLATE_CACHE[key] = res
        return res
    except Exception:
        return topic, bg


# 모델을 켜둔 채 재사용 (매번 재로딩 방지 → 빠름·GPU 활용)
_PIPE_CACHE = {"repo": None, "pipe": None}


def _get_pipe(repo, st):
    if _PIPE_CACHE["repo"] == repo and _PIPE_CACHE["pipe"] is not None:
        st["log"].append("모델 캐시 사용(로딩 생략): " + repo)
        return _PIPE_CACHE["pipe"]
    import torch
    from diffusers import AutoPipelineForText2Image
    # 이전 모델 해제
    if _PIPE_CACHE["pipe"] is not None:
        try:
            _PIPE_CACHE["pipe"] = None
            torch.cuda.empty_cache()
        except Exception:
            pass
    # 크기 vs 여유 VRAM → 오프로드 결정
    size_gb = None
    try:
        from huggingface_hub import scan_cache_dir
        for r in scan_cache_dir().repos:
            if r.repo_id.lower() == repo.lower():
                size_gb = r.size_on_disk / 1e9
                break
    except Exception:
        pass
    free_gb = torch.cuda.mem_get_info()[0] / 1e9 if torch.cuda.is_available() else 0
    use_offload = bool(size_gb and free_gb and size_gb * 1.15 > free_gb)
    st["log"].append("모델 로딩: %s (~%.1fGB, 여유 %.1fGB → %s)" % (
        repo, size_gb or -1, free_gb, "오프로드" if use_offload else "GPU 직접"))
    pipe = AutoPipelineForText2Image.from_pretrained(
        repo, torch_dtype=(torch.float16 if torch.cuda.is_available() else torch.float32))
    if torch.cuda.is_available():
        if use_offload:
            pipe.enable_model_cpu_offload()
        else:
            try:
                pipe.to("cuda")
            except RuntimeError:
                pipe.enable_model_cpu_offload()
    for _m in ("enable_attention_slicing", "enable_vae_slicing", "enable_vae_tiling"):
        try:
            getattr(pipe, _m)()
        except Exception:
            pass
    try:
        pipe.set_progress_bar_config(disable=True)
    except Exception:
        pass
    _PIPE_CACHE.update({"repo": repo, "pipe": pipe})
    return pipe


def _run_spectrum(engine, repo, topic, bg, pid=None):
    st = SPECTRUM_STATE
    st["images"], st["error"], st["log"] = None, None, []
    try:
        if engine and "gpt-image" in engine.lower():
            key = _openai_key()
            if not key:
                st["error"] = "OpenAI 키 필요"; return
            imgs = []
            for name, style in _INTENS:
                if st.get("cancel"):
                    raise _Cancelled()
                st["log"].append("gpt-image 생성: " + name)
                rb = json.dumps({"model": "gpt-image-1", "prompt": _spectrum_prompt(topic, bg, style),
                                 "size": "1024x1024", "quality": "low", "n": 1}).encode()
                req = _urlreq.Request("https://api.openai.com/v1/images/generations", data=rb,
                                      headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
                out = json.load(_urlreq.urlopen(req, timeout=120))
                imgs.append({"name": name, "b64": out["data"][0]["b64_json"]})
            st["images"] = imgs
        else:
            # 로컬 diffusers 생성 (모델 캐시로 warm 유지 → 빠름)
            if not repo:
                st["error"] = "로컬 모델(repo) 미선택"; return
            import io as _io, base64 as _b64, torch
            os.environ.update(_load_env_vars())   # HF 로그인 등
            try:
                pipe = _get_pipe(repo, st)
            except Exception as e:
                st["error"] = "모델 로드 실패: " + str(e)[:150]; return
            rl = repo.lower()
            fast = ("schnell" in rl or "turbo" in rl or "lightning" in rl)
            steps = 4 if fast else 20
            # 한글 주제 → 영어(로컬 CLIP 이해용)
            en_topic, en_bg = _translate_en(topic, bg)
            if (en_topic, en_bg) != (topic, bg):
                st["log"].append("프롬프트 영어화: %s / %s" % (en_topic, en_bg))
            imgs = []

            # 스텝마다 취소 확인 — 한 장이 오래 걸려도(오프로드 시 수 분) 바로 멈춘다
            def _step_cb(_pipe, _step, _ts, cb_kw):
                if st.get("cancel"):
                    raise _Cancelled()
                return cb_kw

            for name, style in _INTENS:
                if st.get("cancel"):
                    raise _Cancelled()
                st["log"].append("생성: " + name)
                kw = {"num_inference_steps": steps, "height": 512, "width": 512}
                if fast:
                    kw["guidance_scale"] = 0.0
                prompt = _build_prompt(en_topic, en_bg, _STYLE_EN.get(name, style))
                if name == _INTENS[0][0]:
                    st["log"].append("최종 프롬프트 예시: " + prompt)
                try:
                    with torch.inference_mode():
                        try:
                            out = pipe(prompt, callback_on_step_end=_step_cb, **kw)
                        except TypeError:
                            # 이 콜백을 지원하지 않는 파이프라인 → 장 단위 취소로 폴백
                            out = pipe(prompt, **kw)
                except _Cancelled:
                    torch.cuda.empty_cache()
                    raise
                except Exception as e:
                    torch.cuda.empty_cache()
                    st["error"] = "'%s' 생성 실패: %s" % (name, str(e)[:120]); return
                im = out.images[0]
                buf = _io.BytesIO(); im.save(buf, format="PNG")
                imgs.append({"name": name, "b64": _b64.b64encode(buf.getvalue()).decode()})
            st["images"] = imgs
    except _Cancelled:
        st["cancelled"] = True
        st["log"].append("사용자가 취소했습니다 (완료된 장이 없으면 저장되지 않음)")
    except Exception as e:
        st["error"] = str(e)[:200]
    finally:
        st["running"] = False
        st["cancel"] = False
        # 생성된 이미지를 프로젝트 state에 저장 (새로고침·확정취소해도 유지, 재생성/재과금 방지)
        if pid and st.get("images"):
            try:
                s = load_state(pid)
                if s is not None:
                    s["spectrum"] = {"repo": repo, "engine": engine, "topic": topic,
                                     "background": bg, "images": st["images"]}
                    save_state(pid, s)
            except Exception:
                pass


def _env_file_candidates():
    """키(.env) 탐색 후보 — 특정 프로젝트 경로 하드코딩 금지.
    우선순위: VRKIT_ENV_FILE(환경변수 경로) → web/.env → ~/.vrkit/.env"""
    c = []
    if os.environ.get("VRKIT_ENV_FILE"):
        c.append(os.environ["VRKIT_ENV_FILE"])
    c.append(os.path.join(BASE, ".env"))
    c.append(os.path.join(os.path.expanduser("~"), ".vrkit", ".env"))
    return c


def _key_from(name):
    """환경변수 우선, 없으면 .env 후보들에서 name 읽기."""
    if os.environ.get(name):
        return os.environ[name]
    for p in _env_file_candidates():
        try:
            if p and os.path.isfile(p):
                for line in open(p, encoding="utf-8", errors="ignore"):
                    s = line.strip()
                    if s.startswith(name) and "=" in s:
                        v = s.split("=", 1)[1].strip().strip('"').strip("'")
                        if v:
                            return v
        except Exception:
            pass
    return None


def _openai_key():
    return _key_from("OPENAI_API_KEY")


def _load_env_vars():
    """web/.env 를 dict 로 파싱 (설치 subprocess 에 주입 — HF_TOKEN 등)."""
    d = {}
    envp = os.path.join(BASE, ".env")
    try:
        if os.path.exists(envp):
            for line in open(envp, encoding="utf-8", errors="ignore"):
                s = line.strip()
                if "=" in s and not s.startswith("#"):
                    k, v = s.split("=", 1)
                    d[k.strip()] = v.strip()
    except Exception:
        pass
    # HF 토큰은 login(표준 토큰파일)으로 관리 → 무효한 .env 값이 덮지 않게 제외
    d.pop("HF_TOKEN", None)
    d.pop("HUGGING_FACE_HUB_TOKEN", None)
    return d


def _run_install(item, cmds):
    st = INSTALL_STATE[item]
    env = os.environ.copy()
    env.update(_load_env_vars())
    try:
        for cmd in cmds:
            st["lines"].append("$ " + " ".join(cmd))
            try:
                p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                     text=True, encoding="utf-8", errors="replace", env=env)
            except FileNotFoundError:
                st["lines"].append("실행기 없음: %s (수동 설치 필요)" % cmd[0])
                st["code"] = -1
                return
            for line in p.stdout:
                st["lines"].append(line.rstrip())
                del st["lines"][:-500]   # 최근 500줄만 보관
            p.wait()
            if p.returncode != 0:
                st["code"] = p.returncode
                return
        st["code"] = 0
    except Exception as e:
        st["lines"].append("ERROR: " + repr(e))
        st["code"] = -1
    finally:
        st["running"] = False


# ---------- 유틸 ----------
def now_iso():
    return datetime.datetime.now().isoformat(timespec="seconds")


def read_json(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def bump_version(pid):
    _versions[pid] = _versions.get(pid, 0) + 1


def state_path(pid):
    return os.path.join(PROJECTS_DIR, pid, "state.json")


def load_state(pid):
    st = read_json(state_path(pid))
    if st is not None:
        _sync_steps_with_flow(pid, st)
    return st


def _sync_steps_with_flow(pid, state):
    """flow.json 에 단계가 추가·개명되면 옛 프로젝트의 state 에 그 칸을 만들어 준다.

    없으면 프론트가 그 단계를 '잠김'으로만 그려서 사용자가 영영 못 연다
    (실측: dusk → lighting 개명 때). 옛 키(dusk 등)는 지우지 않고 그냥 둔다.
    """
    flow = read_json(FLOW_PATH, {"steps": []})
    added = [s["id"] for s in flow.get("steps", []) if s["id"] not in (state.get("steps") or {})]
    if not added:
        return state
    for s in flow.get("steps", []):
        state.setdefault("steps", {}).setdefault(s["id"], {
            "status": "locked", "gate": bool(s.get("gate")),
            "gate_passed": False, "passed_by": None, "passed_at": None,
        })
    state.setdefault("audit_log", []).append(
        {"t": now_iso(), "action": "flow_sync", "detail": "새 단계 추가: " + ", ".join(added)})
    recompute_progress(state)
    save_state(pid, state)
    return state


def save_state(pid, state):
    write_json(state_path(pid), state)
    bump_version(pid)


# ---------- 초기 상태 생성 (빈 값에서 시작) ----------
def _torch_cuda():
    """설치된 torch 가 GPU 를 실제로 쓸 수 있나. (있음/없음/torch 자체가 없음)"""
    try:
        code = ("import torch,json;"
                "print(json.dumps({'ok':bool(torch.cuda.is_available()),"
                "'ver':torch.__version__}))")
        out = subprocess.run(_PYEXE + ["-c", code], capture_output=True, text=True, timeout=60)
        return json.loads((out.stdout or "").strip().splitlines()[-1])
    except Exception:
        return {"ok": False, "ver": None}


def _default_engines():
    """engines.json 의 default/default_repo 를 새 프로젝트 시작값으로 만든다.
    로컬 모델 우선 — 클라우드는 키가 있어야 하고, 팀에 나눠줄 때 과금 주체가 애매해진다."""
    reg = read_json(os.path.join(BASE, "engines.json"), {}) or {}
    roles = reg.get("roles") or {}
    # role 이름과 state 키가 1:1이 아니라 명시적으로 맞춘다 (mesh_3d -> mesh_repo)
    repo_key = {"image": "image_repo", "mesh_3d": "mesh_repo"}
    out = {}
    for role, spec in roles.items():
        if spec.get("default"):
            out[role] = spec["default"]
        if spec.get("default_repo") and role in repo_key:
            out[repo_key[role]] = spec["default_repo"]
    return out


def _origin():
    """이 프로젝트를 만든 PC 표식. 값 자체가 목적이 아니라 '같은 PC인가'만 본다."""
    import getpass, socket
    try:
        return {"host": socket.gethostname(), "user": getpass.getuser()}
    except Exception:
        return {"host": None, "user": None}


def empty_state_from_flow(pid, name):
    flow = read_json(FLOW_PATH, {"steps": []})
    steps = {}
    first = None
    for i, s in enumerate(flow.get("steps", [])):
        sid = s["id"]
        if first is None:
            first = sid
        steps[sid] = {
            "status": "awaiting_user" if i == 0 else "locked",
            "gate": bool(s.get("gate")),
            "gate_passed": False,
            "passed_by": None,
            "passed_at": None,
        }
    return {
        "project_id": pid,
        "name": name or pid,
        "created_at": now_iso(),
        "current_step": first,
        # ★ 어느 PC에서 만들어졌는지 — 폴더째 넘겨받았을 때 남의 작업을 내 것처럼 열지 않으려고 쓴다.
        "origin": _origin(),
        # ★ 모든 입력은 빈 값에서 시작 — 예시/이전맥락 자동 유입 없음
        "inputs": {},
        # ★ 엔진·모델은 빈 값으로 두지 않는다 — 처음 받은 사람이 뭘 골라야 할지 모른 채 멈춘다.
        #   주제·에셋 같은 '내용'은 여전히 빈 값에서 시작한다(예시 누출 방지). 여기 심는 건 도구 선택뿐.
        "engine_choices": _default_engines(),
        "steps": steps,
        "audit_log": [{"t": now_iso(), "action": "create", "detail": "빈 프로젝트 생성"}],
    }


def recompute_progress(state):
    """게이트 통과 여부에 따라 다음 단계 잠금 해제. current_step 갱신."""
    flow = read_json(FLOW_PATH, {"steps": []})
    order = [s["id"] for s in flow.get("steps", [])]
    prev_passed = True
    current = order[0] if order else None
    for sid in order:
        st = state["steps"].setdefault(sid, {"gate": False, "gate_passed": False})
        if not prev_passed:
            st["status"] = "locked"
            continue
        if st.get("gate_passed"):
            st["status"] = "done"
        else:
            st["status"] = "awaiting_user" if st.get("gate") else "active"
            current = sid
        # 다음 단계로 넘어갈 수 있는가?
        if st.get("gate"):
            prev_passed = bool(st.get("gate_passed"))
        else:
            prev_passed = True
    state["current_step"] = current
    return state


# ---------- HTTP 핸들러 ----------
class Handler(BaseHTTPRequestHandler):
    server_version = "VRKitWeb/0.1"

    def log_message(self, fmt, *args):
        sys.stderr.write("[web] " + (fmt % args) + "\n")

    # --- 응답 헬퍼 ---
    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _text(self, text, code=200, ctype="text/plain; charset=utf-8"):
        body = text.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _file(self, path):
        if not os.path.isfile(path):
            return self._text("Not found: " + path, 404)
        ext = os.path.splitext(path)[1].lower()
        ctype = {
            ".html": "text/html; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".js": "application/javascript; charset=utf-8",
            ".json": "application/json; charset=utf-8",
            ".svg": "image/svg+xml",
            ".png": "image/png",
        }.get(ext, "application/octet-stream")
        with open(path, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _body_json(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return {}

    # --- GET ---
    def do_GET(self):
        u = urlparse(self.path)
        p = u.path
        q = parse_qs(u.query)

        if p == "/" or p == "/index.html":
            return self._file(os.path.join(STATIC, "index.html"))
        if p.startswith("/static/"):
            rel = p[len("/static/"):]
            return self._file(os.path.join(STATIC, rel))

        if p == "/api/flow":
            return self._json(read_json(FLOW_PATH, {"steps": []}))
        if p == "/api/engines":
            return self._json(read_json(ENGINES_PATH, {}))
        if p == "/api/lighting":
            return self._json(read_json(LIGHTING_PATH, {"presets": []}))
        if p == "/api/models":
            cat = read_json(os.path.join(BASE, "models.json"), {"image": []})
            return self._json(_annotate_models(cat, _gpu_info()))
        if p == "/api/gpu":
            return self._json(_gpu_info())
        if p == "/api/examples":
            names = []
            if os.path.isdir(EXAMPLES_DIR):
                for fn in sorted(os.listdir(EXAMPLES_DIR)):
                    if fn.endswith(".json"):
                        names.append(fn[:-5])
            return self._json({"examples": names})
        if p.startswith("/api/examples/"):
            name = unquote(p[len("/api/examples/"):])
            data = read_json(os.path.join(EXAMPLES_DIR, name + ".json"))
            if data is None:
                return self._json({"error": "not found"}, 404)
            return self._json(data)
        if p == "/api/projects":
            projs = []
            here = _origin()
            if os.path.isdir(PROJECTS_DIR):
                for d in sorted(os.listdir(PROJECTS_DIR)):
                    st = load_state(d)
                    if st:
                        org = st.get("origin") or {}
                        # foreign = 다른 PC에서 만들어진 프로젝트(폴더째 넘겨받은 흔적).
                        # origin 이 없는 옛 프로젝트는 판정하지 않는다(None).
                        foreign = None
                        if org.get("host"):
                            foreign = (org.get("host") != here.get("host")
                                       or org.get("user") != here.get("user"))
                        projs.append({"id": d, "name": st.get("name", d),
                                      "current_step": st.get("current_step"),
                                      "origin": org or None, "foreign": foreign})
            return self._json({"projects": projs, "here": here})
        if p.startswith("/api/projects/") and p.endswith("/state"):
            pid = p[len("/api/projects/"):-len("/state")]
            st = load_state(pid)
            if st is None:
                return self._json({"error": "no project"}, 404)
            return self._json(st)
        if p == "/api/hf/whoami":
            info = {"logged_in": False, "name": None, "invalid": False}
            try:
                from huggingface_hub import whoami, get_token
                if get_token():
                    try:
                        info["name"] = whoami().get("name")
                        info["logged_in"] = True
                    except Exception:
                        info["invalid"] = True   # 토큰 있으나 무효
            except Exception:
                pass
            return self._json(info)
        if p == "/api/hf/present":
            repo = (q.get("repo", [""])[0]) or ""
            present, size, partial = False, None, False
            try:
                from huggingface_hub import scan_cache_dir
                for r in scan_cache_dir().repos:
                    if r.repo_id.lower() == repo.lower():
                        size = round(r.size_on_disk / 1e9, 2)
                        # ★ 받다 만 걸 '있음'으로 보면 게이트가 잘못 열린다.
                        #   scan_cache_dir 은 완료 blob 만 세므로 .incomplete 를 따로 확인한다.
                        try:
                            blobs = os.path.join(str(r.repo_path), "blobs")
                            partial = any(f.endswith(".incomplete")
                                          for f in os.listdir(blobs)) if os.path.isdir(blobs) else False
                        except Exception:
                            partial = False
                        present = (r.size_on_disk > 5e8) and not partial
                        break
            except Exception:
                pass
            # ★ .incomplete 유무만 보면 오판한다: 중단된 옛 다운로드가 남긴 고아 조각은
            #   지금 받는 파일 집합과 무관해서 영원히 안 지워지고 게이트를 계속 막는다.
            #   diffusers 파이프라인이면 "오프라인으로 해석되는가"가 정확한 판정이다.
            #   단 이미지 모델에만 쓴다 — Hunyuan 같은 메시 모델은 서브폴더로 로드하는
            #   구조라 루트 기준 파이프라인 해석이 실패해도 정상이다.
            if _is_image_repo(repo):
                comp = _diffusers_complete(repo)
                if comp is not None:
                    present = comp
            return self._json({"repo": repo, "present": present, "size": size,
                               "partial": partial})
        if p == "/api/spectrum/status":
            st = SPECTRUM_STATE
            return self._json({"running": st["running"], "images": st["images"],
                               "error": st["error"], "log": st["log"][-40:],
                               "cancelling": bool(st.get("cancel")),
                               "cancelled": bool(st.get("cancelled"))})
        if p == "/api/install/status":
            item = (q.get("item", [""])[0]) or ""
            # 디스크(러너가 쓰는 파일)를 우선 — 서버가 재시작돼도 진행이 보인다
            disk = _install_read(item)
            if disk is not None:
                return self._json({"running": disk["running"], "code": disk["code"],
                                   "lines": disk["lines"][-120:]})
            st = INSTALL_STATE.get(item)
            if not st:
                return self._json({"running": False, "code": None, "lines": []})
            return self._json({"running": st["running"], "code": st["code"],
                               "lines": st["lines"][-120:]})
        if p == "/api/install/available":
            # 그 자리 설치 가능한 항목 목록 (프론트가 '지금 설치' 버튼 노출 판단)
            names = list(INSTALL_CMDS.keys())
            return self._json({"items": names, "winget": bool(shutil.which("winget"))})
        if p == "/api/diagnose/spec":
            if diag is None:
                return self._json({"error": "diag 모듈 로드 실패"}, 500)
            return self._json(diag.spec())
        if p == "/api/diagnose":
            if diag is None:
                return self._json({"error": "diag 모듈 로드 실패"}, 500)
            try:
                hd = (q.get("hunyuan_dir", [None])[0]) or None
                ef = (q.get("env_file", [None])[0]) or None
                ir = (q.get("image_repo", [None])[0]) or None
                return self._json(diag.run(hunyuan_dir=hd, env_file=ef, image_repo=ir))
            except Exception as e:
                return self._json({"error": "진단 실패: %r" % e}, 500)
        if p == "/api/doc":
            ref = (q.get("ref", [""])[0]) or ""
            return self._serve_doc(ref)
        if p.startswith("/sse/projects/"):
            pid = p[len("/sse/projects/"):]
            return self._sse(pid)

        return self._text("Not found", 404)

    # --- POST / PUT ---
    def do_PUT(self):
        u = urlparse(self.path)
        if u.path == "/api/flow":
            data = self._body_json()
            if "steps" not in data:
                return self._json({"error": "invalid flow"}, 400)
            write_json(FLOW_PATH, data)
            # 모든 프로젝트에 버전 신호
            for pid in list(_versions.keys()):
                bump_version(pid)
            return self._json({"ok": True})
        return self._text("Not found", 404)

    def do_POST(self):
        u = urlparse(self.path)
        p = u.path
        body = self._body_json()

        if p == "/api/spectrum":
            if not body.get("topic"):
                return self._json({"error": "먼저 주제를 입력하세요"}, 400)
            with _install_lock:
                if SPECTRUM_STATE.get("running"):
                    return self._json({"started": True, "already": True})
                SPECTRUM_STATE.update({"running": True, "images": None, "error": None, "log": [],
                                       "cancel": False, "cancelled": False})
            engine = body.get("engine", ""); repo = body.get("repo", "")
            threading.Thread(target=_run_spectrum,
                             args=(engine, repo, body.get("topic", ""), body.get("background", ""), body.get("pid")),
                             daemon=True).start()
            return self._json({"started": True, "mode": ("cloud" if "gpt-image" in (engine or "").lower() else "local")})

        if p == "/api/spectrum/cancel":
            # 스레드를 강제로 죽이지 않는다 — 플래그를 세우면 다음 스텝에서 스스로 빠져나온다.
            # (강제 종료는 GPU 메모리와 파이프라인 캐시를 망가뜨린다)
            if not SPECTRUM_STATE.get("running"):
                return self._json({"cancelling": False, "note": "생성 중이 아닙니다"})
            SPECTRUM_STATE["cancel"] = True
            SPECTRUM_STATE["log"].append("취소 요청됨 — 다음 스텝에서 중단합니다")
            return self._json({"cancelling": True})

        if p == "/api/suggest-anchor":
            key = _openai_key()
            if not key:
                return self._json({"error": "OpenAI 키 필요 — 1단계에서 저장"}, 400)
            topic = body.get("topic", ""); bg = body.get("background", "")
            if not topic:
                return self._json({"error": "먼저 주제를 입력하세요"}, 400)
            prompt = (
                "VR 장면. 주제: %s / 배경: %s.\n"
                "이 장면의 스타일 '강도'를 4단계(은은/중간/뚜렷/하이)로 나눠, "
                "각 단계가 이 장면에서 실제로 어떤 룩인지 1줄(대비·채도·조명·분위기 중심, 한국어 25자 내외)로 설명하라.\n"
                'JSON만: {"levels":[{"name":"은은","desc":""},{"name":"중간","desc":""},{"name":"뚜렷","desc":""},{"name":"하이","desc":""}]}'
            ) % (topic, bg)
            reqbody = json.dumps({
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": prompt}],
                "response_format": {"type": "json_object"}, "temperature": 0.6,
            }).encode()
            req = _urlreq.Request("https://api.openai.com/v1/chat/completions", data=reqbody,
                                  headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
            try:
                out = json.load(_urlreq.urlopen(req, timeout=45))
                return self._json(json.loads(out["choices"][0]["message"]["content"]))
            except Exception as e:
                return self._json({"error": "생성 실패: " + str(e)[:150]}, 500)

        if p == "/api/claude/launch":
            pid = body.get("pid")
            st = load_state(pid) if pid else None
            if st is None:
                return self._json({"error": "프로젝트를 찾을 수 없습니다"}, 404)
            msg = _handoff_msg(pid, st)
            try:
                _spawn_claude(msg)
            except Exception as e:
                return self._json({"error": str(e)}, 400)
            with _lock:
                st2 = load_state(pid)
                if st2 is not None:
                    st2["audit_log"].append({"t": now_iso(), "action": "claude_launch",
                                             "detail": "Claude 실행 (지시문 자동 입력)"})
                    save_state(pid, st2)
            return self._json({"started": True, "message": msg})

        if p == "/api/claude/message":
            # 화면에 보여줄 지시문 (실행은 안 함) — 서버가 만든 것과 같은 문장이어야 한다.
            pid = body.get("pid")
            st = load_state(pid) if pid else None
            if st is None:
                return self._json({"error": "프로젝트를 찾을 수 없습니다"}, 404)
            return self._json({"message": _handoff_msg(pid, st)})

        if p == "/api/suggest-assets":
            key = _openai_key()
            if not key:
                return self._json({"error": "OpenAI 키 필요 — 1단계 환경체크에서 저장하세요"}, 400)
            # ★ 값은 state 에서만 읽는다(AGENT_CONTRACT). 클라이언트가 따로 넘기면
            #   화면과 state 가 어긋났을 때 어느 쪽으로 추천했는지 알 수 없다.
            pid = body.get("pid")
            st = load_state(pid) if pid else None
            if st is None:
                return self._json({"error": "프로젝트를 찾을 수 없습니다"}, 404)
            inp = st.get("inputs") or {}
            topic = inp.get("topic") or ""
            bg = inp.get("background") or ""
            if not topic:
                return self._json({"error": "먼저 2단계에서 주제를 입력하고 확정하세요"}, 400)

            refs = st.get("ref_images") or []
            ref = refs[0] if refs else None
            anchor = inp.get("anchor") or ""
            # 앵커가 넣은 배경 이미지면 그 '이름'은 스타일 설명이 아니다 → 프롬프트에 넣지 않는다.
            anchor_txt = "" if (ref and anchor == ref.get("name")) else anchor

            seen = ""
            if ref and ref.get("b64"):
                try:
                    seen = _observe_image(key, ref["b64"], ref.get("ext"))
                except Exception as e:
                    seen = ""   # 관찰 실패해도 글 기준으로는 계속 진행한다

            head = "VR 장면을 만들려고 한다."
            if seen:
                head += ("\n사용자가 준 **배경 그림에서 관찰된 것**(이게 1순위 근거다):\n%s" % seen)
                head += ("\n사용자가 적은 글(보조): 주제 %s / 배경 %s" % (topic, bg))
            else:
                head += " 주제: %s / 배경: %s" % (topic, bg)
            if anchor_txt:
                head += " / 스타일앵커: %s" % anchor_txt
            tail = ("\n이 장면에 필요한 3D 에셋을 카테고리별로 제안하라. "
                    "카테고리 예: 건물/구조물, 자연물, 인물·동물, 소품, 이펙트, 지형·바닥. "
                    "각 항목은 짧은 한국어 명사(2~6자). 카테고리당 3~7개. "
                    'JSON만 출력: {"categories":[{"name":"","items":["",""]}]}')
            content = head + tail

            reqbody = json.dumps({
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": content}],
                "response_format": {"type": "json_object"}, "temperature": 0.5,
            }).encode()
            req = _urlreq.Request("https://api.openai.com/v1/chat/completions", data=reqbody,
                                  headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
            try:
                out = json.load(_urlreq.urlopen(req, timeout=90))
                data = json.loads(out["choices"][0]["message"]["content"])
                with _lock:
                    s2 = load_state(pid)
                    if s2 is not None:
                        s2["asset_suggestions"] = data.get("categories", [])
                        # 무엇을 근거로 뽑았는지 남긴다 — 나중에 "왜 이게 빠졌지"를 추적할 수 있어야 한다.
                        s2["asset_suggest_basis"] = {
                            "topic": topic, "background": bg,
                            "ref_image": (ref or {}).get("file"),
                            "seen": seen,
                            "t": now_iso(),
                        }
                        s2["audit_log"].append({"t": now_iso(), "action": "suggest_assets",
                                                "detail": "에셋 추천 (배경이미지 %s)"
                                                          % ("사용" if ref else "없음")})
                        save_state(pid, s2)
                data["used_ref_image"] = bool(ref)
                return self._json(data)
            except Exception as e:
                return self._json({"error": "제안 실패: " + str(e)[:150]}, 500)

        if p == "/api/install":
            item = body.get("item")
            repo = body.get("repo")
            if repo:
                # 임의 HF 모델 다운로드 (repo id 패턴 검증 — org/name)
                import re
                if not re.match(r"^[A-Za-z0-9._\-]+/[A-Za-z0-9._\-]+$", repo):
                    return self._json({"error": "잘못된 모델 id (org/name 형식)"}, 400)
                # ★ 저장소 통째로(snapshot_download) 받으면 중복 형식까지 딸려와
                #   sdxl-turbo 55.5GB / sd3.5-medium 48.9GB 가 된다. 실제 필요분만 받는다.
                cmds = [
                    _PYEXE + ["-m", "pip", "install", "-U", "diffusers", "transformers",
                              "accelerate", "huggingface_hub"],
                    _PYEXE + [os.path.join(BASE, "model_fetch.py"), repo],
                ]
                # ★ GPU 를 못 쓰는 torch 로 수십 GB 를 받으면, 다 받은 뒤 CPU 로 돌아
                #   "느리기만 하고 에러는 없는" 최악의 상태가 된다. 받기 전에 세운다.
                #   (force=true 로 사용자가 명시적으로 강행할 수는 있다)
                if not body.get("force"):
                    t = _torch_cuda()
                    if not t.get("ok"):
                        return self._json({
                            "error": "gpu_not_ready",
                            "torch": t.get("ver"),
                            "message": ("GPU 를 쓸 수 있는 PyTorch 가 없습니다. 지금 받으면 수십 GB 를 "
                                        "내려받고도 그래픽카드를 못 씁니다. STEP 1 의 'PyTorch (GPU)' 를 "
                                        "먼저 설치한 뒤 다시 시도하세요."),
                        }, 409)
                item = item or ("model:" + repo)   # 상태 키
            else:
                cmds = INSTALL_CMDS.get(item)
            if not cmds:
                return self._json({"error": "그 자리 설치 미지원 항목(수동 설치)"}, 400)
            with _install_lock:
                cur = _install_read(item)
                if cur and cur.get("running"):
                    return self._json({"started": True, "already": True})
                try:
                    _spawn_install(item, cmds)
                except Exception as e:
                    return self._json({"error": "설치 창 실행 실패: " + str(e)[:150]}, 500)
            return self._json({"started": True})

        if p == "/api/hf/login":
            # HF 토큰으로 로그인(검증+표준 토큰 저장) → 이후 모든 다운로드 자동 사용
            token = (body.get("token") or "").strip()
            if not token:
                return self._json({"error": "토큰 필요"}, 400)
            try:
                from huggingface_hub import login, whoami
                login(token=token, add_to_git_credential=False)
                name = whoami().get("name")
                return self._json({"ok": True, "name": name})
            except Exception as e:
                return self._json({"error": "로그인 실패: " + str(e)[:160]}, 400)

        if p == "/api/env":
            # 허용 키만 web/.env 에 저장 (값은 반환/로그 안 함)
            key = (body.get("key") or "").strip()
            val = body.get("value") or ""
            if key not in ("OPENAI_API_KEY", "RODIN_API_KEY", "HF_TOKEN") or not val:
                return self._json({"error": "허용 키/값 필요"}, 400)
            envp = os.path.join(BASE, ".env")
            lines = []
            if os.path.exists(envp):
                with open(envp, "r", encoding="utf-8") as f:
                    lines = f.read().splitlines()
            lines = [l for l in lines if not l.strip().startswith(key + "=")]
            lines.append(key + "=" + val)
            with open(envp, "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
            os.environ[key] = val  # 현재 프로세스 진단에 즉시 반영
            return self._json({"ok": True})

        if p == "/api/projects":
            with _lock:
                pid = "vr_" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                st = empty_state_from_flow(pid, body.get("name"))
                save_state(pid, st)
            return self._json(st)

        if p.startswith("/api/projects/"):
            rest = p[len("/api/projects/"):]
            parts = rest.split("/")
            pid = parts[0]
            action = parts[1] if len(parts) > 1 else ""
            st = load_state(pid)
            if st is None:
                return self._json({"error": "no project"}, 404)

            if action == "input":
                # {field, value}  또는 {step, field, value}
                field = body.get("field")
                if not field:
                    return self._json({"error": "field required"}, 400)
                with _lock:
                    st["inputs"][field] = body.get("value")
                    st["audit_log"].append({"t": now_iso(), "action": "input",
                                            "detail": f"{field} 입력"})
                    recompute_progress(st)
                    save_state(pid, st)
                return self._json(st)

            if action == "gate":
                # ★ 게이트 통과는 UI 클릭(이 엔드포인트)으로만. passed_by=user 기록.
                step = body.get("step")
                if step not in st["steps"]:
                    return self._json({"error": "bad step"}, 400)
                with _lock:
                    st["steps"][step]["gate_passed"] = True
                    st["steps"][step]["passed_by"] = "user(ui)"
                    st["steps"][step]["passed_at"] = now_iso()
                    st["audit_log"].append({"t": now_iso(), "action": "gate_pass",
                                            "detail": f"{step} 게이트 사용자 통과"})
                    recompute_progress(st)
                    save_state(pid, st)
                return self._json(st)

            if action == "ungate":
                step = body.get("step")
                if step in st["steps"]:
                    with _lock:
                        st["steps"][step]["gate_passed"] = False
                        st["steps"][step]["passed_by"] = None
                        st["audit_log"].append({"t": now_iso(), "action": "gate_undo",
                                                "detail": f"{step} 게이트 해제"})
                        recompute_progress(st)
                        save_state(pid, st)
                return self._json(st)

            if action == "engine":
                # {key, value}  key 예: "anchor.image"
                key = body.get("key")
                if not key:
                    return self._json({"error": "key required"}, 400)
                with _lock:
                    st["engine_choices"][key] = body.get("value")
                    st["audit_log"].append({"t": now_iso(), "action": "engine",
                                            "detail": f"{key} = {body.get('value')}"})
                    save_state(pid, st)
                return self._json(st)

            if action == "ref-image":
                # 사용자가 직접 넣은 배경(참고) 이미지 — **딱 한 장만 유지한다.**
                # 여러 장을 두면 "이 중 뭐가 기준이지?"가 생기고, 기준이 흐려지면
                # 에셋 리스트업·배치가 무엇을 보고 판단했는지 알 수 없게 된다.
                # ★ 파일로도 저장한다 — state 안의 base64 만으로는 이후 단계에서
                #   Claude/스크립트가 '이 그림 기준으로' 넘길 실체가 없다.
                b64 = body.get("b64") or ""
                ext = (body.get("ext") or "png").lower()
                if ext not in ("png", "jpg", "jpeg", "webp"):
                    return self._json({"error": "png/jpg/webp 만 됩니다"}, 400)
                if not b64:
                    return self._json({"error": "이미지 데이터가 없습니다"}, 400)
                try:
                    import base64 as _b
                    raw = _b.b64decode(b64)
                except Exception:
                    return self._json({"error": "이미지 데이터를 읽지 못했습니다"}, 400)
                if len(raw) > 12 * 1024 * 1024:
                    return self._json({"error": "이미지가 너무 큽니다 (12MB 초과)"}, 400)
                with _lock:
                    out_dir = os.path.join(PROJECTS_DIR, pid, "out")
                    os.makedirs(out_dir, exist_ok=True)
                    # 이전 배경 파일 정리 (교체이므로 남겨두면 어느 게 현재인지 모른다)
                    for old in (st.get("ref_images") or []):
                        try:
                            if old.get("path") and os.path.isfile(old["path"]):
                                os.remove(old["path"])
                        except Exception:
                            pass
                    fname = "ref_bg.%s" % ("jpg" if ext == "jpeg" else ext)
                    fpath = os.path.join(out_dir, fname)
                    with open(fpath, "wb") as f:
                        f.write(raw)
                    name = body.get("name") or "배경 참고 이미지"
                    st["ref_images"] = [{"name": name, "b64": b64, "ext": ext,
                                         "path": fpath.replace("\\", "/"), "file": fname}]
                    # 한 장뿐이므로 고를 것이 없다 → 그대로 앵커로 확정한다.
                    st["inputs"]["anchor"] = name
                    st["audit_log"].append({"t": now_iso(), "action": "ref_image",
                                            "detail": "배경 참고 이미지 설정: %s (%s)" % (name, fname)})
                    recompute_progress(st)
                    save_state(pid, st)
                return self._json(st)

            if action == "ref-image-delete":
                with _lock:
                    for old in (st.get("ref_images") or []):
                        try:
                            if old.get("path") and os.path.isfile(old["path"]):
                                os.remove(old["path"])
                        except Exception:
                            pass
                    st["ref_images"] = []
                    # 앵커가 그 이미지였으면 같이 푼다 (없는 걸 가리키는 상태 방지)
                    if (st.get("inputs") or {}).get("anchor"):
                        st["inputs"].pop("anchor", None)
                        for sid, sv in st["steps"].items():
                            if sid in ("anchor", "topic"):
                                sv["gate_passed"] = False
                                sv["passed_by"] = None
                    st["audit_log"].append({"t": now_iso(), "action": "ref_image_del",
                                            "detail": "배경 참고 이미지 삭제"})
                    recompute_progress(st)
                    save_state(pid, st)
                return self._json(st)

            if action == "reset":
                # 주제·배경·앵커·에셋리스트 등 입력값과 게이트를 비운다.
                # {fields: [...]} 를 주면 그 입력만, 없으면 전부.
                fields = body.get("fields")
                with _lock:
                    if fields:
                        for f in fields:
                            st["inputs"].pop(f, None)
                        detail = "입력 초기화: " + ", ".join(map(str, fields))
                    else:
                        st["inputs"] = {}
                        detail = "입력 전체 초기화"
                    # 입력이 사라졌으므로 그 입력에 기대던 게이트도 같이 풀어야 한다.
                    # (게이트만 남으면 빈 값으로 다음 단계가 열려 있는 모순 상태가 된다)
                    for sid, sv in st["steps"].items():
                        sv["gate_passed"] = False
                        sv["passed_by"] = None
                        sv["passed_at"] = None
                    st["audit_log"].append({"t": now_iso(), "action": "reset",
                                            "detail": detail + " + 게이트 전체 해제"})
                    recompute_progress(st)
                    save_state(pid, st)
                return self._json(st)

            if action == "fill-from-example":
                # 사용자가 명시적으로 예시 값 복사 (로그 남김)
                name = body.get("example")
                data = read_json(os.path.join(EXAMPLES_DIR, str(name) + ".json"))
                if data is None:
                    return self._json({"error": "example not found"}, 404)
                with _lock:
                    for k, v in (data.get("inputs") or {}).items():
                        st["inputs"][k] = v
                    st["audit_log"].append({"t": now_iso(), "action": "fill_example",
                                            "detail": f"예시 '{name}' 값 명시적 복사"})
                    recompute_progress(st)
                    save_state(pid, st)
                return self._json(st)

        return self._text("Not found", 404)

    # --- 문서 실시간 조회 ---
    def _serve_doc(self, ref):
        # ref 예: "RUN.md#1" -> RUN.md, 앵커 무시(전체 반환). 경로 탈출 방지.
        fname = ref.split("#")[0].strip()
        if not fname:
            return self._json({"error": "no ref"}, 400)
        target = os.path.normpath(os.path.join(HARNESS_ROOT, fname))
        if not target.startswith(HARNESS_ROOT):
            return self._json({"error": "forbidden"}, 403)
        if not os.path.isfile(target):
            return self._json({"ref": ref, "text": f"(문서 없음: {fname})"})
        with open(target, "r", encoding="utf-8") as f:
            text = f.read()
        return self._json({"ref": ref, "text": text})

    # --- SSE ---
    def _sse(self, pid):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        last = -1
        try:
            while True:
                cur = _versions.get(pid, 0)
                if cur != last:
                    last = cur
                    payload = json.dumps({"version": cur})
                    self.wfile.write(("event: update\ndata: " + payload + "\n\n").encode("utf-8"))
                    self.wfile.flush()
                else:
                    # keep-alive 주석
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
                time.sleep(1.0)
        except (BrokenPipeError, ConnectionResetError):
            return
        except Exception:
            return


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8787
    os.makedirs(PROJECTS_DIR, exist_ok=True)
    # 기존 프로젝트 버전 초기화
    if os.path.isdir(PROJECTS_DIR):
        for d in os.listdir(PROJECTS_DIR):
            if os.path.isfile(state_path(d)):
                _versions[d] = 0
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}"
    print(f"VR 제작킷 웹 대시보드 실행 중 → {url}")
    print("종료: Ctrl+C")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n종료합니다.")
        httpd.shutdown()


if __name__ == "__main__":
    main()
