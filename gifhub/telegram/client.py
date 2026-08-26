from pathlib import Path
from typing import Any

import httpx


class TelegramAPIError(RuntimeError):
    pass


class TelegramClient:
    def __init__(self, token: str, *, base_url: str = "https://api.telegram.org") -> None:
        self.token = token
        self.base_url = base_url.rstrip("/")

    def method_url(self, method_name: str) -> str:
        return f"{self.base_url}/bot{self.token}/{method_name}"

    async def request(self, method_name: str, payload: dict[str, Any] | None = None) -> Any:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(self.method_url(method_name), json=payload or {})
        response.raise_for_status()
        data = response.json()
        if not data.get("ok"):
            raise TelegramAPIError(str(data.get("description", "Telegram API request failed.")))
        return data.get("result")

    async def send_message(
        self,
        chat_id: int,
        text: str,
        *,
        reply_markup: dict[str, Any] | None = None,
    ) -> Any:
        payload: dict[str, Any] = {"chat_id": chat_id, "text": text}
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        return await self.request("sendMessage", payload)

    async def send_animation(
        self,
        chat_id: int,
        animation: str,
        *,
        caption: str | None = None,
        reply_markup: dict[str, Any] | None = None,
    ) -> Any:
        payload: dict[str, Any] = {"chat_id": chat_id, "animation": animation}
        if caption is not None:
            payload["caption"] = caption
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        return await self.request("sendAnimation", payload)

    async def answer_callback_query(self, callback_query_id: str, text: str | None = None) -> Any:
        payload: dict[str, Any] = {"callback_query_id": callback_query_id}
        if text:
            payload["text"] = text
        return await self.request("answerCallbackQuery", payload)

    async def edit_message_reply_markup(
        self,
        chat_id: int,
        message_id: int,
        reply_markup: dict[str, Any] | None,
    ) -> Any:
        return await self.request(
            "editMessageReplyMarkup",
            {
                "chat_id": chat_id,
                "message_id": message_id,
                "reply_markup": reply_markup,
            },
        )

    async def get_updates(
        self,
        *,
        offset: int | None = None,
        timeout: int = 30,
    ) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {"timeout": timeout}
        if offset is not None:
            payload["offset"] = offset
        result = await self.request("getUpdates", payload)
        if not isinstance(result, list):
            return []
        return [item for item in result if isinstance(item, dict)]

    async def get_file(self, file_id: str) -> dict[str, Any]:
        result = await self.request("getFile", {"file_id": file_id})
        if not isinstance(result, dict):
            raise TelegramAPIError("getFile did not return an object.")
        return result

    async def download_file(self, file_path: str, destination: Path) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        url = f"{self.base_url}/file/bot{self.token}/{file_path}"
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.get(url)
        response.raise_for_status()
        destination.write_bytes(response.content)
        return destination

    async def answer_inline_query(self, inline_query_id: str, results: list[dict[str, Any]]) -> Any:
        return await self.request(
            "answerInlineQuery",
            {
                "inline_query_id": inline_query_id,
                "results": results,
                "cache_time": 5,
                "is_personal": True,
            },
        )
