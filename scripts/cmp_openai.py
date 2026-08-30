# -*- coding: utf-8 -*-
# 독립 심판: OpenAI 비전으로 콘셉트 vs 렌더 대조 → 차이 목록. 키는 .env에서.
import json, base64, os, sys, urllib.request

ENV = r"C:\Users\ACE\Desktop\bobs_project\Core-CBT\.env"
key=None
with open(ENV, encoding="utf-8") as f:
    for line in f:
        s=line.strip()
        if s.startswith("OPENAI_API_KEY"):
            key=s.split("=",1)[1].strip().strip('"').strip("'"); break
if not key: print("NO_KEY"); sys.exit(1)

D = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
CONCEPT = sys.argv[1] if len(sys.argv)>1 else os.path.join(D,"hanok_style_2.png")
RENDER  = sys.argv[2] if len(sys.argv)>2 else os.path.join(D,"v3_render.png")

def durl(p):
    with open(p,"rb") as fp: b=fp.read()
    return "data:image/png;base64,"+base64.b64encode(b).decode()

prompt = (
 "You are a 3D art director doing a reference-match review for a Korean hanok asset.\n"
 "Image 1 = TARGET concept. Image 2 = 3D render built from it.\n"
 "List ONLY concrete elements that are in the concept but MISSING or clearly DIFFERENT in the render "
 "(e.g., door, number/placement of windows, window lattice, stone base, roof shape/curve, proportions, overall tone/brightness, color).\n"
 "Format each line: ELEMENT | what's different | severity(high/med/low) | how to fix in 3D.\n"
 "IGNORE atmospheric effects that are added later in-engine: floating lanterns, mist, fog, glow haze, smoke.\n"
 "Max 6 lines. If they essentially match, output exactly: MATCH."
)
body=json.dumps({
  "model":"gpt-4o",
  "messages":[{"role":"user","content":[
     {"type":"text","text":prompt},
     {"type":"text","text":"Image 1 (concept target):"},
     {"type":"image_url","image_url":{"url":durl(CONCEPT)}},
     {"type":"text","text":"Image 2 (3D render):"},
     {"type":"image_url","image_url":{"url":durl(RENDER)}},
  ]}],
  "max_tokens":600, "temperature":0.2
}).encode()
req=urllib.request.Request("https://api.openai.com/v1/chat/completions", data=body,
     headers={"Authorization":"Bearer "+key,"Content-Type":"application/json"})
try:
    with urllib.request.urlopen(req, timeout=120) as r:
        data=json.loads(r.read())
    print("=== OpenAI 심판 결과 ===")
    print(data["choices"][0]["message"]["content"])
except urllib.error.HTTPError as e:
    print("HTTP_FAIL", e.code, e.read().decode(errors="replace")[:600])
except Exception as e:
    print("FAIL", repr(e)[:300])
