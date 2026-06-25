# 공통
변경된 프로그램이 있으면 빌드 파일을 수정한다.


# 4_1_video 프로그램 수정
이미지효과 버튼 클릭시 하위의 큐도 클릭한 이미지를 사용하는 구간에만 동일 효과를 적용한다.
이미지 경로에 MP4 동영상도 영상생성시 병합할수 있도록 한다.(이미지효과등 이미지에 국한된 기능은 못사용한다.)
이미지 폴더내 MP4 동영상의 소리는 사용하지 않는다.(오디어MP3 파일만 음성을 출력한다.)


# 4_pngToJpg 프로그램 수정
png 파일을 jpg 파일로 변환한다.
변환시 파일 크기를 최적화 시켜서 영상 합성에 사용될 수 있게 한다.
타임스탬스 계산 로직은 삭제한다.

# 산출물 위치
영상파일은 다음 경로에 위치시킨다.
C:\cursor\wisdom-1\4_1_video\output (O)
C:\Users\PC\AppData\Local\Temp (x)

동영상 생성시 각각의 파일 설정은 아래가 디폴트로 되게 한다.
위치찾기 버튼 클릭시 아래 경로가 우선 지정되어 있어야 한다.
-음성: C:\cursor\wisdom-1\2_1_ttsToVoice\output\all.mp3
-자막: C:\cursor\wisdom-1\2_1_ttsToVoice\output\all.srt
-이미지 : C:\cursor\wisdom-1\2_2_srtToImage\output\
-출력 : C:\cursor\wisdom-1\4_1_video\output\

# 2_2_srtToImage 프로그램 수정


 