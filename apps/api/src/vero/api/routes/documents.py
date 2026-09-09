"""Document upload.

Uploads are the one place an applicant puts bytes into the system, so they are checked
before anything stores them: a size ceiling, and the file's own magic number rather than
the name or the declared content type, both of which the client chooses.

Receiving a document is also what closes the MORE_INFORMATION_REQUIRED loop, and that
transition is attributed to the applicant, because they are the one who caused it.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select

from vero.api.deps import (
    ExtractorDep,
    ProviderDep,
    SessionDep,
    SessionScopeDep,
    StorageDep,
    load_application,
)
from vero.api.workflow_task import advance_workflow
from vero.db.models import Document, WorkflowRun
from vero.domain.enums import Actor, DocumentType, EventType
from vero.domain.schemas import DocumentRead
from vero.events.recorder import EventRecorder

router = APIRouter(prefix="/applications", tags=["documents"])

MAX_UPLOAD_BYTES = 5 * 1024 * 1024
PDF_MAGIC = b"%PDF"


def _validate(content: bytes) -> None:
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE,
            f"document exceeds {MAX_UPLOAD_BYTES} bytes",
        )
    if not content.startswith(PDF_MAGIC):
        # The declared content type and the filename are both attacker-controlled.
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "document is not a PDF")


@router.post(
    "/{application_id}/documents",
    response_model=DocumentRead,
    status_code=status.HTTP_201_CREATED,
)
async def upload_document(
    application_id: uuid.UUID,
    session: SessionDep,
    background: BackgroundTasks,
    scope: SessionScopeDep,
    provider: ProviderDep,
    storage: StorageDep,
    extractor: ExtractorDep,
    document_type: Annotated[DocumentType, Form()],
    file: Annotated[UploadFile, File()],
) -> Document:
    application = load_application(session, application_id)
    content = await file.read()
    _validate(content)

    uri = storage.put(
        application_id=application.id, document_type=document_type, content=content
    )
    digest = storage.content_hash(content)

    existing = session.scalars(
        select(Document).where(
            Document.application_id == application.id, Document.content_hash == digest
        )
    ).first()
    if existing is not None:
        # Re-uploading the same bytes is a no-op rather than a duplicate row; the
        # content hash is what makes that decidable.
        return existing

    document = Document(
        application_id=application.id,
        document_type=document_type,
        storage_uri=uri,
        content_hash=digest,
    )
    session.add(document)
    session.flush()

    run = session.scalars(
        select(WorkflowRun).where(WorkflowRun.application_id == application.id)
    ).one()
    recorder = EventRecorder(session)
    recorder.record(
        run=run,
        event_type=EventType.DOCUMENT_UPLOADED,
        actor=Actor.APPLICANT,
        payload={"document_type": document_type.value},
    )

    # Same reason as intake: the background task reads through a separate session.
    session.commit()

    background.add_task(
        advance_workflow,
        application_id=application.id,
        scope=scope,
        provider=provider,
        storage=storage,
        extractor=extractor,
        resume_after_documents=True,
    )
    return document
