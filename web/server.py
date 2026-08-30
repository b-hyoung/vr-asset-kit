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
EXAMPLES_DIR = os.path.join(BASE, "examples")
PROJECTS_DIR = os.path.join(BASE, "projects")

_lock = threading.Lock()
# 프로젝트별 상태 버전 (SSE 가 이 값 변화를 감지해 푸시)
_versions = {}

# ---------- 그 자리 설치 (화이트리스트만) ----------
# 안전: 미리 정의된 명령만 실행. CUDA/UE 등 무거운 GUI 설치는 제외(가이드만).
_PYEXE = [sys.executable] if sys.executable else ["py", "-3"]
INSTALL_CMDS = {
    "uv": [_PYEXE + ["-m", "pip", "install", "-U", "uv"]],
    "PyTorch (GPU)": [_PYEXE + ["-m", "pip", "install", "torch",
                                "--index-url", "https://download.pytorch.org/whl/cu121"]],
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

# 강도 스펙트럼 4장 생성 (선택 엔진: gpt-image=클라우드 / 그 외=로컬 diffusers)
SPECTRUM_STATE = {"running": False, "images": None, "error": None, "log": []}
_INTENS = [
    ("은은", "은은하고 낮은 대비, 뮤트 파스텔, 부드러운 빛, subtle muted low-contrast"),
    ("중간", "자연스러운 사실적 톤, 보통 대비와 채도, natural realistic"),
    ("뚜렷", "선명하고 높은 대비, 진한 색, 뚜렷한 그림자, vivid high-contrast bold"),
    ("하이", "강렬한 하이톤, 과장된 대비·채도, 극적 조명·발광, hyper vivid dramatic glowing"),
]


def _spectrum_prompt(topic, bg, style):
    return "%s, %s, %s. 하나의 일관된 장면, 디지털 콘셉트 아트." % (topic, bg, style)


def _run_spectrum(engine, repo, topic, bg):
    st = SPECTRUM_STATE
    st["images"], st["error"], st["log"] = None, None, []
    try:
        if engine and "gpt-image" in engine.lower():
            key = _openai_key()
            if not key:
                st["error"] = "OpenAI 키 필요"; return
            imgs = []
            for name, style in _INTENS:
                st["log"].append("gpt-image 생성: " + name)
                rb = json.dumps({"model": "gpt-image-1", "prompt": _spectrum_prompt(topic, bg, style),
                                 "size": "1024x1024", "quality": "low", "n": 1}).encode()
                req = _urlreq.Request("https://api.openai.com/v1/images/generations", data=rb,
                                      headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
                out = json.load(_urlreq.urlopen(req, timeout=120))
                imgs.append({"name": name, "b64": out["data"][0]["b64_json"]})
            st["images"] = imgs
        else:
            # 로컬 diffusers 생성
            if not repo:
                st["error"] = "로컬 모델(repo) 미선택"; return
            steps = 4 if "schnell" in repo.lower() else 25
            outp = os.path.join(BASE, "projects", "_spectrum_out.json")
            jobp = os.path.join(BASE, "projects", "_spectrum_job.json")
            job = {"repo": repo, "steps": steps, "size": 768, "out": outp,
                   "prompts": [{"name": n, "prompt": _spectrum_prompt(topic, bg, s)} for n, s in _INTENS]}
            os.makedirs(os.path.dirname(jobp), exist_ok=True)
            with open(jobp, "w", encoding="utf-8") as f:
                json.dump(job, f, ensure_ascii=False)
            try:
                os.remove(outp)
            except OSError:
                pass
            env = os.environ.copy(); env.update(_load_env_vars())
            cmd = _PYEXE + [os.path.join(BASE, "gen_spectrum.py"), jobp]
            st["log"].append("$ " + " ".join(cmd))
            p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                 text=True, encoding="utf-8", errors="replace", env=env)
            for line in p.stdout:
                st["log"].append(line.rstrip())
                del st["log"][:-400]
            p.wait()
            if p.returncode == 0 and os.path.exists(outp):
                st["images"] = json.load(open(outp, encoding="utf-8"))["images"]
            else:
                st["error"] = "로컬 생성 실패(코드 %s) — 로그 확인" % p.returncode
    except Exception as e:
        st["error"] = str(e)[:200]
    finally:
        st["running"] = False


def _openai_key():
    for p in [os.path.join(BASE, ".env"),
              os.path.join(os.path.expanduser("~"), "Desktop", "bobs_project", "Core-CBT", ".env")]:
        try:
            if os.path.isfile(p):
                for line in open(p, encoding="utf-8", errors="ignore"):
                    s = line.strip()
                    if s.startswith("OPENAI_API_KEY") and "=" in s:
                        v = s.split("=", 1)[1].strip().strip('"').strip("'")
                        if v:
                            return v
        except Exception:
            pass
    return os.environ.get("OPENAI_API_KEY")


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
    return read_json(state_path(pid))


def save_state(pid, state):
    write_json(state_path(pid), state)
    bump_version(pid)


# ---------- 초기 상태 생성 (빈 값에서 시작) ----------
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
        # ★ 모든 입력은 빈 값에서 시작 — 예시/이전맥락 자동 유입 없음
        "inputs": {},
        "engine_choices": {},
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
        if p == "/api/models":
            return self._json(read_json(os.path.join(BASE, "models.json"), {"image": []}))
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
            if os.path.isdir(PROJECTS_DIR):
                for d in sorted(os.listdir(PROJECTS_DIR)):
                    st = load_state(d)
                    if st:
                        projs.append({"id": d, "name": st.get("name", d),
                                      "current_step": st.get("current_step")})
            return self._json({"projects": projs})
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
            present, size = False, None
            try:
                from huggingface_hub import scan_cache_dir
                for r in scan_cache_dir().repos:
                    if r.repo_id.lower() == repo.lower():
                        size = round(r.size_on_disk / 1e9, 2)
                        present = r.size_on_disk > 5e8   # 0.5GB 미만은 메타데이터만 → 미다운로드로 간주
                        break
            except Exception:
                pass
            return self._json({"repo": repo, "present": present, "size": size})
        if p == "/api/spectrum/status":
            st = SPECTRUM_STATE
            return self._json({"running": st["running"], "images": st["images"],
                               "error": st["error"], "log": st["log"][-40:]})
        if p == "/api/install/status":
            item = (q.get("item", [""])[0]) or ""
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
                SPECTRUM_STATE.update({"running": True, "images": None, "error": None, "log": []})
            engine = body.get("engine", ""); repo = body.get("repo", "")
            threading.Thread(target=_run_spectrum,
                             args=(engine, repo, body.get("topic", ""), body.get("background", "")),
                             daemon=True).start()
            return self._json({"started": True, "mode": ("cloud" if "gpt-image" in (engine or "").lower() else "local")})

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

        if p == "/api/suggest-assets":
            key = _openai_key()
            if not key:
                return self._json({"error": "OpenAI 키 필요 — 1단계 환경체크에서 저장하세요"}, 400)
            topic = body.get("topic", ""); bg = body.get("background", ""); anchor = body.get("anchor", "")
            if not topic:
                return self._json({"error": "먼저 주제를 입력하세요"}, 400)
            prompt = (
                "VR 장면을 만들려고 한다. 주제: %s / 배경: %s / 스타일앵커: %s.\n"
                "이 장면에 필요한 3D 에셋을 카테고리별로 제안하라. "
                "카테고리 예: 건물/구조물, 자연물, 인물·동물, 소품, 이펙트, 지형·바닥. "
                "각 항목은 짧은 한국어 명사(2~6자). 카테고리당 3~7개. "
                'JSON만 출력: {"categories":[{"name":"","items":["",""]}]}'
            ) % (topic, bg, anchor)
            reqbody = json.dumps({
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": prompt}],
                "response_format": {"type": "json_object"}, "temperature": 0.5,
            }).encode()
            req = _urlreq.Request("https://api.openai.com/v1/chat/completions", data=reqbody,
                                  headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
            try:
                out = json.load(_urlreq.urlopen(req, timeout=45))
                data = json.loads(out["choices"][0]["message"]["content"])
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
                cmds = [
                    _PYEXE + ["-m", "pip", "install", "-U", "diffusers", "transformers",
                              "accelerate", "huggingface_hub"],
                    _PYEXE + ["-c", "from huggingface_hub import snapshot_download; "
                              "snapshot_download('%s'); print('DONE %s')" % (repo, repo)],
                ]
                item = item or ("model:" + repo)   # 상태 키
            else:
                cmds = INSTALL_CMDS.get(item)
            if not cmds:
                return self._json({"error": "그 자리 설치 미지원 항목(수동 설치)"}, 400)
            with _install_lock:
                cur = INSTALL_STATE.get(item)
                if cur and cur.get("running"):
                    return self._json({"started": True, "already": True})
                INSTALL_STATE[item] = {"running": True, "code": None, "lines": []}
            threading.Thread(target=_run_install, args=(item, cmds), daemon=True).start()
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
