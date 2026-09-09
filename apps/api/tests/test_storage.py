"""Document storage.

Local disk for Phase 1, behind an interface so S3 can replace it later without the
workflow noticing. URIs are content-addressed, which makes re-uploading the same file a
no-op rather than a second copy.
"""

import uuid
from pathlib import Path

import pytest

from vero.domain.enums import DocumentType
from vero.storage import DocumentNotFound, LocalDiskStorage, UnsafeStorageURI


@pytest.fixture
def storage(tmp_path: Path) -> LocalDiskStorage:
    return LocalDiskStorage(root=tmp_path / "store")


@pytest.fixture
def secret_outside_root(tmp_path: Path) -> Path:
    """A real file next to the store, so traversal has something to actually steal."""
    path = tmp_path / "secret.txt"
    path.write_bytes(b"TOP SECRET")
    return path


def test_stored_content_comes_back_unchanged(storage: LocalDiskStorage) -> None:
    uri = storage.put(
        application_id=uuid.uuid4(), document_type=DocumentType.PAY_SLIP, content=b"payslip"
    )
    assert storage.get(uri) == b"payslip"


def test_the_uri_is_opaque_to_callers(storage: LocalDiskStorage) -> None:
    """Callers store this in a column; it must not be a host filesystem path."""
    uri = storage.put(
        application_id=uuid.uuid4(), document_type=DocumentType.PAY_SLIP, content=b"x"
    )
    assert uri.startswith("local://")


def test_identical_content_is_stored_once(storage: LocalDiskStorage) -> None:
    application_id = uuid.uuid4()
    first = storage.put(
        application_id=application_id, document_type=DocumentType.PAY_SLIP, content=b"same"
    )
    second = storage.put(
        application_id=application_id, document_type=DocumentType.PAY_SLIP, content=b"same"
    )
    assert first == second


def test_different_applications_do_not_share_documents(storage: LocalDiskStorage) -> None:
    a = storage.put(
        application_id=uuid.uuid4(), document_type=DocumentType.PAY_SLIP, content=b"same"
    )
    b = storage.put(
        application_id=uuid.uuid4(), document_type=DocumentType.PAY_SLIP, content=b"same"
    )
    assert a != b


def test_a_missing_document_is_reported_not_guessed(storage: LocalDiskStorage) -> None:
    with pytest.raises(DocumentNotFound):
        storage.get("local://" + str(uuid.uuid4()) + "/deadbeef.bin")


@pytest.mark.parametrize(
    "uri",
    ["local://../secret.txt", "local://abc/../../secret.txt", "local://abc/../../secret.txt"],
)
def test_a_uri_cannot_reach_a_file_outside_the_root(
    storage: LocalDiskStorage, secret_outside_root: Path, uri: str
) -> None:
    """The file exists and is readable, so only the root check can stop this.

    Asserting UnsafeStorageURI specifically matters: accepting DocumentNotFound too
    would let this pass merely because the target happened to be missing.
    """
    assert secret_outside_root.read_bytes() == b"TOP SECRET"
    with pytest.raises(UnsafeStorageURI):
        storage.get(uri)


def test_a_non_local_scheme_is_refused(storage: LocalDiskStorage) -> None:
    with pytest.raises(UnsafeStorageURI):
        storage.get("file:///etc/passwd")


def test_content_hash_is_reported_for_the_document_row(storage: LocalDiskStorage) -> None:
    digest = storage.content_hash(b"payslip")
    assert len(digest) == 64
    assert digest == storage.content_hash(b"payslip")
