import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class MediaProbeError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProbeResult:
    duration_seconds: float | None
    width: int | None
    height: int | None
    has_audio: bool
    format_name: str | None


def ffprobe_args(path: Path) -> list[str]:
    return [
        "ffprobe",
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]


def probe_media(path: Path, timeout_seconds: int) -> ProbeResult:
    if shutil.which("ffprobe") is None:
        raise MediaProbeError("ffprobe is not installed or not on PATH.")

    completed = subprocess.run(
        ffprobe_args(path),
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
    )
    if completed.returncode != 0:
        raise MediaProbeError(completed.stderr.strip() or "ffprobe failed.")

    payload: dict[str, Any] = json.loads(completed.stdout)
    streams = payload.get("streams", [])
    video_stream: dict[str, Any] = next(
        (stream for stream in streams if stream.get("codec_type") == "video"),
        {},
    )
    has_audio = any(stream.get("codec_type") == "audio" for stream in streams)
    duration = video_stream.get("duration") or payload.get("format", {}).get("duration")

    return ProbeResult(
        duration_seconds=float(duration) if duration is not None else None,
        width=int(video_stream["width"]) if "width" in video_stream else None,
        height=int(video_stream["height"]) if "height" in video_stream else None,
        has_audio=has_audio,
        format_name=payload.get("format", {}).get("format_name"),
    )
