import asyncio
import re
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote
from uuid import UUID

from gifhub.config import Settings
from gifhub.domain.models import GifRecord
from gifhub.domain.parser import format_tag_list
from gifhub.media.processor import MediaProcessingError
from gifhub.media.validation import MediaValidationError
from gifhub.persistence.sqlalchemy import NotFoundError, ValidationError
from gifhub.services import GifService
from gifhub.telegram.client import TelegramClient

GIF_ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)+$")


class TelegramBot:
    def __init__(
        self,
        *,
        settings: Settings,
        service: GifService,
        client: TelegramClient | None = None,
    ) -> None:
        self.settings = settings
        self.service = service
        self.client = client or TelegramClient(settings.telegram_bot_token)
        self.upload_state: dict[int, dict[str, Any]] = {}
        self.reject_state: dict[int, str] = {}

    async def run_long_polling(self) -> None:
        offset: int | None = None
        while True:
            updates = await self.client.get_updates(offset=offset)
            for update in updates:
                update_id = int(update["update_id"])
                offset = update_id + 1
                await self.handle_update(update)
            await asyncio.sleep(0.2)

    async def handle_update(self, update: dict[str, Any]) -> None:
        if "callback_query" in update:
            await self._handle_callback(update["callback_query"])
            return
        message = update.get("message")
        if not isinstance(message, dict):
            return
        chat = message.get("chat", {})
        chat_id = chat.get("id")
        if not isinstance(chat_id, int):
            return

        text = message.get("text")
        if isinstance(text, str):
            await self._handle_text(chat_id, text)
            return

        file_id = extract_media_file_id(message)
        if file_id is not None:
            await self._handle_media(chat_id, file_id)

    async def _handle_text(self, chat_id: int, text: str) -> None:
        if chat_id in self.reject_state and self._is_admin(chat_id):
            submission_id = self.reject_state.pop(chat_id)
            reason = None if text.strip() in {"-", "skip", "/skip", "بدون دلیل"} else text.strip()
            record = self.service.reject(submission_id, reason=reason)
            await self.client.send_message(
                chat_id, f"Rejected: {record.title or record.submission_id}"
            )
            if record.created_by is not None:
                suffix = f"\nReason: {reason}" if reason else ""
                await self.client.send_message(record.created_by, f"GIF rejected.{suffix}")
            return

        state = self.upload_state.get(chat_id)
        if state and state.get("step") == "awaiting_title":
            title = " ".join(text.split())
            if not title:
                await self.client.send_message(chat_id, "Title is required.")
                return
            state["title"] = title
            state["step"] = "select_tags"
            state["selected_tags"] = []
            await self.client.send_message(
                chat_id,
                "Choose up to 3 tags, then tap Done.",
                reply_markup=self._tag_keyboard(tuple()),
            )
            return

        if text == "/start":
            await self.client.send_message(
                chat_id,
                "Send /upload to add a GIF, or /search to find one.",
            )
            return
        if text == "/upload":
            self.upload_state[chat_id] = {"step": "awaiting_media"}
            await self.client.send_message(chat_id, "Send a GIF, animation, video, or image.")
            return
        if text.startswith("/search"):
            query = text.removeprefix("/search").strip()
            await self._send_search(chat_id, query=query)
            return
        if GIF_ID_RE.match(text.strip()):
            await self._send_gif_by_id(chat_id, text.strip())
            return
        await self.client.send_message(chat_id, "Use /search or send a valid GIF ID.")

    async def _handle_media(self, chat_id: int, file_id: str) -> None:
        state = self.upload_state.get(chat_id)
        if state and state.get("step") != "awaiting_media":
            await self.client.send_message(chat_id, "Finish the current upload first.")
            return

        await self.client.send_message(
            chat_id, "File received. Validating and queueing processing..."
        )
        try:
            file_info = await self.client.get_file(file_id)
            file_path = file_info.get("file_path")
            if not isinstance(file_path, str):
                raise MediaProcessingError("Telegram did not provide file_path.")

            upload_dir = self.settings.data_dir / "telegram-uploads"
            upload_dir.mkdir(parents=True, exist_ok=True)
            suffix = Path(file_path).suffix or ".bin"
            with tempfile.NamedTemporaryFile(
                prefix="gifhub-",
                suffix=suffix,
                dir=upload_dir,
                delete=False,
            ) as handle:
                downloaded = Path(handle.name)
            await self.client.download_file(file_path, downloaded)
            record = self.service.create_upload(
                downloaded,
                created_by=chat_id,
                telegram_file_id=file_id,
            )
            self.upload_state[chat_id] = {
                "step": "awaiting_title",
                "submission_id": str(record.submission_id),
            }
            await self.client.send_message(chat_id, "Now send a short title for this GIF.")
        except (MediaProcessingError, MediaValidationError, ValidationError) as exc:
            self.upload_state.pop(chat_id, None)
            await self.client.send_message(chat_id, f"Upload failed: {exc}")

    async def _handle_callback(self, callback: dict[str, Any]) -> None:
        callback_id = callback.get("id")
        data = callback.get("data")
        message = callback.get("message", {})
        chat = message.get("chat", {})
        chat_id = chat.get("id")
        if (
            not isinstance(callback_id, str)
            or not isinstance(data, str)
            or not isinstance(chat_id, int)
        ):
            return

        if data.startswith("send:"):
            await self.client.answer_callback_query(callback_id)
            await self._send_gif_by_id(chat_id, data.removeprefix("send:"))
            return

        if data.startswith("search_page:"):
            await self.client.answer_callback_query(callback_id)
            _, raw_page, raw_query = data.split(":", 2)
            await self._send_search(chat_id, query=unquote(raw_query), page=int(raw_page))
            return

        if data.startswith("tag:"):
            await self.client.answer_callback_query(callback_id)
            await self._toggle_tag(chat_id, data.removeprefix("tag:"), message)
            return

        if data.startswith("done_tags:"):
            await self.client.answer_callback_query(callback_id)
            await self._finish_tag_selection(chat_id)
            return

        if data.startswith("admin_approve:") and self._is_admin(chat_id):
            await self.client.answer_callback_query(callback_id, "Approving...")
            record = self.service.approve(data.removeprefix("admin_approve:"))
            await self.client.send_message(chat_id, f"Approved: #{record.id}")
            if record.created_by is not None:
                await self.client.send_message(record.created_by, f"GIF approved: #{record.id}")
            return

        if data.startswith("admin_reject:") and self._is_admin(chat_id):
            await self.client.answer_callback_query(callback_id)
            self.reject_state[chat_id] = data.removeprefix("admin_reject:")
            await self.client.send_message(chat_id, "Send reject reason, or send /skip.")

    async def _toggle_tag(self, chat_id: int, tag_id: str, message: dict[str, Any]) -> None:
        state = self.upload_state.get(chat_id)
        if not state or state.get("step") != "select_tags":
            return
        selected: list[str] = state.setdefault("selected_tags", [])
        if tag_id in selected:
            selected.remove(tag_id)
        elif len(selected) < self.settings.max_tags_per_media:
            selected.append(tag_id)
        else:
            await self.client.send_message(chat_id, "You can choose up to 3 tags.")
            return
        message_id = message.get("message_id")
        if isinstance(message_id, int):
            await self.client.edit_message_reply_markup(
                chat_id,
                message_id,
                self._tag_keyboard(tuple(selected)),
            )

    async def _finish_tag_selection(self, chat_id: int) -> None:
        state = self.upload_state.get(chat_id)
        if not state or state.get("step") != "select_tags":
            return
        selected = tuple(state.get("selected_tags", []))
        if not selected:
            await self.client.send_message(chat_id, "Choose at least one tag.")
            return
        try:
            record = self.service.submit_metadata(
                state["submission_id"],
                title=str(state["title"]),
                tag_ids=selected,
            )
        except ValidationError as exc:
            await self.client.send_message(chat_id, str(exc))
            return
        self.upload_state.pop(chat_id, None)
        await self.client.send_message(chat_id, "Submitted for admin review.")
        await self._notify_admins(record.submission_id)

    async def _notify_admins(self, submission_id: UUID) -> None:
        record = self.service.repository.get_by_submission_id(submission_id)
        text = self._format_admin_review(record)
        keyboard = {
            "inline_keyboard": [
                [
                    {"text": "Approve", "callback_data": f"admin_approve:{record.submission_id}"},
                    {"text": "Reject", "callback_data": f"admin_reject:{record.submission_id}"},
                ]
            ]
        }
        for admin_id in self.settings.admin_chat_ids:
            if record.telegram_file_id:
                await self.client.send_animation(
                    admin_id, record.telegram_file_id, caption=text, reply_markup=keyboard
                )
            else:
                await self.client.send_message(admin_id, text, reply_markup=keyboard)

    async def _send_search(self, chat_id: int, *, query: str, page: int = 1) -> None:
        tag = None
        q = query
        if query:
            try:
                tag_ids = self.service.parse_tag_selection(query)
                if len(tag_ids) == 1:
                    tag = tag_ids[0]
                    q = ""
            except ValidationError:
                pass
        records, next_page = self.service.search(q=q, tag=tag, page=page, page_size=2)
        if not records:
            await self.client.send_message(chat_id, "No approved GIF found.")
            return
        for record in records:
            await self.client.send_message(
                chat_id,
                self._format_search_result(record),
                reply_markup=self._send_keyboard(str(record.id)),
            )
        if next_page:
            await self.client.send_message(
                chat_id,
                "More results",
                reply_markup={
                    "inline_keyboard": [
                        [
                            {
                                "text": "Next",
                                "callback_data": f"search_page:{next_page}:{quote(query)}",
                            }
                        ]
                    ]
                },
            )

    async def _send_gif_by_id(self, chat_id: int, gif_id: str) -> None:
        try:
            record = self.service.send_gif(gif_id)
        except NotFoundError:
            await self.client.send_message(chat_id, "Invalid GIF ID. Use /search to find a GIF.")
            return
        animation = record.telegram_file_id or record.file_gif_url
        if not animation:
            await self.client.send_message(chat_id, "This GIF is temporarily unavailable.")
            return
        await self.client.send_animation(chat_id, animation, caption=f"#{record.id}")

    def _tag_keyboard(self, selected: tuple[str, ...]) -> dict[str, Any]:
        rows: list[list[dict[str, str]]] = []
        row: list[dict[str, str]] = []
        selected_set = set(selected)
        for tag in self.service.repository.list_tags():
            marker = "✓ " if tag.id in selected_set else ""
            row.append(
                {"text": f"{marker}{tag.emoji} {tag.name}", "callback_data": f"tag:{tag.id}"}
            )
            if len(row) == 2:
                rows.append(row)
                row = []
        if row:
            rows.append(row)
        rows.append([{"text": "Done", "callback_data": "done_tags:1"}])
        return {"inline_keyboard": rows}

    def _send_keyboard(self, gif_id: str) -> dict[str, Any]:
        return {"inline_keyboard": [[{"text": "▶ Send GIF", "callback_data": f"send:{gif_id}"}]]}

    def _format_search_result(self, record: GifRecord) -> str:
        return f"🎬 {record.title}\n#{record.id}\n\nTags: {format_tag_list(record.tags)}"

    def _format_admin_review(self, record: GifRecord) -> str:
        return (
            f"Review GIF\n"
            f"Submission: {record.submission_id}\n"
            f"Title: {record.title}\n"
            f"Tags: {format_tag_list(record.tags)}\n"
            f"Created by: {record.created_by}"
        )

    def _is_admin(self, chat_id: int) -> bool:
        return chat_id in self.settings.admin_chat_ids


def extract_media_file_id(message: dict[str, Any]) -> str | None:
    photos = message.get("photo")
    if isinstance(photos, list) and photos:
        largest = photos[-1]
        if isinstance(largest, dict) and isinstance(largest.get("file_id"), str):
            return str(largest["file_id"])

    for key in ("animation", "video", "document"):
        item = message.get(key)
        if isinstance(item, dict) and isinstance(item.get("file_id"), str):
            return str(item["file_id"])
    return None
