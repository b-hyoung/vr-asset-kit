# 실행 파이프라인 (검증본) — 도구·명령·값·레시피

후삼국 마을 VR을 실제로 완주하며 **통한 것만** 적는다. `RUN.md`가 이 문서를 참조한다.
경로는 그 프로젝트 실측값이므로, 새 프로젝트에선 `[ ]` 부분을 자기 것으로 바꾼다.

## 0. 도구 스택 (실제로 쓴 것)
| 역할 | 도구 | 비고 |
|---|---|---|
| 컨셉 이미지 | **OpenAI gpt-image-1** (images API) | 키는 `.env`에서만. 단일객체·투명배경·균일광 |
| image→3D | **독립 Hunyuan3D-2** (로컬 GPU) | ★Blender MCP 통합이 아니라 **standalone**으로 돌림 |
| 언리얼 조종 | **UnrealClaude MCP** (Natfii, UE5.7) | STDIO 노드 브릿지 + REST `:3000` |
| 배치 심판 | **OpenAI gpt-4o** (vision) | 독립 심판, JSON(score+actions) |

## 1. 컨셉 이미지 (gpt-image-1)
`scripts/gen_prop_image.py <key>` → `out/prop_<key>.png`. 프롬프트 규칙:
- **단일 객체·중앙·전체 프레임·isometric 3/4·투명배경·균일 스튜디오광** (노을 그림자를 텍스처에 굽지 않기 위해)
- 한국풍 고증 문구 + **배제 명시**(일본/중국 처마·홍칠·종이등롱·현대물)
- images/generations, `background:"transparent"`, quality high

## 2. image→3D (독립 Hunyuan3D-2)
venv: `[image3d]\venv\Scripts\python.exe`, cwd: `[image3d]\Hunyuan3D-2`.
`scripts/gen_props_batch.py` 패턴 (여러 개 = shape 1회 + paint 1회 로드로 효율):
```
rembg → Hunyuan3DDiTFlowMatchingPipeline(shape) → FloaterRemover/DegenerateFaceRemover/FaceReducer(20000)
     → Hunyuan3DPaintPipeline(paint, image) → export glb
```
- 원시 ~100만~200만 폴리 → **FaceReducer 2만**으로 감폴리 필수
- paint의 VAE `.safetensors 없음` 경고는 **`.bin` 폴백이라 무시** 가능
- 결과 glb ~3MB (텍스처 포함). 하드서피스도 이번엔 잘 나옴

## 2.5 Blender 수정/후처리 (필요 시 — Hunyuan 결과가 완벽하지 않을 때)
Hunyuan glb를 Blender로 열어 정리 후 재export. 언리얼 없이 가능.
- **스케일·정렬**: 정규화된 크기를 실측(미터)으로, 바닥(z=0) 정렬, 방향 보정
- **지오메트리 정리**: 구멍/플로터/디제너릿 제거, 필요 시 데시메이트(폴리 예산)
- **UV**: Smart UV Project (없으면 텍스처 깨짐). ★단, **베이크용 UV와 원본 텍스처 UV를 분리**(smart_project가 원본 UV를 덮어쓰면 색이 날아감)
- **★발광 요소(창문·불꽃 등) = emission 맵을 albedo와 따로 베이크**:
  - 창문 발광은 albedo에 구우면 회색이 됨 → **albedo 맵**(밝기 살짝↑)과 **emission 맵**(밝은 부분만 남게 대비↑, 벽·지붕은 emission 0)을 **두 번 EMIT 베이크**
  - 최종 머티리얼 = base color(albedo) + emission color(emit)×강도
  - (BOX projection 머티리얼은 glTF export가 안 되니, 베이크로 텍스처화)
- 정리된 glb로 export → 단계 4.5 임포트

## 3. 언리얼 임포트 + 머티리얼
`scripts/import_ai_all.py` (aiprops.json 목록 읽어 일괄):
1. `AssetImportTask`로 glb 임포트 (Interchange)
2. ★**StaticMesh Nanite 끄기** — 저폴리 Nanite는 렌더에 안 보임
3. ★glTF가 텍스처는 넣는데 **base color 미연결** → 임포트된 Texture2D로 `M_<Name>_AI`(TextureSample→BaseColor, rough 0.82) 직접 생성해 메시에 assign

## 4. 언리얼 execute_script REST 브릿지
UnrealClaude MCP는 숨김툴(execute_script)을 안 노출하므로 **REST로 직접 호출**:
`scripts/ue_exec.py <script.py> "<description>"` → `POST http://localhost:3000/mcp/tool/execute_script`
- `description` 파라미터 **필수**
- Project Settings → Plugins → Unreal Claude → **Auto-approve script execution** 켜면 팝업 없이 실행
- 태스크 큐 → `task_result` 폴링

## 5. 렌더 (SceneCapture2D)
에디터가 백그라운드면 뷰포트/HighResShot이 **stale**. 반드시 SceneCapture2D로:
```
RL.create_render_target2d(world, W, H, RTF_RGBA8)   # ★RGBA8라야 export가 PNG (RGBA16f면 HDR로 깨짐)
SceneCapture2D + SCS_FINAL_COLOR_LDR → capture_scene() → export_render_target(png)
```

## 6. 자동 배치 루프
`scripts/scene_place_loop.py` → `assemble.py`(조립+렌더) → `cmp_openai_scene.py`(gpt-4o JSON) → 재배치 반복.
- 액션: move/move_house/spread_houses/jitter_house_rot/scatter_houses
- 성공 판정은 **village.png 파일 존재**로 (출력 파싱은 UE 로그가 길어 잘림)

## 7. 노을(골든아워) 레시피 — 값
- DirectionalLight: **pitch -2~-3**(태양 지평선), intensity ~6-7, **use_temperature=True + temperature 3000~3800K**
- 라이트 색: **`comp.set_light_color(unreal.LinearColor(r,g,b,1))`** (0~1 float). ⛔`unreal.Color(r,g,b)` 위치인자는 **BGRA로 R↔B 뒤집힘 → 주황이 파랑**
- ⛔ **기본 SkyLight 미개입** (사용자 하드룰). 노을은 태양+Fog로만
- Fog: directional_inscattering_color 따뜻, volumetric on/off 취향 (on이면 어두워짐)
- 노출: PostProcess auto_exposure_bias ~0.8-1.0 override
- PointLight(등불): use_temperature=False + set_light_color 따뜻

## 8. 내보내기
`scripts/export_glb.py` → 레벨을 자체완결 **GLB**(메시+텍스처 내장 + KHR_lights_punctual 조명 포함). USDZ는 Mac에서 Reality Converter로. **하늘·안개·노출은 안 감** → 타깃 재세팅.

## 값 기준 (Quest VR, 프로젝트별로 조정)
폴리 예산·텍스처 크기·미터 단위·네이밍은 프로젝트 `docs/`의 project-spec에 고정한다.
후삼국 실측: 프롭 감폴리 2만, Hunyuan 텍스처 2048, glb ~3MB/에셋.
