"""Request-scoped dependencies.

Everything the workflow needs is injected rather than imported at the point of use, so a
test can swap in a scripted model and a temporary document store without touching the
routes.

The workflow runner is deliberately given a session *factory* rather than the request's
session: it runs after the response has been sent, when that session is already closed.
"""

import uuid
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Annotated

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from vero.agent.provider.base import LLMProvider
from vero.agent.provider.factory import build_provider
from vero.config import Settings, get_settings
from vero.db.models import Application
from vero.db.session import session_factory, session_scope
from vero.document_ai.base import DocumentExtractor
from vero.document_ai.factory import build_extractor
from vero.storage import DocumentStorage, LocalDiskStorage


def get_session() -> Iterator[Session]:
    session = session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_session_scope() -> Callable[[], AbstractContextManager[Session]]:
    return session_scope


def get_storage(settings: Annotated[Settings, Depends(get_settings)]) -> DocumentStorage:
    return LocalDiskStorage(root=Path(settings.storage_dir))


def get_extractor(settings: Annotated[Settings, Depends(get_settings)]) -> DocumentExtractor:
    return build_extractor(settings)


def get_provider(settings: Annotated[Settings, Depends(get_settings)]) -> LLMProvider:
    return build_provider(settings)


SessionDep = Annotated[Session, Depends(get_session)]
StorageDep = Annotated[DocumentStorage, Depends(get_storage)]
ExtractorDep = Annotated[DocumentExtractor, Depends(get_extractor)]
ProviderDep = Annotated[LLMProvider, Depends(get_provider)]
SessionScopeDep = Annotated[
    Callable[[], AbstractContextManager[Session]], Depends(get_session_scope)
]


def load_application(session: Session, application_id: uuid.UUID) -> Application:
    application = session.get(Application, application_id)
    if application is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "application not found")
    return application
