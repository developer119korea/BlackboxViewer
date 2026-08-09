"""main.py
BlackboxViewer - macOS 용 4채널 블랙박스 영상 뷰어 / 채널 추출기

기능
----
1. 폴더 또는 파일을 선택해 .avi 재생목록을 구성
2. 재생목록에서 파일 선택 시 4개 채널(F/B/L/R)을 동시에 미리보기
3. 선택한 파일(들)에 대해 채널별 mp4 추출
   (기존 사용 명령어와 동일한 방식: ffmpeg -map 0:v:N -map 0:a:0 -c copy)

실행 방법
--------
    python3 -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt
    brew install ffmpeg   # 아직 설치 안 했다면
    python3 main.py
"""
import sys
from pathlib import Path
from typing import Dict, List, Optional

from PySide6.QtCore import Qt, Slot, QSize
from PySide6.QtGui import QImage, QPixmap, QShortcut, QKeySequence
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QListWidget, QListWidgetItem, QLabel, QPushButton, QSlider, QSplitter,
    QFileDialog, QMessageBox, QProgressDialog, QStatusBar, QGroupBox,
)

from ffmpeg_utils import probe_file, find_avi_files, ProbeResult, DEFAULT_CHANNEL_SUFFIXES
from video_stream_worker import VideoStreamWorker
from extract_worker import ExtractWorker

APP_TITLE = "BlackboxViewer"


class ChannelView(QWidget):
    """단일 채널 미리보기 위젯 (제목 라벨 + 영상 표시 라벨)"""

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)

        self.title_label = QLabel(title)
        self.title_label.setAlignment(Qt.AlignCenter)
        self.title_label.setStyleSheet(
            "font-weight: bold; color: #ddd; background:#333; padding:3px;"
        )

        self.video_label = QLabel("영상 없음")
        self.video_label.setAlignment(Qt.AlignCenter)
        self.video_label.setMinimumSize(320, 200)
        self.video_label.setStyleSheet("background:#111; color:#777;")

        layout.addWidget(self.title_label)
        layout.addWidget(self.video_label, 1)

    def set_frame(self, image: QImage):
        pix = QPixmap.fromImage(image)
        pix = pix.scaled(self.video_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.video_label.setPixmap(pix)

    def clear(self, text: str = "영상 없음"):
        self.video_label.setPixmap(QPixmap())
        self.video_label.setText(text)


class PlaylistItemWidget(QWidget):
    """재생목록 내에 들어갈 커스텀 위젯 (실제 버튼 + 파일명)"""

    def __init__(self, path: Path, main_window, parent=None):
        super().__init__(parent)
        self.path = path
        self.main_window = main_window

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)

        self.action_btn = QPushButton("▶")
        self.action_btn.setFixedSize(24, 24)
        # 스페이스바 단축키 작동을 위해 개별 버튼 포커스 제외
        self.action_btn.setFocusPolicy(Qt.NoFocus)
        self.action_btn.clicked.connect(self.on_btn_clicked)

        self.name_label = QLabel(path.name)

        layout.addWidget(self.action_btn)
        layout.addWidget(self.name_label)
        layout.addStretch()

    def on_btn_clicked(self):
        # 버튼 클릭 시 해당 파일 재생/일시정지 토글
        self.main_window.toggle_specific_path(self.path)

    def update_state(self, current_path: Optional[Path], is_playing: bool):
        # 현재 재생 중인 파일이라면 '일시정지' 명령 아이콘 표시
        if self.path == current_path and is_playing:
            self.action_btn.setText("❚❚")
        # 그 외에는 '재생' 명령 아이콘 표시
        else:
            self.action_btn.setText("▶")

    def mousePressEvent(self, event):
        # 배경(라벨 등) 클릭 시 목록에서 선택되도록 처리
        self.main_window.select_path_in_playlist(self.path)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        # 더블 클릭 시 즉시 재생
        self.main_window.toggle_specific_path(self.path, force_play=True)
        super().mouseDoubleClickEvent(event)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.resize(1200, 800)

        self.current_probe: Optional[ProbeResult] = None
        self.workers: Dict[str, VideoStreamWorker] = {}
        self.channel_views: Dict[str, ChannelView] = {}
        self.duration = 0.0
        self.is_playing = False
        self.extract_worker: Optional[ExtractWorker] = None
        self.progress_dialog: Optional[QProgressDialog] = None
        self._extract_done_count = 0
        self._last_extract_dir: Optional[Path] = None

        self._current_path: Optional[Path] = None
        self._selected_path: Optional[Path] = None

        self._build_ui()

    # ---------------------------------------------------------- UI 구성
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)

        # 상단 툴바
        toolbar = QHBoxLayout()
        btn_open_folder = QPushButton("폴더 열기")
        btn_open_folder.clicked.connect(self.open_folder)
        btn_open_files = QPushButton("파일 열기")
        btn_open_files.clicked.connect(self.open_files)
        btn_extract = QPushButton("선택 파일 채널 추출")
        btn_extract.clicked.connect(self.extract_selected)
        btn_extract_all = QPushButton("전체 목록 채널 추출")
        btn_extract_all.clicked.connect(self.extract_all)

        toolbar.addWidget(btn_open_folder)
        toolbar.addWidget(btn_open_files)
        toolbar.addStretch(1)
        toolbar.addWidget(btn_extract)
        toolbar.addWidget(btn_extract_all)
        root_layout.addLayout(toolbar)

        # 본문: 좌측 재생목록 / 우측 미리보기
        splitter = QSplitter(Qt.Horizontal)
        root_layout.addWidget(splitter, 1)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.addWidget(QLabel("재생목록 (.avi)"))
        self.playlist = QListWidget()
        self.playlist.setSelectionMode(QListWidget.SingleSelection)
        self.playlist.itemSelectionChanged.connect(self.on_playlist_selection)

        # 목록 아이템 더블클릭 이벤트 연결 (PlaylistItemWidget에서도 처리하지만 안전장치로 추가)
        self.playlist.itemDoubleClicked.connect(self.on_playlist_double_clicked)

        left_layout.addWidget(self.playlist, 1)
        splitter.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)

        self.preview_group = QGroupBox("채널 미리보기 (동시 재생)")
        self.grid = QGridLayout(self.preview_group)
        for i, suffix in enumerate(DEFAULT_CHANNEL_SUFFIXES):
            view = ChannelView(suffix)
            self.channel_views[suffix] = view
            self.grid.addWidget(view, i // 2, i % 2)
        right_layout.addWidget(self.preview_group, 1)

        # 타임라인 UI
        timeline_layout = QHBoxLayout()
        self.timeline_slider = QSlider(Qt.Horizontal)
        self.timeline_slider.setEnabled(False)
        self.time_label = QLabel("00:00 / 00:00")

        timeline_layout.addWidget(self.timeline_slider)
        timeline_layout.addWidget(self.time_label)
        right_layout.addLayout(timeline_layout)

        # 재생 컨트롤 UI
        controls = QHBoxLayout()
        self.btn_play_pause = QPushButton("▶")
        self.btn_play_pause.setFocusPolicy(Qt.NoFocus) # 스페이스바와 중복 방지
        self.btn_play_pause.clicked.connect(self.toggle_play)

        self.btn_stop = QPushButton("■")
        self.btn_stop.setFocusPolicy(Qt.NoFocus)
        self.btn_stop.clicked.connect(self.stop_playback)

        controls.addWidget(self.btn_play_pause)
        controls.addWidget(self.btn_stop)
        controls.addStretch(1)
        right_layout.addLayout(controls)

        splitter.addWidget(right)
        splitter.setSizes([300, 900])

        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("준비 완료. 폴더 또는 파일을 열어 재생목록을 구성하세요.")

        # 전역 스페이스바 단축키 설정
        self.shortcut_space = QShortcut(QKeySequence(Qt.Key_Space), self)
        self.shortcut_space.activated.connect(self.toggle_play)

    def format_time(self, seconds: float) -> str:
        """초 단위 시간을 MM:SS 형식의 문자열로 변환합니다."""
        m = int(seconds // 60)
        s = int(seconds % 60)
        return f"{m:02d}:{s:02d}"

    def update_timeline(self, current_time: float):
        """재생 중인 시간으로 타임라인과 레이블을 갱신합니다."""
        self.timeline_slider.setValue(int(current_time))
        self.time_label.setText(f"{self.format_time(current_time)} / {self.format_time(self.duration)}")

    def update_playlist_icons(self):
        """재생목록 아이템 내 버튼의 상태를 갱신합니다."""
        for i in range(self.playlist.count()):
            item = self.playlist.item(i)
            widget = self.playlist.itemWidget(item)
            if isinstance(widget, PlaylistItemWidget):
                widget.update_state(self._current_path, self.is_playing)

    # ---------------------------------------------------------- 파일 열기
    def open_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "블랙박스 영상 폴더 선택")
        if not folder:
            return
        files = find_avi_files(Path(folder))
        self._add_to_playlist(files)

    def open_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, "AVI 파일 선택", "", "AVI Files (*.avi)")
        if not files:
            return
        self._add_to_playlist([Path(f) for f in files])

    def _add_to_playlist(self, files: List[Path]):
        existing = {self.playlist.item(i).data(Qt.UserRole) for i in range(self.playlist.count())}
        added = 0
        for f in files:
            key = str(f)
            if key in existing:
                continue

            # 리스트 아이템 생성
            item = QListWidgetItem()
            item.setData(Qt.UserRole, key)
            item.setSizeHint(QSize(200, 36)) # 버튼이 들어갈 충분한 높이 제공
            self.playlist.addItem(item)

            # 커스텀 위젯을 아이템에 연결
            widget = PlaylistItemWidget(f, self)
            self.playlist.setItemWidget(item, widget)
            added += 1

        self.statusBar().showMessage(f"{added}개 파일 추가됨 (총 {self.playlist.count()}개)")
        self.update_playlist_icons()

    # ---------------------------------------------------------- 재생목록 상호작용
    def on_playlist_selection(self):
        items = self.playlist.selectedItems()
        if not items:
            self._selected_path = None
        else:
            self._selected_path = Path(items[-1].data(Qt.UserRole))

    def on_playlist_double_clicked(self, item):
        """리스트 아이템 자체를 더블클릭 했을 때 자동 재생"""
        path = Path(item.data(Qt.UserRole))
        self.toggle_specific_path(path, force_play=True)

    def select_path_in_playlist(self, path: Path):
        """특정 경로를 리스트 위젯에서 선택 상태로 만듭니다."""
        self._selected_path = path
        for i in range(self.playlist.count()):
            item = self.playlist.item(i)
            if item.data(Qt.UserRole) == str(path):
                self.playlist.setCurrentItem(item)
                break

    def toggle_specific_path(self, path: Path, force_play=False):
        """주어진 경로의 파일을 토글(재생/일시정지) 하거나 교체하여 재생합니다."""
        self.select_path_in_playlist(path)

        if self._current_path != path:
            # 다른 파일이면 새로 로드하고 무조건 재생
            self._stop_workers_and_wait()
            if self.load_file(path):
                self.start_playback()
        else:
            # 같은 파일(이미 로드된 상태)이면 상태 토글
            if force_play:
                if not self.is_playing:
                    self.start_playback()
            else:
                if self.is_playing:
                    self.pause_playback()
                else:
                    self.start_playback()

    def load_file(self, path: Path) -> bool:
        try:
            self.current_probe = probe_file(path)
        except Exception as exc:
            QMessageBox.warning(self, "오류", f"파일을 분석할 수 없습니다:\n{exc}")
            self.current_probe = None
            return False

        self._current_path = path
        self.duration = self.current_probe.duration

        self.timeline_slider.setRange(0, int(self.duration))
        self.update_timeline(0.0)

        active_suffixes = {s.suffix for s in self.current_probe.video_streams}
        for suffix, view in self.channel_views.items():
            if suffix in active_suffixes:
                view.clear("대기 중 (재생 버튼을 누르세요)")
            else:
                view.clear("채널 없음")

        self.statusBar().showMessage(
            f"{path.name} 로드됨 - 비디오 채널 {len(self.current_probe.video_streams)}개, "
            f"길이 {self.duration:.1f}초"
        )
        return True

    # ---------------------------------------------------------- 재생 제어
    def toggle_play(self):
        """메인 재생 버튼 또는 스페이스바 입력 시 호출"""
        if not self._selected_path and not self._current_path:
            QMessageBox.information(self, "안내", "먼저 재생목록에서 파일을 선택하세요.")
            return

        target_path = self._selected_path or self._current_path
        self.toggle_specific_path(target_path)

    def start_playback(self):
        if not self.current_probe:
            return

        if not self.workers:
            self._spawn_workers(0.0)
        else:
            for worker in self.workers.values():
                worker.resume()

        self.is_playing = True
        self.btn_play_pause.setText("❚❚") # 메인 버튼도 갱신
        self.statusBar().showMessage("재생 중")
        self.update_playlist_icons()

    def pause_playback(self):
        if not self.workers:
            return

        for worker in self.workers.values():
            worker.pause()

        self.is_playing = False
        self.btn_play_pause.setText("▶")
        self.statusBar().showMessage("일시정지")
        self.update_playlist_icons()

    def stop_playback(self):
        self._stop_workers_and_wait()
        self.is_playing = False
        self.btn_play_pause.setText("▶")
        self.update_timeline(0.0)

        for view in self.channel_views.values():
            view.clear("정지됨 - 재생 버튼을 누르세요")

        self.statusBar().showMessage("정지됨 - 다시 재생하면 처음부터 시작합니다.")
        self.update_playlist_icons()

    def _spawn_workers(self, start_time: float = 0.0):
        if not self.current_probe:
            return

        path_str = str(self.current_probe.path)

        for s in self.current_probe.video_streams:
            worker = VideoStreamWorker(
                file_path=path_str,
                stream_index=s.index,
                suffix=s.suffix,
                width=s.width,
                height=s.height,
                fps=s.fps,
                start_time=start_time,
            )
            worker.frameReady.connect(self.on_frame_ready)
            worker.errorOccurred.connect(self.on_worker_error)
            worker.finished_playback.connect(self.on_worker_finished)

            self.workers[s.suffix] = worker
            worker.start()

    @Slot(object, QImage)
    def on_frame_ready(self, suffix, image):
        view = self.channel_views.get(suffix)
        if view:
            view.set_frame(image)

        first_worker_suffix = next(iter(self.workers.keys()), None)
        if suffix == first_worker_suffix:
            worker = self.workers.get(suffix)
            if worker:
                self.update_timeline(worker._position)

    @Slot(object)
    def on_worker_finished(self, suffix):
        worker = self.workers.get(suffix)
        if worker is None:
            return

        if worker.isRunning():
            return

        self.workers.pop(suffix, None)

        if not self.workers:
            self.is_playing = False
            self.btn_play_pause.setText("▶")
            self.statusBar().showMessage("재생 종료")
            self.update_playlist_icons()

    @Slot(object, str)
    def on_worker_error(self, suffix, message):
        self.statusBar().showMessage(f"[{suffix}] 오류: {message}")

    def _stop_workers_and_wait(self):
        workers = list(self.workers.values())
        self.workers.clear()

        for worker in workers:
            worker.stop()

        for worker in workers:
            if worker.isRunning():
                worker.wait(5000)

        self.is_playing = False

    # ---------------------------------------------------------- 채널 추출
    def extract_selected(self):
        items = self.playlist.selectedItems()
        if not items:
            QMessageBox.information(self, "안내", "추출할 파일을 재생목록에서 선택하세요.")
            return
        files = [Path(i.data(Qt.UserRole)) for i in items]
        self._run_extraction(files)

    def extract_all(self):
        if self.playlist.count() == 0:
            QMessageBox.information(self, "안내", "재생목록이 비어 있습니다.")
            return
        files = [Path(self.playlist.item(i).data(Qt.UserRole)) for i in range(self.playlist.count())]
        self._run_extraction(files)

    def _run_extraction(self, files: List[Path]):
        out_dir = QFileDialog.getExistingDirectory(
            self, "추출된 mp4 저장 폴더 선택 (취소 시 원본과 같은 폴더에 저장)"
        )
        target_dir = Path(out_dir) if out_dir else None

        self.progress_dialog = QProgressDialog("채널 추출 준비 중...", "취소", 0, len(files), self)
        self.progress_dialog.setWindowModality(Qt.WindowModal)
        self.progress_dialog.setMinimumDuration(0)
        self.progress_dialog.canceled.connect(self._cancel_extraction)

        self._extract_done_count = 0
        self._last_extract_dir: Optional[Path] = target_dir
        self.extract_worker = ExtractWorker(files, target_dir)
        self.extract_worker.fileStarted.connect(self._on_extract_file_started)
        self.extract_worker.channelDone.connect(self._on_extract_channel_done)
        self.extract_worker.fileDone.connect(self._on_extract_file_done)
        self.extract_worker.allDone.connect(self._on_extract_all_done)
        self.extract_worker.start()

    def _cancel_extraction(self):
        if self.extract_worker:
            self.extract_worker.cancel()

    def _on_extract_file_started(self, path_str):
        name = Path(path_str).name
        if self.progress_dialog:
            self.progress_dialog.setLabelText(f"추출 중: {name}")

    def _on_extract_channel_done(self, src, out_path):
        self.statusBar().showMessage(f"완료: {Path(out_path).name}")

    def _on_extract_file_done(self, src, success, message):
        self._extract_done_count += 1
        if self.progress_dialog:
            self.progress_dialog.setValue(self._extract_done_count)
        if not success:
            self.statusBar().showMessage(f"실패: {Path(src).name} - {message}")

    def _on_extract_all_done(self):
        if self.progress_dialog:
            self.progress_dialog.setValue(self.progress_dialog.maximum())
            self.progress_dialog.close()

        if self._last_extract_dir is None:
            self._last_extract_dir = (
                self.current_probe.path.parent if self.current_probe else None
            )

        msg = QMessageBox(self)
        msg.setWindowTitle("완료")
        msg.setText("채널 추출이 완료되었습니다.")
        msg.setInformativeText(
            f"저장 위치: {self._last_extract_dir}"
            if self._last_extract_dir else ""
        )
        open_btn = msg.addButton("폴더 열기", QMessageBox.AcceptRole)
        msg.addButton("닫기", QMessageBox.RejectRole)
        msg.exec()

        if msg.clickedButton() is open_btn and self._last_extract_dir:
            self._open_folder(self._last_extract_dir)

    def _open_folder(self, folder: Path):
        import subprocess
        try:
            subprocess.Popen(["open", str(folder)])
        except Exception as exc:
            QMessageBox.warning(self, "오류", f"폴더를 열 수 없습니다.\n{exc}")

    def closeEvent(self, event):
        self._stop_workers_and_wait()
        if self.extract_worker and self.extract_worker.isRunning():
            self.extract_worker.cancel()
            self.extract_worker.wait(2000)
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_TITLE)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()