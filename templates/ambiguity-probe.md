# 모호어 분해 프로브: 스펙트럼 4장

`meta.md` §8 실행 절차. 브리프의 형용사를 텍스트로 묻지 않고 **이미지로 고르게 한다.**

## 언제 쓰나

브리프에 이런 단어가 있을 때: 판타지풍, 소박한, 미래적인, 자연스럽게, 웅장한, 아늑한,
사실적인, 몽환적인 — **AI가 해석하면 안 되는 모든 수식어.**

## 절차

1. 모호어 1개를 고른다 (한 번에 하나씩 — 두 개를 섞으면 뭘 고른 건지 알 수 없다)
2. **공통 베이스 프롬프트**를 쓴다 — 4장 모두에 그대로 붙는다. 여기에 배제 요소를 전부 넣는다
3. 베이스에 **강도 변주 4단계**만 덧붙여 4장 생성 (권장 size 1536x1024, 각 1장)
4. 사용자에게 보여주고 하나를 고르게 한다. 불합격이면 사유를 배제 요소에 추가하고 재생성(최대 3회)
5. 선택된 것을 장면 브리프의 "확정된 정의" 표에 기록 → 그 이미지가 **스타일 앵커**

## 베이스 프롬프트 뼈대

```
[매체: Concept art / photoreal render 등],
[시점·구도: 슬롯 3],
[대상: 슬롯 1],
[시간대·분위기: 슬롯 5],
[필수 요소: 슬롯 6].
[배제 요소: 슬롯 7 — "ONLY X, NOT Y: no A, no B, no C" 형식으로 강하게]
```

배제는 부드럽게 쓰면 안 먹는다. `ONLY ... — NOT ...: no ..., no ...` 형식으로 나열한다.

## 강도 변주 4단계 (모호어에 맞춰 바꿔 쓴다)

| # | 라벨 | 변주 방향 |
|---|---|---|
| 1 | 은은한 | 그 성질을 **최소한**으로. 사실적·절제된 톤, 암시적 디테일만 |
| 2 | 중간 | 살짝 고조. 라이팅·채도로만 표현, 여전히 믿을 만한 수준 |
| 3 | 뚜렷한 | 눈에 보이게. 명시적 요소가 화면에 존재, 극적인 하늘·빛 |
| 4 | 하이 | 재해석 수준. 물리적으로 불가능한 요소 허용, 압도적 스케일 |

## 예시 (후삼국 프로젝트 · "판타지풍")

베이스:
```
Concept art, aerial view from a fortress gate looking down at a small Korean thatched-roof
village at dusk, Later Three Kingdoms period of Korea (9th century), humble straw-roof houses
(chogajip) with mud walls, dirt paths, wooden fences, clay jar terraces.
Korean traditional architecture ONLY — NOT Japanese, NOT Chinese: no curved pagoda roofs,
no red lacquer, no paper lanterns hanging in rows, no modern objects.
```

1. 은은한 — `Grounded historical look, muted natural colors, only subtle folk-belief details: a sacred tree with straw rope, small flags. No magical effects.`
2. 중간 — `Slightly heightened atmosphere: warm glowing windows, faint mist, saturated sunset sky, banners with symbolic patterns. Still believable.`
3. 뚜렷한 — `Visible fantasy: softly glowing patterns on banners, floating lantern lights drifting above paths, luminous mist, dramatic sky.`
4. 하이 — `High fantasy reinterpretation: giant spirit tree over the village, glowing runes, impossible rock spires in background, ethereal light.`

베이스는 고정, 뒷부분만 교체된 것에 주목 — **변수는 하나여야 비교가 성립한다.**
