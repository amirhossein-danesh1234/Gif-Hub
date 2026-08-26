from pathlib import Path
from typing import Protocol

from gifhub.domain.models import StoredObject


class StorageBackend(Protocol):
    async def put_file(
        self,
        local_path: Path,
        storage_key: str,
        content_type: str,
    ) -> StoredObject: ...

    async def get_file(self, storage_key: str, destination: Path) -> Path: ...

    async def delete_file(self, storage_key: str) -> None: ...

    async def create_signed_url(self, storage_key: str, expires_seconds: int) -> str: ...

    async def exists(self, storage_key: str) -> bool: ...
