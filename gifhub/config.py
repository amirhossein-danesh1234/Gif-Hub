from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"
    app_debug: bool = False
    log_level: str = "INFO"

    telegram_enabled: bool = False
    telegram_bot_token: str = ""
    telegram_use_long_polling: bool = True
    telegram_admin_chat_ids: str = ""

    data_dir: Path = Path("./data")
    database_path: Path = Path("./data/gifhub.sqlite3")
    database_url: str = "sqlite:///./data/gifhub.sqlite3"
    redis_url: str = "redis://localhost:6379/0"
    public_base_url: str = "http://localhost:8000"

    max_upload_bytes: int = 10_485_760
    max_video_duration_seconds: int = 20
    max_output_gif_bytes: int = 10_485_760
    max_output_mp4_bytes: int = 10_485_760
    max_dimension_px: int = 1280
    target_gif_width_px: int = 480
    target_mp4_width_px: int = 640
    target_gif_fps: int = 12
    target_mp4_fps: int = 24
    static_image_duration_seconds: int = 3
    max_tags_per_media: int = 3
    min_tags_per_media: int = 1

    ffmpeg_timeout_seconds: int = 120
    ffprobe_timeout_seconds: int = 20
    signed_url_ttl_seconds: int = 300

    @property
    def storage_dir(self) -> Path:
        return self.data_dir / "storage"

    @property
    def admin_chat_ids(self) -> set[int]:
        values = self.telegram_admin_chat_ids.replace(";", ",").split(",")
        return {int(value.strip()) for value in values if value.strip()}


def get_settings() -> Settings:
    return Settings()
