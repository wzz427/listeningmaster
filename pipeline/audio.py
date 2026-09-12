"""音频预处理。

用 imageio-ffmpeg 自带的 ffmpeg（conda 装 ffmpeg 在这台机器上会因为顺带装的图形库报编码错，
见 docs/lessons.md）。识别要求单声道：说话人分离只支持单声道。
"""

import subprocess
from pathlib import Path

import imageio_ffmpeg

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()


def to_mono_16k_wav(src: Path, dst: Path) -> Path:
    """转成 16kHz、16 位、单声道 WAV。"""
    dst.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [FFMPEG, "-y", "-loglevel", "error", "-i", str(src),
         "-ac", "1", "-ar", "16000", "-sample_fmt", "s16", str(dst)],
        check=True,
    )
    return dst


def probe(src: Path) -> str:
    """返回 ffmpeg 读到的音频信息，用来确认时长和声道数。"""
    out = subprocess.run(
        [FFMPEG, "-hide_banner", "-i", str(src)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    return "\n".join(
        line.strip() for line in out.stderr.splitlines()
        if "Duration" in line or "Stream" in line
    )
