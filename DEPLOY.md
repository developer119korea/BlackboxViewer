### BlackboxViewer 맥OS 앱 빌드 및 배포 가이드

본 문서는 파이썬 기반 맥OS 애플리케이션 BlackboxViewer를 독립 실행형 앱(.app) 및 설치용 디스크 이미지(.dmg)로 빌드하는 과정을 안내합니다. 

특히 개발 환경과 달리 빌드된 가상 환경에서 발생하는 [Errno 2] No such file or directory: 'ffprobe' 에러 해결 방안을 포함하고 있습니다. 

### 1. 사전 준비 사항 (Prerequisites)

빌드를 진행하기 전, 개발 환경에 아래 패키지들이 설치되어 있어야 합니다. 

bash

# Homebrew 및 멀티미디어 처리를 위한 FFmpeg 설치

brew install ffmpeg

# DMG 패키징 도구 설치

brew install create-dmg

코드를 사용할 때는 주의가 필요합니다.

### 2. 배포용 앱 빌드 (PyInstaller)

일반 사용자의 컴퓨터에 ffmpeg나 ffprobe가 설치되어 있지 않더라도 앱이 정상 작동할 수 있도록, **바이너리 파일을 앱 패키지 내부에 포함(Embedding)**하여 빌드합니다. 

### 코드 확인 (필수)

main.py 라이브러리 임포트 최상단에 빌드된 가상 경로(sys.\_MEIPASS)를 시스템 PATH에 주입하는 코드가 포함되어 있어야 합니다. 

python

import os
import sys

if getattr(sys, 'frozen', False):
base_path = sys.\_MEIPASS
if base_path not in os.environ["PATH"]:
os.environ["PATH"] = base_path + os.pathsep + os.environ["PATH"]

코드를 사용할 때는 주의가 필요합니다.

### 앱 빌드 명령어 실행

터미널에서 가상환경(venv)을 활성화한 후, 프로젝트 루트에서 아래 명령어를 실행합니다. 입력 요구 프롬프트를 건너뛰기 위해 --noconfirm 옵션을 사용합니다. 

bash

pyinstaller --windowed --noconfirm \
 --name "BlackboxViewer" \
 --icon="cobra_wheels.icns" \
 --add-binary "/opt/homebrew/bin/ffmpeg:." \
 --add-binary "/opt/homebrew/bin/ffprobe:." \
 main.py

코드를 사용할 때는 주의가 필요합니다.

- 빌드가 완료되면 프로젝트 루트의 dist/BlackboxViewer.app 경로에 앱이 생성됩니다.

### 3. DMG 디스크 이미지 패키징 (create-dmg)

사용자가 앱을 쉽게 설치할 수 있도록 Applications 바로가기가 포함된 .dmg 파일을 생성합니다. 

AppleScript 오작동 방지를 위해 --icon 옵션에는 호스트 경로가 아닌 **DMG 내부의 순수 앱 파일명**을 지정해야 합니다. 

bash

create-dmg \
 --volname "CobraWheels" \
 --volicon "cobra_wheels.icns" \
 --window-pos 200 120 \
 --window-size 600 300 \
 --icon-size 100 \
 --icon "BlackboxViewer.app" 175 120 \
 --app-drop-link 425 120 \
 "BlackboxViewer.dmg" \
 "dist/BlackboxViewer.app"

코드를 사용할 때는 주의가 필요합니다.

- 성공적으로 완료되면 루트 디렉토리에 BlackboxViewer.dmg 파일이 생성됩니다.

### 4. 주요 트러블슈팅 (Troubleshooting)

### Q1. 빌드된 앱 실행 시 ffprobe를 찾을 수 없다는 에러가 발생합니다.

- **원인:** 맥OS .app 패키지는 실행 시 터미널의 환경변수(PATH)를 상속받지 못해 외부 경로(/opt/homebrew/bin)에 있는 ffprobe를 탐색하지 못합니다.
- **해결책:** 빌드 시 --add-binary 옵션으로 바이너리를 앱 내부에 삽입하고, 파이썬 코드 최상단에서 sys.\_MEIPASS를 통해 해당 바이너리가 포함된 내부 임시 경로를 PATH 환경변수에 추가하여 해결했습니다. (일반 사용자 환경에서 별도 설치 불필요)

### Q2. PyInstaller 빌드 중 Continue? (y/N) 프롬프트에서 키보드 입력이 안 됩니다.

- **원인:** 특정 터미널 및 가상환경에서 대화형 프롬프트 입력이 먹통이 되는 현상입니다.
- **해결책:** 명령어에 --noconfirm (또는 -y) 옵션을 추가하여 기존 dist 디렉토리를 자동으로 삭제하고 덮어쓰도록 강제했습니다.
