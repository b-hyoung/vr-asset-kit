# -*- coding: utf-8 -*-
# Run UE python in the editor via UnrealClaude REST (execute_script) + poll result.
# Usage: py -u ue_exec.py <script.py> "<description>" [--grep PREFIX] [--timeout SEC]
#
# 실측 함정 (08-31):
#  · 제출 POST 를 60초로 잡으면 에디터가 바쁠 때(DDC 정리·셰이더 컴파일·**승인 대화상자**)
#    task_id 를 못 받고 죽는다 → 제출 타임아웃을 넉넉히.
#  · 플러그인 설정 bAutoApproveScripts=false 면 에디터에 모달이 떠서 게임스레드가 멈춘다.
#    그동안 REST 는 통째로 무응답이다 — 죽은 게 아니라 승인 대기다.
#  · 출력이 길면 잘리므로 결과 파싱을 REPORT 로그에 의존하지 말고 --grep 으로 요약줄만 뽑거나
#    별도 검증 스크립트를 돌릴 것.
#  · 파이프로 넘길 때 stdout 버퍼링 때문에 아무것도 안 보인다 → `py -u` 로 실행.
import sys, json, time, urllib.request, urllib.error

BASE = "http://localhost:3000"
SUBMIT_TIMEOUT = 300      # 승인 대기/에디터 바쁨을 견딜 만큼
POLL_TIMEOUT = 60


def post(path, payload, timeout):
    req = urllib.request.Request(BASE + path, data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode("utf-8", "replace"))
        except Exception:
            return {"success": False, "http_error": e.code, "data": {"status": "pending"}}
    except Exception as e:
        return {"success": False, "err": str(e), "data": {"status": "pending"}}


def main():
    argv = sys.argv[1:]
    grep = None
    total = 900
    if "--grep" in argv:
        i = argv.index("--grep"); grep = argv[i + 1]; del argv[i:i + 2]
    if "--timeout" in argv:
        i = argv.index("--timeout"); total = int(argv[i + 1]); del argv[i:i + 2]
    script_path = argv[0]
    desc = argv[1] if len(argv) > 1 else "Claude UE script"

    with open(script_path, encoding="utf-8") as f:
        code = f.read()

    sub = post("/mcp/tool/execute_script",
               {"script_content": code, "script_type": "python", "description": desc},
               SUBMIT_TIMEOUT)
    tid = (sub.get("data") or {}).get("task_id")
    if not tid:
        print("NO_TASK_ID:", json.dumps(sub)[:800])
        print("힌트: 에디터에 'Execute PYTHON Script?' 승인창이 떠 있는지 확인 "
              "(Project Settings > Plugins > Unreal Claude > Auto-approve script execution)")
        return 1
    print("task_id:", tid, flush=True)

    deadline = time.time() + total
    last = None
    while time.time() < deadline:
        res = post("/mcp/tool/task_result", {"task_id": tid}, POLL_TIMEOUT)
        d = res.get("data") or {}
        last = res
        if d.get("status") in ("completed", "success", "failed", "error", "done"):
            break
        time.sleep(3)

    d = (last or {}).get("data") or {}
    print("STATUS:", d.get("status"), "| success:", (last or {}).get("success"),
          "| dur_ms:", d.get("duration_ms"), flush=True)
    out = (d.get("data") or {}).get("output", "") or ""
    if grep:
        for line in out.splitlines():
            if line.startswith(grep):
                print(line, flush=True)
    else:
        print("--- output ---")
        print(out)
    msg = (last or {}).get("message")
    if msg:
        print("MESSAGE:", str(msg)[:500], flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
