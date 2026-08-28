# -*- coding: utf-8 -*-
# 자율 배치 루프: 조립(UE) -> OpenAI 자연스러움 판정 -> 재배치 -> 반복.
import json, subprocess, sys, os, random, shutil

# ★ 예시 템플릿(.example). 경로를 특정 프로젝트로 하드코딩하지 않는다.
#   SCR : 작업 스크래치 폴더  — 환경변수 VRKIT_SCRATCH 또는 CLI 2번째 인자
#   DOCS: 프로젝트 docs 폴더  — 환경변수 VRKIT_DOCS   또는 CLI 3번째 인자
#   (웹 사용 시 state.inputs / 프로젝트 경로에서 주입)
SCR  = (sys.argv[2] if len(sys.argv) > 2 else None) or os.environ.get("VRKIT_SCRATCH") \
       or os.path.join(os.path.expanduser("~"), "Desktop", "vr_scratch")
DOCS = (sys.argv[3] if len(sys.argv) > 3 else None) or os.environ.get("VRKIT_DOCS") \
       or os.path.join(os.path.expanduser("~"), "Desktop", "vr_docs")
os.makedirs(SCR, exist_ok=True)
LAYOUT = os.path.join(SCR, "layout.json")
VILLAGE= os.path.join(SCR, "village.png")
UE_EXEC= os.path.join(SCR, "ue_exec.py")
ASSEMBLE=os.path.join(SCR, "assemble.py")
JUDGE  = os.path.join(DOCS, "cmp_openai_scene.py")
MAXITER = int(sys.argv[1]) if len(sys.argv)>1 else 3

layout = {
  # 넓게넓게 (spread wide, organic)
  "houses": [[0,0,25,1.0],[1000,-620,-40,1.05],[2100,-150,60,0.95],[2700,750,-15,1.0],
             [-1050,350,205,1.0],[-2150,-500,150,1.05],[650,1250,110,0.9],
             [-800,1700,30,1.0],[1700,1550,-30,0.95],
             [500,-1050,70,0.95],[-1600,700,120,1.0],[1450,300,-55,0.9],
             [-350,900,200,1.05],[2250,1450,15,0.95],[-1900,1300,80,0.9],
             [900,650,-20,1.0],[-1300,-1050,140,1.0]],
  "well":  [250,-450], "wheel":[2350,-1550], "tree":[-1500,1500], "rocks":[-2400,-1500],
  "sun":   [-2.5,44,7.0],
  "cam":   [-5400,-4800,2400, 650,450,170, 60]
}

import random as _rnd
def _prescatter(L):
    cx=sum(h[0] for h in L["houses"])/len(L["houses"]); cy=sum(h[1] for h in L["houses"])/len(L["houses"])
    for h in L["houses"]:
        h[0]+=_rnd.uniform(-260,260); h[1]+=_rnd.uniform(-260,260); h[2]=(h[2]+_rnd.uniform(-30,30))%360
_prescatter(layout)

def run(cmd):
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return (p.stdout or "") + (p.stderr or "")

def centroid(hs):
    return (sum(h[0] for h in hs)/len(hs), sum(h[1] for h in hs)/len(hs))

def apply(actions):
    for a in actions:
        op=a.get("op")
        if op=="move" and a.get("target") in ("well","wheel","tree","rocks"):
            layout[a["target"]][0]+=int(a.get("dx",0)); layout[a["target"]][1]+=int(a.get("dy",0))
        elif op=="move_house":
            i=int(a.get("index",-1))
            if 0<=i<len(layout["houses"]):
                layout["houses"][i][0]+=int(a.get("dx",0)); layout["houses"][i][1]+=int(a.get("dy",0))
        elif op=="spread_houses":
            f=float(a.get("factor",1.1)); cx,cy=centroid(layout["houses"])
            for h in layout["houses"]:
                h[0]=cx+(h[0]-cx)*f; h[1]=cy+(h[1]-cy)*f
        elif op=="jitter_house_rot":
            for h in layout["houses"]:
                h[2]=(h[2]+random.uniform(-28,28))%360
        elif op=="scatter_houses":
            amt=float(a.get("amount",350))
            for h in layout["houses"]:
                h[0]+=random.uniform(-amt,amt); h[1]+=random.uniform(-amt,amt); h[2]=(h[2]+random.uniform(-22,22))%360

hist=[]
for it in range(1, MAXITER+1):
    with open(LAYOUT,"w",encoding="utf-8") as f: json.dump(layout,f)
    print(f"\n===== ITER {it} : assemble+render =====")
    try: os.remove(VILLAGE)
    except OSError: pass
    try: os.remove(os.path.join(SCR,"asm_err.txt"))
    except OSError: pass
    run(["py", UE_EXEC, ASSEMBLE, f"Assemble village iter {it}"])
    ok = os.path.exists(VILLAGE)
    print("assemble:", "OK" if ok else "FAIL")
    if not ok:
        try: print("asm_err:", open(os.path.join(SCR,"asm_err.txt"),encoding="utf-8").read()[:400])
        except OSError: pass
        break
    print("----- OpenAI judge -----")
    jout = run(["py", JUDGE, VILLAGE]).strip()
    js = jout
    if "```" in js: js = js.split("```")[1].replace("json","",1)
    try:
        J=json.loads(js)
    except Exception:
        print("JUDGE_PARSE_FAIL:", jout[:300]); break
    score=J.get("score"); verdict=J.get("verdict"); issues=J.get("issues",[]); actions=J.get("actions",[])
    print(f"SCORE={score} VERDICT={verdict}")
    print("ISSUES:", "; ".join(issues[:6]))
    print("ACTIONS:", json.dumps(actions)[:400])
    # snapshot this iter render
    try: shutil.copyfile(VILLAGE, os.path.join(SCR, f"village_iter{it}.png"))
    except Exception: pass
    hist.append({"iter":it,"score":score,"verdict":verdict,"issues":issues})
    if verdict=="NATURAL" or (isinstance(score,(int,float)) and score>=8):
        print(f"\n*** CONVERGED at iter {it} (score {score}) ***"); break
    apply(actions)

with open(os.path.join(SCR,"loop_history.json"),"w",encoding="utf-8") as f:
    json.dump({"history":hist,"final_layout":layout}, f, ensure_ascii=False, indent=1)
print("\n===== LOOP DONE =====")
print(json.dumps(hist, ensure_ascii=False))
