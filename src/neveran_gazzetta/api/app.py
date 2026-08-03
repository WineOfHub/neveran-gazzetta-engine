from __future__ import annotations

import secrets
from collections.abc import Callable
from typing import Any
from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException, status

from neveran_gazzetta import __version__
from neveran_gazzetta.worker.runner import GazzettaWorker


def create_app(
    *,
    service_token: str,
    worker: GazzettaWorker | None = None,
    status_provider: Callable[[], dict[str, Any]] | None = None,
    release_provider: Callable[[], dict[str, Any]] | None = None,
    ready_provider: Callable[[], dict[str, Any]] | None = None,
    run_provider: Callable[[UUID], dict[str, Any]] | None = None,
) -> FastAPI:
    if not service_token:
        raise ValueError("service_token obbligatorio")
    app = FastAPI(title="Neveran Gazzetta Engine", version=__version__)
    expected_authorization = f"Bearer {service_token}"

    def require_token(authorization: str | None = Header(default=None)) -> None:
        if authorization is None or not secrets.compare_digest(
            authorization, expected_authorization
        ):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="unauthorized")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @app.get("/v1/ready", dependencies=[Depends(require_token)])
    def ready() -> dict[str, Any]:
        try:
            details = ready_provider() if ready_provider else {}
        except Exception as exc:
            raise HTTPException(status_code=503, detail="not_ready") from exc
        return {"status": "ready", **details}

    @app.get("/v1/status", dependencies=[Depends(require_token)])
    def engine_status() -> dict[str, Any]:
        return status_provider() if status_provider else {"status": "unknown"}

    @app.get("/v1/retrieval/release", dependencies=[Depends(require_token)])
    def retrieval_release() -> dict[str, Any]:
        if release_provider is None:
            raise HTTPException(status_code=503, detail="release_unavailable")
        return release_provider()

    @app.get("/v1/runs/{run_id}", dependencies=[Depends(require_token)])
    def run_status(run_id: UUID) -> dict[str, Any]:
        if run_provider is None:
            raise HTTPException(status_code=503, detail="run_provider_unavailable")
        try:
            return run_provider(run_id)
        except Exception as exc:
            raise HTTPException(status_code=404, detail="run_not_found") from exc

    @app.post("/v1/internal/tick", dependencies=[Depends(require_token)])
    def tick() -> dict[str, Any]:
        if worker is None:
            raise HTTPException(status_code=503, detail="worker_unavailable")
        result = worker.tick()
        return {
            "status": result.status.value,
            "job_id": str(result.job_id) if result.job_id else None,
            "error_code": result.error_code,
        }

    return app
