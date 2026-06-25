로컬 FFmpeg (시스템 PATH 불필요)

1) Gyan full_build 등의 bin 에서 다음 두 파일만 이 폴더에 두면 됩니다.
   ffmpeg.exe
   ffprobe.exe

   경로 예:
   wisdom/tools/ffmpeg/bin/ffmpeg.exe
   wisdom/tools/ffmpeg/bin/ffprobe.exe

2) Video Studio 실행 시와 scenevid CLI 시작 시 위 경로가 프로세스 PATH 앞에 붙고,
   내부 호출도 절대 경로로 FFmpeg/fprobe 를 씁니다. 시스템에 FFmpeg 설치 안 해도 동작합니다.

3) (참고) 일부 FFmpeg 빌드는 같은 bin 의 DLL 여러 개가 필요할 수 있습니다. 실행 시 DLL
   오류가 나면 Gyan 패키지의 bin 전체를 복사하세요.
