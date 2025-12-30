import uuid
import aiofiles
import aiofiles.os
from pathlib import Path
from typing import Any
from app.core.config import get_settings

settings = get_settings()


class StorageService:
    def __init__(self):
        self.upload_dir = Path(settings.upload_dir)
        self.upload_dir.mkdir(parents=True, exist_ok=True)

    def _get_file_path(self, key: str) -> Path:
        """Get file path with path traversal protection."""
        if not key or ".." in key or key.startswith("/") or key.startswith("\\"):
            raise ValueError(f"Invalid storage key: {key}")

        file_path = (self.upload_dir / key).resolve()

        if not str(file_path).startswith(str(self.upload_dir.resolve())):
            raise ValueError(f"Path traversal attempt detected: {key}")

        return file_path

    async def save_file(self, file_content: bytes, filename: str) -> str:
        """Save file and return storage key."""
        file_id = str(uuid.uuid4())
        ext = Path(filename).suffix or ".pdf"
        key = f"{file_id}{ext}"
        return await self.save_file_with_key(file_content, key)

    async def save_file_with_key(self, file_content: bytes, key: str) -> str:
        """Save file using a provided storage key."""
        file_path = self._get_file_path(key)
        file_path.parent.mkdir(parents=True, exist_ok=True)

        async with aiofiles.open(file_path, "wb") as f:
            await f.write(file_content)

        return key

    async def save_upload_file(
        self,
        upload_file: Any,
        max_size: int,
        *,
        required_ext: str | None = None,
        magic_header: bytes | None = None,
    ) -> str:
        """Stream an upload to disk with size and magic header checks."""
        filename = getattr(upload_file, "filename", "") or ""
        ext = Path(filename).suffix or ""
        if required_ext:
            ext = required_ext
        file_id = str(uuid.uuid4())
        key = f"{file_id}{ext}"
        file_path = self._get_file_path(key)
        file_path.parent.mkdir(parents=True, exist_ok=True)

        bytes_read = 0
        header = bytearray()
        try:
            async with aiofiles.open(file_path, "wb") as f:
                while chunk := await upload_file.read(8192):
                    bytes_read += len(chunk)
                    if bytes_read > max_size:
                        raise ValueError("File size exceeds limit")
                    if magic_header and len(header) < len(magic_header):
                        needed = len(magic_header) - len(header)
                        header.extend(chunk[:needed])
                    await f.write(chunk)

            if bytes_read < (len(magic_header) if magic_header else 1):
                raise ValueError("Invalid file format")
            if magic_header and bytes(header[: len(magic_header)]) != magic_header:
                raise ValueError("Invalid file format")
        except Exception:
            if await aiofiles.os.path.exists(file_path):
                await aiofiles.os.remove(file_path)
            raise

        return key

    async def get_file_path(self, key: str) -> Path:
        """Get absolute file path for a storage key."""
        file_path = self._get_file_path(key)
        if not await aiofiles.os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {key}")
        return file_path

    async def read_file(self, key: str) -> bytes:
        """Read file content."""
        file_path = await self.get_file_path(key)
        async with aiofiles.open(file_path, "rb") as f:
            return await f.read()

    async def delete_file(self, key: str) -> None:
        """Delete a file."""
        file_path = self._get_file_path(key)
        if await aiofiles.os.path.exists(file_path):
            await aiofiles.os.remove(file_path)

    def get_upload_url(self, key: str) -> str:
        """For local storage, return the API endpoint for upload."""
        return f"/api/v1/papers/upload/{key}"
