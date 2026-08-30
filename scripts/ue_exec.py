# -*- coding: utf-8 -*-
# Run UE python in the editor via UnrealClaude REST (execute_script) + poll result.
# Usage: py ue_exec.py <script.py> "<description>"
import sys, json, time, urllib.request

BASE = "http://localhost:3000"

def post(path, payload):
    req = urllib.request.Request(BASE + path, data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode("utf-8", "replace"))
        except Exception:
            return {"success": False, "http_error": e.code, "data": {"status": "pending"}}
    except Exception as e:
        return {"success": False, "err": str(e), "data": {"status": "pending"}}

def main():
    script_path = sys.argv[1]
    desc = sys.argv[2] if len(sys.argv) > 2 else "Claude UE script"
    with open(script_path, encoding="utf-8") as f:
        code = f.read()
    sub = post("/mcp/tool/execute_script",
               {"script_content": code, "script_type": "python", "description": desc})
    tid = (sub.get("data") or {}).get("task_id")
    if not tid:
        print("NO_TASK_ID:", json.dumps(sub)[:800]); return
    print("task_id:", tid)
    last = None
    for _ in range(120):  # up to ~4 min
        res = post("/mcp/tool/task_result", {"task_id": tid})
        d = res.get("data") or {}
        st = d.get("status")
        last = res
        if st in ("completed", "success", "failed", "error", "done"):
            break
        time.sleep(2)
    d = last.get("data") or {}
    print("STATUS:", d.get("status"), "| success:", last.get("success"))
    # print message + any captured output/result
    msg = last.get("message") or d.get("message")
    if msg: print("MESSAGE:\n" + str(msg))
    for k in ("result", "output", "stdout", "return_value", "data"):
        v = d.get(k)
        if v not in (None, "", {}):
            print(f"{k.upper()}:", json.dumps(v)[:2000] if not isinstance(v, str) else v[:2000])

if __name__ == "__main__":
    main()
