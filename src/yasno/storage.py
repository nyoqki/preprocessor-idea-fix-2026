import asyncio
import os
import re
import tempfile
from pathlib import Path
from typing import Protocol

from yasno.config import Settings

_KEY_PART = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class StorageError(Exception):
    pass


class InvalidKeyError(StorageError, ValueError):
    pass


class ObjectNotFoundError(StorageError, LookupError):
    pass


class Storage(Protocol):
    async def put(self, key: str, data: bytes, content_type: str | None = None) -> None: ...

    async def get(self, key: str) -> bytes: ...

    async def delete(self, key: str) -> None: ...

    async def exists(self, key: str) -> bool: ...


def validate_key(key: str) -> list[str]:
    if not key or len(key) > 512:
        raise InvalidKeyError(key)
    parts = key.split("/")
    for part in parts:
        if not _KEY_PART.fullmatch(part) or part.strip(".") == "":
            raise InvalidKeyError(key)
    return parts


class LocalStorage:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def path_for(self, key: str) -> Path:
        path = self.root.joinpath(*validate_key(key)).resolve()
        if not path.is_relative_to(self.root) or path == self.root:
            raise InvalidKeyError(key)
        return path

    def _put(self, key: str, data: bytes) -> None:
        path = self.path_for(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=".", suffix=".tmp")
        tmp = Path(tmp_name)
        try:
            with os.fdopen(fd, "wb") as file:
                file.write(data)
                file.flush()
                os.fsync(file.fileno())
            tmp.replace(path)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise

    def _get(self, key: str) -> bytes:
        path = self.path_for(key)
        try:
            return path.read_bytes()
        except (FileNotFoundError, IsADirectoryError, NotADirectoryError) as exc:
            raise ObjectNotFoundError(key) from exc

    def _delete(self, key: str) -> None:
        self.path_for(key).unlink(missing_ok=True)

    def _exists(self, key: str) -> bool:
        return self.path_for(key).is_file()

    async def put(self, key: str, data: bytes, content_type: str | None = None) -> None:
        await asyncio.to_thread(self._put, key, data)

    async def get(self, key: str) -> bytes:
        return await asyncio.to_thread(self._get, key)

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self._delete, key)

    async def exists(self, key: str) -> bool:
        return await asyncio.to_thread(self._exists, key)


def create_storage(settings: Settings) -> Storage:
    return LocalStorage(settings.storage_dir)
