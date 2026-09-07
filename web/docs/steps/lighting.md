# 6. 조명·시간대 선택

> ⛔ **노을은 기본값이 아니다.** 시간대는 사용자가 고르는 값이고, 고른 프리셋 하나만 적용한다.
> 아무것도 고르지 않았으면 **조명을 건드리지 않는다** (임의로 노을을 넣지 말 것).

## 어떻게 고르나
웹 이 단계에서 카드로 하나 선택 → `state.json` 의 `inputs.lighting` 에 id 로 저장된다.
값 표는 **`web/lighting.json`** 에 있고 직접 고쳐도 된다(서버가 `/api/lighting` 로 읽어 온다).

## 적용
```
py -u scripts/apply_lighting.py --project <프로젝트id>   # 고른 프리셋을 에디터에 적용
py -u scripts/apply_lighting.py --list                   # 프리셋 목록
py -u scripts/apply_lighting.py noon --dry-run           # 값만 확인
```
`--project` 인데 선택이 비어 있으면 **아무것도 하지 않고 끝난다.**
에디터 안에서 도는 실제 스크립트는 `scripts/ue/apply_lighting.py` 이고,
`scripts/apply_lighting.py` 가 스크래치에 써 둔 `lighting.json` 만 읽는다.

## 프리셋

| id | 이름 | 태양 pitch / 색온도 | 쓰는 자리 |
|---|---|---|---|
| `none` | 손대지 않음 | — | 조명을 이미 잡아뒀거나 나중에 직접 잡을 때 |
| `dusk` | 노을(골든아워) | -3 / 3600K | 따뜻한 주황·긴 그림자 (**실측값**) |
| `noon` | 한낮 | -55 / 6000K | 에셋 원색 확인, 밝고 그림자 짧음 |
| `overcast` | 흐림·비 | -40 / 6800K | 낮은 대비, 젖은 바닥·수면 |
| `dawn_fog` | 새벽·안개 | -2 / 7600K | 푸른 기 + 짙은 안개로 거리 지우기 |
| `night_moon` | 밤·달빛 | -12 / 9000K | 인공광(화로·등불)이 주광일 때 |
| `indoor_neutral` | 실내·중립 | -60 / 5500K | 실내·검수용 중립광 |

정확한 수치(안개 밀도·인스캐터링 등)는 `web/lighting.json` 이 원본이다. 이 표는 요약이다.

## ⛔ 하드룰 (프리셋과 무관하게 항상)
- **기본 SkyLight 는 절대 건드리지 않는다** (사용자 지시).
- 라이트 색은 **`set_light_color(LinearColor(r,g,b,1))`** 로. `FColor` 위치인자는 BGRA 로 뒤집혀 파래진다.
- 적용 뒤 판정은 **`render_360` 8방향 평균 밝기**로 한다 — 밝은 쪽 한 컷만 보고 통과시키지 않는다.
  ```
  python -u scripts/ue_exec.py scripts/ue/render_360.py "360 check" --grep CHECK360
  ```
- `night_moon` / `indoor_neutral` 은 태양만으로 평균 밝기 6 을 못 넘긴다 — 인공광·채움광을 같이 넣는다.
