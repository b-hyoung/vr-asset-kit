# -*- coding: utf-8 -*-
"""설치/다운로드 실행기 — 서버와 **분리된 프로세스**로 자기 콘솔 창에서 돈다.

왜 분리했나 (실측 사고):
  기존엔 server.py 안에서 daemon=True 스레드로 돌렸다. 서버를 재시작하면
  다운로드가 조용히 죽고, 진행 상태(INSTALL_STATE)도 메모리와 함께 날아갔다.
  5.5GB 받다 끊긴 .incomplete 만 남고 UI 는 "왜 확정이 안 되지" 상태가 된다.

구조:
  - 서버는 job.json 만 쓰고 이 스크립트를 새 콘솔로 띄운다 → 서버가 죽어도 계속 받는다.
  - 진행은 **파일**(log/status)에 남는다 → 서버가 재시작해도 상태를 다시 읽을 수 있다.
  - 다 끝나면 창은 스스로 닫힌다 (실패했을 때만 잠깐 남겨 원인을 보여준다).

사용: py install_runner.py <job.json>
job.json: {"item":..., "cmds":[[...],...], "log":path, "status":path}
"""
import json
import os
import subprocess
import sys
import time

HOLD_ON_FAIL_SEC = 20   # 실패 시 원인을 읽을 수 있게 창을 잠깐 붙잡는다


def main():
    if len(sys.argv) < 2:
        print("usage: install_runner.py <job.json>")
        return 2
    with open(sys.argv[1], encoding="utf-8") as f:
        job = json.load(f)

    item = job.get("item", "?")
    cmds = job.get("cmds") or []
    log_path = job["log"]
    status_path = job["status"]

    def write_status(running, code, note=""):
        tmp = status_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"item": item, "running": running, "code": code,
                       "note": note, "pid": os.getpid(), "t": time.time()}, f)
        os.replace(tmp, status_path)   # 원자적 교체 (반쯤 쓰인 상태 안 읽히게)

    log = open(log_path, "w", encoding="utf-8", errors="replace")

    def emit(line):
        print(line, flush=True)
        log.write(line + "\n")
        log.flush()          # UI 가 실시간으로 읽어야 하므로 매 줄 flush

    write_status(True, None)
    emit("=== %s 설치/다운로드 시작 ===" % item)
    emit("(이 창은 끝나면 자동으로 닫힙니다. 서버를 재시작해도 이 작업은 계속됩니다.)")

    code = 0
    try:
        for cmd in cmds:
            emit("")
            emit("$ " + " ".join(cmd))
            try:
                p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                     text=True, encoding="utf-8", errors="replace")
            except FileNotFoundError:
                emit("실행기 없음: %s (수동 설치 필요)" % cmd[0])
                code = -1
                break
            for line in p.stdout:
                emit(line.rstrip())
            p.wait()
            if p.returncode != 0:
                code = p.returncode
                emit("!! 실패 (exit %s)" % code)
                break
    except Exception as e:
        emit("ERROR: " + repr(e))
        code = -1

    write_status(False, code)
    emit("")
    emit("=== 종료 (exit %s) ===" % code)
    log.close()

    if code != 0:
        # 실패했을 때만 창을 붙잡는다 — 성공이면 바로 닫혀야 방해가 안 된다
        emit("실패했습니다. %d초 후 닫힙니다." % HOLD_ON_FAIL_SEC)
        time.sleep(HOLD_ON_FAIL_SEC)
    return code


if __name__ == "__main__":
    sys.exit(main())
