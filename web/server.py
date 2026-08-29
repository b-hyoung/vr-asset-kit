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
                return self._json(diag.run(hunyuan_dir=hd, env_file=ef))
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

        if p == "/api/env":
            # 허용 키만 web/.env 에 저장 (값은 반환/로그 안 함)
            key = (body.get("key") or "").strip()
            val = body.get("value") or ""
            if key not in ("OPENAI_API_KEY",) or not val:
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
