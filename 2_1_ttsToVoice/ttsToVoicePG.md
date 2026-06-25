# 2_1_ttsToVoice

## TTS 호흡·쉼 태그

대본 TTS 줄에 넣은 대괄호 태그는 `elsub/elevenlabs_client.prepare_tts_for_api`에서 SSML로 바꿉니다.

| 태그 | 쉼 |
|------|-----|
| `[breathes]` | 0.5s |
| `[short pause]` | 0.4s |
| `[short pause][breathes][continues]` | 1.0s |
| `[continues]` | (제거, 문장 이어 읽기) |

`elsub/tts_merge.py`는 줄 끝 `[breathes]`·`[short pause]`가 있으면 다음 자막과 **한 API 호출로 묶지 않습니다**. 문장부호 없이 이어지는 줄만 붙입니다.

## 파트 첫 줄·첫 음절 품질

파트 2번째 이후 첫 자막에 붙는 `[short pause][breathes][continues]` 는 **API 텍스트 맨 앞 SSML break** 로 넣지 않습니다 (첫 음절이 작거나 깨지는 현상). 대신:

1. 맨 앞 태그 제거 후 본문만 ElevenLabs 합성
2. `prepend_silence_mp3` 로 세그먼트 MP3 앞에 무음(약 1초) 추가
3. 자막 길이 분배 시 `tts_synthesis_weight` 로 선행 무음 구간 반영

GUI: `2_1_ttsToVoice/dist/2_1_ttsToVoice_gui.exe`
