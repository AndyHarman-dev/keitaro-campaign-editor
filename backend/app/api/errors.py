"""Maps service errors to HTTP responses in one place."""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.schemas import KeitaroFailure
from app.keitaro.client import KeitaroError
from app.services.campaigns import CreateFailed, MissingDefault


def _failure(error: KeitaroError, archived: bool = False) -> JSONResponse:
    body = KeitaroFailure(message=error.message, keitaro_status=error.status,
                          archived_campaign=archived)
    return JSONResponse(status_code=502, content={"detail": body.model_dump()})


def install(app: FastAPI) -> None:
    @app.exception_handler(KeitaroError)
    async def keitaro_error(request: Request, exc: KeitaroError) -> JSONResponse:
        return _failure(exc)

    @app.exception_handler(CreateFailed)
    async def create_failed(request: Request, exc: CreateFailed) -> JSONResponse:
        return _failure(exc.error, exc.archived_campaign)

    @app.exception_handler(MissingDefault)
    async def missing_default(request: Request, exc: MissingDefault) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(exc)})
