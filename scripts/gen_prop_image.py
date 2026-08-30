# -*- coding: utf-8 -*-
# 프롭 컨셉 생성 (gpt-image-1, text->image). 단일객체·투명배경·균일광(노을은 언리얼에서).
# ★ topic 무관: 에셋 설명을 인자/props.json 로 받는다 (후삼국 등 특정 예시 하드코딩 금지).
#
# usage:
#   py gen_prop_image.py <name> "<무엇인지 한 줄 설명>" ["<스타일 앵커>"]
#   py gen_prop_image.py <name>        → out/props.json 의 {name:{desc, style}} 조회
#
# out/props.json 예: { "well": {"desc":"돌 우물, 나무 지붕", "style":"조선 저잣거리, 노을"} }
import json, base64, os, sys, urllib.request, urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))

# 키: 환경변수 우선, 없으면 web/.env, 그다음 알려진 경로
def _load_key():
    if os.environ.get("OPENAI_API_KEY"):
        return os.environ["OPENAI_API_KEY"]
    cands = [os.path.join(HERE, "..", "web", ".env"),
             r"C:\Users\ACE\Desktop\bobs_project\Core-CBT\.env"]
    for p in cands:
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
    return None

# ★ 고품질 게임 에셋 레퍼런스 템플릿 (topic 무관)
STUDIO = ("Single object, centered, full object in frame, isometric 3/4 view, "
          "plain transparent background, soft even studio lighting (no harsh shadows, no colored light). "
          "Clean high-detail game-asset reference, physically-based, crisp sharp focus, "
          "high fidelity, professional 3D concept art, no text, no watermark, no people, no clutter.")

name = sys.argv[1] if len(sys.argv) > 1 else None
desc = sys.argv[2] if len(sys.argv) > 2 else None
style = sys.argv[3] if len(sys.argv) > 3 else ""

if not name:
    print("usage: gen_prop_image.py <name> \"<desc>\" [style]"); sys.exit(1)

# 설명이 없으면 props.json 에서 조회
if not desc:
    pj = os.path.join(HERE, "out", "props.json")
    if os.path.isfile(pj):
        try:
            m = json.load(open(pj, encoding="utf-8"))
            item = m.get(name, {})
            desc = item.get("desc"); style = style or item.get("style", "")
        except Exception:
            pass
if not desc:
    print("설명 없음: 인자로 desc를 주거나 out/props.json에 %s 를 넣어라" % name); sys.exit(1)

key = _load_key()
if not key:
    print("NO_KEY"); sys.exit(1)

prompt = "%s. %s. %s" % (desc, style, STUDIO)
body = json.dumps({"model": "gpt-image-1", "prompt": prompt, "size": "1024x1024",
                   "n": 1, "quality": "high", "background": "transparent"}).encode()
req = urllib.request.Request("https://api.openai.com/v1/images/generations", data=body,
                             headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
try:
    with urllib.request.urlopen(req, timeout=300) as r:
        data = json.loads(r.read())
    os.makedirs(os.path.join(HERE, "out"), exist_ok=True)
    p = os.path.join(HERE, "out", "prop_%s.png" % name)
    with open(p, "wb") as im:
        im.write(base64.b64decode(data["data"][0]["b64_json"]))
    print("OK", p)
except urllib.error.HTTPError as e:
    print("HTTP_FAIL", e.code, e.read().decode(errors="replace")[:500])
except Exception as e:
    print("FAIL", repr(e)[:300])

# ── (참고) 예시 프롬프트: 후삼국 마을. 이 파일에 하드코딩하지 말고 props.json/인자로 넘길 것.
#   well: "돌 우물(원형 돌담+나무 지붕+두레박)"  house_a: "일자형 한옥(기와 박공지붕)" 등
