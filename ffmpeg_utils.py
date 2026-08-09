"""ffmpeg_utils.py
BlackboxViewer 용 FFmpeg / FFprobe 헬퍼 함수 모음.

- probe_file(): .avi 파일의 비디오 채널(스트림) 정보와 길이를 조회
- build_extract_commands(): 기존에 사용하시던 것과 동일한 형식의
  ffmpeg 채널 추출 명령어를 생성
      ffmpeg -i in.avi -map 0:v:N -map 0:a:0 -c copy in_SUFFIX.mp4
- find_avi_files(): 폴더에서 .avi 파일을 재귀적으로 탐색
"""
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List

FFPROBE = "ffprobe"
FFMPEG = "ffmpeg"

# 비디오 스트림 순서(0,1,2,3) -> 채널 접미사 매핑
# 블랙박스 채널 구성이 다르면 이 리스트만 바꿔주면 됩니다.
DEFAULT_CHANNEL_SUFFIXES = ["F", "B", "L", "R"]


@dataclass
class VideoStreamInfo:
    index: int          # -map 0:v:N 에 쓰이는 비디오 스트림 인덱스 (0-based)
    codec_name: str
    width: int
    height: int
    fps: float
    suffix: str          # 채널 접미사 (F/B/L/R ...)


@dataclass
class ProbeResult:
    path: Path
    duration: float
    video_streams: List[VideoStreamInfo]
    has_audio: bool


def _parse_fps(rate_str: str) -> float:
    """ffprobe 의 r_frame_rate ("30000/1001" 같은 분수 문자열) 를 float 로 변환"""
    try:
        if "/" in rate_str:
            num, den = rate_str.split("/")
            den = float(den)
            return float(num) / den if den else 30.0
        return float(rate_str)
    except Exception:
        return 30.0


def probe_file(path: Path) -> ProbeResult:
    """avi 파일의 모든 비디오 스트림 정보와 길이를 조회합니다."""
    cmd = [
        FFPROBE, "-v", "error",
        "-show_entries", "stream=index,codec_type,codec_name,width,height,r_frame_rate",
        "-show_entries", "format=duration",
        "-of", "json",
        str(path),
    ]
    out = subprocess.run(cmd, capture_output=True, text=True, check=True)
    data = json.loads(out.stdout)

    duration = float(data.get("format", {}).get("duration", 0.0) or 0.0)

    video_streams: List[VideoStreamInfo] = []
    has_audio = False
    v_idx = 0
    for s in data.get("streams", []):
        if s.get("codec_type") == "video":
            suffix = (
                DEFAULT_CHANNEL_SUFFIXES[v_idx]
                if v_idx < len(DEFAULT_CHANNEL_SUFFIXES)
                else f"CH{v_idx}"
            )
            video_streams.append(VideoStreamInfo(
                index=v_idx,
                codec_name=s.get("codec_name", ""),
                width=int(s.get("width") or 0),
                height=int(s.get("height") or 0),
                fps=_parse_fps(s.get("r_frame_rate", "30/1")),
                suffix=suffix,
            ))
            v_idx += 1
        elif s.get("codec_type") == "audio":
            has_audio = True

    return ProbeResult(path=path, duration=duration, video_streams=video_streams, has_audio=has_audio)


def build_extract_commands(
    path: Path,
    out_dir: Path,
    streams: List[VideoStreamInfo],
    has_audio: bool,
) -> List[List[str]]:
    """
    기존 사용 명령어와 동일한 형식의 채널별 추출 명령을 생성합니다.

    예) R_2026_08_04_15_57_06_Q_N.avi
        ffmpeg -i R_..._Q_N.avi -map 0:v:0 -map 0:a:0 -c copy R_..._Q_N_F.mp4
        ffmpeg -i R_..._Q_N.avi -map 0:v:1 -map 0:a:0 -c copy R_..._Q_N_B.mp4
        ...
    """
    stem = path.stem
    commands = []
    for s in streams:
        out_path = out_dir / f"{stem}_{s.suffix}.mp4"
        cmd = [FFMPEG, "-y", "-i", str(path), "-map", f"0:v:{s.index}"]
        if has_audio:
            cmd += ["-map", "0:a:0"]
        cmd += ["-c", "copy", str(out_path)]
        commands.append(cmd)
    return commands


def find_avi_files(root: Path) -> List[Path]:
    """폴더 하위의 모든 .avi 파일을 재귀적으로 찾습니다. 파일이면 그대로 반환."""
    if root.is_file():
        return [root] if root.suffix.lower() == ".avi" else []
    return sorted(root.rglob("*.avi"))
