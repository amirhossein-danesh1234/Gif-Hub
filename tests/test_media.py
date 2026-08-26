import shutil
import subprocess
from pathlib import Path

import pytest

from gifhub.config import Settings
from gifhub.media.probe import ffprobe_args
from gifhub.media.processor import MediaProcessor
from gifhub.media.validation import MediaValidationError, sniff_media_type, validate_upload_size
from gifhub.storage.local import LocalStorageBackend

PNG_1X1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010802000000907753de"
    "0000000c49444154789c6360f8cf00000301010018dd8db00000000049454e44ae426082"
)


def test_sniff_media_type_and_size_validation(tmp_path: Path) -> None:
    png = tmp_path / "sample.png"
    png.write_bytes(PNG_1X1)
    assert sniff_media_type(png).content_type == "image/png"
    validate_upload_size(png, 1024)
    with pytest.raises(MediaValidationError):
        validate_upload_size(png, 1)


def test_invalid_signature_is_rejected(tmp_path: Path) -> None:
    fake = tmp_path / "fake-video.mp4"
    fake.write_text("not a video", encoding="utf-8")
    with pytest.raises(MediaValidationError):
        sniff_media_type(fake)


def test_ffprobe_args_are_safe_argument_list(tmp_path: Path) -> None:
    path = tmp_path / "file name.mp4"
    args = ffprobe_args(path)
    assert isinstance(args, list)
    assert args[0] == "ffprobe"
    assert str(path) in args


@pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe not installed",
)
@pytest.mark.asyncio
async def test_media_processor_generates_assets_from_generated_mp4(tmp_path: Path) -> None:
    source = tmp_path / "sample.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=64x64:rate=2",
            "-t",
            "1",
            "-pix_fmt",
            "yuv420p",
            str(source),
        ],
        check=True,
        capture_output=True,
    )
    settings = Settings(data_dir=tmp_path / "data", database_path=tmp_path / "db.sqlite3")
    storage = LocalStorageBackend(settings.storage_dir)
    processor = MediaProcessor(settings=settings, storage=storage)

    result = await processor.process_local_file(source, media_id="media-1")

    assert await storage.exists(result.original_key)
    assert await storage.exists(result.normalized_gif_key)
    assert await storage.exists(result.optimized_mp4_key)
    assert await storage.exists(result.thumbnail_key)
