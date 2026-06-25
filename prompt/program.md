프로그램은 루트 하위에 폴더구조로 생성한다.
build는 빌드에 필요한 프로그램 및 파일이 위치한다.
dist는 파이썬 빌드 후 exe 프로그램이 위치한다.
output은 exe 실행 후 산출물이 위치한다.

개별 프로그램은 각 모듈 폴더의 `build`·`dist`·`output`을 사용한다.

```
wisdom
   |- elevenlabs_tts_subtitle
   |   |- build
   |   |- dist
   |   `- output
   |- image_prompt_pipeline
   |   |- build
   |   |- dist
   |   `- output
   |- knowledge_channel_tts
   |   |- build
   |   |- dist
   |   `- output
   |- manuscript_700_splitter
   |   |- build
   |   |- dist
   |   `- output
   ...
```
