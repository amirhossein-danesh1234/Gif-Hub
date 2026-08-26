from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from gifhub.api.app import create_app
from gifhub.config import Settings
from gifhub.persistence.sqlalchemy import GifRepository
from gifhub.services import GifService, InMemoryProcessingQueue
from gifhub.telegram.bot import TelegramBot, extract_media_file_id
from gifhub.telegram.client import TelegramClient

PNG_1X1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010802000000907753de"
    "0000000c49444154789c6360f8cf00000301010018dd8db00000000049454e44ae426082"
)


class FakeTelegramClient:
    def __init__(self) -> None:
        self.messages: list[tuple[int, str, dict[str, Any] | None]] = []
        self.animations: list[tuple[int, str, str | None]] = []
        self.callbacks: list[str] = []

    async def send_message(
        self,
        chat_id: int,
        text: str,
        *,
        reply_markup: dict[str, Any] | None = None,
    ) -> None:
        self.messages.append((chat_id, text, reply_markup))

    async def send_animation(
        self,
        chat_id: int,
        animation: str,
        *,
        caption: str | None = None,
        reply_markup: dict[str, Any] | None = None,
    ) -> None:
        self.animations.append((chat_id, animation, caption))

    async def answer_callback_query(self, callback_query_id: str, text: str | None = None) -> None:
        self.callbacks.append(callback_query_id)

    async def edit_message_reply_markup(
        self,
        chat_id: int,
        message_id: int,
        reply_markup: dict[str, Any] | None,
    ) -> None:
        self.messages.append((chat_id, f"edit:{message_id}", reply_markup))


@pytest.fixture()
def service(tmp_path: Path) -> GifService:
    settings = Settings(
        data_dir=tmp_path / "data",
        database_url=f"sqlite:///{tmp_path / 'gifhub.sqlite3'}",
        telegram_admin_chat_ids="900",
    )
    repository = GifRepository(settings.database_url)
    repository.initialize()
    return GifService(
        settings=settings,
        repository=repository,
        queue=InMemoryProcessingQueue(),
    )


def approved_gif(service: GifService, title: str, gif_id: str, sha256: str = "sha") -> None:
    record = service.repository.create_draft(
        created_by=100, sha256=sha256, telegram_file_id=f"tg-{gif_id}"
    )
    service.repository.attach_processed_assets(
        record.submission_id,
        sha256=sha256,
        file_gif_url=f"https://cdn/{gif_id}.gif",
        file_mp4_url=f"https://cdn/{gif_id}.mp4",
        thumbnail_url=f"https://cdn/{gif_id}.jpg",
        telegram_file_id=f"tg-{gif_id}",
    )
    service.submit_metadata(record.submission_id, title=title, tag_ids=("laugh",))
    service.repository.approve_gif(record.submission_id, id_factory=lambda _title, _tags: gif_id)


def test_api_health_ready_search_get_send_and_admin_flow(service: GifService) -> None:
    client = TestClient(
        create_app(settings=service.settings, repository=service.repository, service=service)
    )
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/ready").json()["status"] == "ready"
    assert "gifhub_media_total" in client.get("/metrics").text

    upload_response = client.post(
        "/upload",
        files={"upload_file": ("sample.png", PNG_1X1, "image/png")},
        params={"created_by": 100},
    )
    assert upload_response.status_code == 200
    uploaded_submission_id = upload_response.json()["submission_id"]
    pending_upload = client.post(
        "/submit-metadata",
        json={
            "submission_id": uploaded_submission_id,
            "title": "Uploaded GIF",
            "tag_ids": ["laugh"],
        },
    )
    assert pending_upload.status_code == 200
    assert pending_upload.json()["status"] == "pending"

    record = service.repository.create_draft(
        created_by=100, sha256="api", telegram_file_id="tg-api"
    )
    service.repository.attach_processed_assets(
        record.submission_id,
        sha256="api",
        file_gif_url="https://cdn/api.gif",
        file_mp4_url="https://cdn/api.mp4",
        thumbnail_url="https://cdn/api.jpg",
        telegram_file_id="tg-api",
    )
    submit_response = client.post(
        "/submit-metadata",
        json={
            "submission_id": str(record.submission_id),
            "title": "Laugh Cat",
            "tag_ids": ["laugh"],
        },
    )
    assert submit_response.status_code == 200
    assert client.get("/search", params={"tag": "laugh"}).json()["results"] == []

    approve_response = client.post(
        "/admin/approve",
        json={"submission_id": str(record.submission_id)},
        headers={"X-Admin-Chat-Id": "900"},
    )
    assert approve_response.status_code == 200
    gif_id = approve_response.json()["id"]
    assert gif_id is not None

    search_response = client.get("/search", params={"tag": "laugh", "page": 1, "page_size": 1})
    assert search_response.status_code == 200
    assert search_response.json()["results"][0]["id"] == gif_id

    assert client.get(f"/gif/{gif_id}").status_code == 200
    send_response = client.post("/callback/send-gif", json={"gif_id": gif_id})
    assert send_response.json()["usage_count"] == 1


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ({"photo": [{"file_id": "small"}, {"file_id": "large"}]}, "large"),
        ({"animation": {"file_id": "gif"}}, "gif"),
        ({"video": {"file_id": "video"}}, "video"),
        ({"document": {"file_id": "doc"}}, "doc"),
        ({"text": "hello"}, None),
    ],
)
def test_extract_media_file_id(message: dict[str, object], expected: str | None) -> None:
    assert extract_media_file_id(message) == expected


def test_telegram_method_url_uses_bot_api_shape() -> None:
    client = TelegramClient("TOKEN", base_url="https://api.telegram.org")
    assert client.method_url("sendMessage") == "https://api.telegram.org/botTOKEN/sendMessage"


@pytest.mark.asyncio
async def test_telegram_search_click_send_manual_id_invalid_id_and_pagination(
    service: GifService,
) -> None:
    approved_gif(service, "Laugh Cat", "laugh-cat-83k", sha256="one")
    approved_gif(service, "Laugh Dog", "laugh-dog-k2p", sha256="two")
    approved_gif(service, "Laugh Face", "laugh-face-91x", sha256="three")
    fake = FakeTelegramClient()
    bot = TelegramBot(settings=service.settings, service=service, client=fake)  # type: ignore[arg-type]

    await bot.handle_update({"message": {"chat": {"id": 100}, "text": "/search laugh"}})
    assert "🎬" in fake.messages[0][1]
    assert fake.messages[0][2]["inline_keyboard"][0][0]["callback_data"].startswith("send:")
    assert fake.messages[-1][2]["inline_keyboard"][0][0]["callback_data"].startswith("search_page:")

    await bot.handle_update(
        {
            "callback_query": {
                "id": "cb1",
                "data": "send:laugh-cat-83k",
                "message": {"chat": {"id": 100}, "message_id": 1},
            }
        }
    )
    assert fake.animations[-1] == (100, "tg-laugh-cat-83k", "#laugh-cat-83k")

    await bot.handle_update({"message": {"chat": {"id": 100}, "text": "laugh-dog-k2p"}})
    assert fake.animations[-1] == (100, "tg-laugh-dog-k2p", "#laugh-dog-k2p")

    await bot.handle_update({"message": {"chat": {"id": 100}, "text": "missing-gif-123"}})
    assert "Invalid GIF ID" in fake.messages[-1][1]


@pytest.mark.asyncio
async def test_telegram_reject_with_reason_notifies_user(service: GifService) -> None:
    record = service.repository.create_draft(
        created_by=100, sha256="reject", telegram_file_id="tg-reject"
    )
    service.repository.attach_processed_assets(
        record.submission_id,
        sha256="reject",
        file_gif_url="https://cdn/reject.gif",
        file_mp4_url="https://cdn/reject.mp4",
        thumbnail_url="https://cdn/reject.jpg",
        telegram_file_id="tg-reject",
    )
    service.submit_metadata(record.submission_id, title="Reject Me", tag_ids=("laugh",))
    fake = FakeTelegramClient()
    bot = TelegramBot(settings=service.settings, service=service, client=fake)  # type: ignore[arg-type]

    await bot.handle_update(
        {
            "callback_query": {
                "id": "cb-reject",
                "data": f"admin_reject:{record.submission_id}",
                "message": {"chat": {"id": 900}, "message_id": 1},
            }
        }
    )
    await bot.handle_update({"message": {"chat": {"id": 900}, "text": "not suitable"}})

    assert any(chat_id == 100 and "not suitable" in text for chat_id, text, _ in fake.messages)
