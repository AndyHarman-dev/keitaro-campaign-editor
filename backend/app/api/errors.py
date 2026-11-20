"""Maps service errors to HTTP responses in one place."""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.schemas import FlowProblem, KeitaroFailure
from app.domain.flow import InvalidPush, NotArchived
from app.keitaro.client import KeitaroError
from app.services.campaigns import CreateFailed, MissingDefault
from app.services.flows import Conflict, FlowNotFound, StaleVersion

_STALE = "This flow changed in another tab or window. Reload to see the latest state."


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

    @app.exception_handler(Conflict)
    async def conflict(request: Request, exc: Conflict) -> JSONResponse:
        body = FlowProblem(kind="conflict", message=str(exc))
        return JSONResponse(status_code=409, content={"detail": body.model_dump()})

    @app.exception_handler(StaleVersion)
    async def stale(request: Request, exc: StaleVersion) -> JSONResponse:
        body = FlowProblem(kind="stale", message=_STALE)
        return JSONResponse(status_code=409, content={"detail": body.model_dump()})

    @app.exception_handler(FlowNotFound)
    async def not_found(request: Request, exc: FlowNotFound) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(InvalidPush)
    @app.exception_handler(NotArchived)
    async def unprocessable(request: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.exception_handler(MissingDefault)
    async def missing_default(request: Request, exc: MissingDefault) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(exc)})
