# scripts — 검증된 실행 스크립트 (후삼국에서 실제로 통한 것)

경로·API키는 그 프로젝트 실측값이라, 새 프로젝트에선 상단 상수를 자기 것으로 바꾼다.
자세한 흐름은 `../RUN.md`, 도구·값은 `../harness/pipeline.md`.

## 범용 도구 (그대로 재사용)
| 스크립트 | 역할 | 실행 위치 |
|---|---|---|
| `gen_prop_image.py <key>` | gpt-image-1 컨셉 이미지 (단일객체·투명배경). PROMPTS 딕셔너리에 프롬프트 | 일반 파이썬(.env 키) |
| `gen_prop_3d.py <img> <out.glb>` | 독립 Hunyuan3D-2 단일 image→3D (shape+paint+감폴리) | **Hunyuan3D-2 venv** |
| `gen_props_batch.py` | 여러 개 배치 (모델 1회 로드). PROPS 리스트 편집 | **Hunyuan3D-2 venv** |
| `ue_exec.py <script.py> "<desc>"` | 언리얼 execute_script REST 브릿지(:3000) + 폴링 | 일반 파이썬 |
| `import_ai_all.py` | glb 일괄 임포트 + Nanite off + `M_*_AI` 텍스처 머티리얼 생성 (aiprops.json 읽음) | ue_exec 경유(UE python) |
| `import_shoot.py` | glb 1개 임포트+스폰+SceneCapture QC 렌더 (aiprop.json) | ue_exec 경유 |
| `fix_ai_mat.py` | 임포트된 텍스처로 머티리얼 재생성 후 재렌더 | ue_exec 경유 |
| `export_glb.py` | 현재 레벨을 자체완결 GLB로 export (메시+텍스처+조명) | ue_exec 경유 |
| `cmp_openai.py <concept> <render>` | 레퍼런스 대조 심판(gpt-4o) — "없는 요소" 찾기 | 일반 파이썬 |
| `cmp_openai_scene.py <render>` | 배치 자연스러움 심판(gpt-4o) → JSON(score+actions) | 일반 파이썬 |

## 프로젝트 특화 = 패턴 참고본 (복사해서 자기 씬에 맞게 수정)
| 스크립트 | 역할 |
|---|---|
| `assemble.example.py` | 씬 조립 엔진: layout.json 읽어 집·프롭 배치 + 노을 조명 + 이펙트 + SceneCapture 렌더. **build_*/place_ai/setup_effects 패턴** 참고 |
| `scene_place_loop.example.py` | 자동 배치 오케스트레이터: 초기 layout → assemble → cmp_openai_scene 심판 → 재배치 반복 |

## 핵심 주의 (스크립트에 녹아있음)
- 라이트 색 = `set_light_color(LinearColor(r,g,b,1))` (`unreal.Color()` 위치인자 BGRA 뒤집힘)
- 임포트 메시 Nanite off, 렌더 RT는 RTF_RGBA8
- 사용자 수동 수정 후엔 assemble 재실행 금지(clear+재빌드)
- 기본 SkyLight 미개입 / API키 파일에서만
