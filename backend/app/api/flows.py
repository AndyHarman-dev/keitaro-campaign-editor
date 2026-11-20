
from fastapi import APIRouter

from app.api.deps import Config, Db, Keitaro, cached_offers
from app.api.schemas import (
    EditorView,
    FlowProblemBody,
    ForgetIn,
    KeitaroFailureBody,
    OpRequest,
    VersionIn,
    VersionsIn,
)
from app.api.views import Catalog, editor_view
from app.config import Settings
from app.db.codec import op_from_json
from app.keitaro.client import KeitaroClient
from app.services.flows import FlowService, Outcome

router = APIRouter(prefix="/api", responses={502: {"model": KeitaroFailureBody},
                                                409: {"model": FlowProblemBody}})


async def _view(kt: KeitaroClient, outcome: Outcome, settings: Settings) -> EditorView:
    catalog = Catalog(await cached_offers(kt), settings.tracker_host)
    return editor_view(outcome, catalog, settings)


@router.get("/campaigns/{campaign_id}/editor")
async def open_editor(campaign_id: int, kt: Keitaro, db: Db, settings: Config) -> EditorView:
    return await _view(kt, await FlowService(kt, db).open(campaign_id), settings)


@router.post("/campaigns/{campaign_id}/fetch")
async def fetch(campaign_id: int, kt: Keitaro, db: Db, settings: Config) -> EditorView:
    return await _view(kt, await FlowService(kt, db).fetch(campaign_id), settings)


@router.post("/flows/{stream_id}/ops")
async def apply_op(stream_id: int, body: OpRequest, kt: Keitaro, db: Db,
                   settings: Config) -> EditorView:
    op = op_from_json(body.op.model_dump())
    return await _view(kt, await FlowService(kt, db).apply(stream_id, body.version, op), settings)


@router.post("/flows/{stream_id}/forget")
async def forget(stream_id: int, body: ForgetIn, kt: Keitaro, db: Db,
                 settings: Config) -> EditorView:
    outcome = await FlowService(kt, db).forget(stream_id, body.version, body.offer_id)
    return await _view(kt, outcome, settings)


@router.post("/flows/{stream_id}/push")
async def push(stream_id: int, body: VersionIn, kt: Keitaro, db: Db,
               settings: Config) -> EditorView:
    service = FlowService(kt, db)
    notes = await service.push(stream_id, body.version)
    return await _view(kt, await service.reload(stream_id, notes), settings)


@router.post("/flows/{stream_id}/cancel")
async def cancel(stream_id: int, body: VersionIn, kt: Keitaro, db: Db,
                 settings: Config) -> EditorView:
    service = FlowService(kt, db)
    await service.cancel({stream_id: body.version})
    return await _view(kt, await service.reload(stream_id, []), settings)


@router.post("/campaigns/{campaign_id}/push")
async def push_all(campaign_id: int, body: VersionsIn, kt: Keitaro, db: Db,
                   settings: Config) -> EditorView:
    service = FlowService(kt, db)
    notes = await service.push_all(body.versions)
    return await _view(kt, await service.outcome(campaign_id, notes), settings)


@router.post("/campaigns/{campaign_id}/cancel")
async def cancel_all(campaign_id: int, body: VersionsIn, kt: Keitaro, db: Db,
                     settings: Config) -> EditorView:
    service = FlowService(kt, db)
    await service.cancel(body.versions)
    return await _view(kt, await service.outcome(campaign_id, []), settings)
