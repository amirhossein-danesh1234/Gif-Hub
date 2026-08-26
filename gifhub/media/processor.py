import asyncio
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path

from pydantic import BaseModel

from gifhub.config import Settings
from gifhub.domain.hash import sha256_file
from gifhub.media.probe import ProbeResult, probe_media
from gifhub.media.validation import MediaType, sniff_media_type, validate_upload_size
from gifhub.storage.base import StorageBackend


class MediaProcessingError(RuntimeError):
    pass


class ProcessedMedia(BaseModel):
    media_id: str
    sha256: str
    content_type: str
    original_key: str
    normalized_gif_key: str
    optimized_mp4_key: str
    thumbnail_key: str


class MediaProcessor:
    def __init__(self, *, settings: Settings, storage: StorageBackend) -> None:
        self.settings = settings
        self.storage = storage

    async def process_local_file(
        self,
        input_path: Path,
        media_id: str | None = None,
    ) -> ProcessedMedia:
        if shutil.which("ffmpeg") is None:
            raise MediaProcessingError("ffmpeg is not installed or not on PATH.")

        validate_upload_size(input_path, self.settings.max_upload_bytes)
        media_type = sniff_media_type(input_path)
        if media_type.category in {"video", "animation"}:
            probe = await asyncio.to_thread(
                probe_media,
                input_path,
                self.settings.ffprobe_timeout_seconds,
            )
            self._validate_probe(probe)

        sha256 = sha256_file(input_path)
        resolved_media_id = media_id or str(uuid.uuid4())

        with tempfile.TemporaryDirectory(prefix="gifhub-") as temp_dir_name:
            temp_dir = Path(temp_dir_name)
            gif_path = temp_dir / "normalized.gif"
            mp4_path = temp_dir / "optimized.mp4"
            thumbnail_path = temp_dir / "thumbnail.jpg"

            await self._run_ffmpeg(self._gif_args(input_path, gif_path, media_type))
            await self._run_ffmpeg(self._mp4_args(input_path, mp4_path, media_type))
            await self._run_ffmpeg(self._thumbnail_args(input_path, thumbnail_path, media_type))

            original_key = f"media/{resolved_media_id}/original/{sha256}.{media_type.extension}"
            normalized_gif_key = f"media/{resolved_media_id}/normalized/{sha256}.gif"
            optimized_mp4_key = f"media/{resolved_media_id}/optimized/{sha256}.mp4"
            thumbnail_key = f"media/{resolved_media_id}/thumbnail/{sha256}.jpg"

            await self.storage.put_file(input_path, original_key, media_type.content_type)
            await self.storage.put_file(gif_path, normalized_gif_key, "image/gif")
            await self.storage.put_file(mp4_path, optimized_mp4_key, "video/mp4")
            await self.storage.put_file(thumbnail_path, thumbnail_key, "image/jpeg")

        return ProcessedMedia(
            media_id=resolved_media_id,
            sha256=sha256,
            content_type=media_type.content_type,
            original_key=original_key,
            normalized_gif_key=normalized_gif_key,
            optimized_mp4_key=optimized_mp4_key,
            thumbnail_key=thumbnail_key,
        )

    def _validate_probe(self, probe: ProbeResult) -> None:
        if (
            probe.duration_seconds is not None
            and probe.duration_seconds > self.settings.max_video_duration_seconds
        ):
            raise MediaProcessingError("Video duration exceeds configured limit.")
        if probe.width is not None and probe.width > self.settings.max_dimension_px:
            raise MediaProcessingError("Video width exceeds configured limit.")
        if probe.height is not None and probe.height > self.settings.max_dimension_px:
            raise MediaProcessingError("Video height exceeds configured limit.")

    async def _run_ffmpeg(self, args: list[str]) -> None:
        completed = await asyncio.to_thread(
            subprocess.run,
            args,
            check=False,
            capture_output=True,
            text=True,
            timeout=self.settings.ffmpeg_timeout_seconds,
        )
        if completed.returncode != 0:
            raise MediaProcessingError(completed.stderr.strip() or "ffmpeg failed.")

    def _gif_args(self, input_path: Path, output_path: Path, media_type: MediaType) -> list[str]:
        vf = (
            f"fps={self.settings.target_gif_fps},"
            f"scale={self.settings.target_gif_width_px}:-1:flags=lanczos"
        )
        if media_type.category == "image":
            return [
                "ffmpeg",
                "-y",
                "-loop",
                "1",
                "-t",
                str(self.settings.static_image_duration_seconds),
                "-i",
                str(input_path),
                "-an",
                "-vf",
                vf,
                str(output_path),
            ]
        return ["ffmpeg", "-y", "-i", str(input_path), "-an", "-vf", vf, str(output_path)]

    def _mp4_args(self, input_path: Path, output_path: Path, media_type: MediaType) -> list[str]:
        vf = f"fps={self.settings.target_mp4_fps},scale={self.settings.target_mp4_width_px}:-2"
        common = [
            "-an",
            "-vf",
            vf,
            "-movflags",
            "+faststart",
            "-pix_fmt",
            "yuv420p",
            str(output_path),
        ]
        if media_type.category == "image":
            return [
                "ffmpeg",
                "-y",
                "-loop",
                "1",
                "-t",
                str(self.settings.static_image_duration_seconds),
                "-i",
                str(input_path),
                *common,
            ]
        return ["ffmpeg", "-y", "-i", str(input_path), *common]

    def _thumbnail_args(
        self,
        input_path: Path,
        output_path: Path,
        media_type: MediaType,
    ) -> list[str]:
        vf = "scale=320:-1"
        if media_type.category == "image":
            return [
                "ffmpeg",
                "-y",
                "-i",
                str(input_path),
                "-frames:v",
                "1",
                "-vf",
                vf,
                str(output_path),
            ]
        return [
            "ffmpeg",
            "-y",
            "-ss",
            "0",
            "-i",
            str(input_path),
            "-frames:v",
            "1",
            "-vf",
            vf,
            str(output_path),
        ]
