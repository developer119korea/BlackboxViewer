# BlackboxViewer

macOS 용 4채널 블랙박스 영상(.avi) 뷰어 겸 채널 추출기.

## 기능

- 폴더/파일 선택으로 `.avi` 재생목록 구성 (폴더 선택 시 하위 폴더까지 재귀 탐색)
- 재생목록에서 파일 선택 시 4개 채널(F/B/L/R)을 **동시에** 미리보기
- 재생 / 일시정지 / 정지 지원
- 선택한 파일 또는 재생목록 전체를 대상으로 채널별 mp4 추출

## 설치

```bash
# ffmpeg 설치 (없다면)
brew install ffmpeg

# 가상환경 및 의존성 설치
cd BlackboxViewer
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## 실행

```bash
python3 main.py
```

## 사용법

1. 상단 "폴더 열기" 또는 "파일 열기"로 `.avi` 파일을 재생목록에 추가합니다.
2. 재생목록에서 파일을 클릭하면 파일이 분석되고, 각 채널 미리보기 영역이 활성화됩니다.
3. "▶ 재생"을 누르면 4개 채널이 동시에 재생됩니다.
4. 채널을 mp4로 추출하려면
   - 재생목록에서 파일(복수 선택 가능)을 선택 후 "선택 파일 채널 추출", 또는
   - "전체 목록 채널 추출"
     을 누르고 저장 폴더를 선택합니다. (취소하면 원본과 같은 폴더에 저장)

## 채널 매핑 변경

비디오 스트림 순서(0,1,2,3)에 대응하는 접미사는
`ffmpeg_utils.py` 의 `DEFAULT_CHANNEL_SUFFIXES = ["F", "B", "L", "R"]` 에서
바꿀 수 있습니다.

## 참고

- 미리보기는 각 채널을 `ffmpeg`로 raw 프레임 디코딩하여 표시하는 방식이라
  4채널이 프레임 단위로 완벽히 맞물리지는 않지만, 확인 용도로는 충분히
  동기화되어 보입니다. (정밀한 동기화가 필요하면 재생 속도를 다소 낮추거나
  프레임 스킵 로직을 추가하는 방향으로 확장할 수 있습니다.)
- 채널 추출은 재인코딩 없이 `-c copy`를 사용하므로 매우 빠릅니다.
- 오디오 스트림이 없는 파일은 `-map 0:a:0` 없이 비디오만 추출합니다.

## 프로젝트 구조

```
BlackboxViewer/
├── main.py                 # GUI 진입점
├── ffmpeg_utils.py          # ffprobe/ffmpeg 명령 생성 및 스트림 분석
├── video_stream_worker.py   # 채널별 미리보기 디코딩 스레드
├── extract_worker.py        # 채널 추출(mp4) 백그라운드 스레드
├── requirements.txt
└── README.md
```
