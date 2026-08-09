"""extract_worker.py
선택된 .avi 파일(들)에 대해 채널별 mp4 추출(ffmpeg -c copy)을
백그라운드에서 수행하고 진행 상황을 시그널로 알려주는 워커.
"""
import subprocess
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import QThread, Signal

from ffmpeg_utils import probe_file, build_extract_commands


class ExtractWorker(QThread):
    fileStarted = Signal(str)             # source file path
    channelDone = Signal(str, str)        # source file path, output file path
    fileDone = Signal(str, bool, str)     # source file path, success, message
    allDone = Signal()

    def __init__(self, files: List[Path], out_dir: Optional[Path], parent=None):
        super().__init__(parent)
        self.files = files
        self.out_dir = out_dir
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        for f in self.files:
            if self._cancel:
                break
            self.fileStarted.emit(str(f))
            try:
                info = probe_file(f)
                if not info.video_streams:
                    self.fileDone.emit(str(f), False, "비디오 채널을 찾을 수 없습니다.")
                    continue

                target_dir = self.out_dir if self.out_dir else f.parent
                target_dir.mkdir(parents=True, exist_ok=True)
                commands = build_extract_commands(f, target_dir, info.video_streams, info.has_audio)

                ok = True
                err_msg = ""
                for cmd in commands:
                    if self._cancel:
                        ok = False
                        break
                    result = subprocess.run(cmd, capture_output=True, text=True)
                    if result.returncode != 0:
                        ok = False
                        err_msg = result.stderr[-500:] if result.stderr else "알 수 없는 오류"
                        break
                    self.channelDone.emit(str(f), cmd[-1])

                self.fileDone.emit(str(f), ok, "완료" if ok else err_msg)
            except Exception as exc:
                self.fileDone.emit(str(f), False, str(exc))

        self.allDone.emit()
