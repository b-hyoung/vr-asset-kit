# 4.5 언리얼 임포트

UnrealClaude MCP로 **직접** 임포트·스폰·배치.

## 함정 (실측)
- **저폴리 메시가 Nanite면 렌더에 안 보임** → Nanite 끄기
- glTF 임포트가 base color 미연결 → 임포트 텍스처로 **`M_*_AI` 머티리얼 직접 생성**
- 에디터 백그라운드면 뷰포트 캡처가 stale → SceneCapture2D로 렌더(RTF_RGBA8)
