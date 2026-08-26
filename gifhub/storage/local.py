import asyncio
import shutil
from pathlib import Path

from gifhub.domain.models import StoredObject


class LocalStorageBackend:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def _resolve_key(self, storage_key: str) -> Path:
        destination = (self.root / storage_key).resolve()
        root = self.root.resolve()
        try:
            destination.relative_to(root)
        except ValueError as exc:
            raise ValueError("Storage key escapes storage root.") from exc
        if Path(storage_key).is_absolute():
            raise ValueError("Storage key escapes storage root.")
        return destination

    async def put_file(self, local_path: Path, storage_key: str, content_type: str) -> StoredObject:
        destination = self._resolve_key(storage_key)
        destination.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(shutil.copyfile, local_path, destination)
        return StoredObject(
            storage_key=storage_key,
            content_type=content_type,
            size_bytes=destination.stat().st_size,
            local_path=destination,
        )

    async def get_file(self, storage_key: str, destination: Path) -> Path:
        source = self._resolve_key(storage_key)
        destination.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(shutil.copyfile, source, destination)
        return destination

    async def delete_file(self, storage_key: str) -> None:
        path = self._resolve_key(storage_key)
        if path.exists():
            path.unlink()

    async def create_signed_url(self, storage_key: str, expires_seconds: int) -> str:
        path = self._resolve_key(storage_key)
        return f"file://{path}?expires={expires_seconds}"

    async def exists(self, storage_key: str) -> bool:
        return self._resolve_key(storage_key).exists()
