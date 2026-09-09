"""Where uploaded documents live.

Local disk for Phase 1, behind an interface so S3 can take over in Phase 4 without the
workflow noticing. URIs are content-addressed and scoped to an application, so
re-uploading the same file is a no-op and two applicants never collide.

URIs arrive from user-controlled data, so resolution is checked against the storage root
rather than trusted.
"""

import hashlib
import uuid
from pathlib import Path
from typing import Protocol

from vero.domain.enums import DocumentType

SCHEME = "local://"


class StorageError(Exception):
    pass


class DocumentNotFound(StorageError):
    pass


class UnsafeStorageURI(StorageError):
    pass


class DocumentStorage(Protocol):
    def put(
        self, *, application_id: uuid.UUID, document_type: DocumentType, content: bytes
    ) -> str: ...

    def get(self, uri: str) -> bytes: ...

    def content_hash(self, content: bytes) -> str: ...


class LocalDiskStorage:
    def __init__(self, root: Path) -> None:
        self._root = root.resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    def content_hash(self, content: bytes) -> str:
        return hashlib.sha256(content).hexdigest()

    def put(
        self, *, application_id: uuid.UUID, document_type: DocumentType, content: bytes
    ) -> str:
        digest = self.content_hash(content)
        relative = f"{application_id}/{digest}.bin"
        path = self._root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return f"{SCHEME}{relative}"

    def get(self, uri: str) -> bytes:
        path = self._resolve(uri)
        try:
            return path.read_bytes()
        except FileNotFoundError as exc:
            raise DocumentNotFound(uri) from exc

    def _resolve(self, uri: str) -> Path:
        if not uri.startswith(SCHEME):
            raise UnsafeStorageURI(f"unsupported storage uri: {uri}")
        candidate = (self._root / uri[len(SCHEME) :]).resolve()
        # Compare resolved paths: a uri full of ".." must not reach outside the root.
        if not candidate.is_relative_to(self._root):
            raise UnsafeStorageURI(f"uri escapes the storage root: {uri}")
        return candidate
