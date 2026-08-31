# -*- coding: utf-8 -*-
# 독립 심판(장면 배치): 마을 렌더 1장을 보고 "배치가 자연스러운가" 판정 → JSON(점수+액션).
# 레퍼런스 불필요. 하네스 scene-loop 규칙 기반. 키는 .env에서.
# usage: py cmp_openai_scene.py <village_render.png>
import json, base64, os, sys, urllib.request

def _key():  # 환경변수 → VRKIT_ENV_FILE → web/.env → scripts/.env → ~/.vrkit/.env (프로젝트 경로 하드코딩 금지)
    if os.environ.get("OPENAI_API_KEY"): return os.environ["OPENAI_API_KEY"]
    h=os.path.dirname(os.path.abspath(__file__)); c=[]
    if os.environ.get("VRKIT_ENV_FILE"): c.append(os.environ["VRKIT_ENV_FILE"])
    c+=[os.path.join(h,"..","web",".env"), os.path.join(h,".env"),
        os.path.join(os.path.expanduser("~"),".vrkit",".env")]
    for p in c:
        try:
            if p and os.path.isfile(p):
                for line in open(p,encoding="utf-8",errors="ignore"):
                    s=line.strip()
                    if s.startswith("OPENAI_API_KEY") and "=" in s:
                        v=s.split("=",1)[1].strip().strip('"').strip("'")
                        if v: return v
        except Exception: pass
    return None
key=_key()
if not key: print(json.dumps({"error":"NO_KEY"})); sys.exit(1)

RENDER = sys.argv[1] if len(sys.argv)>1 else "village.png"
def durl(p):
    with open(p,"rb") as fp: b=fp.read()
    return "data:image/png;base64,"+base64.b64encode(b).decode()

prompt = (
 "You are an environment art director reviewing a 3D blockout of a Later-Baekje era Korean hanok VILLAGE, "
 "viewed from outside a fortress wall at dusk. Judge ONLY the NATURALNESS of the LAYOUT/placement, not textures or poly detail.\n"
 "A natural village should have: houses loosely clustered and varied in rotation (NOT a rigid grid, NOT all identical angle), "
 "a well near the houses, a water mill at the settlement edge (where a stream would run), a large sacred tree as a landmark with open space around it, "
 "and rocks scattered at the outskirts. Nothing should float above ground, overlap/intersect other objects, or be evenly/gridded.\n"
 "Return STRICT JSON only with this schema:\n"
 '{"score": <0-10 int>, "verdict": "NATURAL"|"ADJUST", "issues": [<short strings>], '
 '"actions": [ objects from this vocabulary ONLY: '
 '{"op":"move","target":"well"|"wheel"|"tree"|"rocks","dx":<cm int>,"dy":<cm int>}, '
 '{"op":"move_house","index":<int>,"dx":<cm int>,"dy":<cm int>}, '
 '{"op":"spread_houses","factor":<float 0.6-1.6>}, '
 '{"op":"jitter_house_rot"}, '
 '{"op":"scatter_houses","amount":<cm int 200-600>} ] }\n'
 "If houses look aligned/gridded/in-a-row, PREFER scatter_houses (breaks rows) over spread_houses. "
 "score>=8 means verdict NATURAL and actions can be empty. Keep actions <=5, each a concrete fix for a real issue you SEE. "
 "dx=+east/-west, dy=+north/-south, in centimeters (typical village move 200-1200)."
)
body=json.dumps({
  "model":"gpt-4o",
  "response_format":{"type":"json_object"},
  "messages":[{"role":"user","content":[
     {"type":"text","text":prompt},
     {"type":"text","text":"Village render:"},
     {"type":"image_url","image_url":{"url":durl(RENDER)}},
  ]}],
  "max_tokens":700, "temperature":0.3
}).encode()
req=urllib.request.Request("https://api.openai.com/v1/chat/completions", data=body,
     headers={"Authorization":"Bearer "+key,"Content-Type":"application/json"})
try:
    with urllib.request.urlopen(req, timeout=120) as r:
        data=json.loads(r.read())
    print(data["choices"][0]["message"]["content"])
except urllib.error.HTTPError as e:
    print(json.dumps({"error":"HTTP","code":e.code,"body":e.read().decode(errors="replace")[:400]}))
except Exception as e:
    print(json.dumps({"error":repr(e)[:200]}))
