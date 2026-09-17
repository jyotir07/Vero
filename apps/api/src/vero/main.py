from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from vero.api.routes import applications, documents, events
from vero.config import get_settings

app = FastAPI(
    title="Vero API",
    version="0.1.0",
    description=(
        "Simulated AI credit underwriting agent. This is a technical demonstration "
        "using synthetic data, not a real credit decisioning system."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(applications.router)
app.include_router(documents.router)
app.include_router(events.router)


@app.get("/health", tags=["health"])
def health() -> dict[str, str]:
    return {"status": "ok"}
