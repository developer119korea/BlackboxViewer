"""BlackboxViewer video stream worker.

A worker is created once per channel and kept alive while the current file
is loaded. Seeking never destroys/recreates the QThread; only the ffmpeg
subprocess is restarted inside the same worker thread.

Seek requests are coalesced: while ffmpeg is being restarted, the newest
requested position replaces older positions. A short debounce also prevents
rapid slider movement from spawning a sequence of ffmpeg processes.
"""

import subprocess
import threading
import time
from typing import Optional

from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QImage


FFMPEG = "ffmpeg"


class VideoStreamWorker(QThread):
    frameReady = Signal(object, QImage)
    positionChanged = Signal(object, float)
    finished_playback = Signal(object)
    errorOccurred = Signal(object, str)

    def __init__(
        self,
        file_path: str,
        stream_index: int,
        suffix: str,
        width: int,
        height: int,
        fps: float,
        start_time: float = 0.0,
        parent=None,
    ):
        super().__init__(parent)

        self.file_path = file_path
        self.stream_index = stream_index
        self.suffix = suffix
        self.width = max(int(width), 2)
        self.height = max(int(height), 2)
        self.fps = fps if fps and fps > 0 else 30.0

        self._start_time = max(float(start_time), 0.0)
        self._position = self._start_time

        self._proc: Optional[subprocess.Popen] = None
        self._state_lock = threading.Lock()

        self._stop_event = threading.Event()
        self._wake_event = threading.Event()
        self._pause_event = threading.Event()
        self._pause_event.set()


    # ------------------------------------------------------------------ control
    def pause(self):
        self._pause_event.clear()

    def resume(self):
        self._pause_event.set()
        self._wake_event.set()

    def stop(self):
        """Stop this worker permanently.

        This is only used when changing files or closing the application.
        A normal seek never calls stop().
        """
        self._stop_event.set()
        self._pause_event.set()
        self._wake_event.set()

        with self._state_lock:
            proc = self._proc

        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
            except Exception:
                pass

    # ------------------------------------------------------------------ run
    def run(self):
        frame_size = self.width * self.height * 3
        current_time = self._start_time
        proc = None

        try:
            proc = self._start_ffmpeg(current_time)
            if proc is None:
                return

            self._set_proc(proc)
            frame_interval = 1.0 / self.fps

            while not self._stop_event.is_set():
                if not self._pause_event.is_set():
                    self._pause_event.wait()
                    continue

                loop_start = time.monotonic()
                raw = self._read_exact(frame_size)

                if raw is None:
                    break

                image = QImage(
                    raw,
                    self.width,
                    self.height,
                    self.width * 3,
                    QImage.Format_BGR888,
                )
                self.frameReady.emit(self.suffix, image.copy())

                current_time += frame_interval
                self._position = current_time

                elapsed = time.monotonic() - loop_start
                sleep_time = frame_interval - elapsed
                if sleep_time > 0:
                    self._wake_event.wait(sleep_time)
                    self._wake_event.clear()

        finally:
            self._cleanup_process()

        if not self._stop_event.is_set():
            self.positionChanged.emit(self.suffix, self._position)

        self.finished_playback.emit(self.suffix)

    # ------------------------------------------------------------------ ffmpeg
    def _start_ffmpeg(self, start_time: float):
        cmd = [
            FFMPEG,
            "-ss", str(max(0.0, start_time)),
            "-i", self.file_path,
            "-map", f"0:v:{self.stream_index}",
            "-f", "rawvideo",
            "-pix_fmt", "bgr24",
            "-vsync", "0",
            "pipe:1",
        ]

        try:
            return subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                bufsize=self.width * self.height * 3 * 2,
            )
        except FileNotFoundError:
            self.errorOccurred.emit(
                self.suffix,
                "ffmpeg 실행 파일을 찾을 수 없습니다. (brew install ffmpeg)",
            )
        except Exception as exc:
            self.errorOccurred.emit(self.suffix, str(exc))

        return None

    def _set_proc(self, proc):
        with self._state_lock:
            self._proc = proc

    def _read_exact(self, n: int) -> Optional[bytes]:
        with self._state_lock:
            proc = self._proc

        if proc is None or proc.stdout is None:
            return None

        buf = bytearray()
        while len(buf) < n and not self._stop_event.is_set():
            try:
                chunk = proc.stdout.read(n - len(buf))
            except (BrokenPipeError, OSError, ValueError):
                return None

            if not chunk:
                return None
            buf.extend(chunk)

        return bytes(buf) if len(buf) == n else None

    def _cleanup_process(self):
        with self._state_lock:
            proc = self._proc
            self._proc = None

        if proc is None:
            return

        try:
            if proc.stdout:
                proc.stdout.close()
        except Exception:
            pass

        try:
            if proc.poll() is None:
                proc.terminate()
                proc.wait(timeout=1.5)
        except Exception:
            try:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait(timeout=1.0)
            except Exception:
                pass
