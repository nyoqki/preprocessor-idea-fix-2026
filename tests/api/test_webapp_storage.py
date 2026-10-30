from pathlib import Path

import pytest

from yasno.storage import InvalidKeyError, LocalStorage, ObjectNotFoundError


@pytest.fixture
def storage(tmp_path: Path) -> LocalStorage:
    return LocalStorage(tmp_path / "root")


async def test_put_get_delete(storage: LocalStorage) -> None:
    await storage.put("submissions/2026/11/a.jpg", b"one", "image/jpeg")
    await storage.put("submissions/2026/11/a.jpg", b"two", "image/jpeg")
    assert await storage.exists("submissions/2026/11/a.jpg")
    assert await storage.get("submissions/2026/11/a.jpg") == b"two"
    await storage.delete("submissions/2026/11/a.jpg")
    await storage.delete("submissions/2026/11/a.jpg")
    assert not await storage.exists("submissions/2026/11/a.jpg")
    with pytest.raises(ObjectNotFoundError):
        await storage.get("submissions/2026/11/a.jpg")


async def test_no_temporary_files_left(storage: LocalStorage) -> None:
    await storage.put("a/b.bin", b"data")
    assert [p.name for p in (storage.root / "a").iterdir()] == ["b.bin"]


@pytest.mark.parametrize(
    "key",
    ["", "../x", "a/../../x", "/etc/passwd", "a//b", "a/./b", "a\\b", ".hidden", "a/..", "x\x00"],
)
async def test_rejects_unsafe_keys(storage: LocalStorage, key: str) -> None:
    with pytest.raises(InvalidKeyError):
        await storage.put(key, b"data")
    with pytest.raises(InvalidKeyError):
        await storage.get(key)


async def test_directory_is_not_an_object(storage: LocalStorage) -> None:
    await storage.put("dir/file.txt", b"data")
    assert not await storage.exists("dir")
    with pytest.raises(ObjectNotFoundError):
        await storage.get("dir")
